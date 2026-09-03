from __future__ import annotations

import csv
from pathlib import Path

from .models import FigureRecord, SeriesRecord
from .naming import canonical_subseries, proposed_set_name


PRODUCT_COLUMNS = (
    "product-name",
    "model-number",
    "genre",
    "console-id",
    "release-date",
    "figure-realm-link",
)

AUDIT_COLUMNS = (
    "figure-realm-id",
    "source-name",
    "proposed-product-name",
    "model-number",
    "proposed-set-name",
    "subseries",
    "manufacturer",
    "exclusive",
    "release-year",
    "upc",
    "source-url",
    "image-url",
    "detail-fetched",
    "naming-reason",
    "review-required",
)

SET_COLUMNS = (
    "proposed-set-name",
    "figure-realm-series-id",
    "source-series-name",
    "source-subseries-name",
    "canonical-subseries-name",
    "manufacturer",
    "year-start",
    "year-end",
    "source-series-expected-items",
    "scraped-items",
    "source-url",
)


def _write(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def export_all(
    output_dir: Path,
    series: tuple[SeriesRecord, ...],
    figures: list[FigureRecord],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ordered = sorted(figures, key=lambda item: (int(item.series_id), item.source_name.casefold(), int(item.figure_id)))
    importable = [item for item in ordered if not item.review_required]
    products_path = output_dir / "products.csv"
    _write(
        products_path,
        PRODUCT_COLUMNS,
        [
            {
                "product-name": item.proposed_product_name,
                "model-number": item.model_number,
                "genre": "Action Figures",
                "console-id": item.proposed_set_name,
                "release-date": item.release_year,
                "figure-realm-link": item.source_url,
            }
            for item in importable
        ],
    )

    audit_path = output_dir / "audit.csv"
    audit_rows = [
            {
                "figure-realm-id": item.figure_id,
                "source-name": item.source_name,
                "proposed-product-name": item.proposed_product_name,
                "model-number": item.model_number,
                "proposed-set-name": item.proposed_set_name,
                "subseries": item.subseries,
                "manufacturer": item.manufacturer,
                "exclusive": item.exclusive,
                "release-year": item.release_year,
                "upc": item.upc,
                "source-url": item.source_url,
                "image-url": item.image_url,
                "detail-fetched": "yes" if item.detail_fetched else "no",
                "naming-reason": item.naming_reason,
                "review-required": "yes" if item.review_required else "no",
            }
            for item in ordered
        ]
    _write(audit_path, AUDIT_COLUMNS, audit_rows)

    review_path = output_dir / "review.csv"
    _write(
        review_path,
        AUDIT_COLUMNS,
        [row for row in audit_rows if row["review-required"] == "yes"],
    )

    sets_path = output_dir / "set-proposals.csv"
    series_by_id = {item.identity: item for item in series}
    set_groups: dict[tuple[str, str], list[FigureRecord]] = {}
    for figure in ordered:
        series_key = figure.series_identity or figure.series_id
        set_name = figure.proposed_set_name or proposed_set_name(
            series_by_id[series_key], figure.subseries
        )
        set_groups.setdefault((series_key, set_name), []).append(figure)

    set_rows: list[dict[str, object]] = []
    for (series_key, set_name), group in sorted(
        set_groups.items(),
        key=lambda item: (
            int(series_by_id[item[0][0]].series_id),
            item[0][1].casefold(),
        ),
    ):
        source_series = series_by_id[series_key]
        years = sorted(
            {item.release_year for item in group if item.release_year.isdigit()}, key=int
        )
        set_rows.append(
            {
                "proposed-set-name": set_name,
                "figure-realm-series-id": source_series.series_id,
                "source-series-name": source_series.source_name,
                "source-subseries-name": " | ".join(
                    sorted({item.subseries for item in group}, key=str.casefold)
                ),
                "canonical-subseries-name": canonical_subseries(group[0].subseries),
                "manufacturer": group[0].manufacturer,
                "year-start": years[0] if years else "",
                "year-end": years[-1] if years else "",
                "source-series-expected-items": (
                    source_series.expected_items
                    if source_series.expected_items is not None
                    else ""
                ),
                "scraped-items": len(group),
                "source-url": source_series.source_url,
            }
        )
    _write(
        sets_path,
        SET_COLUMNS,
        set_rows,
    )
    return {
        "products": products_path,
        "audit": audit_path,
        "review": review_path,
        "sets": sets_path,
    }
