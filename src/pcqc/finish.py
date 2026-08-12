"""Evidence-backed trading-card finish resolution and deterministic image observations."""

from __future__ import annotations

import math
import re
import statistics
from pathlib import Path

from PIL import Image, ImageOps

from pcqc.models import (
    CatalogEvidence,
    EvidencePacket,
    FinishEvidenceFact,
    FinishImageFeatures,
    FinishMatch,
    FinishResolution,
    FinishType,
    FinishVisualOutput,
    ProductCandidate,
)


FINISH_PATTERNS: list[tuple[FinishType, re.Pattern[str]]] = [
    (FinishType.REVERSE_HOLO, re.compile(r"\b(?:reverse|rev)[ -]?(?:holo|foil)\b", re.I)),
    (FinishType.COSMOS_HOLO, re.compile(r"\bcosmos[ -]?holo\b", re.I)),
    (FinishType.REGULAR, re.compile(r"\b(?:non|no)[ -]?(?:holo|foil)\b|\bregular\b", re.I)),
    (FinishType.SPECIAL_FOIL, re.compile(r"\b(?:etched|textured|cracked ice|galaxy|special)[ -]?foil\b", re.I)),
    (FinishType.HOLO, re.compile(r"\bholo(?:graphic)?\b", re.I)),
    (FinishType.FOIL, re.compile(r"\bfoil\b", re.I)),
]
FINISH_RESOLUTION_POLICY_VERSION = "2026-08-10-finish-resolution-v5"
NON_SINGLE_PRODUCT_PATTERN = re.compile(
    r"\b(?:booster|blister)\s+pack\b|\b(?:booster|collection|display)\s+box\b|"
    r"\b(?:theme|starter)\s+deck\b|\bcard\s+collection\b|\bcollector(?:'s)?\s+tin\b",
    re.I,
)
NON_CARD_LISTING_PATTERN = re.compile(r"\bcard\s+not\s+included\b|\bcase\s+only\b", re.I)


def finishes_from_text(text: str) -> list[FinishType]:
    values: list[FinishType] = []
    for finish, pattern in FINISH_PATTERNS:
        if pattern.search(text):
            values.append(finish)
    specific = {
        FinishType.REVERSE_HOLO,
        FinishType.COSMOS_HOLO,
        FinishType.REGULAR,
        FinishType.SPECIAL_FOIL,
    }
    if any(value in specific for value in values):
        values = [value for value in values if value not in {FinishType.HOLO, FinishType.FOIL}]
    return list(dict.fromkeys(values))


def catalog_finish_text(product_name: str, catalog: CatalogEvidence | None) -> str:
    values = [product_name]
    if catalog:
        values.extend(value for value in (catalog.description, catalog.notes) if value)
    return " ".join(values)


def _single_finish(text: str) -> FinishType:
    finishes = finishes_from_text(text)
    return finishes[0] if len(finishes) == 1 else FinishType.UNKNOWN


def candidate_finish(candidate: ProductCandidate) -> FinishType:
    return _single_finish(catalog_finish_text(candidate.product_name, candidate.catalog))


def finish_family_key(product_name: str) -> str:
    """Normalize a catalog name so named finish siblings share one family key."""
    return " ".join(re.sub(r"\[[^]]+\]", "", product_name).lower().split())


def finish_family_candidates(packet: EvidencePacket) -> list[ProductCandidate]:
    assigned_base = finish_family_key(packet.product.product_name)
    family: list[ProductCandidate] = []
    for candidate in packet.replacement_candidates:
        candidate_base = finish_family_key(candidate.product_name)
        if candidate_base == assigned_base and candidate_finish(candidate) != FinishType.UNKNOWN:
            family.append(candidate)
    return family


def finish_is_applicable(packet: EvidencePacket) -> bool:
    return not (
        NON_SINGLE_PRODUCT_PATTERN.search(packet.product.product_name)
        or NON_CARD_LISTING_PATTERN.search(packet.sale.sale_title)
    )


def _assigned_finish(packet: EvidencePacket) -> tuple[FinishType, list[FinishEvidenceFact]]:
    text = catalog_finish_text(packet.product.product_name, packet.catalog)
    finish = _single_finish(text)
    facts: list[FinishEvidenceFact] = []
    if finish != FinishType.UNKNOWN:
        facts.append(
            FinishEvidenceFact(
                source="assigned_catalog_metadata",
                fact=f"Assigned catalog explicitly identifies {finish.value}.",
                finish=finish,
            )
        )
        return finish, facts

    # Pokemon base entries can omit "regular". Requiring both named holo siblings avoids
    # treating every unsuffixed product as non-foil (for example, Typhlosion #16 is Holo).
    sibling_finishes = {
        candidate_finish(candidate) for candidate in finish_family_candidates(packet)
    }
    if (
        sibling_finishes
        and packet.catalog
        and packet.catalog.product_id_verified
        and packet.catalog.schema_version >= 2
    ):
        finish = FinishType.REGULAR
        facts.append(
            FinishEvidenceFact(
                source="catalog_variant_family",
                fact=(
                    "Metadata-complete unsuffixed assigned product has separately named finish "
                    "siblings in the same PriceCharting family and no finish marker of its own."
                ),
                finish=finish,
            )
        )
    return finish, facts


