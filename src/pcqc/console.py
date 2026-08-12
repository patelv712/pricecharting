"""Persistent POC run orchestration and UI-facing review projections."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import threading
import time
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from pcqc.catalog import CatalogFetcher, enrich_candidate_catalogs
from pcqc.candidates import candidate_query, rank_candidates
from pcqc.conditions import condition_name
from pcqc.config import Settings
from pcqc.evidence import build_evidence_packet
from pcqc.finish_provider import TargetedFinishReviewer
from pcqc.finish_workflow import FinishAwareReviewer
from pcqc.image import ImageFetcher
from pcqc.models import EvidencePacket, NormalizedSale, ReviewResult
from pcqc.pricecharting import PriceChartingClient, fallback_product
from pcqc.provider import OpenAICompatibleReviewer, public_packet
from pcqc.rules import RulesReviewer
from pcqc.version import REVIEW_POLICY_VERSION, RUN_SCHEMA_VERSION


RunMode = Literal["rules", "multimodal"]
RunStatus = Literal["queued", "running", "completed", "completed_with_errors", "failed"]
AdjudicationAction = Literal[
    "accepted",
    "keep",
    "delete",
    "change_condition",
    "reassign_product",
    "needs_follow_up",
]
ListingValidity = Literal["valid", "invalid", "uncertain"]
AssignmentVerdict = Literal["correct", "incorrect", "uncertain"]

MAX_RUN_ROWS = 100
PRODUCT_IDENTITY_DIMENSIONS = {
    "artwork",
    "event_or_release",
    "set_and_card_number",
    "language",
    "finish",
    "printing_or_parallel",
}
HISTORICAL_SALE_FIELDS = {
    "target",
    "target_condition_id",
    "review_action_condition_id",
    "status_raw",
    "review_date",
    "most_recent_report",
    "score",
}
INTERNAL_DIAGNOSTIC_CODES = {
    "discarded_irrelevant_predicted_condition_id",
}


class AdjudicationRequest(BaseModel):
    action: AdjudicationAction
    listing_validity: ListingValidity | None = None
    product_assignment: AssignmentVerdict | None = None
    condition_assignment: AssignmentVerdict | None = None
    condition_id: int | None = None
    replacement_product_id: str | None = None
    notes: str = Field(default="", max_length=2000)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _without_local_paths(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_local_paths(item)
            for key, item in value.items()
            if key not in {"cache_path", "crop_paths"}
        }
    if isinstance(value, list):
        return [_without_local_paths(item) for item in value]
    return value


def _public_record(record: dict[str, object]) -> dict[str, object]:
    value = deepcopy(record)
    sale = value.get("sale")
    if isinstance(sale, dict):
        history = value.setdefault("historical_outcome", {})
        if isinstance(history, dict) and "score" not in history and "score" in sale:
            history["score"] = sale["score"]
        for field in HISTORICAL_SALE_FIELDS:
            sale.pop(field, None)
    return value


def _recommended_actions(result: ReviewResult) -> list[str]:
    actions: list[str] = []
    comparisons = result.identity_comparison.model_dump()
    product_mismatch = any(
        comparisons[dimension] == "mismatch"
        for dimension in PRODUCT_IDENTITY_DIMENSIONS
    ) or bool(result.replacement_product_id)

    if result.decision and result.decision.value == "deleted":
        actions.append("delete")
    else:
        if product_mismatch:
            actions.append("reassign_product")
        if result.decision and result.decision.value == "condition_change":
            actions.append("change_condition")
        if result.needs_modification and not product_mismatch:
            actions.append("human_review")
        if not actions and result.decision and result.decision.value == "ignored":
            actions.append("keep")
    return actions or ["human_review"]


def project_review(result: ReviewResult) -> dict[str, object]:
    comparisons = result.identity_comparison.model_dump()
    product_mismatches = [
        dimension
        for dimension in PRODUCT_IDENTITY_DIMENSIONS
        if comparisons[dimension] == "mismatch"
    ]
    unresolved_dimensions = [
        dimension for dimension, value in comparisons.items() if value == "uncertain"
    ]
    if result.decision and result.decision.value == "deleted":
        listing_validity = "invalid"
    elif result.decision:
        listing_validity = "valid"
    else:
        listing_validity = "uncertain"
    if product_mismatches or result.replacement_product_id:
        product_assignment = "wrong"
    elif result.needs_modification:
        product_assignment = "uncertain"
    else:
        product_assignment = "correct"
    condition_assignment = (
        "corrected"
        if result.decision and result.decision.value == "condition_change"
        else "correct"
        if result.decision
        else "uncertain"
    )
    finish = result.finish_resolution
    all_evidence_codes = list(
        dict.fromkeys(
            result.rationale_codes
            + result.deterministic_evidence.identity_conflicts
            + result.deterministic_evidence.identity_warnings
            + result.deterministic_evidence.deletion_flags
            + result.deterministic_evidence.enrichment_warnings
        )
    )
    return {
        "recommended_actions": _recommended_actions(result),
        "listing_validity": listing_validity,
        "product_assignment": product_assignment,
        "condition_assignment": condition_assignment,
        "recommended_condition": (
            condition_name(result.predicted_condition_id)
            if result.predicted_condition_id
            else None
        ),
        "product_mismatches": sorted(product_mismatches),
        "unresolved_dimensions": sorted(unresolved_dimensions),
        "finish_status": finish.finish_match.value if finish else "unknown",
        "evidence_and_flags": [
            code for code in all_evidence_codes if code not in INTERNAL_DIAGNOSTIC_CODES
        ],
        "diagnostic_codes": [
            code for code in all_evidence_codes if code in INTERNAL_DIAGNOSTIC_CODES
        ],
    }


class ReviewEngine:
    """Prepare one evidence packet and run the selected reviewer."""

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.image_fetcher = ImageFetcher(config.cache_dir)
        self.catalog_fetcher = CatalogFetcher(config.cache_dir)
        self.pricecharting_client = (
            PriceChartingClient(config.pricecharting_api_token, config.cache_dir)
            if config.pricecharting_api_token
            else None
        )
        self._rules_reviewer = RulesReviewer()
        self._multimodal_reviewer = None

    def _reviewer(self, mode: RunMode):
        if mode == "rules":
            return self._rules_reviewer
        if not self.config.llm_api_key or not self.config.llm_model:
            raise RuntimeError("Gemini is not configured")
        if self._multimodal_reviewer is None:
            main = OpenAICompatibleReviewer(
                api_key=self.config.llm_api_key,
                base_url=self.config.llm_base_url,
                model=self.config.llm_model,
            )
            self._multimodal_reviewer = FinishAwareReviewer(
                main_reviewer=main,
                finish_reviewer=TargetedFinishReviewer(
                    api_key=self.config.llm_api_key,
                    base_url=self.config.llm_base_url,
                    model=self.config.finish_llm_model or self.config.llm_model,
                ),
                cache_dir=self.config.cache_dir,
            )
        return self._multimodal_reviewer

    def review(
        self, sale: NormalizedSale, mode: RunMode
    ) -> tuple[ReviewResult, EvidencePacket]:
        product = fallback_product(sale.product_id, sale.product_title)
        candidates = []
        enrichment_warnings: list[str] = []
        if self.pricecharting_client:
            try:
                product = self.pricecharting_client.get_product(
                    sale.product_id, fallback_name=sale.product_title
                )
            except Exception as exc:
                enrichment_warnings.append(
                    f"assigned_product_api_unavailable:{type(exc).__name__}"
                )
            try:
                candidates = rank_candidates(
                    sale,
                    self.pricecharting_client.search_products(candidate_query(sale)),
                )
            except Exception as exc:
                candidates = []
                enrichment_warnings.append(
                    f"candidate_search_unavailable:{type(exc).__name__}"
                )
        image = self.image_fetcher.fetch(sale.identifier, sale.picture_url)
        catalog = self.catalog_fetcher.fetch(product)
        candidates = enrich_candidate_catalogs(
            candidates,
            self.catalog_fetcher,
            assigned_product_id=product.product_id,
        )
        packet = build_evidence_packet(
            sale,
            product,
            image,
            catalog,
            replacement_candidates=candidates,
            enrichment_warnings=enrichment_warnings,
        )
        return self._reviewer(mode).review(packet), packet


class RunStore:
    """Small JSON-backed store intended for a single-user POC deployment."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, run_id: str) -> Path:
        if not run_id or any(char not in "0123456789abcdef" for char in run_id):
            raise KeyError(run_id)
        return self.root / f"{run_id}.json"

    def _write(self, run: dict[str, object]) -> None:
        path = self._path(str(run["id"]))
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(run, indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(path)

    @staticmethod
    def _hydrate_historical_scores(run: dict[str, object]) -> dict[str, object]:
        sales = run.get("sales", [])
        reviews = run.get("reviews", {})
        if not isinstance(sales, list) or not isinstance(reviews, dict):
            return run
        scores = {
            str(sale.get("identifier")): sale.get("score")
            for sale in sales
            if isinstance(sale, dict) and sale.get("identifier") is not None
        }
        for identifier, record in reviews.items():
            if not isinstance(record, dict):
                continue
            history = record.setdefault("historical_outcome", {})
            if (
                isinstance(history, dict)
                and "score" not in history
                and identifier in scores
            ):
                history["score"] = scores[identifier]
        return run

    def create(
        self,
        sales: list[NormalizedSale],
        *,
        filename: str,
        mode: RunMode,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        run_id = uuid.uuid4().hex[:12]
        run: dict[str, object] = {
            "schema_version": RUN_SCHEMA_VERSION,
            "id": run_id,
            "filename": Path(filename).name or "sales.csv",
            "mode": mode,
            "status": "queued",
            "created_at": utc_now(),
            "started_at": None,
            "completed_at": None,
            "total": len(sales),
            "processed": 0,
            "failed": 0,
            "sales": [sale.model_dump(mode="json") for sale in sales],
            "reviews": {},
        } | dict(metadata or {})
        with self._lock:
            self._write(run)
        return self.summary(run)

    def get(self, run_id: str) -> dict[str, object]:
        with self._lock:
            path = self._path(run_id)
            if not path.exists():
                raise KeyError(run_id)
            return self._hydrate_historical_scores(
                json.loads(path.read_text(encoding="utf-8"))
            )

    def save(self, run: dict[str, object]) -> None:
        with self._lock:
            self._write(run)

    def list(self) -> list[dict[str, object]]:
        runs = []
        with self._lock:
            for path in self.root.glob("*.json"):
                try:
                    runs.append(json.loads(path.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError):
                    continue
        runs.sort(key=lambda run: str(run.get("created_at", "")), reverse=True)
        return [self.summary(run) for run in runs]

    @staticmethod
    def summary(run: dict[str, object]) -> dict[str, object]:
        reviews = run.get("reviews", {})
        action_counts: dict[str, int] = {}
        reviewed = 0
        if isinstance(reviews, dict):
            for record in reviews.values():
                if not isinstance(record, dict):
                    continue
                ui = record.get("ui", {})
                if isinstance(ui, dict):
                    for action in ui.get("recommended_actions", []):
                        action_counts[str(action)] = action_counts.get(str(action), 0) + 1
                if record.get("adjudication"):
                    reviewed += 1
        return {
            key: deepcopy(run.get(key))
            for key in (
                "id",
                "filename",
                "mode",
                "status",
                "created_at",
                "started_at",
                "completed_at",
                "total",
                "processed",
                "failed",
                "schema_version",
                "policy_version",
                "prompt_version",
                "model_version",
                "input_sha256",
                "selection_strategy",
                "selection_requested_count",
                "selection_seed",
                "source_row_count",
            )
        } | {"action_counts": action_counts, "adjudicated": reviewed}


class ConsoleService:
    def __init__(
        self,
        config: Settings,
        *,
        store: RunStore | None = None,
        engine: ReviewEngine | None = None,
    ) -> None:
        self.config = config
        self.store = store or RunStore(config.cache_dir / "console-runs")
        self.engine = engine or ReviewEngine(config)
        self._processing_lock = threading.Lock()
        self.request_interval_seconds = float(
            os.getenv("PCQC_CONSOLE_REQUEST_INTERVAL_SECONDS", "0")
        )

    def create_run(
        self,
        sales: list[NormalizedSale],
        *,
        filename: str,
        mode: RunMode,
        selection_metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if not sales:
            raise ValueError("The CSV contains no sale rows")
        if len(sales) > MAX_RUN_ROWS:
            raise ValueError(f"A POC run is limited to {MAX_RUN_ROWS} rows")
        if mode == "multimodal" and (
            not self.config.llm_api_key or not self.config.llm_model
        ):
            raise ValueError("Gemini is not configured")
        reviewer = self.engine._reviewer(mode)
        canonical_input = json.dumps(
            [sale.model_dump(mode="json") for sale in sales],
            sort_keys=True,
            separators=(",", ":"),
        )
        metadata = {
            "policy_version": REVIEW_POLICY_VERSION,
            "prompt_version": getattr(reviewer, "prompt_version", "unknown"),
            "model_version": getattr(reviewer, "model", "unknown"),
            "input_sha256": hashlib.sha256(canonical_input.encode()).hexdigest(),
        } | dict(selection_metadata or {})
        return self.store.create(
            sales, filename=filename, mode=mode, metadata=metadata
        )

    def process_run(self, run_id: str) -> None:
        with self._processing_lock:
            self._process_run(run_id)

    def _process_run(self, run_id: str) -> None:
        run = self.store.get(run_id)
        run["status"] = "running"
        run["started_at"] = utc_now()
        self.store.save(run)
        sales = [NormalizedSale.model_validate(value) for value in run["sales"]]
        try:
            for index, sale in enumerate(sales):
                if index and run["mode"] == "multimodal" and self.request_interval_seconds:
                    time.sleep(self.request_interval_seconds)
                record: dict[str, object] = {
                    "identifier": sale.identifier,
                    "sale": sale.model_dump(
                        mode="json", exclude=HISTORICAL_SALE_FIELDS
                    ),
                    "historical_outcome": {
                        "target": sale.target.value if sale.target else None,
                        "target_condition_id": sale.target_condition_id,
                        "status_raw": sale.status_raw,
                        "score": sale.score,
                    },
                    "result": None,
                    "evidence": None,
                    "ui": {
                        "recommended_actions": ["human_review"],
                        "listing_validity": "uncertain",
                        "product_assignment": "uncertain",
                        "condition_assignment": "uncertain",
                        "evidence_and_flags": [],
                    },
                    "adjudication": None,
                    "error": None,
                }
                try:
                    result, packet = self.engine.review(sale, run["mode"])
                    record["result"] = _without_local_paths(
                        result.model_dump(mode="json")
                    )
                    record["evidence"] = _without_local_paths(
                        public_packet(packet, include_image=True)
                    )
                    record["ui"] = project_review(result)
                except Exception as exc:
                    record["error"] = f"{type(exc).__name__}:{str(exc)[:500]}"
                    run["failed"] = int(run["failed"]) + 1
                reviews = run["reviews"]
                assert isinstance(reviews, dict)
                reviews[sale.identifier] = record
                run["processed"] = int(run["processed"]) + 1
                self.store.save(run)
            run["status"] = (
                "completed_with_errors" if int(run["failed"]) else "completed"
            )
        except Exception:
            run["status"] = "failed"
            raise
        finally:
            run["completed_at"] = utc_now()
            self.store.save(run)

    def get_run(self, run_id: str) -> dict[str, object]:
        return self.store.summary(self.store.get(run_id))

    def list_runs(self) -> list[dict[str, object]]:
        return self.store.list()

    def list_reviews(
        self,
        run_id: str,
        *,
        action: str | None = None,
        adjudication: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, object]]:
        run = self.store.get(run_id)
        reviews = run.get("reviews", {})
        if not isinstance(reviews, dict):
            return []
        values: list[dict[str, object]] = []
        needle = (query or "").strip().lower()
        for record in reviews.values():
            if not isinstance(record, dict):
                continue
            ui = record.get("ui", {})
            actions = ui.get("recommended_actions", []) if isinstance(ui, dict) else []
            if action and action not in actions:
                continue
            current_adjudication = record.get("adjudication")
            if adjudication == "pending" and current_adjudication:
                continue
            if adjudication == "reviewed" and not current_adjudication:
                continue
            sale = record.get("sale", {})
            searchable = " ".join(
                str(value)
                for value in (
                    record.get("identifier", ""),
                    sale.get("sale_title", "") if isinstance(sale, dict) else "",
                    sale.get("product_title", "") if isinstance(sale, dict) else "",
                )
            ).lower()
            if needle and needle not in searchable:
                continue
            values.append(_public_record(record))
        values.sort(
            key=lambda record: int(
                (record.get("sale") or {}).get("sale_amount_pennies", 0)
            ),
            reverse=True,
        )
        return values

    def get_review(self, run_id: str, identifier: str) -> dict[str, object]:
        run = self.store.get(run_id)
        reviews = run.get("reviews", {})
        if not isinstance(reviews, dict) or identifier not in reviews:
            raise KeyError(identifier)
        return _public_record(reviews[identifier])

    def adjudicate(
        self, run_id: str, identifier: str, value: AdjudicationRequest
    ) -> dict[str, object]:
        run = self.store.get(run_id)
        reviews = run.get("reviews", {})
        if not isinstance(reviews, dict) or identifier not in reviews:
            raise KeyError(identifier)
        record = reviews[identifier]
        record["adjudication"] = value.model_dump(mode="json") | {
            "reviewed_at": utc_now()
        }
        self.store.save(run)
        return _public_record(record)

    def export_csv(self, run_id: str) -> str:
        rows = self.list_reviews(run_id)
        output = io.StringIO(newline="")
        fields = [
            "identifier",
            "sale_title",
            "assigned_product_id",
            "assigned_product_title",
            "sale_amount_pennies",
            "original_condition_id",
            "recommended_actions",
            "predicted_condition_id",
            "replacement_product_id",
            "needs_modification",
            "model",
            "model_decision",
            "model_confidence",
            "historical_status",
            "upstream_questionable_sale_score",
            "reason",
            "adjudication_action",
            "adjudication_listing_validity",
            "adjudication_product_assignment",
            "adjudication_condition_assignment",
            "adjudication_notes",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for record in rows:
            sale = record.get("sale") or {}
            result = record.get("result") or {}
            ui = record.get("ui") or {}
            adjudication = record.get("adjudication") or {}
            writer.writerow(
                {
                    "identifier": record.get("identifier"),
                    "sale_title": sale.get("sale_title"),
                    "assigned_product_id": sale.get("product_id"),
                    "assigned_product_title": sale.get("product_title"),
                    "sale_amount_pennies": sale.get("sale_amount_pennies"),
                    "original_condition_id": sale.get("original_condition_id"),
                    "recommended_actions": "|".join(ui.get("recommended_actions", [])),
                    "predicted_condition_id": result.get("predicted_condition_id"),
                    "replacement_product_id": result.get("replacement_product_id"),
                    "needs_modification": result.get("needs_modification"),
                    "model": result.get("model"),
                    "model_decision": result.get("decision"),
                    "model_confidence": "not_produced",
                    "historical_status": (
                        record.get("historical_outcome") or {}
                    ).get("status_raw"),
                    "upstream_questionable_sale_score": (
                        record.get("historical_outcome") or {}
                    ).get("score"),
                    "reason": result.get("reason"),
                    "adjudication_action": adjudication.get("action"),
                    "adjudication_listing_validity": adjudication.get(
                        "listing_validity"
                    ),
                    "adjudication_product_assignment": adjudication.get(
                        "product_assignment"
                    ),
                    "adjudication_condition_assignment": adjudication.get(
                        "condition_assignment"
                    ),
                    "adjudication_notes": adjudication.get("notes"),
                }
            )
        return output.getvalue()
