from __future__ import annotations

from pathlib import Path

from pcqc.provider import ProviderHTTPError
from pcqc.models import (
    Decision,
    ImageEvidence,
    ReviewResult,
    Route,
    TargetLabel,
)
from pcqc.pilot import (
    read_prediction_checkpoint,
    run_multimodal_pilot,
    stratified_target_sample,
    stratified_pilot_sample,
    summarize_pilot,
)


def _result(
    decision: Decision | None,
    *,
    condition_id: int | None = None,
    needs_modification: bool = False,
    route: Route = Route.HUMAN_REVIEW,
) -> ReviewResult:
    return ReviewResult(
        decision=decision,
        predicted_condition_id=condition_id,
        needs_modification=needs_modification,
        route=route,
        reason="test",
        provider="test",
        model="test",
        latency_ms=100,
        input_tokens=10,
        output_tokens=5,
    )


def test_stratified_sample_is_deterministic_and_includes_missing_images(sale) -> None:
    rows = []
    for target in TargetLabel:
        for index in range(4):
            rows.append(
                sale.model_copy(
                    update={
                        "identifier": f"{target.value}-{index}",
                        "product_id": f"{target.value}-{index}".replace("_", ""),
                        "target": target,
                        "target_condition_id": 7
                        if target == TargetLabel.CONDITION_CHANGE
                        else None,
                        "original_condition_id": 1,
                        "picture_url": None if index == 0 else f"https://example.test/{index}.jpg",
                    }
                )
            )
    first = stratified_pilot_sample(rows, per_target=3, seed="stable")
    second = stratified_pilot_sample(rows, per_target=3, seed="stable")
    assert [row.identifier for row in first] == [row.identifier for row in second]
    assert len(first) == 12
    for target in TargetLabel:
        target_rows = [row for row in first if row.target == target]
        assert len(target_rows) == 3
        assert any(row.picture_url is None for row in target_rows)


def test_target_count_sample_supports_poc_profile(sale) -> None:
    rows = []
    counts = {
        TargetLabel.IGNORED: 3,
        TargetLabel.DELETED: 3,
        TargetLabel.CONDITION_CHANGE: 3,
        TargetLabel.NEEDS_MODIFICATION: 1,
    }
    for target, count in counts.items():
        for index in range(count + 2):
            rows.append(
                sale.model_copy(
                    update={
                        "identifier": f"{target.value}-{index}",
                        "product_id": f"{target.value}-{index}",
                        "target": target,
                        "target_condition_id": (
                            7 if target == TargetLabel.CONDITION_CHANGE else None
                        ),
                        "original_condition_id": 1,
                    }
                )
            )
    sample = stratified_target_sample(rows, target_counts=counts, seed="stable")
    assert len(sample) == 10
    assert {
        target: sum(row.target == target for row in sample) for target in counts
    } == counts


def test_sample_excludes_post_review_condition_state(sale) -> None:
    rows = []
    for target in TargetLabel:
        for index in range(2):
            rows.append(
                sale.model_copy(
                    update={
                        "identifier": f"{target.value}-{index}",
                        "target": target,
                        "target_condition_id": 7
                        if target == TargetLabel.CONDITION_CHANGE
                        else None,
                        "original_condition_id": 1,
                    }
                )
            )
    rows.append(
        sale.model_copy(
            update={
                "identifier": "ambiguous-condition-state",
                "target": TargetLabel.CONDITION_CHANGE,
                "target_condition_id": 7,
                "original_condition_id": 7,
            }
        )
    )
    sample = stratified_pilot_sample(rows, per_target=2, seed="stable")
    assert "ambiguous-condition-state" not in {row.identifier for row in sample}


def test_pilot_checkpoints_and_resumes(tmp_path: Path, sale) -> None:
    rows = [
        sale.model_copy(update={"identifier": "ignored", "target": TargetLabel.IGNORED}),
        sale.model_copy(
            update={
                "identifier": "condition",
                "target": TargetLabel.CONDITION_CHANGE,
                "target_condition_id": 7,
            }
        ),
        sale.model_copy(
            update={"identifier": "needs", "target": TargetLabel.NEEDS_MODIFICATION}
        ),
    ]

    class FakeReviewer:
        calls = 0

        def review(self, packet):
            self.calls += 1
            if packet.sale.target == TargetLabel.CONDITION_CHANGE:
                return _result(Decision.CONDITION_CHANGE, condition_id=7)
            if packet.sale.target == TargetLabel.NEEDS_MODIFICATION:
                return _result(
                    None,
                    needs_modification=True,
                    route=Route.HUMAN_REVIEW,
                )
            return _result(Decision.IGNORED)

    class FakeImageFetcher:
        def fetch(self, identifier, url):
            return ImageEvidence(available=True, usable=True, content_type="image/jpeg")

    reviewer = FakeReviewer()
    checkpoint = tmp_path / "predictions.jsonl"
    report, records = run_multimodal_pilot(
        rows,
        reviewer=reviewer,
        image_fetcher=FakeImageFetcher(),
        checkpoint_path=checkpoint,
        pricecharting_client=None,
        max_failures=2,
    )
    assert reviewer.calls == 3
    assert report["successful_rows"] == 3
    assert report["condition_id_metrics"]["exact_accuracy"] == 1.0
    assert report["historical_needs_mod_escalation_proxy"]["recall"] == 1.0
    assert report["historical_needs_mod_escalation_proxy"]["escalation_rate"] == round(1 / 3, 6)
    assert report["decision_metrics"]["coverage"] == 1.0
    assert len(records) == 3
    assert len(read_prediction_checkpoint(checkpoint)) == 3

    resumed_report, _ = run_multimodal_pilot(
        rows,
        reviewer=reviewer,
        image_fetcher=FakeImageFetcher(),
        checkpoint_path=checkpoint,
        pricecharting_client=None,
        max_failures=2,
    )
    assert reviewer.calls == 3
    assert resumed_report == report


