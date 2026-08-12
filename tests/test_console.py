from __future__ import annotations

import csv
from io import StringIO

from fastapi.testclient import TestClient

from pcqc.api import app, console_service
from pcqc.config import Settings
from pcqc.console import (
    AdjudicationRequest,
    ConsoleService,
    RunStore,
    project_review,
)
from pcqc.io import read_sales_text
from pcqc.models import ReviewResult


UNLABELED_CSV = """identifier,unified-id,product-title,sale-title,sale-amount-pennies,broad-category,condition-id,picture-url
sale-1,G100,Card One,Card One PSA 10,12500,trading-cards,1,
sale-2,G200,Card Two,Card Two single card,950,trading-cards,1,
"""


def test_uploaded_csv_does_not_require_historical_labels() -> None:
    sales = read_sales_text(UNLABELED_CSV)
    assert len(sales) == 2
    assert sales[0].target is None
    assert sales[0].status_raw is None
    assert sales[0].score == 0


def test_uploaded_csv_rejects_duplicate_identifiers() -> None:
    duplicate = UNLABELED_CSV + "sale-1,G300,Card Three,Card Three,100,trading-cards,1,\n"
    try:
        read_sales_text(duplicate)
    except ValueError as exc:
        assert "Duplicate identifier" in str(exc)
    else:
        raise AssertionError("Expected duplicate identifier validation")


def test_product_mismatch_projects_to_reassignment() -> None:
    result = ReviewResult(
        decision="ignored",
        needs_modification=True,
        reason="The listing language differs from the assigned product.",
        identity_comparison={"language": "mismatch"},
        rationale_codes=["language_mismatch"],
        route="human_review",
        provider="test",
        model="test",
    )
    projection = project_review(result)
    assert projection["recommended_actions"] == ["reassign_product"]
    assert projection["product_assignment"] == "wrong"
    assert projection["listing_validity"] == "valid"
    assert projection["evidence_and_flags"] == ["language_mismatch"]
    assert projection["diagnostic_codes"] == []
    assert "evidence_facts" not in projection


def test_projection_hides_internal_protocol_diagnostics() -> None:
    result = ReviewResult(
        decision="ignored",
        reason="The current assignment matches.",
        rationale_codes=[
            "discarded_irrelevant_predicted_condition_id",
            "catalog_artwork_not_verified",
        ],
        route="human_review",
        provider="test",
        model="test",
    )
    projection = project_review(result)
    assert projection["evidence_and_flags"] == ["catalog_artwork_not_verified"]
    assert projection["diagnostic_codes"] == [
        "discarded_irrelevant_predicted_condition_id"
    ]


def _service(tmp_path) -> ConsoleService:
    config = Settings(
        pricecharting_api_token=None,
        llm_api_key=None,
        llm_base_url="https://example.test",
        llm_model=None,
        finish_llm_model=None,
        cache_dir=tmp_path / "cache",
        random_seed="test",
    )
    return ConsoleService(config, store=RunStore(tmp_path / "runs"))


def test_rules_run_persists_reviews_adjudication_and_export(tmp_path) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        read_sales_text(UNLABELED_CSV), filename="upload.csv", mode="rules"
    )
    service.process_run(str(run["id"]))

    summary = service.get_run(str(run["id"]))
    assert summary["status"] == "completed"
    assert summary["processed"] == 2
    assert summary["failed"] == 0
    assert summary["schema_version"] == 2
    assert summary["policy_version"]
    assert summary["prompt_version"] == "relationship-rules-v1"
    assert len(summary["input_sha256"]) == 64

    reviews = service.list_reviews(str(run["id"]))
    assert len(reviews) == 2
    assert all(review["historical_outcome"]["target"] is None for review in reviews)
    assert all(review["historical_outcome"]["score"] == 0 for review in reviews)
    assert all("target" not in review["sale"] for review in reviews)
    assert all("status_raw" not in review["sale"] for review in reviews)
    first = service.adjudicate(
        str(run["id"]),
        "sale-1",
        AdjudicationRequest(action="accepted", notes="Slab grade is explicit."),
    )
    assert first["adjudication"]["action"] == "accepted"
    assert service.get_run(str(run["id"]))["adjudicated"] == 1

    exported = list(csv.DictReader(StringIO(service.export_csv(str(run["id"])))))
    assert len(exported) == 2
    sale_one = next(row for row in exported if row["identifier"] == "sale-1")
    assert sale_one["adjudication_action"] == "accepted"
    assert sale_one["predicted_condition_id"] == "7"
    assert sale_one["model_confidence"] == "not_produced"
    assert sale_one["upstream_questionable_sale_score"] == "0"


def test_adjudication_records_independent_human_judgments(tmp_path) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        read_sales_text(UNLABELED_CSV), filename="upload.csv", mode="rules"
    )
    service.process_run(str(run["id"]))
    saved = service.adjudicate(
        str(run["id"]),
        "sale-1",
        AdjudicationRequest(
            action="needs_follow_up",
            listing_validity="uncertain",
            product_assignment="correct",
            condition_assignment="correct",
            notes="Historical deletion reason is unavailable.",
        ),
    )
    assert saved["adjudication"]["listing_validity"] == "uncertain"
    assert saved["adjudication"]["product_assignment"] == "correct"
    assert saved["adjudication"]["condition_assignment"] == "correct"

    exported = list(csv.DictReader(StringIO(service.export_csv(str(run["id"])))))
    sale_one = next(row for row in exported if row["identifier"] == "sale-1")
    assert sale_one["adjudication_listing_validity"] == "uncertain"
    assert sale_one["adjudication_product_assignment"] == "correct"
    assert sale_one["adjudication_condition_assignment"] == "correct"


