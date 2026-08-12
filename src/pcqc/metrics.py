"""Dependency-free classification and selective-risk metrics."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from pcqc.models import EvaluationSummary


def classification_summary(
    truth: Sequence[str],
    predicted: Sequence[str],
    *,
    labels: Sequence[str],
    accepted: Sequence[bool] | None = None,
    metadata: dict[str, object] | None = None,
) -> EvaluationSummary:
    if len(truth) != len(predicted):
        raise ValueError("truth and predicted lengths differ")
    if accepted is not None and len(accepted) != len(truth):
        raise ValueError("accepted and truth lengths differ")
    matrix: dict[str, dict[str, int]] = {
        actual: {guess: 0 for guess in labels} for actual in labels
    }
    for actual, guess in zip(truth, predicted, strict=True):
        if actual not in matrix or guess not in matrix[actual]:
            raise ValueError(f"Unknown label pair: {actual!r}, {guess!r}")
        matrix[actual][guess] += 1

    per_class: dict[str, dict[str, float | int]] = {}
    f1_values: list[float] = []
    for label in labels:
        tp = matrix[label][label]
        fp = sum(matrix[actual][label] for actual in labels if actual != label)
        fn = sum(matrix[label][guess] for guess in labels if guess != label)
        support = sum(matrix[label].values())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        per_class[label] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": support,
        }

    correct = sum(actual == guess for actual, guess in zip(truth, predicted, strict=True))
    coverage = None
    covered_accuracy = None
    if accepted is not None:
        covered = [i for i, is_accepted in enumerate(accepted) if is_accepted]
        coverage = len(covered) / len(truth) if truth else 0.0
        covered_accuracy = (
            sum(truth[i] == predicted[i] for i in covered) / len(covered) if covered else 0.0
        )
    return EvaluationSummary(
        labels=list(labels),
        sample_count=len(truth),
        accuracy=round(correct / len(truth), 6) if truth else 0.0,
        macro_f1=round(sum(f1_values) / len(f1_values), 6) if f1_values else 0.0,
        per_class=per_class,
        confusion_matrix=matrix,
        coverage=None if coverage is None else round(coverage, 6),
        covered_accuracy=None if covered_accuracy is None else round(covered_accuracy, 6),
        metadata=dict(metadata or {}),
    )


def routing_summary(needs_modification: Sequence[bool], routed_to_human: Sequence[bool]) -> dict[str, float | int]:
    if len(needs_modification) != len(routed_to_human):
        raise ValueError("routing arrays differ in length")
    counts: defaultdict[str, int] = defaultdict(int)
    for actual, routed in zip(needs_modification, routed_to_human, strict=True):
        counts[("tp" if actual and routed else "fn" if actual else "fp" if routed else "tn")] += 1
    precision = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 0.0
    recall = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else 0.0
    return {
        "sample_count": len(needs_modification),
        "true_positive": counts["tp"],
        "false_positive": counts["fp"],
        "false_negative": counts["fn"],
        "true_negative": counts["tn"],
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "human_review_rate": round(sum(routed_to_human) / len(routed_to_human), 6)
        if routed_to_human
        else 0.0,
    }


def escalation_summary(
    historical_needs_modification: Sequence[bool],
    system_escalated: Sequence[bool],
) -> dict[str, float | int]:
    """Compare the POC's unresolved-evidence flag with the historical needsMod proxy."""
    summary = routing_summary(historical_needs_modification, system_escalated)
    summary["escalation_rate"] = summary.pop("human_review_rate")
    return summary
