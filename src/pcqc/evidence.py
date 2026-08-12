"""Deterministic relationship-first evidence construction."""

from __future__ import annotations

import math
import re

from pcqc.models import (
    CatalogEvidence,
    DerivedEvidence,
    DeterministicEvidenceSummary,
    EvidencePacket,
    ImageEvidence,
    NormalizedSale,
    ProductEvidence,
    ProductCandidate,
)


STOP_WORDS = {
    "a",
    "and",
    "card",
    "cards",
    "for",
    "from",
    "in",
    "of",
    "the",
    "to",
    "with",
    "tcg",
}
DELETION_PATTERNS: dict[str, re.Pattern[str]] = {
    "lot_bundle": re.compile(r"\b(lot|bundle|collection|playset|set of|x\s?\d+)\b", re.I),
    "custom_or_proxy": re.compile(r"\b(custom|proxy|reprint|replica|fan[ -]?made)\b", re.I),
    "damaged_item": re.compile(r"\b(damaged|crease[dm]?|torn|altered|poor|dmg)\b", re.I),
    "non_card_item": re.compile(r"\b(figure|case only|display stand|magnet|extended art case)\b", re.I),
}
GRADING_COMPANY_PATTERN = re.compile(r"\b(PSA|BGS|CGC|SGC|TAG|ACE)\b", re.I)
COMPANY_GRADE_PATTERN = re.compile(
    r"\b(PSA|BGS|CGC|SGC|TAG|ACE)\s*(10|9\.5|9|8\.5|8|7\.5|7|6|5|4|3|2|1)\b",
    re.I,
)
EXPLICIT_GRADE_PATTERN = re.compile(
    r"\b(?:grade|graded|gem mint|mint)\s*(10|9\.5|9|8\.5|8|7\.5|7|6|5|4|3|2|1)\b",
    re.I,
)
CHAMPIONSHIP_YEAR_PATTERN = re.compile(
    r"\bchampionship\s*['’]?\s*(\d{2}|\d{4})\b",
    re.I,
)

IDENTITY_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "finish": [
        ("reverse_holo", re.compile(r"\b(?:reverse|rev)\s+(?:holo|foil)\b", re.I)),
        ("cosmos_holo", re.compile(r"\bcosmos\s+holo\b", re.I)),
        ("non_holo", re.compile(r"\b(?:non|no)[ -]?(?:holo|foil)\b", re.I)),
        ("holo", re.compile(r"\bholo(?:graphic)?\b", re.I)),
        ("foil", re.compile(r"\bfoil\b", re.I)),
    ],
    "printing": [
        ("special_alternate_art", re.compile(r"\bspecial\s+(?:alternate|alt)\s+art\b", re.I)),
        ("alternate_art", re.compile(r"\b(?:alternate|alt)[ -]?art\b|\bparallel\b", re.I)),
        ("full_art", re.compile(r"\bfull[ -]?art\b", re.I)),
        ("manga", re.compile(r"\bmanga\b", re.I)),
    ],
    "language": [
        ("japanese", re.compile(r"\b(?:japanese|japan|jp|jpn)\b", re.I)),
        ("english", re.compile(r"\b(?:english|eng)\b", re.I)),
        ("indonesian", re.compile(r"\b(?:indonesian|indonesia)\b", re.I)),
        ("korean", re.compile(r"\b(?:korean|korea)\b", re.I)),
        ("chinese", re.compile(r"\b(?:chinese|china)\b", re.I)),
    ],
    "packaging": [
        ("case", re.compile(r"\b(?:booster\s+)?case\b", re.I)),
        ("booster_box", re.compile(r"\bbooster\s+box\b|\bdisplay\s+box\b", re.I)),
        ("sealed_collection", re.compile(r"\b(?:sealed|premium)\s+(?:card\s+)?collection\b", re.I)),
        ("single_card", re.compile(r"\bsingle\s+card\b", re.I)),
    ],
}
CARD_CODE_PATTERN = re.compile(r"\b[A-Z]{1,5}\d{1,3}-\d{2,3}\b", re.I)


def identity_markers(text: str) -> dict[str, list[str]]:
    """Extract only explicit product-identity facts; absence is never treated as a base variant."""
    markers: dict[str, list[str]] = {}
    for dimension, patterns in IDENTITY_PATTERNS.items():
        values = [name for name, pattern in patterns if pattern.search(text)]
        # Specific finish/printing terms subsume generic ones found inside the same phrase.
        if dimension == "finish" and "reverse_holo" in values:
            values = [value for value in values if value not in {"holo", "foil"}]
        if dimension == "finish" and "cosmos_holo" in values:
            values = [value for value in values if value != "holo"]
        if dimension == "finish" and "non_holo" in values:
            values = [value for value in values if value not in {"holo", "foil"}]
        if dimension == "printing" and "special_alternate_art" in values:
            values = [value for value in values if value != "alternate_art"]
        if values:
            markers[dimension] = sorted(set(values))
    card_codes = sorted({match.group(0).upper() for match in CARD_CODE_PATTERN.finditer(text)})
    if card_codes:
        markers["card_code"] = card_codes
    return markers


