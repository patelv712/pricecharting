from __future__ import annotations

from pcqc.evidence import (
    build_derived_evidence,
    build_evidence_packet,
    extract_grade,
    identity_conflicts,
    identity_markers,
)
from pcqc.models import Decision, ProductEvidence, Route
from pcqc.models import ProductCandidate
from pcqc.rules import RulesReviewer


def test_grade_extraction_requires_context() -> None:
    assert extract_grade("Charizard #10 Holo 2024") == (None, None, None)
    assert extract_grade("Charizard PSA 10 Gem Mint") == ("PSA", 10.0, 7)
    assert extract_grade("Card CGC 10 Pristine") == ("CGC", 10.0, 19)
    assert extract_grade("Card BGS 10 Black Label") == ("BGS", 10.0, 20)
    assert extract_grade("Card graded 6") == (None, 6.0, 16)


def test_rules_detect_condition_change(sale) -> None:
    product = ProductEvidence(
        product_id=sale.product_id,
        product_name=sale.product_title,
        price_anchors={1: 1000, 7: 300000},
        source="test",
    )
    result = RulesReviewer().review(build_evidence_packet(sale, product))
    assert result.decision == Decision.CONDITION_CHANGE
    assert result.predicted_condition_id == 7
    assert result.route == Route.HUMAN_REVIEW
    assert not result.visual.image_usable


def test_rules_detect_deleted_listing(sale) -> None:
    changed = sale.model_copy(update={"sale_title": "Custom proxy card bundle lot"})
    product = ProductEvidence(product_id=sale.product_id, product_name=sale.product_title, source="test")
    result = RulesReviewer().review(build_evidence_packet(changed, product))
    assert result.decision == Decision.DELETED
    assert "title_lot_bundle" in result.rationale_codes


def test_championship_event_year_conflict_forces_modification(sale) -> None:
    changed = sale.model_copy(
        update={
            "product_title": "DON!! Card [Championship 2024]",
            "sale_title": (
                "2024 ONE PIECE PROMO CHAMPIONSHIP 23 WORLD FINAL "
                "MONKEY D LUFFY PSA 10"
            ),
        }
    )
    product = ProductEvidence(
        product_id=changed.product_id,
        product_name="DON!! Card [Championship 2024]",
        console_name="One Piece Promo",
        source="test",
    )
    packet = build_evidence_packet(changed, product)
    assert identity_conflicts(changed.sale_title, product.product_name) == [
        "championship_year_conflict:sale=2023:catalog=2024"
    ]
    result = RulesReviewer().review(packet)
    assert result.needs_modification
    assert result.predicted_label().value == "needs_modification"


def test_finish_markers_are_specific_and_conflicts_fail_closed(sale) -> None:
    assert identity_markers("Tyrantrum Reverse Holo #45") == {
        "finish": ["reverse_holo"]
    }
    assert identity_markers("Typhlosion non-holo PSA 10") == {
        "finish": ["non_holo"]
    }
    changed = sale.model_copy(
        update={
            "sale_title": "Typhlosion #16 non-holo PSA 10",
            "product_title": "Typhlosion Holo #16",
        }
    )
    product = ProductEvidence(
        product_id=changed.product_id,
        product_name="Typhlosion Holo #16",
        source="test",
    )
    packet = build_evidence_packet(changed, product)
    assert packet.derived.identity_conflicts == [
        "finish_conflict:sale=non_holo:catalog=holo"
    ]
    assert RulesReviewer().review(packet).needs_modification


def test_explicit_variant_without_catalog_marker_requires_review(sale) -> None:
    changed = sale.model_copy(
        update={
            "sale_title": "Buggy Alternate Art OP09-042 Japanese",
            "product_title": "Buggy OP09-042",
        }
    )
    product = ProductEvidence(
        product_id=changed.product_id,
        product_name="Buggy OP09-042",
        console_name="One Piece Japanese Emperors in the New World",
        source="test",
    )
    packet = build_evidence_packet(changed, product)
    assert "printing_catalog_unspecified:sale=alternate_art" in (
        packet.derived.identity_warnings
    )
    result = RulesReviewer().review(packet)
    assert result.needs_modification
    assert result.predicted_label().value == "needs_modification"


def test_catalog_variant_family_prevents_false_finish_match(sale) -> None:
    changed = sale.model_copy(
        update={
            "product_id": "12584352",
            "product_title": "Tyrantrum #45",
            "sale_title": "Tyrantrum 045/088 Perfect Order Pokemon Card",
        }
    )
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
        ),
        ProductCandidate(
            product_id="12385647",
            product_name="Tyrantrum [Reverse Holo] #45",
            retrieval_score=24,
        ),
    ]
    packet = build_evidence_packet(
        changed, product, replacement_candidates=candidates
    )
    assert packet.derived.identity_warnings == [
        "catalog_variant_family_ambiguous:dimensions=finish:"
        "siblings=12368512,12385647"
    ]
    result = RulesReviewer().review(packet)
    assert result.needs_modification
    assert result.predicted_label().value == "needs_modification"


def test_catalog_variant_family_ignores_other_languages_and_same_variant(sale) -> None:
    changed = sale.model_copy(
        update={
            "product_id": "13159364",
            "product_title": "Portgas.D.Ace [Alternate Art] OP16-118",
        }
    )
    product = ProductEvidence(
        product_id="13159364",
        product_name=changed.product_title,
        console_name="One Piece Japanese The Time of Battle",
        source="test",
    )
    candidates = [
        ProductCandidate(
            product_id="13159363",
            product_name="Portgas.D.Ace OP16-118",
            console_name="One Piece Japanese The Time of Battle",
            retrieval_score=70,
        ),
        ProductCandidate(
            product_id="13335495",
            product_name="Portgas.D.Ace [Alternate Art] OP16-118",
            console_name="One Piece The Time of Battle",
            retrieval_score=54,
        ),
    ]
    packet = build_evidence_packet(
        changed, product, replacement_candidates=candidates
    )
    assert packet.derived.identity_warnings == [
        "catalog_variant_family_ambiguous:dimensions=printing:siblings=13159363"
    ]


def test_price_is_not_used_as_sole_deletion_or_condition_proof(sale) -> None:
    changed = sale.model_copy(update={"sale_title": sale.product_title, "sale_amount_pennies": 99999999})
    product = ProductEvidence(
        product_id=sale.product_id,
        product_name=sale.product_title,
        price_anchors={1: 1000, 7: 300000},
        source="test",
    )
    derived = build_derived_evidence(changed, product)
    result = RulesReviewer().review(build_evidence_packet(changed, product))
    assert derived.nearest_condition_id is not None
    assert result.decision == Decision.IGNORED


def test_enrichment_warnings_remain_auditable(sale) -> None:
    product = ProductEvidence(
        product_id=sale.product_id,
        product_name=sale.product_title,
        source="sales-export",
    )
    packet = build_evidence_packet(
        sale,
        product,
        enrichment_warnings=[
            "assigned_product_api_unavailable:TimeoutError",
            "candidate_search_unavailable:TimeoutError",
        ],
    )
    result = RulesReviewer().review(packet)
    assert result.deterministic_evidence.enrichment_warnings == [
        "assigned_product_api_unavailable:TimeoutError",
        "candidate_search_unavailable:TimeoutError",
    ]
