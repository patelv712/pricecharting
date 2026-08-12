"""Command-line entry points for profiling, evaluation, and live smoke tests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import uvicorn

from pcqc.catalog import CatalogFetcher, enrich_candidate_catalogs
from pcqc.candidates import candidate_query, rank_candidates
from pcqc.comparison import compare_evaluations, comparison_markdown
from pcqc.config import Settings
from pcqc.evaluate import evaluate_sales
from pcqc.evidence import build_evidence_packet
from pcqc.finish import extract_image_features, resolve_finish
from pcqc.finish_provider import TargetedFinishReviewer
from pcqc.finish_workflow import FinishAwareReviewer
from pcqc.finish_evaluation import evaluate_finish_results, read_finish_benchmark
from pcqc.image import ImageFetcher
from pcqc.io import profile_sales, read_sales
from pcqc.models import TargetLabel
from pcqc.pilot import (
    run_multimodal_pilot,
    stratified_pilot_sample,
    stratified_target_sample,
)
from pcqc.pricecharting import PriceChartingClient, PriceGuideIndex, fallback_product
from pcqc.provider import SYSTEM_PROMPT, OpenAICompatibleReviewer
from pcqc.rules import RulesReviewer
from pcqc.split import (
    grouped_hash_split,
    grouped_three_way_split,
    split_summary,
    three_way_split_summary,
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _manifest_product_ids(paths: list[Path]) -> set[str]:
    product_ids: set[str] = set()
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        sample = value.get("sample") if isinstance(value, dict) else None
        if not isinstance(sample, list):
            raise ValueError(f"Manifest has no sample list: {path}")
        for row in sample:
            if isinstance(row, dict) and row.get("product_id") is not None:
                product_ids.add(str(row["product_id"]))
    return product_ids


def _partition_fingerprint(sales: list[object]) -> str:
    rows = sorted(f"{sale.identifier}:{sale.product_id}" for sale in sales)
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def profile_command(args: argparse.Namespace) -> None:
    sales = read_sales(args.sales, limit=args.limit)
    payload = profile_sales(sales)
    _write_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


def baseline_command(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    sales = read_sales(args.sales, limit=args.limit)
    development, test = grouped_hash_split(
        sales, test_fraction=args.test_fraction, seed=settings.random_seed
    )
    index = PriceGuideIndex()
    for guide_path in args.price_guide:
        index.load(guide_path)

    def resolve(sale: object) -> object:
        return index.get(sale.product_id) or fallback_product(sale.product_id, sale.product_title)

    reviewer = RulesReviewer()
    report, predictions = evaluate_sales(test, reviewer, product_resolver=resolve)
    report["data_profile"] = profile_sales(sales)
    report["split"] = split_summary(development, test)
    report["price_guide_products_loaded"] = len(index)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.output_dir / "baseline-report.json", report)
    _write_jsonl(args.output_dir / "baseline-predictions.jsonl", predictions)
    print(json.dumps(report, indent=2, sort_keys=True))


def live_smoke_command(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    if not settings.pricecharting_api_token:
        raise SystemExit("PRICECHARTING_API_TOKEN is required")
    sales = read_sales(args.sales)
    sale = next((row for row in sales if row.picture_url), sales[0])
    client = PriceChartingClient(settings.pricecharting_api_token, settings.cache_dir)
    product = client.get_product(sale.product_id, fallback_name=sale.product_title)
    candidates = rank_candidates(sale, client.search_products(candidate_query(sale)))
    image = ImageFetcher(settings.cache_dir).fetch(sale.identifier, sale.picture_url)
    catalog_fetcher = CatalogFetcher(settings.cache_dir)
    catalog = catalog_fetcher.fetch(product)
    candidates = enrich_candidate_catalogs(
        candidates,
        catalog_fetcher,
        assigned_product_id=product.product_id,
    )
    packet = build_evidence_packet(
        sale, product, image, catalog, replacement_candidates=candidates
    )
    result = RulesReviewer().review(packet)
    payload = {
        "sale_identifier": sale.identifier,
        "product_id": sale.product_id,
        "product_source": product.source,
        "product_name": product.product_name,
        "price_anchor_count": len(product.price_anchors),
        "image": image.model_dump(mode="json", exclude={"cache_path"}),
        "catalog": catalog.model_dump(
            mode="json", exclude={"image": {"cache_path"}}
        ),
        "derived": packet.derived.model_dump(mode="json"),
        "replacement_candidates": [
            candidate.model_dump(mode="json") for candidate in candidates
        ],
        "result": result.model_dump(mode="json"),
    }
    _write_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


def review_command(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    sales = read_sales(args.sales)
    sale = next((row for row in sales if row.identifier == args.identifier), None)
    if sale is None:
        raise SystemExit(f"No sale found for identifier {args.identifier!r}")
    product = fallback_product(sale.product_id, sale.product_title)
    candidates = []
    if settings.pricecharting_api_token:
        client = PriceChartingClient(
            settings.pricecharting_api_token, settings.cache_dir
        )
        product = client.get_product(sale.product_id, fallback_name=sale.product_title)
        candidates = rank_candidates(
            sale, client.search_products(candidate_query(sale))
        )
    image = ImageFetcher(settings.cache_dir).fetch(sale.identifier, sale.picture_url)
    catalog_fetcher = CatalogFetcher(settings.cache_dir)
    catalog = catalog_fetcher.fetch(product)
    candidates = enrich_candidate_catalogs(
        candidates,
        catalog_fetcher,
        assigned_product_id=product.product_id,
    )
    packet = build_evidence_packet(
        sale, product, image, catalog, replacement_candidates=candidates
    )
    if args.provider == "llm":
        if not settings.llm_api_key or not settings.llm_model:
            raise SystemExit("LLM_API_KEY and LLM_MODEL are required for --provider llm")
        main_reviewer = OpenAICompatibleReviewer(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
        reviewer = FinishAwareReviewer(
            main_reviewer=main_reviewer,
            finish_reviewer=TargetedFinishReviewer(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                model=settings.finish_llm_model or settings.llm_model,
            ),
            cache_dir=settings.cache_dir,
        )
    else:
        reviewer = RulesReviewer()
    result = reviewer.review(packet)
    output_packet = (
        packet.model_copy(update={"finish_resolution": result.finish_resolution})
        if result.finish_resolution
        else packet
    )
    payload = {
        "identifier": sale.identifier,
        "evidence": output_packet.model_dump(
            mode="json",
            exclude={
                "sale": {
                    "target",
                    "target_condition_id",
                    "review_action_condition_id",
                    "status_raw",
                }
            },
        ),
        "result": result.model_dump(mode="json"),
    }
    _write_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


def finish_review_command(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    if not settings.pricecharting_api_token:
        raise SystemExit("PRICECHARTING_API_TOKEN is required")
    if not settings.llm_api_key or not settings.finish_llm_model:
        raise SystemExit("LLM_API_KEY and FINISH_LLM_MODEL are required")
    sales = read_sales(args.sales)
    sale = next((row for row in sales if row.identifier == args.identifier), None)
    if sale is None:
        raise SystemExit(f"No sale found for identifier {args.identifier!r}")
    client = PriceChartingClient(
        settings.pricecharting_api_token, settings.cache_dir
    )
    product = client.get_product(sale.product_id, fallback_name=sale.product_title)
    candidates = rank_candidates(
        sale, client.search_products(candidate_query(sale))
    )
    image = ImageFetcher(settings.cache_dir).fetch(sale.identifier, sale.picture_url)
    catalog_fetcher = CatalogFetcher(settings.cache_dir)
    catalog = catalog_fetcher.fetch(product)
    candidates = enrich_candidate_catalogs(
        candidates,
        catalog_fetcher,
        assigned_product_id=product.product_id,
        limit=8,
    )
    packet = build_evidence_packet(
        sale, product, image, catalog, replacement_candidates=candidates
    )
    if not image.usable or not image.cache_path:
        features = extract_image_features(Path("missing"), settings.cache_dir)
        visual = None
    else:
        features = extract_image_features(image.cache_path, settings.cache_dir)
        finish_reviewer = TargetedFinishReviewer(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.finish_llm_model,
        )
        finish_response = finish_reviewer.review(packet, features)
        visual = finish_response.visual
    resolution = resolve_finish(packet, visual=visual, image_features=features)
    if visual is not None:
        resolution = resolution.model_copy(
            update={"provider_metadata": finish_response.metadata}
        )
    payload = {
        "identifier": sale.identifier,
        "prompt_version": (
            finish_reviewer.prompt_version if visual is not None else None
        ),
        "assigned_product": {
            "product_id": product.product_id,
            "product_name": product.product_name,
            "catalog": catalog.model_dump(mode="json", exclude={"image": {"cache_path"}}),
        },
        "candidate_finishes": [
            {
                "product_id": candidate.product_id,
                "product_name": candidate.product_name,
                "catalog_verified": bool(
                    candidate.catalog and candidate.catalog.product_id_verified
                ),
            }
            for candidate in candidates
        ],
        "resolution": resolution.model_dump(mode="json"),
    }
    _write_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


def finish_evaluate_command(args: argparse.Namespace) -> None:
    benchmark = read_finish_benchmark(args.benchmark)
    payload = evaluate_finish_results(benchmark, args.results_dir)
    _write_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


def multimodal_eval_command(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    if args.mode != "rules" and (not settings.llm_api_key or not settings.llm_model):
        raise SystemExit("LLM_API_KEY and LLM_MODEL are required")
    sales = read_sales(args.sales)
    excluded_product_ids = _manifest_product_ids(args.exclude_manifest)
    development, validation, final = grouped_three_way_split(
        sales,
        validation_fraction=args.validation_fraction,
        final_fraction=args.final_fraction,
        seed=settings.random_seed,
        excluded_product_ids=excluded_product_ids,
    )
    if args.evaluation_split == "final" and not args.unlock_final_holdout:
        raise SystemExit(
            "Refusing to inspect the final holdout without --unlock-final-holdout"
        )
    evaluation_rows = validation if args.evaluation_split == "validation" else final
    if args.sample_size is not None:
        if args.sample_size < 10:
            raise SystemExit("--sample-size must be at least 10")
        standard_count = round(args.sample_size * 0.30)
        target_counts = {
            TargetLabel.IGNORED: standard_count,
            TargetLabel.DELETED: standard_count,
            TargetLabel.CONDITION_CHANGE: standard_count,
            TargetLabel.NEEDS_MODIFICATION: args.sample_size - 3 * standard_count,
        }
        sample = stratified_target_sample(
            evaluation_rows,
            target_counts=target_counts,
            seed=settings.random_seed,
        )
    else:
        target_counts = None
        sample = stratified_pilot_sample(
            evaluation_rows,
            per_target=args.per_target,
            seed=settings.random_seed,
        )
    if args.mode == "rules":
        reviewer = RulesReviewer()
    else:
        main_reviewer = OpenAICompatibleReviewer(
            api_key=settings.llm_api_key or "",
            base_url=settings.llm_base_url,
            model=settings.llm_model or "",
            include_image=args.mode == "multimodal",
        )
        reviewer = (
            FinishAwareReviewer(
                main_reviewer=main_reviewer,
                finish_reviewer=TargetedFinishReviewer(
                    api_key=settings.llm_api_key or "",
                    base_url=settings.llm_base_url,
                    model=settings.finish_llm_model or settings.llm_model or "",
                ),
                cache_dir=settings.cache_dir,
            )
            if args.mode == "multimodal"
            else main_reviewer
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "model": reviewer.model,
        "mode": args.mode,
        "prompt_version": reviewer.prompt_version,
        "source_file_sha256": hashlib.sha256(args.sales.read_bytes()).hexdigest(),
        "per_target": args.per_target,
        "sample_size": args.sample_size,
        "target_counts": {
            target.value: count for target, count in (target_counts or {}).items()
        },
        "sample_count": len(sample),
        "condition_change_policy": "exclude rows where condition-id already equals target status",
        "evaluation_split": args.evaluation_split,
        "excluded_prior_product_count": len(excluded_product_ids),
        "excluded_manifests": [str(path) for path in args.exclude_manifest],
        "split": three_way_split_summary(development, validation, final),
        "partition_fingerprints": {
            "development": _partition_fingerprint(development),
            "validation": _partition_fingerprint(validation),
            "final": _partition_fingerprint(final),
        },
        "sample": [
            {
                "sample_index": index,
                "identifier": sale.identifier,
                "product_id": sale.product_id,
                "target": sale.target.value if sale.target else None,
                "target_condition_id": sale.target_condition_id,
                "original_condition_id": sale.original_condition_id,
                "has_picture_url": bool(sale.picture_url),
            }
            for index, sale in enumerate(sample, start=1)
        ],
    }
    if args.evaluation_split == "final":
        if args.frozen_policy is None:
            raise SystemExit("--frozen-policy is required for final evaluation")
        frozen = json.loads(args.frozen_policy.read_text(encoding="utf-8"))
        expected = {
            "model": manifest["model"],
            "mode": manifest["mode"],
            "prompt_version": manifest["prompt_version"].split(":", 1)[0],
            "source_file_sha256": manifest["source_file_sha256"],
            "final_partition_fingerprint": manifest["partition_fingerprints"]["final"],
            "final_sample_size": len(sample),
            "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        }
        mismatches = {
            key: {"frozen": frozen.get(key), "current": value}
            for key, value in expected.items()
            if frozen.get(key) != value
        }
        if mismatches:
            raise SystemExit(f"Frozen policy mismatch: {json.dumps(mismatches)}")
    manifest_path = args.output_dir / "gemini-pilot-manifest.json"
    if args.evaluation_split == "final" and manifest_path.exists():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        immutable_keys = (
            "model",
            "mode",
            "prompt_version",
            "source_file_sha256",
            "partition_fingerprints",
            "sample",
        )
        if any(existing_manifest.get(key) != manifest.get(key) for key in immutable_keys):
            raise SystemExit(
                "Final evaluation directory is locked to a different cohort or policy"
            )
    else:
        _write_json(manifest_path, manifest)
    pricecharting_client = (
        PriceChartingClient(settings.pricecharting_api_token, settings.cache_dir)
        if settings.pricecharting_api_token
        else None
    )
    report, _ = run_multimodal_pilot(
        sample,
        reviewer=reviewer,
        image_fetcher=ImageFetcher(settings.cache_dir),
        catalog_fetcher=CatalogFetcher(settings.cache_dir),
        checkpoint_path=args.output_dir / "gemini-pilot-predictions.jsonl",
        pricecharting_client=pricecharting_client,
        max_failures=args.max_failures,
        retry_errors=args.retry_errors,
        request_interval_seconds=args.request_interval_seconds,
        max_quota_retries=args.max_quota_retries,
        workers=args.workers,
    )
    report["model"] = reviewer.model
    report["mode"] = args.mode
    report["sample_count"] = len(sample)
    report["split_product_overlap"] = manifest["split"]["product_overlap"]
    report["evaluation_split"] = args.evaluation_split
    _write_json(args.output_dir / "gemini-pilot-report.json", report)
    if args.evaluation_split == "final":
        _write_json(
            args.output_dir / "final-evaluation-lock.json",
            {
                "source_file_sha256": manifest["source_file_sha256"],
                "final_partition_fingerprint": manifest["partition_fingerprints"]["final"],
                "prompt_version": manifest["prompt_version"],
                "model": manifest["model"],
                "mode": manifest["mode"],
                "sample_count": len(sample),
                "successful_rows": report["successful_rows"],
                "complete": report["successful_rows"] == len(sample),
            },
        )
    print(json.dumps(report, indent=2, sort_keys=True))


def compare_command(args: argparse.Namespace) -> None:
    summary, disagreements = compare_evaluations(
        sales_path=args.sales,
        evaluation_dirs={
            "rules": args.rules_dir,
            "text-only": args.text_only_dir,
            "multimodal": args.multimodal_dir,
        },
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.output_dir / "comparison.json", summary)
    _write_jsonl(args.output_dir / "disagreements.jsonl", disagreements)
    (args.output_dir / "comparison.md").write_text(
        comparison_markdown(summary), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcqc")
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile = subparsers.add_parser("profile", help="Profile a reviewed-sale CSV")
    profile.add_argument("--sales", type=Path, required=True)
    profile.add_argument("--output", type=Path, required=True)
    profile.add_argument("--limit", type=int)
    profile.set_defaults(func=profile_command)

    baseline = subparsers.add_parser("baseline", help="Evaluate the deterministic baseline")
    baseline.add_argument("--sales", type=Path, required=True)
    baseline.add_argument("--output-dir", type=Path, required=True)
    baseline.add_argument("--price-guide", type=Path, action="append", default=[])
    baseline.add_argument("--limit", type=int)
    baseline.add_argument("--test-fraction", type=float, default=0.30)
    baseline.set_defaults(func=baseline_command)

    smoke = subparsers.add_parser("live-smoke", help="Test live product and image enrichment")
    smoke.add_argument("--sales", type=Path, required=True)
    smoke.add_argument("--output", type=Path, required=True)
    smoke.set_defaults(func=live_smoke_command)

    review = subparsers.add_parser("review", help="Review one labeled-export row")
    review.add_argument("--sales", type=Path, required=True)
    review.add_argument("--identifier", required=True)
    review.add_argument("--provider", choices=("rules", "llm"), default="rules")
    review.add_argument("--output", type=Path, required=True)
    review.set_defaults(func=review_command)

    finish_review = subparsers.add_parser(
        "finish-review", help="Run targeted finish resolution for one sale"
    )
    finish_review.add_argument("--sales", type=Path, required=True)
    finish_review.add_argument("--identifier", required=True)
    finish_review.add_argument("--output", type=Path, required=True)
    finish_review.set_defaults(func=finish_review_command)

    finish_evaluate = subparsers.add_parser(
        "finish-evaluate", help="Score targeted finish-resolution artifacts"
    )
    finish_evaluate.add_argument("--benchmark", type=Path, required=True)
    finish_evaluate.add_argument("--results-dir", type=Path, required=True)
    finish_evaluate.add_argument("--output", type=Path, required=True)
    finish_evaluate.set_defaults(func=finish_evaluate_command)

    multimodal = subparsers.add_parser(
        "multimodal-eval", help="Run a resumable stratified multimodal pilot"
    )
    multimodal.add_argument("--sales", type=Path, required=True)
    multimodal.add_argument("--output-dir", type=Path, required=True)
    multimodal.add_argument(
        "--mode",
        choices=("rules", "text-only", "multimodal"),
        default="multimodal",
    )
    sample_group = multimodal.add_mutually_exclusive_group()
    sample_group.add_argument("--per-target", type=int, default=5)
    sample_group.add_argument(
        "--sample-size",
        type=int,
        help="Use a 30/30/30/10 resolved/needsMod evaluation profile",
    )
    multimodal.add_argument("--validation-fraction", type=float, default=0.20)
    multimodal.add_argument("--final-fraction", type=float, default=0.20)
    multimodal.add_argument(
        "--exclude-manifest",
        type=Path,
        action="append",
        default=[],
        help="Prior pilot manifest whose products must remain in development",
    )
    multimodal.add_argument(
        "--evaluation-split",
        choices=("validation", "final"),
        default="validation",
    )
    multimodal.add_argument(
        "--unlock-final-holdout",
        action="store_true",
        help="Explicitly authorize the one-time final-holdout evaluation",
    )
    multimodal.add_argument(
        "--frozen-policy",
        type=Path,
        help="Policy lock required for final-holdout evaluation",
    )
    multimodal.add_argument("--max-failures", type=int, default=5)
    multimodal.add_argument("--retry-errors", action="store_true")
    multimodal.add_argument("--request-interval-seconds", type=float, default=12)
    multimodal.add_argument("--max-quota-retries", type=int, default=3)
    multimodal.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Concurrent model requests after sequential evidence preparation",
    )
    multimodal.set_defaults(func=multimodal_eval_command)

    compare = subparsers.add_parser(
        "compare-evaluations", help="Compare paired rules/text/image evaluation arms"
    )
    compare.add_argument("--sales", type=Path, required=True)
    compare.add_argument("--rules-dir", type=Path, required=True)
    compare.add_argument("--text-only-dir", type=Path, required=True)
    compare.add_argument("--multimodal-dir", type=Path, required=True)
    compare.add_argument("--output-dir", type=Path, required=True)
    compare.set_defaults(func=compare_command)

    serve = subparsers.add_parser("serve", help="Run the HTTP service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=lambda args: uvicorn.run("pcqc.api:app", host=args.host, port=args.port))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
