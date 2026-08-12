"""Deterministic, resumable multimodal pilot execution."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pcqc.catalog import CatalogFetcher, enrich_candidate_catalogs
from pcqc.candidates import candidate_query, rank_candidates
from pcqc.evidence import build_evidence_packet
from pcqc.image import ImageFetcher
from pcqc.metrics import classification_summary, escalation_summary
from pcqc.models import (
    Decision,
    ImageEvidence,
    NormalizedSale,
    ReviewResult,
    TargetLabel,
)
from pcqc.pricecharting import PriceChartingClient, fallback_product
from pcqc.provider import (
    PROMPT_VERSION,
    OpenAICompatibleReviewer,
    ProviderHTTPError,
    public_packet,
)


def _sample_key(sale: NormalizedSale, seed: str) -> str:
    return hashlib.sha256(f"{seed}:pilot:{sale.identifier}".encode()).hexdigest()


def _sample_target(
    sales: list[NormalizedSale],
    *,
    target: TargetLabel,
    count: int,
    seed: str,
) -> list[NormalizedSale]:
    candidates = [sale for sale in sales if sale.target == target]
    if target == TargetLabel.CONDITION_CHANGE:
        candidates = [
            sale
            for sale in candidates
            if sale.original_condition_id != sale.target_condition_id
        ]
    present = sorted(
        (sale for sale in candidates if sale.picture_url),
        key=lambda sale: _sample_key(sale, seed),
    )
    missing = sorted(
        (sale for sale in candidates if not sale.picture_url),
        key=lambda sale: _sample_key(sale, seed),
    )
    target_rows: list[NormalizedSale] = []
    if missing and count >= 2:
        target_rows.append(missing[0])
    target_rows.extend(present[: count - len(target_rows)])
    if len(target_rows) < count:
        already_selected = {sale.identifier for sale in target_rows}
        remaining = sorted(
            (sale for sale in candidates if sale.identifier not in already_selected),
            key=lambda sale: _sample_key(sale, seed),
        )
        target_rows.extend(remaining[: count - len(target_rows)])
    if len(target_rows) != count:
        raise ValueError(f"Not enough {target.value} rows for requested sample")
    return target_rows


def stratified_pilot_sample(
    sales: list[NormalizedSale],
    *,
    per_target: int,
    seed: str,
) -> list[NormalizedSale]:
    """Sample each historical target and force one missing-image case when available."""
    if per_target < 1:
        raise ValueError("per_target must be positive")
    selected: list[NormalizedSale] = []
    for target in TargetLabel:
        selected.extend(
            _sample_target(sales, target=target, count=per_target, seed=seed)
        )
    return selected


def stratified_target_sample(
    sales: list[NormalizedSale],
    *,
    target_counts: dict[TargetLabel, int],
    seed: str,
) -> list[NormalizedSale]:
    """Select deterministic per-target counts for a fixed paired evaluation cohort."""
    selected: list[NormalizedSale] = []
    for target in TargetLabel:
        count = target_counts.get(target, 0)
        if count < 0:
            raise ValueError("target counts cannot be negative")
        if count == 0:
            continue
        selected.extend(
            _sample_target(sales, target=target, count=count, seed=seed)
        )
    return selected


def read_prediction_checkpoint(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, object]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not isinstance(value.get("identifier"), str):
            raise ValueError(f"Invalid checkpoint row {line_number}")
        rows[value["identifier"]] = value
    return rows


def append_prediction(path: Path, prediction: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(prediction, sort_keys=True) + "\n")
        handle.flush()


def evidence_fingerprint(packet: object, reviewer: object) -> str:
    """Bind a checkpoint result to the exact label-blind model input."""
    payload = {
        "model": getattr(reviewer, "model", type(reviewer).__name__),
        "prompt_version": getattr(reviewer, "prompt_version", PROMPT_VERSION),
        "inference_mode": getattr(reviewer, "inference_mode", "multimodal"),
        "evidence": public_packet(
            packet, include_image=getattr(reviewer, "include_image", True)
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def summarize_pilot(records: list[dict[str, object]]) -> dict[str, object]:
    successful = [record for record in records if isinstance(record.get("result"), dict)]
    failures = [record for record in records if record.get("error")]
    truth: list[str] = []
    predicted: list[str] = []
    needs_mod_truth: list[bool] = []
    escalated: list[bool] = []
    accepted: list[bool] = []
    condition_total = 0
    condition_exact = 0
    condition_predictions = 0
    latencies: list[int] = []
    input_tokens = 0
    output_tokens = 0
    target_results: dict[str, Counter[str]] = {}

    for record in successful:
        target = TargetLabel(str(record["target"]))
        result = ReviewResult.model_validate(record["result"])
        target_counter = target_results.setdefault(target.value, Counter())
        target_counter[result.predicted_label().value] += 1
        needs_mod = target == TargetLabel.NEEDS_MODIFICATION
        needs_mod_truth.append(needs_mod)
        escalated.append(result.needs_modification)
        if result.latency_ms is not None:
            latencies.append(result.latency_ms)
        input_tokens += result.input_tokens or 0
        output_tokens += result.output_tokens or 0
        if target == TargetLabel.CONDITION_CHANGE:
            condition_total += 1
            if result.decision == Decision.CONDITION_CHANGE:
                condition_predictions += 1
                if result.predicted_condition_id == record.get("target_condition_id"):
                    condition_exact += 1
        if not needs_mod:
            truth.append(target.value)
            prediction = result.decision.value if result.decision else Decision.IGNORED.value
            predicted.append(prediction)
            accepted.append(not result.needs_modification)

    labels = [decision.value for decision in Decision]
    decision_metrics = classification_summary(
        truth,
        predicted,
        labels=labels,
        accepted=accepted,
        metadata={
            "successful_rows": len(successful),
            "failed_rows": len(failures),
            "excluded_needs_modification_rows": sum(needs_mod_truth),
        },
    )
    return {
        "requested_rows": len(records),
        "successful_rows": len(successful),
        "failed_rows": len(failures),
        "failure_types": dict(Counter(str(record["error"]).split(":", 1)[0] for record in failures)),
        "decision_metrics": decision_metrics.model_dump(mode="json"),
        "condition_id_metrics": {
            "support": condition_total,
            "exact_matches": condition_exact,
            "exact_accuracy": round(condition_exact / condition_total, 6)
            if condition_total
            else 0.0,
            "accuracy_given_condition_change_prediction": round(
                condition_exact / condition_predictions, 6
            )
            if condition_predictions
            else 0.0,
        },
        "historical_needs_mod_escalation_proxy": escalation_summary(
            needs_mod_truth, escalated
        ),
        "prediction_counts_by_historical_target": {
            target: dict(sorted(counts.items())) for target, counts in sorted(target_results.items())
        },
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "latency_p50_ms": _percentile(latencies, 0.50),
            "latency_p95_ms": _percentile(latencies, 0.95),
            "estimated_cost_usd": round(
                input_tokens / 1_000_000 * 1.50
                + output_tokens / 1_000_000 * 7.50,
                6,
            ),
            "pricing": {
                "input_per_million_usd": 1.50,
                "output_per_million_usd": 7.50,
            },
        },
    }


def run_multimodal_pilot(
    sales: list[NormalizedSale],
    *,
    reviewer: OpenAICompatibleReviewer,
    image_fetcher: ImageFetcher,
    checkpoint_path: Path,
    pricecharting_client: PriceChartingClient | None,
    max_failures: int,
    catalog_fetcher: CatalogFetcher | None = None,
    retry_errors: bool = False,
    request_interval_seconds: float = 0,
    max_quota_retries: int = 3,
    workers: int = 1,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if workers < 1:
        raise ValueError("workers must be positive")
    checkpoint = read_prediction_checkpoint(checkpoint_path)
    failures = 0 if retry_errors else sum(bool(row.get("error")) for row in checkpoint.values())
    prepared: list[tuple[int, dict[str, object], object, object, object]] = []
    for index, sale in enumerate(sales, start=1):
        prior = checkpoint.get(sale.identifier)
        record: dict[str, object] = {
            "sample_index": index,
            "identifier": sale.identifier,
            "product_id": sale.product_id,
            "target": sale.target.value if sale.target else None,
            "target_condition_id": sale.target_condition_id,
            "original_condition_id": sale.original_condition_id,
            "has_picture_url": bool(sale.picture_url),
        }
        try:
            product = fallback_product(sale.product_id, sale.product_title)
            enrichment_warnings: list[str] = []
            if pricecharting_client:
                try:
                    product = pricecharting_client.get_product(
                        sale.product_id, fallback_name=sale.product_title
                    )
                except Exception as exc:
                    record["enrichment_error"] = type(exc).__name__
                    enrichment_warnings.append(
                        f"assigned_product_api_unavailable:{type(exc).__name__}"
                    )
            candidates = []
            if pricecharting_client:
                try:
                    candidates = rank_candidates(
                        sale,
                        pricecharting_client.search_products(candidate_query(sale)),
                    )
                except Exception as exc:
                    record["candidate_search_error"] = type(exc).__name__
                    enrichment_warnings.append(
                        f"candidate_search_unavailable:{type(exc).__name__}"
                    )
            if getattr(reviewer, "include_image", True):
                image = image_fetcher.fetch(sale.identifier, sale.picture_url)
                catalog = (
                    catalog_fetcher.fetch(product) if catalog_fetcher else None
                )
                if catalog_fetcher:
                    candidates = enrich_candidate_catalogs(
                        candidates,
                        catalog_fetcher,
                        assigned_product_id=product.product_id,
                    )
            else:
                image = ImageEvidence(
                    available=bool(sale.picture_url),
                    usable=False,
                    error="disabled_for_ablation",
                )
                catalog = None
            packet = build_evidence_packet(
                sale,
                product,
                image,
                catalog,
                replacement_candidates=candidates,
                enrichment_warnings=enrichment_warnings,
            )
            fingerprint = evidence_fingerprint(packet, reviewer)
            record["input_fingerprint"] = fingerprint
            if (
                prior
                and prior.get("input_fingerprint") == fingerprint
                and not (retry_errors and prior.get("error"))
            ):
                continue
            record["product_source"] = product.source
            record["replacement_candidate_count"] = len(candidates)
            record["image_usable"] = image.usable
            record["image_error"] = image.error
            if catalog:
                record["catalog_image_usable"] = bool(
                    catalog.image and catalog.image.usable
                )
                record["catalog_product_id_verified"] = (
                    catalog.product_id_verified
                )
                record["catalog_error"] = catalog.error
            prepared.append((index, record, packet, product, image))
        except Exception as exc:
            failures += 1
            record["error"] = f"{type(exc).__name__}:{exc}"
            append_prediction(checkpoint_path, record)
            checkpoint[sale.identifier] = record
            print(f"[{index}/{len(sales)}] {sale.identifier}: error", flush=True)
            if failures >= max_failures:
                break

    def infer(
        item: tuple[int, dict[str, object], object, object, object]
    ) -> tuple[int, dict[str, object]]:
        index, record, packet, _, _ = item
        try:
            quota_attempt = 0
            while True:
                try:
                    result = reviewer.review(packet)
                    break
                except ProviderHTTPError as exc:
                    retryable_quota = (
                        exc.status_code == 429
                        and exc.retry_after_seconds is not None
                    )
                    retryable_transient = exc.status_code in {500, 502, 503, 504}
                    if (
                        not (retryable_quota or retryable_transient)
                        or quota_attempt >= max_quota_retries
                    ):
                        raise
                    quota_attempt += 1
                    wait_seconds = (
                        exc.retry_after_seconds + 1
                        if retryable_quota
                        else min(30.0, 5.0 * 2 ** (quota_attempt - 1))
                    )
                    print(
                        f"[{index}/{len(sales)}] provider wait "
                        f"{wait_seconds:.1f}s ({quota_attempt}/{max_quota_retries})",
                        flush=True,
                    )
                    time.sleep(wait_seconds)
            record["result"] = result.model_dump(mode="json")
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}:{exc}"
        return index, record

    def persist(index: int, record: dict[str, object]) -> None:
        nonlocal failures
        if record.get("error"):
            failures += 1
        append_prediction(checkpoint_path, record)
        checkpoint[str(record["identifier"])] = record
        result = record.get("result")
        outcome = (
            "error"
            if record.get("error")
            else result["decision"] or "needs_modification"
        )
        print(
            f"[{index}/{len(sales)}] {record['identifier']}: {outcome}",
            flush=True,
        )

    if workers == 1:
        last_model_request_at: float | None = None
        for item in prepared:
            if last_model_request_at is not None:
                elapsed = time.monotonic() - last_model_request_at
                if elapsed < request_interval_seconds:
                    time.sleep(request_interval_seconds - elapsed)
            last_model_request_at = time.monotonic()
            persist(*infer(item))
            if failures >= max_failures:
                break
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(infer, item) for item in prepared]
            for future in as_completed(futures):
                persist(*future.result())
    ordered: list[dict[str, object]] = []
    for index, sale in enumerate(sales, start=1):
        if sale.identifier not in checkpoint:
            continue
        # Labels are evaluation metadata, not part of the cached model response.
        current = dict(checkpoint[sale.identifier])
        current.update(
            {
                "sample_index": index,
                "target": sale.target.value if sale.target else None,
                "target_condition_id": sale.target_condition_id,
                "original_condition_id": sale.original_condition_id,
            }
        )
        ordered.append(current)
    return summarize_pilot(ordered), ordered
