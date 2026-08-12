from __future__ import annotations

from pathlib import Path

import pytest

from pcqc.io import normalize_product_id, normalize_status, profile_sales, read_sales
from pcqc.models import TargetLabel
from pcqc.split import (
    grouped_hash_split,
    grouped_three_way_split,
    split_summary,
    three_way_split_summary,
)


def test_status_slugs_are_decoded() -> None:
    assert normalize_status("ignored") == (TargetLabel.IGNORED, None)
    assert normalize_status("needsMod") == (TargetLabel.NEEDS_MODIFICATION, None)
    assert normalize_status("manualonly") == (TargetLabel.CONDITION_CHANGE, 7)
    assert normalize_status("gradeseventeen") == (TargetLabel.CONDITION_CHANGE, 17)
    with pytest.raises(ValueError, match="Unknown"):
        normalize_status("mystery")


def test_product_id_and_csv_profile(tmp_path: Path) -> None:
    assert normalize_product_id("G9647987") == "9647987"
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        "identifier,status,review-date,most-recent-report,unified-id,product-title,sale-title,sale-amount-pennies,score,broad-category,condition-id,picture-url\n"
        "1,ignored,2026-01-01,2026-01-01,G100,Card A,Card A,1000,2,trading-cards,1,\n"
        "2,manualonly,2026-01-02,2026-01-02,G100,Card A,Card A PSA 10,2000,3,trading-cards,1,https://example.test/a.jpg\n",
        encoding="utf-8",
    )
    rows = read_sales(csv_path)
    profile = profile_sales(rows)
    assert profile["row_count"] == 2
    assert profile["unique_products"] == 1
    assert profile["missing_images"] == 1
    assert rows[1].target_condition_id == 7


def test_same_condition_button_is_a_confirmation(tmp_path: Path) -> None:
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        "identifier,status,review-date,most-recent-report,unified-id,product-title,sale-title,sale-amount-pennies,score,broad-category,condition-id,picture-url\n"
        "1,manualonly,2026-01-01,2026-01-01,G100,Card A,Card A PSA 10,1000,2,trading-cards,7,\n",
        encoding="utf-8",
    )
    row = read_sales(csv_path)[0]
    assert row.target == TargetLabel.IGNORED
    assert row.target_condition_id is None
    assert row.review_action_condition_id == 7


def test_group_split_has_no_product_leakage(sale) -> None:
    rows = []
    for product_id in range(100, 140):
        rows.append(sale.model_copy(update={"identifier": f"{product_id}-a", "product_id": str(product_id)}))
        rows.append(sale.model_copy(update={"identifier": f"{product_id}-b", "product_id": str(product_id)}))
    development, test = grouped_hash_split(rows, test_fraction=0.3, seed="test")
    summary = split_summary(development, test)
    assert summary["product_overlap"] == 0
    assert len(development) + len(test) == len(rows)
    assert development and test


def test_three_way_split_is_grouped_and_excludes_seen_products(sale) -> None:
    rows = [
        sale.model_copy(
            update={"identifier": f"sale-{index}", "product_id": f"product-{index // 2}"}
        )
        for index in range(60)
    ]
    kwargs = {
        "validation_fraction": 0.2,
        "final_fraction": 0.2,
        "seed": "test",
        "excluded_product_ids": {"product-0", "product-1"},
    }
    first = grouped_three_way_split(rows, **kwargs)
    second = grouped_three_way_split(rows, **kwargs)
    assert [[row.identifier for row in split] for split in first] == [
        [row.identifier for row in split] for split in second
    ]
    development, validation, final = first
    assert {"product-0", "product-1"} <= {row.product_id for row in development}
    summary = three_way_split_summary(development, validation, final)
    assert summary["product_overlap"] == 0
    assert summary["development_rows"] + summary["validation_rows"] + summary["final_rows"] == 60
