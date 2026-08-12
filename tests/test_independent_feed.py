from __future__ import annotations

from pathlib import Path

from pcqc.io import read_sales
from pcqc.models import Decision, ImageEvidence, ReviewResult, Route, TargetLabel
from pcqc.pilot import run_multimodal_pilot


def test_independent_feed_runs_without_original_dataset(tmp_path: Path) -> None:
    feed = tmp_path / "independent-sales.csv"
    header = (
        "identifier,status,review-date,most-recent-report,unified-id,product-title,"
        "sale-title,sale-amount-pennies,score,broad-category,condition-id,picture-url\n"
    )
    feed.write_text(
        header
        + "new-ignored,ignored,2026-07-29,2026-07-29,G900001,New Card A,"
        "New Card A raw,1000,1,trading-cards,1,\n"
        + "new-deleted,deleted,2026-07-29,2026-07-29,G900002,New Card B,"
        "New Card B bundle lot,2000,2,trading-cards,1,\n"
        + "new-condition,gradednew,2026-07-29,2026-07-29,G900003,New Card C,"
        "New Card C PSA 9,3000,3,trading-cards,1,\n"
        + "new-needs-mod,needsMod,2026-07-29,2026-07-29,G900004,New Card D,"
        "Different valid card,4000,4,trading-cards,1,\n",
        encoding="utf-8",
    )
    sales = read_sales(feed)
    assert {sale.product_id for sale in sales} == {
        "900001",
        "900002",
        "900003",
        "900004",
    }

    class IndependentReviewer:
        model = "independent-test-model"
        calls = 0

        def review(self, packet):
            self.calls += 1
            if "bundle" in packet.sale.sale_title:
                decision = Decision.DELETED
                condition_id = None
                needs_modification = False
                route = Route.HUMAN_REVIEW
            elif "PSA 9" in packet.sale.sale_title:
                decision = Decision.CONDITION_CHANGE
                condition_id = 5
                needs_modification = False
                route = Route.HUMAN_REVIEW
            elif "Different" in packet.sale.sale_title:
                decision = None
                condition_id = None
                needs_modification = True
                route = Route.HUMAN_REVIEW
            else:
                decision = Decision.IGNORED
                condition_id = None
                needs_modification = False
                route = Route.HUMAN_REVIEW
            return ReviewResult(
                decision=decision,
                predicted_condition_id=condition_id,
                needs_modification=needs_modification,
                route=route,
                reason="Independent feed test",
                provider="test",
                model=self.model,
            )

    class MissingImageFetcher:
        def fetch(self, identifier, url):
            return ImageEvidence(available=False, usable=False, error="missing_url")

    reviewer = IndependentReviewer()
    report, records = run_multimodal_pilot(
        sales,
        reviewer=reviewer,
        image_fetcher=MissingImageFetcher(),
        checkpoint_path=tmp_path / "independent-predictions.jsonl",
        pricecharting_client=None,
        max_failures=1,
    )
    assert reviewer.calls == 4
    assert report["decision_metrics"]["accuracy"] == 1.0
    assert report["condition_id_metrics"]["exact_accuracy"] == 1.0
    assert report["historical_needs_mod_escalation_proxy"]["recall"] == 1.0
    assert all(record.get("input_fingerprint") for record in records)
    assert records[-1]["target"] == TargetLabel.NEEDS_MODIFICATION.value