def extract_image_features(image_path: Path, cache_dir: Path) -> FinishImageFeatures:
    try:
        with Image.open(image_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        width, height = image.size
        aspect = width / height if height else 0
        sample = image.copy()
        sample.thumbnail((256, 256))
        hsv = sample.convert("HSV")
        hsv_pixels = (
            hsv.get_flattened_data() if hasattr(hsv, "get_flattened_data") else hsv.getdata()
        )
        luminance_image = sample.convert("L")
        luminance_pixels = (
            luminance_image.get_flattened_data()
            if hasattr(luminance_image, "get_flattened_data")
            else luminance_image.getdata()
        )
        saturation = [pixel[1] / 255 for pixel in hsv_pixels]
        luminance = [value / 255 for value in luminance_pixels]
        highlight_count = sum(
            value > 0.94 and saturation[index] < 0.30
            for index, value in enumerate(luminance)
        )
        digest = image_path.stem.split("-")[-1]
        crop_dir = cache_dir / "finish-crops" / digest
        crop_dir.mkdir(parents=True, exist_ok=True)
        regions = {
            "full": (0.02, 0.02, 0.98, 0.98),
            "illustration": (0.08, 0.12, 0.92, 0.48),
            "card_body": (0.08, 0.46, 0.92, 0.90),
        }
        crop_paths: dict[str, Path] = {}
        for name, (left, top, right, bottom) in regions.items():
            cropped = image.crop(
                (
                    round(width * left),
                    round(height * top),
                    round(width * right),
                    round(height * bottom),
                )
            )
            cropped.thumbnail((900, 1200))
            output = crop_dir / f"{name}.jpg"
            cropped.save(output, "JPEG", quality=92)
            crop_paths[name] = output
        inset_x = max(1, round(width * 0.14))
        inset_y = max(1, round(height * 0.10))
        strips = [
            image.crop((0, 0, width, inset_y)),
            image.crop((0, height - inset_y, width, height)),
            image.crop((0, inset_y, inset_x, height - inset_y)),
            image.crop((width - inset_x, inset_y, width, height - inset_y)),
        ]
        target_width = min(900, width)
        resized = []
        for strip in strips:
            scale = target_width / strip.width
            resized.append(
                strip.resize((target_width, max(1, round(strip.height * scale))))
            )
        border_montage = Image.new(
            "RGB",
            (target_width, sum(strip.height for strip in resized)),
            color=(255, 255, 255),
        )
        offset = 0
        for strip in resized:
            border_montage.paste(strip, (0, offset))
            offset += strip.height
        border_output = crop_dir / "outer_border.jpg"
        border_montage.save(border_output, "JPEG", quality=92)
        crop_paths["outer_border"] = border_output
        return FinishImageFeatures(
            image_sha256=digest,
            width=width,
            height=height,
            aspect_ratio=round(aspect, 6),
            card_like_aspect=0.58 <= aspect <= 0.82,
            saturation_mean=round(statistics.fmean(saturation), 6),
            saturation_stdev=round(statistics.pstdev(saturation), 6),
            luminance_stdev=round(statistics.pstdev(luminance), 6),
            highlight_fraction=round(highlight_count / max(1, len(luminance)), 6),
            crop_paths=crop_paths,
        )
    except Exception as exc:
        return FinishImageFeatures(
            width=0,
            height=0,
            aspect_ratio=0,
            saturation_mean=0,
            saturation_stdev=0,
            luminance_stdev=0,
            highlight_fraction=0,
            error=f"image_feature_error:{type(exc).__name__}",
        )


def resolve_finish(
    packet: EvidencePacket,
    *,
    visual: FinishVisualOutput | None = None,
    image_features: FinishImageFeatures | None = None,
) -> FinishResolution:
    if not finish_is_applicable(packet):
        return FinishResolution(
            policy_version=FINISH_RESOLUTION_POLICY_VERSION,
            applicable=False,
            verification_required=False,
            rationale_codes=["finish_not_applicable_non_single_card"],
            image_features=image_features,
        )
    assigned, evidence = _assigned_finish(packet)
    title_finishes = finishes_from_text(packet.sale.sale_title)
    title_finish = (
        title_finishes[0] if len(title_finishes) == 1 else FinishType.UNKNOWN
    )
    visual_finish = (
        visual.observed_finish
        if visual
        and visual.visually_determinable
        and visual.observed_finish != FinishType.UNKNOWN
        else FinishType.UNKNOWN
    )
    sibling_finishes = {
        candidate_finish(candidate) for candidate in finish_family_candidates(packet)
    }
    verification_required = bool(
        assigned != FinishType.UNKNOWN
        or title_finish != FinishType.UNKNOWN
        or sibling_finishes
    )
    visual_identity_finish = visual_finish
    visual_normalized_to_catalog = False
    if (
        visual_finish == FinishType.COSMOS_HOLO
        and assigned == FinishType.HOLO
        and FinishType.COSMOS_HOLO not in sibling_finishes
    ):
        # Cosmos can describe the visible pattern of a catalog product whose identity is simply
        # Holo. It is only a separate identity when PriceCharting exposes a cosmos sibling.
        visual_identity_finish = FinishType.HOLO
        visual_normalized_to_catalog = True
    generic_foil_normalized_to_holo = False
    if (
        visual_finish == FinishType.FOIL
        and FinishType.FOIL not in sibling_finishes
        and (
            assigned == FinishType.HOLO
            or title_finish == FinishType.HOLO
        )
    ):
        visual_identity_finish = FinishType.HOLO
        generic_foil_normalized_to_holo = True
    observed = FinishType.UNKNOWN
    rationale: list[str] = []
    if title_finish != FinishType.UNKNOWN:
        evidence.append(
            FinishEvidenceFact(
                source="listing_title",
                fact=f"Listing title explicitly identifies {title_finish.value}.",
                finish=title_finish,
            )
        )
        rationale.append("explicit_listing_finish")
    if visual_finish != FinishType.UNKNOWN and visual:
        evidence.append(
            FinishEvidenceFact(
                source="targeted_visual_review",
                fact=visual.reason,
                finish=visual_finish,
            )
        )
        rationale.append("targeted_visual_finish")
        if visual_normalized_to_catalog:
            evidence.append(
                FinishEvidenceFact(
                    source="catalog_finish_taxonomy",
                    fact=(
                        "Visual cosmos pattern is treated as Holo identity because this verified "
                        "PriceCharting family has no separate Cosmos Holo sibling."
                    ),
                    finish=FinishType.HOLO,
                )
            )
            rationale.append("visual_cosmos_normalized_to_catalog_holo")
        if generic_foil_normalized_to_holo:
            evidence.append(
                FinishEvidenceFact(
                    source="catalog_finish_taxonomy",
                    fact=(
                        "Generic visual foil is treated as Holo identity because the verified "
                        "PriceCharting family does not expose a separate Foil sibling."
                    ),
                    finish=FinishType.HOLO,
                )
            )
            rationale.append("visual_foil_normalized_to_catalog_holo")

    if title_finish != FinishType.UNKNOWN and visual_identity_finish != FinishType.UNKNOWN:
        if title_finish == visual_identity_finish:
            observed = title_finish
            rationale.append("title_visual_finish_agreement")
        else:
            rationale.append("title_visual_finish_conflict")
    elif title_finish != FinishType.UNKNOWN:
        observed = title_finish
    elif visual_identity_finish != FinishType.UNKNOWN:
        observed = visual_identity_finish

    if assigned == FinishType.UNKNOWN or observed == FinishType.UNKNOWN:
        match = FinishMatch.UNKNOWN
        rationale.append("finish_not_determinable")
    elif assigned == observed:
        match = FinishMatch.MATCH
        rationale.append("finish_match")
    else:
        match = FinishMatch.MISMATCH
        rationale.append("finish_mismatch")

    replacement_id: str | None = None
    if match == FinishMatch.MISMATCH:
        eligible = [
            candidate
            for candidate in packet.replacement_candidates
            if candidate.product_id != packet.product.product_id
            and candidate_finish(candidate) == observed
            and candidate.catalog
            and candidate.catalog.product_id_verified
            and candidate.catalog.image
            and candidate.catalog.image.usable
        ]
        if visual and visual.matching_candidate_id:
            eligible = [
                candidate
                for candidate in eligible
                if candidate.product_id == visual.matching_candidate_id
            ]
        if len(eligible) == 1:
            replacement_id = eligible[0].product_id
            rationale.append("unique_verified_finish_replacement")
            evidence.append(
                FinishEvidenceFact(
                    source="verified_replacement_catalog",
                    fact=(
                        f"PriceCharting candidate {replacement_id} is the unique verified "
                        f"{observed.value} sibling."
                    ),
                    finish=observed,
                )
            )
        else:
            rationale.append("replacement_not_unique_or_unverified")

    return FinishResolution(
        policy_version=FINISH_RESOLUTION_POLICY_VERSION,
        verification_required=verification_required,
        assigned_finish=assigned,
        observed_finish=observed,
        finish_match=match,
        replacement_product_id=replacement_id,
        requires_human_review=True,
        evidence=evidence,
        rationale_codes=list(dict.fromkeys(rationale)),
        visual=visual,
        image_features=image_features,
    )
