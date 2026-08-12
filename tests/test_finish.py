from __future__ import annotations

from PIL import Image

from pcqc.evidence import build_evidence_packet
from pcqc.finish import (
    candidate_finish,
    extract_image_features,
    finish_family_candidates,
    finishes_from_text,
    resolve_finish,
)
from pcqc.models import (
    CatalogEvidence,
    FinishMatch,
    FinishType,
    FinishVisualOutput,
    ImageEvidence,
    ProductCandidate,
    ProductEvidence,
)


def _catalog(description: str | None = None) -> CatalogEvidence:
    return CatalogEvidence(
        product_id_verified=True,
        description=description,
        image=ImageEvidence(available=True, usable=True, content_type="image/jpeg"),
    )


def test_finish_text_ontology_prioritizes_specific_treatments() -> None:
    assert finishes_from_text("Reverse Holo Foil") == [FinishType.REVERSE_HOLO]
    assert finishes_from_text("Cosmos Holo promo") == [FinishType.COSMOS_HOLO]
    assert finishes_from_text("Non-Holo deck card") == [FinishType.REGULAR]
    assert finishes_from_text("Description: Holo") == [FinishType.HOLO]


def test_catalog_description_resolves_unsuffixed_holo(sale) -> None:
    product = ProductEvidence(
        product_id="920639",
        product_name="Typhlosion #16",
        console_name="Pokemon Mysterious Treasures",
        source="test",
    )
    packet = build_evidence_packet(
        sale.model_copy(update={"product_id": "920639"}),
        product,
        catalog=_catalog("Holo"),
    )
    resolution = resolve_finish(
        packet,
        visual=FinishVisualOutput(
            visually_determinable=True,
            observed_finish=FinishType.HOLO,
            evidence_regions=["slab_label", "illustration"],
            reason="PSA label says HOLO and reflection is inside the illustration.",
        ),
    )
    assert resolution.assigned_finish == FinishType.HOLO
    assert resolution.observed_finish == FinishType.HOLO
    assert resolution.finish_match == FinishMatch.MATCH


def test_cosmos_pattern_normalizes_to_holo_without_cosmos_product(sale) -> None:
    product = ProductEvidence(
        product_id="920639",
        product_name="Typhlosion #16",
        console_name="Pokemon Mysterious Treasures",
        source="test",
    )
    packet = build_evidence_packet(
        sale.model_copy(update={"sale_title": "Typhlosion #16 Holo PSA 10"}),
        product,
        catalog=_catalog("Holo"),
        replacement_candidates=[
            ProductCandidate(
                product_id="920764",
                product_name="Typhlosion [Reverse Holo] #16",
                retrieval_score=70,
                catalog=_catalog(),
            )
        ],
    )
    resolution = resolve_finish(
        packet,
        visual=FinishVisualOutput(
            visually_determinable=True,
            observed_finish=FinishType.COSMOS_HOLO,
            evidence_regions=["illustration"],
            reason="Stars and circles are visible within the illustration.",
        ),
    )
    assert resolution.observed_finish == FinishType.HOLO
    assert resolution.finish_match == FinishMatch.MATCH
    assert "visual_cosmos_normalized_to_catalog_holo" in resolution.rationale_codes


def test_generic_visual_foil_normalizes_to_holo_without_foil_sibling(sale) -> None:
    product = ProductEvidence(
        product_id="889180", product_name="Mew EX #100", source="test"
    )
    packet = build_evidence_packet(
        sale.model_copy(update={"sale_title": "Mew EX #100 Holo PSA 8"}),
        product,
        catalog=_catalog(),
    )
    resolution = resolve_finish(
        packet,
        visual=FinishVisualOutput(
            visually_determinable=True,
            observed_finish=FinishType.FOIL,
            evidence_regions=["illustration", "border"],
            reason="Reflective treatment is visible across the card.",
        ),
    )
    assert resolution.observed_finish == FinishType.HOLO
    assert resolution.finish_match == FinishMatch.UNKNOWN
    assert "visual_foil_normalized_to_catalog_holo" in resolution.rationale_codes


def test_unsuffixed_catalog_with_named_cosmos_sibling_is_regular(sale) -> None:
    product = ProductEvidence(
        product_id="806540",
        product_name="Pikachu #42",
        console_name="Pokemon XY",
        source="test",
    )
    cosmos = ProductCandidate(
        product_id="7051675",
        product_name="Pikachu [Cosmos Holo] #42",
        retrieval_score=70,
        catalog=_catalog(),
    )
    packet = build_evidence_packet(
        sale.model_copy(update={"product_id": "806540"}),
        product,
        catalog=_catalog(),
        replacement_candidates=[cosmos],
    )
    resolution = resolve_finish(
        packet,
        visual=FinishVisualOutput(
            visually_determinable=True,
            observed_finish=FinishType.COSMOS_HOLO,
            matching_candidate_id="7051675",
            evidence_regions=["illustration"],
            reason="Cosmos star pattern is visible in the illustration.",
        ),
    )
    assert resolution.assigned_finish == FinishType.REGULAR
    assert resolution.finish_match == FinishMatch.MISMATCH
    assert resolution.replacement_product_id == "7051675"


