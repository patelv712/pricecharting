"""Evaluation orchestration for labeled reviewed-sale exports."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from pcqc.evidence import build_evidence_packet
from pcqc.metrics import classification_summary, escalation_summary
from pcqc.models import Decision, NormalizedSale, ReviewResult, TargetLabel
from pcqc.pricecharting import fallback_product


class Reviewer(Protocol):
    def review(self, packet: object) -> ReviewResult: ...


def evaluate_sales(
    sales: Iterable[NormalizedSale],
    reviewer: Reviewer,
    *,
    product_resolver: Callable[[NormalizedSale], object] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    rows = list(sales)
    predictions: list[dict[str, object]] = []
    truth: list[str] = []
    guessed: list[str] = []
    needs_mod_truth: list[bool] = []
    escalated: list[bool] = []
    accepted: list[bool] = []
    condition_total = 0
    condition_exact = 0
    condition_change_predictions = 0

    for sale in rows:
        product = (
            product_resolver(sale)
            if product_resolver
            else fallback_product(sale.product_id, sale.product_title)
        )
        packet = build_evidence_packet(sale, product)
        result = reviewer.review(packet)
        predictions.append(
            {
                "identifier": sale.identifier,
                "product_id": sale.product_id,
                "target": sale.target.value if sale.target else None,
                "target_condition_id": sale.target_condition_id,
                "result": result.model_dump(mode="json"),
            }
        )
        is_needs_mod = sale.target == TargetLabel.NEEDS_MODIFICATION
        needs_mod_truth.append(is_needs_mod)
        escalated.append(result.needs_modification)
        if sale.target == TargetLabel.CONDITION_CHANGE:
            condition_total += 1
            if result.decision == Decision.CONDITION_CHANGE:
                condition_change_predictions += 1
                if result.predicted_condition_id == sale.target_condition_id:
                    condition_exact += 1
        if not is_needs_mod and sale.target is not None:
            truth.append(sale.target.value)
            guessed.append(result.decision.value if result.decision else Decision.IGNORED.value)
            accepted.append(not result.needs_modification)

    labels = [Decision.IGNORED.value, Decision.DELETED.value, Decision.CONDITION_CHANGE.value]
    decision_metrics = classification_summary(
        truth,
        guessed,
        labels=labels,
        accepted=accepted,
        metadata={"excluded_needs_modification_rows": sum(needs_mod_truth)},
    )
    report: dict[str, object] = {
        "decision_metrics": decision_metrics.model_dump(mode="json"),
        "condition_id_metrics": {
            "support": condition_total,
            "exact_matches": condition_exact,
            "exact_accuracy": round(condition_exact / condition_total, 6)
            if condition_total
            else 0.0,
            "accuracy_given_condition_change_prediction": round(
                condition_exact / condition_change_predictions, 6
            )
            if condition_change_predictions
            else 0.0,
        },
        "historical_needs_mod_escalation_proxy": escalation_summary(
            needs_mod_truth, escalated
        ),
    }
    return report, predictions
