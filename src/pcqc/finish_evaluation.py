"""Metrics for independently labeled finish-resolution artifacts."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from statistics import median

from pydantic import BaseModel, ConfigDict

from pcqc.models import FinishMatch, FinishResolution, FinishType


class FinishBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str
    assigned_product_id: str
    expected_assigned_finish: FinishType
    expected_observed_finish: FinishType
    expected_finish_match: FinishMatch
    expected_replacement_product_id: str | None = None
    visually_determinable: bool
    adjudication_status: str
    evidence_notes: list[str]


class FinishBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    purpose: str
    limitations: list[str]
    cases: list[FinishBenchmarkCase]


def read_finish_benchmark(path: Path) -> FinishBenchmark:
    return FinishBenchmark.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_finish_results(
    benchmark: FinishBenchmark, results_dir: Path
) -> dict[str, object]:
    exact_finish = 0
    exact_assigned = 0
    exact_replacement = 0
    replacement_support = 0
    expected_mismatch = 0
    detected_mismatch = 0
    predicted_mismatch = 0
    correct_predicted_mismatch = 0
    unsafe_false_matches: list[str] = []
    unknown = 0
    missing: list[str] = []
    specialist_latencies: list[int] = []
    specialist_input_tokens = 0
    specialist_output_tokens = 0
    specialist_billable_output_tokens = 0
    specialist_costs: list[float] = []
    per_finish: dict[str, Counter[str]] = {}

    for case in benchmark.cases:
        path = results_dir / f"{case.identifier}.json"
        if not path.exists():
            missing.append(case.identifier)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        resolution = FinishResolution.model_validate(payload["resolution"])
        if resolution.provider_metadata:
            metadata = resolution.provider_metadata
            specialist_latencies.append(metadata.latency_ms)
            specialist_input_tokens += metadata.input_tokens or 0
            specialist_output_tokens += metadata.output_tokens or 0
            specialist_billable_output_tokens += metadata.billable_output_tokens or 0
            if metadata.estimated_cost_usd is not None:
                specialist_costs.append(metadata.estimated_cost_usd)
        if resolution.assigned_finish == case.expected_assigned_finish:
            exact_assigned += 1
        if resolution.observed_finish == case.expected_observed_finish:
            exact_finish += 1
        if resolution.finish_match == FinishMatch.UNKNOWN:
            unknown += 1
        if case.expected_finish_match == FinishMatch.MISMATCH:
            expected_mismatch += 1
            if resolution.finish_match == FinishMatch.MISMATCH:
                detected_mismatch += 1
            if resolution.finish_match == FinishMatch.MATCH:
                unsafe_false_matches.append(case.identifier)
        if resolution.finish_match == FinishMatch.MISMATCH:
            predicted_mismatch += 1
            if case.expected_finish_match == FinishMatch.MISMATCH:
                correct_predicted_mismatch += 1
        if case.expected_replacement_product_id is not None:
            replacement_support += 1
            if (
                resolution.replacement_product_id
                == case.expected_replacement_product_id
            ):
                exact_replacement += 1
        finish_counter = per_finish.setdefault(
            case.expected_observed_finish.value, Counter()
        )
        finish_counter["support"] += 1
        if resolution.observed_finish == case.expected_observed_finish:
            finish_counter["exact"] += 1

    completed = len(benchmark.cases) - len(missing)
    ordered_latencies = sorted(specialist_latencies)
    p95_index = max(0, math.ceil(len(ordered_latencies) * 0.95) - 1) if ordered_latencies else 0
    return {
        "benchmark_case_count": len(benchmark.cases),
        "completed_case_count": completed,
        "missing_identifiers": missing,
        "seed_only_not_statistically_valid": len(benchmark.cases) < 100,
        "assigned_finish_accuracy": round(exact_assigned / completed, 6)
        if completed
        else 0.0,
        "observed_finish_accuracy": round(exact_finish / completed, 6)
        if completed
        else 0.0,
        "finish_mismatch_recall": round(detected_mismatch / expected_mismatch, 6)
        if expected_mismatch
        else 0.0,
        "finish_mismatch_precision": round(
            correct_predicted_mismatch / predicted_mismatch, 6
        )
        if predicted_mismatch
        else 0.0,
        "exact_replacement_accuracy": round(
            exact_replacement / replacement_support, 6
        )
        if replacement_support
        else 0.0,
        "unknown_rate": round(unknown / completed, 6) if completed else 0.0,
        "unsafe_false_match_count": len(unsafe_false_matches),
        "unsafe_false_match_identifiers": unsafe_false_matches,
        "specialist_measurement_count": len(specialist_latencies),
        "specialist_latency_ms_p50": round(median(ordered_latencies), 3)
        if ordered_latencies
        else None,
        "specialist_latency_ms_p95": ordered_latencies[p95_index]
        if ordered_latencies
        else None,
        "specialist_input_tokens_total": specialist_input_tokens,
        "specialist_output_tokens_total": specialist_output_tokens,
        "specialist_billable_output_tokens_total": specialist_billable_output_tokens,
        "specialist_estimated_cost_usd_total": round(sum(specialist_costs), 8)
        if specialist_costs
        else None,
        "per_finish": {
            finish: {
                "support": counts["support"],
                "exact_accuracy": round(counts["exact"] / counts["support"], 6),
            }
            for finish, counts in sorted(per_finish.items())
        },
    }
