from __future__ import annotations

import json

from pcqc.finish_evaluation import evaluate_finish_results, read_finish_benchmark
from pcqc.models import FinishProviderMetadata, FinishResolution


def test_finish_evaluation_reports_unsafe_matches(tmp_path) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "purpose": "test",
                "limitations": ["small"],
                "cases": [
                    {
                        "identifier": "mismatch",
                        "assigned_product_id": "1",
                        "expected_assigned_finish": "regular",
                        "expected_observed_finish": "reverse_holo",
                        "expected_finish_match": "mismatch",
                        "expected_replacement_product_id": "2",
                        "visually_determinable": True,
                        "adjudication_status": "test",
                        "evidence_notes": ["test"],
                    }
                ],
            }
        )
    )
    results = tmp_path / "results"
    results.mkdir()
    resolution = FinishResolution(
        assigned_finish="regular",
        observed_finish="regular",
        finish_match="match",
        provider_metadata=FinishProviderMetadata(
            provider="test",
            model="finish-model",
            prompt_version="v1",
            latency_ms=100,
            input_tokens=50,
            output_tokens=10,
            billable_output_tokens=20,
            total_tokens=70,
            estimated_cost_usd=0.001,
        ),
    )
    (results / "mismatch.json").write_text(
        json.dumps({"resolution": resolution.model_dump(mode="json")})
    )
    report = evaluate_finish_results(read_finish_benchmark(benchmark_path), results)
    assert report["unsafe_false_match_count"] == 1
    assert report["unsafe_false_match_identifiers"] == ["mismatch"]
    assert report["finish_mismatch_recall"] == 0
    assert report["specialist_latency_ms_p50"] == 100
    assert report["specialist_input_tokens_total"] == 50
    assert report["specialist_billable_output_tokens_total"] == 20
    assert report["specialist_estimated_cost_usd_total"] == 0.001
