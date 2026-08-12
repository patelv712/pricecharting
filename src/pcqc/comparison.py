"""Paired evaluation comparison and disagreement export."""

from __future__ import annotations

import json
from pathlib import Path

from pcqc.io import read_sales
from pcqc.models import TargetLabel
from pcqc.pilot import read_prediction_checkpoint


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _prediction_label(record: dict[str, object]) -> str | None:
    result = record.get("result")
    if not isinstance(result, dict):
        return None
    if result.get("needs_modification"):
        return TargetLabel.NEEDS_MODIFICATION.value
    decision = result.get("decision")
    return str(decision) if decision is not None else None


def _prediction_decision(record: dict[str, object]) -> str | None:
    result = record.get("result")
    if not isinstance(result, dict):
        return None
    decision = result.get("decision")
    return str(decision) if decision is not None else "ignored"


def compare_evaluations(
    *,
    sales_path: Path,
    evaluation_dirs: dict[str, Path],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    manifests = {
        mode: _load_json(path / "gemini-pilot-manifest.json")
        for mode, path in evaluation_dirs.items()
    }
    reports = {
        mode: _load_json(path / "gemini-pilot-report.json")
        for mode, path in evaluation_dirs.items()
    }
    predictions = {
        mode: read_prediction_checkpoint(path / "gemini-pilot-predictions.jsonl")
        for mode, path in evaluation_dirs.items()
    }
    sample_ids = {
        mode: [str(row["identifier"]) for row in manifest["sample"]]
        for mode, manifest in manifests.items()
    }
    first_mode = next(iter(sample_ids))
    expected_ids = sample_ids[first_mode]
    if any(ids != expected_ids for ids in sample_ids.values()):
        raise ValueError("Evaluation cohorts differ; paired comparison is invalid")
    final_fingerprints = {
        str(manifest["partition_fingerprints"]["final"])
        for manifest in manifests.values()
    }
    if len(final_fingerprints) != 1:
        raise ValueError("Final partition fingerprints differ")

    sales = {sale.identifier: sale for sale in read_sales(sales_path)}
    disagreements: list[dict[str, object]] = []
    image_improved = 0
    image_degraded = 0
    image_unchanged = 0
    action_improved = 0
    action_degraded = 0
    action_unchanged = 0
    for identifier in expected_ids:
        labels = {
            mode: _prediction_label(rows.get(identifier, {}))
            for mode, rows in predictions.items()
        }
        decisions = {
            mode: _prediction_decision(rows.get(identifier, {}))
            for mode, rows in predictions.items()
        }
        sale = sales[identifier]
        if len(set(labels.values())) > 1:
            disagreements.append(
                {
                    "identifier": identifier,
                    "target": sale.target.value if sale.target else None,
                    "product_id": sale.product_id,
                    "product_title": sale.product_title,
                    "sale_title": sale.sale_title,
                    "picture_url": sale.picture_url,
                    "labels": labels,
                    "decisions": decisions,
                    "reasons": {
                        mode: (
                            rows[identifier].get("result", {}).get("reason")
                            if isinstance(rows.get(identifier, {}).get("result"), dict)
                            else rows.get(identifier, {}).get("error")
                        )
                        for mode, rows in predictions.items()
                    },
                }
            )
        if (
            sale.target not in (None, TargetLabel.NEEDS_MODIFICATION)
            and labels.get("text-only") is not None
            and labels.get("multimodal") is not None
        ):
            text_correct = decisions["text-only"] == sale.target.value
            image_correct = decisions["multimodal"] == sale.target.value
            if image_correct and not text_correct:
                image_improved += 1
            elif text_correct and not image_correct:
                image_degraded += 1
            else:
                image_unchanged += 1
            text_action_correct = labels["text-only"] == sale.target.value
            image_action_correct = labels["multimodal"] == sale.target.value
            if image_action_correct and not text_action_correct:
                action_improved += 1
            elif text_action_correct and not image_action_correct:
                action_degraded += 1
            else:
                action_unchanged += 1

    summary = {
        "cohort_size": len(expected_ids),
        "cohort_identical_across_modes": True,
        "final_partition_fingerprint": next(iter(final_fingerprints)),
        "modes": {
            mode: {
                "model": report.get("model"),
                "decision_metrics": report.get("decision_metrics"),
                "condition_id_metrics": report.get("condition_id_metrics"),
                "escalation_metrics": report.get(
                    "historical_needs_mod_escalation_proxy",
                    report.get("historical_needs_mod_routing_proxy"),
                ),
                "usage": report.get("usage"),
            }
            for mode, report in reports.items()
        },
        "paired_image_decision_effect": {
            "resolved_support": image_improved + image_degraded + image_unchanged,
            "image_improved": image_improved,
            "image_degraded": image_degraded,
            "unchanged_correctness": image_unchanged,
            "net_improvement": image_improved - image_degraded,
        },
        "paired_image_action_effect": {
            "resolved_support": action_improved + action_degraded + action_unchanged,
            "image_improved": action_improved,
            "image_degraded": action_degraded,
            "unchanged_correctness": action_unchanged,
            "net_improvement": action_improved - action_degraded,
            "definition": "Unresolved-evidence escalations count as different from resolved labels.",
        },
        "disagreement_count": len(disagreements),
    }
    return summary, disagreements


def comparison_markdown(summary: dict[str, object]) -> str:
    lines = [
        "# Paired Validation Comparison",
        "",
        f"- Cohort size: {summary['cohort_size']}",
        f"- Cross-mode cohort identity verified: {summary['cohort_identical_across_modes']}",
        f"- Disagreements: {summary['disagreement_count']}",
        "",
        "| Mode | Accuracy | Macro-F1 | Deleted precision | Condition ID accuracy | "
        "Escalation rate | Cost | p50 latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, values in summary["modes"].items():
        decision = values["decision_metrics"]
        condition = values["condition_id_metrics"]
        escalation = values["escalation_metrics"]
        usage = values["usage"]
        escalation_rate = escalation.get(
            "escalation_rate", escalation.get("human_review_rate", 0)
        )
        lines.append(
            f"| {mode} | {decision['accuracy']:.3f} | {decision['macro_f1']:.3f} | "
            f"{decision['per_class']['deleted']['precision']:.3f} | "
            f"{condition['exact_accuracy']:.3f} | {escalation_rate:.3f} | "
            f"${usage['estimated_cost_usd']:.4f} | {usage['latency_p50_ms'] or 0} ms |"
        )
    effect = summary["paired_image_decision_effect"]
    lines.extend(
        [
            "",
            "## Paired Image Effect",
            "",
            f"- Image improved correctness: {effect['image_improved']}",
            f"- Image degraded correctness: {effect['image_degraded']}",
            f"- Net improvement: {effect['net_improvement']}",
            "",
            "No AI-generated confidence score is used by the active reviewer contract.",
        ]
    )
    return "\n".join(lines) + "\n"
