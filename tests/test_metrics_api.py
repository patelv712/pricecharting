from __future__ import annotations

from fastapi.testclient import TestClient

from pcqc.api import app, settings
from pcqc.evaluate import evaluate_sales
from pcqc.metrics import classification_summary, routing_summary
from pcqc.models import Decision, ReviewResult, Route, TargetLabel


def test_metric_calculation() -> None:
    report = classification_summary(
        ["ignored", "ignored", "deleted", "deleted"],
        ["ignored", "deleted", "deleted", "deleted"],
        labels=["ignored", "deleted"],
        accepted=[True, False, True, True],
    )
    assert report.accuracy == 0.75
    assert report.coverage == 0.75
    assert report.covered_accuracy == 1.0
    routes = routing_summary([True, False, True], [True, True, False])
    assert routes["precision"] == 0.5
    assert routes["recall"] == 0.5


def test_health_and_rule_review(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PCQC_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("PRICECHARTING_API_TOKEN", raising=False)
    settings.cache_clear()
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    response = client.post(
        "/check-sale",
        json={
            "identifier": "1",
            "product_id": "G123",
            "product_title": "Charizard Base Set",
            "sale_title": "Charizard Base Set PSA 10",
            "sale_amount_pennies": 100000,
            "original_condition_id": 1,
        },
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "condition_change"
    assert response.json()["predicted_condition_id"] == 7


def test_evaluation_separates_exact_condition_and_routing(sale) -> None:
    rows = [
        sale.model_copy(
            update={
                "identifier": "condition",
                "target": TargetLabel.CONDITION_CHANGE,
                "target_condition_id": 7,
            }
        ),
        sale.model_copy(update={"identifier": "needs-mod", "target": TargetLabel.NEEDS_MODIFICATION}),
    ]

    class FakeReviewer:
        def review(self, packet):
            if packet.sale.identifier == "needs-mod":
                return ReviewResult(
                    decision=None,
                    needs_modification=True,
                    route=Route.HUMAN_REVIEW,
                    reason="Insufficient evidence",
                    provider="test",
                    model="test",
                )
            return ReviewResult(
                decision=Decision.CONDITION_CHANGE,
                predicted_condition_id=7,
                route=Route.HUMAN_REVIEW,
                reason="Explicit grade",
                provider="test",
                model="test",
            )

    report, predictions = evaluate_sales(rows, FakeReviewer())
    assert report["condition_id_metrics"]["exact_accuracy"] == 1.0
    assert report["historical_needs_mod_escalation_proxy"]["recall"] == 1.0
    assert report["historical_needs_mod_escalation_proxy"]["escalation_rate"] == 0.5
    assert report["decision_metrics"]["coverage"] == 1.0
    assert len(predictions) == 2