def marker_relationships(
    sale_markers: dict[str, list[str]], catalog_markers: dict[str, list[str]]
) -> tuple[list[str], list[str]]:
    conflicts: list[str] = []
    warnings: list[str] = []
    for dimension in sorted(set(sale_markers) & set(catalog_markers)):
        sale_values = set(sale_markers[dimension])
        catalog_values = set(catalog_markers[dimension])
        if sale_values.isdisjoint(catalog_values):
            conflicts.append(
                f"{dimension}_conflict:sale={','.join(sorted(sale_values))}:"
                f"catalog={','.join(sorted(catalog_values))}"
            )
    for dimension in ("finish", "printing", "language", "packaging", "card_code"):
        if dimension in sale_markers and dimension not in catalog_markers:
            warnings.append(
                f"{dimension}_catalog_unspecified:sale="
                + ",".join(sale_markers[dimension])
            )
    return conflicts, warnings


def candidate_variant_warnings(
    product: ProductEvidence, candidates: list[ProductCandidate]
) -> list[str]:
    """Flag same-product families whose catalog contains identity-changing variants."""
    assigned_base = re.sub(r"\[[^]]+\]", " ", product.product_name)
    assigned_base_tokens = normalized_tokens(assigned_base)
    if not assigned_base_tokens:
        return []
    assigned_base_key = " ".join(assigned_base_tokens)
    assigned_markers = identity_markers(product.product_name)
    assigned_console_key = " ".join(normalized_tokens(product.console_name or ""))
    dimensions: set[str] = set()
    sibling_ids: list[str] = []
    for candidate in candidates:
        if candidate.product_id == product.product_id:
            continue
        candidate_console_key = " ".join(
            normalized_tokens(candidate.console_name or "")
        )
        if (
            assigned_console_key
            and candidate_console_key
            and candidate_console_key != assigned_console_key
        ):
            continue
        candidate_base = re.sub(r"\[[^]]+\]", " ", candidate.product_name)
        if " ".join(normalized_tokens(candidate_base)) != assigned_base_key:
            continue
        markers = identity_markers(candidate.product_name)
        candidate_dimensions = {
            dimension
            for dimension in ("finish", "printing")
            if set(markers.get(dimension, []))
            != set(assigned_markers.get(dimension, []))
        }
        if candidate_dimensions:
            dimensions.update(candidate_dimensions)
            sibling_ids.append(candidate.product_id)
    if not dimensions:
        return []
    return [
        "catalog_variant_family_ambiguous:dimensions="
        + ",".join(sorted(dimensions))
        + ":siblings="
        + ",".join(sorted(sibling_ids))
    ]


def _normalized_year(value: str) -> int:
    parsed = int(value)
    return 2000 + parsed if parsed < 100 else parsed


def identity_conflicts(sale_title: str, product_text: str) -> list[str]:
    """Extract explicit identity contradictions that token overlap cannot detect."""
    sale_years = {
        _normalized_year(match.group(1))
        for match in CHAMPIONSHIP_YEAR_PATTERN.finditer(sale_title)
    }
    product_years = {
        _normalized_year(match.group(1))
        for match in CHAMPIONSHIP_YEAR_PATTERN.finditer(product_text)
    }
    conflicts: list[str] = []
    if sale_years and product_years and sale_years.isdisjoint(product_years):
        conflicts.append(
            "championship_year_conflict:"
            f"sale={','.join(map(str, sorted(sale_years)))}:"
            f"catalog={','.join(map(str, sorted(product_years)))}"
        )
    return conflicts


def normalized_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    return [token for token in tokens if token not in STOP_WORDS and len(token) > 1]


def token_overlap(sale_title: str, product_text: str) -> tuple[float, list[str]]:
    sale_tokens = set(normalized_tokens(sale_title))
    product_tokens = set(normalized_tokens(product_text))
    if not product_tokens:
        return 0.0, []
    missing = sorted(product_tokens - sale_tokens)
    return len(product_tokens & sale_tokens) / len(product_tokens), missing


def extract_grade(title: str) -> tuple[str | None, float | None, int | None]:
    company_match = GRADING_COMPANY_PATTERN.search(title)
    company = company_match.group(1).upper() if company_match else None
    company_grade_match = COMPANY_GRADE_PATTERN.search(title)
    explicit_grade_match = EXPLICIT_GRADE_PATTERN.search(title)
    grade_match = company_grade_match or explicit_grade_match
    if company_grade_match:
        company = company_grade_match.group(1).upper()
        grade = float(company_grade_match.group(2))
    else:
        grade = float(explicit_grade_match.group(1)) if explicit_grade_match else None
    if grade is None:
        return company, None, None
    if grade == 10:
        lowered = title.lower()
        if company == "BGS" and "black" in lowered:
            condition_id = 20
        elif company == "CGC" and "pristine" in lowered:
            condition_id = 19
        else:
            condition_id = {"PSA": 7, "BGS": 8, "CGC": 17, "SGC": 18, "TAG": 21, "ACE": 22}.get(company)
    elif grade == 9.5:
        condition_id = 6
    elif grade >= 9:
        condition_id = 5
    elif grade >= 8:
        condition_id = 2
    elif grade >= 7:
        condition_id = 3
    else:
        condition_id = {1.0: 9, 2.0: 10, 3.0: 13, 4.0: 14, 5.0: 15, 6.0: 16}.get(grade)
    return company, grade, condition_id