def test_unsuffixed_product_with_only_unknown_self_candidate_stays_unknown(sale) -> None:
    product = ProductEvidence(
        product_id="5326233", product_name="Zapdos EX #204", source="test"
    )
    packet = build_evidence_packet(
        sale,
        product,
        catalog=_catalog(),
        replacement_candidates=[
            ProductCandidate(
                product_id="5326233",
                product_name="Zapdos EX #204",
                retrieval_score=80,
            )
        ],
    )
    resolution = resolve_finish(packet)
    assert resolution.assigned_finish == FinishType.UNKNOWN
    assert resolution.finish_match == FinishMatch.UNKNOWN
    assert not resolution.verification_required


def test_finish_is_not_applicable_to_booster_pack(sale) -> None:
    product = ProductEvidence(
        product_id="3269421", product_name="Booster Pack", source="test"
    )
    packet = build_evidence_packet(
        sale.model_copy(update={"sale_title": "Base Set 2 Foil Booster Pack"}),
        product,
        catalog=_catalog(),
    )
    resolution = resolve_finish(packet)
    assert not resolution.applicable
    assert not resolution.verification_required
    assert resolution.assigned_finish == FinishType.UNKNOWN
    assert resolution.observed_finish == FinishType.UNKNOWN
    assert "finish_not_applicable_non_single_card" in resolution.rationale_codes


def test_reverse_holo_resolves_to_unique_verified_sibling(sale) -> None:
    product = ProductEvidence(
        product_id="12584352",
        product_name="Tyrantrum #45",
        console_name="Pokemon Perfect Order",
        source="test",
    )
    candidates = [
        ProductCandidate(
            product_id="12368512",
            product_name="Tyrantrum [Holo] #45",
            retrieval_score=26,
            catalog=_catalog(),
        ),
        ProductCandidate(
            product_id="12385647",
            product_name="Tyrantrum [Reverse Holo] #45",
            retrieval_score=24,
            catalog=_catalog(),
        ),
    ]
    packet = build_evidence_packet(
        sale.model_copy(
            update={
                "product_id": "12584352",
                "sale_title": "Tyrantrum 045/088 Perfect Order Pokemon Card",
            }
        ),
        product,
        catalog=_catalog(),
        replacement_candidates=candidates,
    )
    visual = FinishVisualOutput(
        visually_determinable=True,
        observed_finish=FinishType.REVERSE_HOLO,
        matching_candidate_id="12385647",
        evidence_regions=["card_body", "border"],
        reason="Reflective pattern is visible outside the illustration window.",
    )
    resolution = resolve_finish(packet, visual=visual)
    assert resolution.assigned_finish == FinishType.REGULAR
    assert candidate_finish(candidates[1]) == FinishType.REVERSE_HOLO
    assert resolution.finish_match == FinishMatch.MISMATCH
    assert resolution.replacement_product_id == "12385647"


def test_finish_family_normalizes_assigned_and_candidate_labels(sale) -> None:
    packet = build_evidence_packet(
        sale,
        ProductEvidence(
            product_id="1", product_name="Pikachu [Holo] #42", source="test"
        ),
        replacement_candidates=[
            ProductCandidate(
                product_id="2",
                product_name="Pikachu [Reverse Holo] #42",
                retrieval_score=80,
            )
        ],
    )
    assert [candidate.product_id for candidate in finish_family_candidates(packet)] == [
        "2"
    ]


def test_unknown_visual_evidence_remains_unknown(sale) -> None:
    product = ProductEvidence(
        product_id=sale.product_id, product_name="Card [Holo] #1", source="test"
    )
    packet = build_evidence_packet(sale, product, catalog=_catalog())
    resolution = resolve_finish(
        packet,
        visual=FinishVisualOutput(
            visually_determinable=False,
            observed_finish=FinishType.UNKNOWN,
            reason="Lighting does not reveal reflective treatment.",
        ),
    )
    assert resolution.finish_match == FinishMatch.UNKNOWN
    assert resolution.observed_finish == FinishType.UNKNOWN
    assert resolution.requires_human_review


def test_title_and_visual_finish_conflict_is_unknown(sale) -> None:
    product = ProductEvidence(
        product_id="920639", product_name="Typhlosion #16", source="test"
    )
    packet = build_evidence_packet(
        sale.model_copy(update={"sale_title": "Typhlosion #16 Holo"}),
        product,
        catalog=_catalog("Holo"),
    )
    resolution = resolve_finish(
        packet,
        visual=FinishVisualOutput(
            visually_determinable=True,
            observed_finish=FinishType.REVERSE_HOLO,
            evidence_regions=["card_body"],
            reason="Reflection appears outside the illustration.",
        ),
    )
    assert resolution.observed_finish == FinishType.UNKNOWN
    assert resolution.finish_match == FinishMatch.UNKNOWN
    assert "title_visual_finish_conflict" in resolution.rationale_codes


def test_image_features_and_crops_are_reproducible(tmp_path) -> None:
    image_path = tmp_path / "listing-sha.jpg"
    image = Image.new("RGB", (700, 1000), color=(210, 170, 30))
    image.save(image_path)
    features = extract_image_features(image_path, tmp_path)
    assert features.width == 700
    assert features.height == 1000
    assert features.card_like_aspect
    assert set(features.crop_paths) == {
        "full",
        "illustration",
        "card_body",
        "outer_border",
    }
    assert all(path.exists() for path in features.crop_paths.values())