def test_existing_run_hydrates_score_from_original_sale_rows(tmp_path) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        read_sales_text(UNLABELED_CSV), filename="legacy.csv", mode="rules"
    )
    service.process_run(str(run["id"]))
    stored = service.store.get(str(run["id"]))
    del stored["reviews"]["sale-1"]["historical_outcome"]["score"]
    service.store.save(stored)

    review = service.get_review(str(run["id"]), "sale-1")
    assert review["historical_outcome"]["score"] == 0


def test_review_console_api_end_to_end_in_rules_mode(tmp_path) -> None:
    service = _service(tmp_path)
    app.dependency_overrides[console_service] = lambda: service
    try:
        with TestClient(app) as client:
            root = client.get("/")
            assert root.status_code == 200
            assert "Evidence console" in root.text
            script = client.get("/static/app.js")
            assert "Evidence and review flags" in script.text
            assert "Model confidence" in script.text
            assert "Resolved label is our normalized evaluation category" in script.text
            assert "PriceCharting has not documented its calculation or scale" in script.text
            assert "PriceCharting recorded outcome" in script.text
            assert "Not applicable - sale deleted" in script.text
            assert "POC conclusion" in script.text
            assert "POC and PriceCharting disagree" in script.text
            assert "Differs from PriceCharting" in script.text
            assert "The export does not include the deletion reason" in script.text
            assert "No final action" in script.text
            assert "Blocked: variant evidence incomplete" in script.text
            assert "Outdated saved run" in script.text
            assert "current_policy_version" in client.get("/api/config").json()
            assert "Ignored (kept current assignment)" in script.text
            assert "The POC discarded that value" in script.text
            stylesheet = client.get("/static/app.css")
            assert "grid-template-rows: minmax(0, 1fr)" in stylesheet.text
            assert "min-height: 0" in stylesheet.text
            assert ".info-tooltip" in stylesheet.text
            assert ".outcome-comparison.disagreement" in stylesheet.text

            response = client.post(
                "/api/runs",
                json={
                    "filename": "sample.csv",
                    "csv_text": UNLABELED_CSV,
                    "mode": "rules",
                    "limit": 2,
                },
            )
            assert response.status_code == 202
            run_id = response.json()["id"]

            run = client.get(f"/api/runs/{run_id}").json()
            assert run["status"] == "completed"
            reviews = client.get(f"/api/runs/{run_id}/reviews").json()
            assert len(reviews) == 2

            saved = client.put(
                f"/api/runs/{run_id}/reviews/sale-1/adjudication",
                json={"action": "accepted", "notes": "Verified"},
            )
            assert saved.status_code == 200
            assert saved.json()["adjudication"]["notes"] == "Verified"

            exported = client.get(f"/api/runs/{run_id}/export")
            assert exported.status_code == 200
            assert "attachment" in exported.headers["content-disposition"]
            assert "recommended_actions" in exported.text
    finally:
        app.dependency_overrides.clear()


def test_api_previews_and_scores_only_selected_listing_ids(tmp_path) -> None:
    service = _service(tmp_path)
    app.dependency_overrides[console_service] = lambda: service
    try:
        with TestClient(app) as client:
            preview = client.post(
                "/api/runs/preview", json={"csv_text": UNLABELED_CSV}
            )
            assert preview.status_code == 200
            assert preview.json()["total"] == 2
            assert [row["identifier"] for row in preview.json()["rows"]] == [
                "sale-1",
                "sale-2",
            ]

            response = client.post(
                "/api/runs",
                json={
                    "filename": "sample.csv",
                    "csv_text": UNLABELED_CSV,
                    "mode": "rules",
                    "selected_identifiers": ["sale-2"],
                },
            )
            assert response.status_code == 202
            run_id = response.json()["id"]
            run = client.get(f"/api/runs/{run_id}").json()
            assert run["total"] == 1
            reviews = client.get(f"/api/runs/{run_id}/reviews").json()
            assert [review["identifier"] for review in reviews] == ["sale-2"]
            assert run["selection_strategy"] == "specific_rows"

            missing = client.post(
                "/api/runs",
                json={
                    "filename": "sample.csv",
                    "csv_text": UNLABELED_CSV,
                    "mode": "rules",
                    "selected_identifiers": ["not-in-feed"],
                },
            )
            assert missing.status_code == 400
            assert "not-in-feed" in missing.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_random_sample_is_seeded_and_reproducible(tmp_path) -> None:
    service = _service(tmp_path)
    app.dependency_overrides[console_service] = lambda: service
    payload = {
        "filename": "sample.csv",
        "csv_text": UNLABELED_CSV,
        "mode": "rules",
        "random_sample_size": 1,
        "random_seed": 8675309,
    }
    try:
        with TestClient(app) as client:
            first = client.post("/api/runs", json=payload)
            second = client.post("/api/runs", json=payload)
            assert first.status_code == 202
            assert second.status_code == 202

            first_run = client.get(f"/api/runs/{first.json()['id']}").json()
            second_run = client.get(f"/api/runs/{second.json()['id']}").json()
            assert first_run["selection_strategy"] == "random_sample"
            assert first_run["selection_seed"] == 8675309
            assert first_run["source_row_count"] == 2
            first_ids = [
                row["identifier"]
                for row in client.get(
                    f"/api/runs/{first.json()['id']}/reviews"
                ).json()
            ]
            second_ids = [
                row["identifier"]
                for row in client.get(
                    f"/api/runs/{second.json()['id']}/reviews"
                ).json()
            ]
            assert first_ids == second_ids
            assert len(first_ids) == 1
    finally:
        app.dependency_overrides.clear()