def price_ratio(left: int, right: int) -> float:
    if left <= 0 or right <= 0:
        return math.inf
    return max(left, right) / min(left, right)


def build_derived_evidence(sale: NormalizedSale, product: ProductEvidence) -> DerivedEvidence:
    product_text = " ".join(
        value for value in [sale.product_title, product.product_name, product.console_name] if value
    )
    overlap, missing = token_overlap(sale.sale_title, product_text)
    sale_markers = identity_markers(sale.sale_title)
    catalog_markers = identity_markers(product_text)
    marker_conflicts, warnings = marker_relationships(sale_markers, catalog_markers)
    conflicts = identity_conflicts(sale.sale_title, product_text) + marker_conflicts
    deletion_flags = [
        code for code, pattern in DELETION_PATTERNS.items() if pattern.search(sale.sale_title)
    ]
    company, grade, title_condition = extract_grade(sale.sale_title)
    original_price = product.price_anchors.get(sale.original_condition_id)
    ranked = sorted(
        (
            (price_ratio(sale.sale_amount_pennies, anchor), condition_id)
            for condition_id, anchor in product.price_anchors.items()
            if anchor > 0
        ),
        key=lambda item: item[0],
    )
    nearest_ratio, nearest_condition = ranked[0] if ranked else (None, None)
    second_ratio = ranked[1][0] if len(ranked) > 1 else None
    evidence_count = 1
    evidence_count += int(bool(product.price_anchors))
    evidence_count += int(grade is not None)
    evidence_count += int(bool(product.console_name or product.genre))
    return DerivedEvidence(
        title_product_overlap=round(overlap, 6),
        missing_product_tokens=missing,
        deletion_flags=deletion_flags,
        identity_conflicts=conflicts,
        identity_warnings=warnings,
        sale_identity_markers=sale_markers,
        catalog_identity_markers=catalog_markers,
        extracted_grading_company=company,
        extracted_grade=grade,
        title_supported_condition_id=title_condition,
        original_condition_price=original_price,
        nearest_condition_id=nearest_condition,
        nearest_condition_ratio=None if nearest_ratio is None else round(nearest_ratio, 6),
        second_nearest_condition_ratio=None if second_ratio is None else round(second_ratio, 6),
        evidence_count=evidence_count,
    )


def build_evidence_packet(
    sale: NormalizedSale,
    product: ProductEvidence,
    image: ImageEvidence | None = None,
    catalog: CatalogEvidence | None = None,
    replacement_candidates: list[ProductCandidate] | None = None,
    enrichment_warnings: list[str] | None = None,
) -> EvidencePacket:
    candidates = replacement_candidates or []
    derived = build_derived_evidence(sale, product)
    variant_warnings = candidate_variant_warnings(product, candidates)
    if variant_warnings:
        derived = derived.model_copy(
            update={
                "identity_warnings": list(
                    dict.fromkeys(derived.identity_warnings + variant_warnings)
                )
            }
        )
    return EvidencePacket(
        sale=sale,
        product=product,
        derived=derived,
        image=image,
        catalog=catalog,
        replacement_candidates=candidates,
        enrichment_warnings=list(dict.fromkeys(enrichment_warnings or [])),
    )


def deterministic_evidence_summary(
    packet: EvidencePacket,
) -> DeterministicEvidenceSummary:
    image = packet.image
    catalog_image = packet.catalog.image if packet.catalog else None
    return DeterministicEvidenceSummary(
        image_available=bool(image and image.available),
        image_usable=bool(image and image.usable),
        title_product_overlap=packet.derived.title_product_overlap,
        deletion_flags=packet.derived.deletion_flags,
        identity_conflicts=packet.derived.identity_conflicts,
        identity_warnings=packet.derived.identity_warnings,
        sale_identity_markers=packet.derived.sale_identity_markers,
        catalog_identity_markers=packet.derived.catalog_identity_markers,
        title_supported_condition_id=packet.derived.title_supported_condition_id,
        catalog_price_anchor_count=len(packet.product.price_anchors),
        catalog_image_available=bool(catalog_image and catalog_image.usable),
        catalog_product_id_verified=bool(
            packet.catalog and packet.catalog.product_id_verified
        ),
        enrichment_warnings=packet.enrichment_warnings,
    )
