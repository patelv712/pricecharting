"""Reviewed-sale CSV ingestion, validation, and profiling."""

from __future__ import annotations

import csv
from collections import Counter
from io import StringIO
from pathlib import Path
from typing import Iterable

from pcqc.conditions import CONDITIONS, STATUS_SLUG_TO_CONDITION_ID
from pcqc.models import NormalizedSale, TargetLabel


INFERENCE_REQUIRED_COLUMNS = {
    "identifier",
    "unified-id",
    "product-title",
    "sale-title",
    "sale-amount-pennies",
    "broad-category",
    "condition-id",
}
REVIEW_METADATA_COLUMNS = {
    "status",
    "review-date",
    "most-recent-report",
    "score",
    "picture-url",
}
REQUIRED_COLUMNS = INFERENCE_REQUIRED_COLUMNS | REVIEW_METADATA_COLUMNS


def normalize_product_id(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("G"):
        normalized = normalized[1:]
    if not normalized.isdigit():
        raise ValueError(f"Invalid unified-id: {value!r}")
    return normalized


def normalize_status(status: str) -> tuple[TargetLabel, int | None]:
    normalized = status.strip()
    if normalized == "ignored":
        return TargetLabel.IGNORED, None
    if normalized == "deleted":
        return TargetLabel.DELETED, None
    if normalized == "needsMod":
        return TargetLabel.NEEDS_MODIFICATION, None
    if normalized in STATUS_SLUG_TO_CONDITION_ID:
        return TargetLabel.CONDITION_CHANGE, STATUS_SLUG_TO_CONDITION_ID[normalized]
    raise ValueError(f"Unknown review status: {status!r}")


def normalize_row(
    row: dict[str, str], *, require_review_metadata: bool = True
) -> NormalizedSale:
    raw_status = (row.get("status") or "").strip()
    if require_review_metadata and not raw_status:
        raise ValueError("Missing review status")
    if raw_status:
        target, review_action_condition_id = normalize_status(raw_status)
    else:
        target, review_action_condition_id = None, None
    condition_id = int(row["condition-id"])
    if condition_id not in CONDITIONS:
        raise ValueError(f"Unsupported original condition id: {condition_id}")
    target_condition_id = review_action_condition_id
    if target == TargetLabel.CONDITION_CHANGE and review_action_condition_id == condition_id:
        # Reviewers can confirm an existing condition by pressing its condition button
        # instead of Ignore. Semantically this is a correct listing, not a change.
        target = TargetLabel.IGNORED
        target_condition_id = None
    picture_url = (row.get("picture-url") or "").strip() or None
    return NormalizedSale(
        identifier=row["identifier"].strip(),
        target=target,
        target_condition_id=target_condition_id,
        review_action_condition_id=review_action_condition_id,
        status_raw=raw_status or None,
        review_date=(row.get("review-date") or "").strip() or None,
        most_recent_report=(row.get("most-recent-report") or "").strip() or None,
        product_id=normalize_product_id(row["unified-id"]),
        product_title=row["product-title"].strip(),
        sale_title=row["sale-title"].strip(),
        sale_amount_pennies=int(row["sale-amount-pennies"]),
        score=int((row.get("score") or "0").strip() or 0),
        broad_category=row["broad-category"].strip(),
        original_condition_id=condition_id,
        picture_url=picture_url,
    )


def _read_sales_handle(
    handle: Iterable[str],
    *,
    limit: int | None = None,
    require_review_metadata: bool = True,
) -> list[NormalizedSale]:
    sales: list[NormalizedSale] = []
    reader = csv.DictReader(handle)
    required = REQUIRED_COLUMNS if require_review_metadata else INFERENCE_REQUIRED_COLUMNS
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    seen_identifiers: set[str] = set()
    for index, row in enumerate(reader):
        if limit is not None and index >= limit:
            break
        try:
            sale = normalize_row(
                row, require_review_metadata=require_review_metadata
            )
            if sale.identifier in seen_identifiers:
                raise ValueError(f"Duplicate identifier: {sale.identifier}")
            seen_identifiers.add(sale.identifier)
            sales.append(sale)
        except Exception as exc:
            raise ValueError(f"Invalid row {index + 2}: {exc}") from exc
    return sales


def read_sales(path: Path, *, limit: int | None = None) -> list[NormalizedSale]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return _read_sales_handle(handle, limit=limit, require_review_metadata=True)


def read_sales_text(
    value: str,
    *,
    limit: int | None = None,
    require_review_metadata: bool = False,
) -> list[NormalizedSale]:
    """Parse an uploaded CSV without requiring historical reviewer labels."""
    return _read_sales_handle(
        StringIO(value.lstrip("\ufeff"), newline=""),
        limit=limit,
        require_review_metadata=require_review_metadata,
    )


def profile_sales(sales: Iterable[NormalizedSale]) -> dict[str, object]:
    rows = list(sales)
    target_counts = Counter(sale.target.value for sale in rows if sale.target is not None)
    condition_counts = Counter(sale.original_condition_id for sale in rows)
    status_counts = Counter(sale.status_raw for sale in rows if sale.status_raw is not None)
    product_counts = Counter(sale.product_id for sale in rows)
    missing_images = sum(sale.picture_url is None for sale in rows)
    repeated_rows = sum(count for count in product_counts.values() if count > 1)
    return {
        "row_count": len(rows),
        "target_counts": dict(sorted(target_counts.items())),
        "status_counts": dict(status_counts.most_common()),
        "condition_counts": {str(k): v for k, v in sorted(condition_counts.items())},
        "unique_products": len(product_counts),
        "rows_in_repeated_product_groups": repeated_rows,
        "largest_product_group": max(product_counts.values(), default=0),
        "missing_images": missing_images,
        "image_coverage": 0 if not rows else round((len(rows) - missing_images) / len(rows), 6),
        "review_date_min": min((sale.review_date for sale in rows), default=None),
        "review_date_max": max((sale.review_date for sale in rows), default=None),
        "sale_amount_min": min((sale.sale_amount_pennies for sale in rows), default=None),
        "sale_amount_max": max((sale.sale_amount_pennies for sale in rows), default=None),
        "score_min": min((sale.score for sale in rows), default=None),
        "score_max": max((sale.score for sale in rows), default=None),
    }
