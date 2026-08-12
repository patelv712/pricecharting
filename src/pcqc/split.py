"""Leakage-resistant deterministic dataset splitting."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Iterable

from pcqc.models import NormalizedSale


def _group_fraction(group_id: str, seed: str) -> float:
    digest = hashlib.sha256(f"{seed}:{group_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def grouped_hash_split(
    sales: Iterable[NormalizedSale],
    *,
    test_fraction: float = 0.30,
    seed: str = "pricecharting-poc-v1",
) -> tuple[list[NormalizedSale], list[NormalizedSale]]:
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between 0 and 1")
    development: list[NormalizedSale] = []
    test: list[NormalizedSale] = []
    for sale in sales:
        destination = test if _group_fraction(sale.product_id, seed) < test_fraction else development
        destination.append(sale)
    return development, test


def grouped_three_way_split(
    sales: Iterable[NormalizedSale],
    *,
    validation_fraction: float = 0.20,
    final_fraction: float = 0.20,
    seed: str = "pricecharting-poc-v1",
    excluded_product_ids: Iterable[str] = (),
) -> tuple[list[NormalizedSale], list[NormalizedSale], list[NormalizedSale]]:
    """Create stable product splits, keeping previously seen products in development."""
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between 0 and 1")
    if not 0 < final_fraction < 1:
        raise ValueError("final_fraction must be between 0 and 1")
    if validation_fraction + final_fraction >= 1:
        raise ValueError("validation_fraction + final_fraction must be less than 1")

    excluded = set(excluded_product_ids)
    development: list[NormalizedSale] = []
    validation: list[NormalizedSale] = []
    final: list[NormalizedSale] = []
    for sale in sales:
        if sale.product_id in excluded:
            development.append(sale)
            continue
        fraction = _group_fraction(sale.product_id, seed)
        if fraction < final_fraction:
            final.append(sale)
        elif fraction < final_fraction + validation_fraction:
            validation.append(sale)
        else:
            development.append(sale)
    return development, validation, final


def split_summary(
    development: Iterable[NormalizedSale], test: Iterable[NormalizedSale]
) -> dict[str, object]:
    development_rows = list(development)
    test_rows = list(test)
    development_products = {sale.product_id for sale in development_rows}
    test_products = {sale.product_id for sale in test_rows}
    return {
        "development_rows": len(development_rows),
        "test_rows": len(test_rows),
        "development_products": len(development_products),
        "test_products": len(test_products),
        "product_overlap": len(development_products & test_products),
        "development_targets": dict(
            Counter(sale.target.value for sale in development_rows if sale.target is not None)
        ),
        "test_targets": dict(Counter(sale.target.value for sale in test_rows if sale.target is not None)),
    }


def three_way_split_summary(
    development: Iterable[NormalizedSale],
    validation: Iterable[NormalizedSale],
    final: Iterable[NormalizedSale],
) -> dict[str, object]:
    partitions = {
        "development": list(development),
        "validation": list(validation),
        "final": list(final),
    }
    products = {
        name: {sale.product_id for sale in rows} for name, rows in partitions.items()
    }
    overlap = (
        (products["development"] & products["validation"])
        | (products["development"] & products["final"])
        | (products["validation"] & products["final"])
    )
    summary: dict[str, object] = {"product_overlap": len(overlap)}
    for name, rows in partitions.items():
        summary[f"{name}_rows"] = len(rows)
        summary[f"{name}_products"] = len(products[name])
        summary[f"{name}_targets"] = dict(
            Counter(sale.target.value for sale in rows if sale.target is not None)
        )
    return summary
