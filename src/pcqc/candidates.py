"""Deterministic ranking of PriceCharting replacement-product candidates."""

from __future__ import annotations

import re

from pcqc.evidence import identity_markers, normalized_tokens
from pcqc.models import NormalizedSale, ProductCandidate, ProductEvidence


GRADE_NOISE = re.compile(
    r"\b(?:PSA|BGS|CGC|SGC|TAG|ACE)\s*(?:10|9\.5|9|8\.5|8|7\.5|7|6|5|4|3|2|1)?\b",
    re.I,
)
LISTING_NOISE = re.compile(
    r"\b(?:gem mint|mint|near mint|nm|graded|rare|authentic|free shipping)\b",
    re.I,
)


def candidate_query(sale: NormalizedSale) -> str:
    """Keep listing identity terms while removing condition and marketplace noise."""
    cleaned = GRADE_NOISE.sub(" ", sale.sale_title)
    cleaned = LISTING_NOISE.sub(" ", cleaned)
    return " ".join(cleaned.split())[:240]


def _token_f1(left: str, right: str) -> float:
    left_tokens = set(normalized_tokens(left))
    right_tokens = set(normalized_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    shared = len(left_tokens & right_tokens)
    precision = shared / len(right_tokens)
    recall = shared / len(left_tokens)
    return 2 * precision * recall / (precision + recall) if shared else 0.0


def rank_candidates(
    sale: NormalizedSale,
    products: list[ProductEvidence],
    *,
    limit: int = 8,
) -> list[ProductCandidate]:
    sale_markers = identity_markers(sale.sale_title)
    ranked: list[ProductCandidate] = []
    for product in products:
        candidate_text = " ".join(
            value for value in (product.product_name, product.console_name) if value
        )
        product_markers = identity_markers(candidate_text)
        score = round(_token_f1(sale.sale_title, candidate_text) * 60)
        components = [f"token_f1={score}/60"]
        for dimension in ("card_code", "finish", "printing", "language", "packaging"):
            sale_values = set(sale_markers.get(dimension, []))
            product_values = set(product_markers.get(dimension, []))
            if sale_values and product_values:
                if sale_values & product_values:
                    score += 8
                    components.append(f"{dimension}_match=+8")
                else:
                    score -= 12
                    components.append(f"{dimension}_conflict=-12")
        if product.product_id == sale.product_id:
            components.append("currently_assigned")
        ranked.append(
            ProductCandidate(
                product_id=product.product_id,
                product_name=product.product_name,
                console_name=product.console_name,
                retrieval_score=max(0, min(100, score)),
                score_components=components,
            )
        )
    ranked.sort(key=lambda item: (-item.retrieval_score, item.product_id))
    return ranked[:limit]