def test_summary_keeps_failures_out_of_accuracy() -> None:
    records = [
        {
            "identifier": "ok",
            "target": "deleted",
            "target_condition_id": None,
            "result": _result(Decision.DELETED).model_dump(mode="json"),
        },
        {
            "identifier": "failed",
            "target": "ignored",
            "target_condition_id": None,
            "error": "TimeoutError:provider timeout",
        },
    ]
    report = summarize_pilot(records)
    assert report["requested_rows"] == 2
    assert report["successful_rows"] == 1
    assert report["failed_rows"] == 1
    assert report["decision_metrics"]["accuracy"] == 1.0
    assert report["usage"]["total_tokens"] == 15


def test_retry_errors_replaces_failed_checkpoint_row(tmp_path: Path, sale) -> None:
    checkpoint = tmp_path / "predictions.jsonl"

    class FlakyReviewer:
        calls = 0

        def review(self, packet):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary")
            return _result(Decision.IGNORED)

    class FakeImageFetcher:
        def fetch(self, identifier, url):
            return ImageEvidence(available=True, usable=True, content_type="image/jpeg")

    reviewer = FlakyReviewer()
    first_report, _ = run_multimodal_pilot(
        [sale],
        reviewer=reviewer,
        image_fetcher=FakeImageFetcher(),
        checkpoint_path=checkpoint,
        pricecharting_client=None,
        max_failures=1,
    )
    assert first_report["failed_rows"] == 1
    second_report, records = run_multimodal_pilot(
        [sale],
        reviewer=reviewer,
        image_fetcher=FakeImageFetcher(),
        checkpoint_path=checkpoint,
        pricecharting_client=None,
        max_failures=1,
        retry_errors=True,
    )
    assert second_report["failed_rows"] == 0
    assert second_report["successful_rows"] == 1
    assert records[0]["result"]["decision"] == "ignored"


def test_pilot_retries_quota_without_recording_failure(tmp_path: Path, sale, monkeypatch) -> None:
    waits = []

    class QuotaReviewer:
        calls = 0

        def review(self, packet):
            self.calls += 1
            if self.calls == 1:
                error = ProviderHTTPError(429, "Please retry in 2.5s.")
                raise error
            return _result(Decision.IGNORED)

    class FakeImageFetcher:
        def fetch(self, identifier, url):
            return ImageEvidence(available=True, usable=True, content_type="image/jpeg")

    monkeypatch.setattr("pcqc.pilot.time.sleep", waits.append)
    report, _ = run_multimodal_pilot(
        [sale],
        reviewer=QuotaReviewer(),
        image_fetcher=FakeImageFetcher(),
        checkpoint_path=tmp_path / "predictions.jsonl",
        pricecharting_client=None,
        max_failures=1,
        max_quota_retries=1,
    )
    assert report["successful_rows"] == 1
    assert report["failed_rows"] == 0
    assert waits == [3.5]


def test_checkpoint_is_invalidated_when_same_listing_input_changes(tmp_path: Path, sale) -> None:
    class CountingReviewer:
        model = "test-model"
        calls = 0

        def review(self, packet):
            self.calls += 1
            return _result(Decision.IGNORED)

    class FakeImageFetcher:
        def fetch(self, identifier, url):
            return ImageEvidence(
                available=True,
                usable=True,
                content_type="image/jpeg",
                sha256="image-hash",
            )

    reviewer = CountingReviewer()
    checkpoint = tmp_path / "predictions.jsonl"
    kwargs = {
        "reviewer": reviewer,
        "image_fetcher": FakeImageFetcher(),
        "checkpoint_path": checkpoint,
        "pricecharting_client": None,
        "max_failures": 1,
    }
    run_multimodal_pilot([sale], **kwargs)
    run_multimodal_pilot([sale], **kwargs)
    assert reviewer.calls == 1

    changed = sale.model_copy(update={"sale_title": "A completely different listing"})
    run_multimodal_pilot([changed], **kwargs)
    assert reviewer.calls == 2


def test_checkpoint_label_change_updates_metrics_without_new_inference(tmp_path: Path, sale) -> None:
    class CountingReviewer:
        model = "test-model"
        calls = 0

        def review(self, packet):
            self.calls += 1
            return _result(Decision.IGNORED)

    class FakeImageFetcher:
        def fetch(self, identifier, url):
            return ImageEvidence(
                available=True,
                usable=True,
                content_type="image/jpeg",
                sha256="image-hash",
            )

    reviewer = CountingReviewer()
    checkpoint = tmp_path / "predictions.jsonl"
    kwargs = {
        "reviewer": reviewer,
        "image_fetcher": FakeImageFetcher(),
        "checkpoint_path": checkpoint,
        "pricecharting_client": None,
        "max_failures": 1,
    }
    run_multimodal_pilot([sale], **kwargs)
    relabeled = sale.model_copy(update={"target": TargetLabel.DELETED})
    report, records = run_multimodal_pilot([relabeled], **kwargs)
    assert reviewer.calls == 1
    assert records[0]["target"] == "deleted"
    assert report["decision_metrics"]["accuracy"] == 0.0
