from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from pcqc.evidence import build_evidence_packet
from pcqc.models import (
    CatalogEvidence,
    Decision,
    FinishEvidenceFact,
    FinishMatch,
    FinishResolution,
    FinishType,
    ImageEvidence,
    ProductCandidate,
    ProductEvidence,
)
from pcqc.provider import OpenAICompatibleReviewer, ProviderHTTPError

from conftest import FakeResponse


def _envelope(content: str) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    }


def test_provider_repairs_invalid_output_and_hides_labels(sale) -> None:
    requests = []
    valid = {
        "decision": "condition_change",
        "predicted_condition_id": 7,
        "needs_modification": False,
        "reason": "PSA 10 is explicit in the title.",
        "rationale_codes": ["title_grade_conflicts_with_condition"],
    }

    def opener(request, timeout):
        requests.append(json.loads(request.data))
        if len(requests) == 1:
            return FakeResponse(_envelope("not json"))
        return FakeResponse(_envelope(json.dumps(valid)))

    product = ProductEvidence(product_id=sale.product_id, product_name=sale.product_title, source="test")
    reviewer = OpenAICompatibleReviewer(
        api_key="provider-secret",
        base_url="https://llm.example/v1",
        model="vision-test",
        opener=opener,
    )
    result = reviewer.review(build_evidence_packet(sale, product))
    assert result.decision == Decision.CONDITION_CHANGE
    assert result.route.value == "human_review"
    assert result.input_tokens == 12
    assert len(requests) == 2
    first_prompt = json.dumps(requests[0])
    assert '"target"' not in first_prompt
    assert "review_action_condition_id" not in first_prompt
    assert "most_recent_report" not in first_prompt
    assert '"score"' not in first_prompt
    prompt_payload = json.loads(requests[0]["messages"][1]["content"][0]["text"])
    assert "source" not in prompt_payload["evidence"]["product"]
    assert "provider-secret" not in first_prompt
    assert "condition_catalog" in first_prompt
    assert "raw_confidence" not in first_prompt
    assert "final_confidence" not in first_prompt
    assert "valid single-item sale" in requests[0]["messages"][0]["content"]
    assert prompt_payload["evidence"]["condition_catalog"]["7"] == "PSA 10"


def test_text_only_provider_omits_image_bytes_and_metadata(
    sale, tmp_path
) -> None:
    image_path = tmp_path / "listing.jpg"
    image_path.write_bytes(b"not-a-real-image")
    requests = []
    valid = {
        "decision": "ignored",
        "predicted_condition_id": None,
        "needs_modification": False,
        "reason": "Text-only evidence is insufficient for automation.",
        "visual": {"image_usable": False},
    }

    def opener(request, timeout):
        requests.append(json.loads(request.data))
        return FakeResponse(_envelope(json.dumps(valid)))

    product = ProductEvidence(
        product_id=sale.product_id,
        product_name=sale.product_title,
        source="test",
    )
    packet = build_evidence_packet(
        sale,
        product,
        ImageEvidence(
            available=True,
            usable=True,
            content_type="image/jpeg",
            cache_path=image_path,
        ),
    )
    reviewer = OpenAICompatibleReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="m",
        opener=opener,
        include_image=False,
    )
    reviewer.review(packet)
    content = requests[0]["messages"][1]["content"]
    prompt_payload = json.loads(content[0]["text"])
    assert len(content) == 1
    assert "image" not in prompt_payload["evidence"]
    assert "base64" not in json.dumps(requests[0])
    assert reviewer.inference_mode == "text_only"


def test_multimodal_provider_sends_catalog_image_and_rejects_unverified_match(
    sale, tmp_path
) -> None:
    listing_path = tmp_path / "listing.jpg"
    catalog_path = tmp_path / "catalog.jpg"
    listing_path.write_bytes(b"listing-image")
    catalog_path.write_bytes(b"catalog-image")
    requests = []
    output = {
        "decision": "ignored",
        "predicted_condition_id": None,
        "needs_modification": False,
        "reason": "The names appear similar.",
        "catalog_comparison": "mismatch",
    }

    def opener(request, timeout):
        requests.append(json.loads(request.data))
        return FakeResponse(_envelope(json.dumps(output)))

    product = ProductEvidence(
        product_id=sale.product_id,
        product_name=sale.product_title,
        source="test",
    )
    packet = build_evidence_packet(
        sale,
        product,
        ImageEvidence(
            available=True,
            usable=True,
            content_type="image/jpeg",
            cache_path=listing_path,
        ),
        CatalogEvidence(
            page_url="https://www.pricecharting.com/game/example/card",
            image_url="https://images.example/card.jpg",
            product_id_verified=True,
            image=ImageEvidence(
                available=True,
                usable=True,
                content_type="image/jpeg",
                cache_path=catalog_path,
            ),
        ),
    )
    reviewer = OpenAICompatibleReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="m",
        opener=opener,
    )
    result = reviewer.review(packet)
    content = requests[0]["messages"][1]["content"]
    assert [item["type"] for item in content] == [
        "text",
        "text",
        "image_url",
        "text",
        "image_url",
    ]
    assert result.needs_modification
    assert "catalog_artwork_not_verified" in result.rationale_codes


def test_provider_cannot_override_deterministic_identity_conflict(sale) -> None:
    output = {
        "decision": "ignored",
        "predicted_condition_id": None,
        "needs_modification": False,
        "reason": "The generic DON card title appears to match.",
        "catalog_comparison": "match",
    }

    def opener(request, timeout):
        return FakeResponse(_envelope(json.dumps(output)))

    changed = sale.model_copy(
        update={
            "product_title": "DON!! Card [Championship 2024]",
            "sale_title": (
                "2024 ONE PIECE PROMO CHAMPIONSHIP 23 WORLD FINAL PSA 10"
            ),
        }
    )
    product = ProductEvidence(
        product_id=changed.product_id,
        product_name="DON!! Card [Championship 2024]",
        source="test",
    )
    reviewer = OpenAICompatibleReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="m",
        opener=opener,
    )
    result = reviewer.review(build_evidence_packet(changed, product))
    assert result.needs_modification
    assert (
        "championship_year_conflict:sale=2023:catalog=2024"
        in result.rationale_codes
    )


def test_provider_cannot_accept_unverified_or_mismatched_finish(sale) -> None:
    outputs = [
        {
            "decision": "ignored",
            "needs_modification": False,
            "reason": "Finish is difficult to see.",
            "catalog_comparison": "match",
            "identity_comparison": {"finish": "uncertain"},
        },
        {
            "decision": "ignored",
            "needs_modification": False,
            "reason": "Listing is reverse holo but catalog is regular.",
            "catalog_comparison": "mismatch",
            "identity_comparison": {"finish": "mismatch"},
        },
    ]

    def opener(request, timeout):
        return FakeResponse(_envelope(json.dumps(outputs.pop(0))))

    reviewer = OpenAICompatibleReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="m",
        opener=opener,
    )
    product = ProductEvidence(
        product_id=sale.product_id,
        product_name=sale.product_title,
        source="test",
    )
    uncertain = reviewer.review(build_evidence_packet(sale, product))
    mismatch = reviewer.review(build_evidence_packet(sale, product))
    assert uncertain.needs_modification
    assert "finish_not_verified" in uncertain.rationale_codes
    assert mismatch.needs_modification
    assert "finish_mismatch" in mismatch.rationale_codes


def test_targeted_finish_mismatch_overrides_general_model(sale, tmp_path) -> None:
    listing = tmp_path / "listing.jpg"
    assigned = tmp_path / "assigned.jpg"
    replacement = tmp_path / "replacement.jpg"
    for path in (listing, assigned, replacement):
        path.write_bytes(b"image")
    output = {
        "decision": "ignored",
        "needs_modification": False,
        "reason": "The general model incorrectly considers the finish a match.",
        "catalog_comparison": "match",
        "identity_comparison": {"finish": "match"},
    }

    def opener(request, timeout):
        return FakeResponse(_envelope(json.dumps(output)))

    product = ProductEvidence(
        product_id="12584352", product_name="Tyrantrum #45", source="test"
    )
    packet = build_evidence_packet(
        sale.model_copy(update={"product_id": "12584352"}),
        product,
        ImageEvidence(
            available=True, usable=True, content_type="image/jpeg", cache_path=listing
        ),
        CatalogEvidence(
            product_id_verified=True,
            notes="Non-holo deck exclusive",
            image=ImageEvidence(
                available=True,
                usable=True,
                content_type="image/jpeg",
                cache_path=assigned,
            ),
        ),
        replacement_candidates=[
            ProductCandidate(
                product_id="12385647",
                product_name="Tyrantrum [Reverse Holo] #45",
                retrieval_score=80,
                catalog=CatalogEvidence(
                    product_id_verified=True,
                    image=ImageEvidence(
                        available=True,
                        usable=True,
                        content_type="image/jpeg",
                        cache_path=replacement,
                    ),
                ),
            )
        ],
    ).model_copy(
        update={
            "finish_resolution": FinishResolution(
                assigned_finish=FinishType.REGULAR,
                observed_finish=FinishType.REVERSE_HOLO,
                finish_match=FinishMatch.MISMATCH,
                replacement_product_id="12385647",
                evidence=[
                    FinishEvidenceFact(
                        source="targeted_visual_review",
                        fact="Reflection is visible outside the illustration.",
                        finish=FinishType.REVERSE_HOLO,
                    )
                ],
            )
        }
    )
    result = OpenAICompatibleReviewer(
        api_key="secret", base_url="https://example.test", model="m", opener=opener
    ).review(packet)
    assert result.needs_modification
    assert result.identity_comparison.finish == "mismatch"
    assert result.replacement_product_id == "12385647"
    assert "targeted_finish_mismatch" in result.rationale_codes
    assert "targeted_finish_replacement" in result.rationale_codes
    assert "finish_not_verified" not in result.rationale_codes
    assert not any(
        code.startswith("catalog_variant_family_ambiguous:")
        for code in result.rationale_codes
    )


def test_targeted_finish_match_clears_only_finish_warnings(sale, tmp_path) -> None:
    listing = tmp_path / "listing.jpg"
    assigned = tmp_path / "assigned.jpg"
    sibling = tmp_path / "sibling.jpg"
    for path in (listing, assigned, sibling):
        path.write_bytes(b"image")
    output = {
        "decision": "ignored",
        "needs_modification": False,
        "reason": "The assigned holo product and listing match.",
        "catalog_comparison": "match",
        "identity_comparison": {"finish": "uncertain"},
    }

    def opener(request, timeout):
        return FakeResponse(_envelope(json.dumps(output)))

    product = ProductEvidence(
        product_id="920639", product_name="Typhlosion #16", source="test"
    )
    packet = build_evidence_packet(
        sale.model_copy(
            update={
                "product_id": "920639",
                "sale_title": "Typhlosion #16 Holo PSA 10",
            }
        ),
        product,
        ImageEvidence(
            available=True, usable=True, content_type="image/jpeg", cache_path=listing
        ),
        CatalogEvidence(
            product_id_verified=True,
            description="Holo",
            image=ImageEvidence(
                available=True,
                usable=True,
                content_type="image/jpeg",
                cache_path=assigned,
            ),
        ),
        replacement_candidates=[
            ProductCandidate(
                product_id="920764",
                product_name="Typhlosion [Reverse Holo] #16",
                retrieval_score=80,
                catalog=CatalogEvidence(
                    product_id_verified=True,
                    image=ImageEvidence(
                        available=True,
                        usable=True,
                        content_type="image/jpeg",
                        cache_path=sibling,
                    ),
                ),
            )
        ],
    ).model_copy(
        update={
            "finish_resolution": FinishResolution(
                assigned_finish=FinishType.HOLO,
                observed_finish=FinishType.HOLO,
                finish_match=FinishMatch.MATCH,
            )
        }
    )
    assert any(
        warning.startswith("finish_catalog_unspecified:")
        for warning in packet.derived.identity_warnings
    )
    result = OpenAICompatibleReviewer(
        api_key="secret", base_url="https://example.test", model="m", opener=opener
    ).review(packet)
    assert not result.needs_modification
    assert result.identity_comparison.finish == "match"
    assert not any("finish_catalog_unspecified" in code for code in result.rationale_codes)


def test_verified_visual_identity_match_clears_resolved_variant_warnings(
    sale, tmp_path
) -> None:
    listing = tmp_path / "listing.jpg"
    assigned = tmp_path / "assigned.jpg"
    listing.write_bytes(b"image")
    assigned.write_bytes(b"image")
    output = {
        "decision": "ignored",
        "needs_modification": False,
        "reason": "The English pre-errata printing matches the assigned catalog image.",
        "catalog_comparison": "match",
        "identity_comparison": {
            "artwork": "match",
            "language": "match",
            "printing_or_parallel": "match",
        },
    }

    def opener(request, timeout):
        return FakeResponse(_envelope(json.dumps(output)))

    product = ProductEvidence(
        product_id="6235276",
        product_name="Nami [Alternate Art] OP01-016",
        console_name="One Piece Romance Dawn",
        source="test",
    )
    packet = build_evidence_packet(
        sale.model_copy(
            update={
                "product_id": product.product_id,
                "product_title": product.product_name,
                "sale_title": (
                    "NAMI ONE PIECE OP01-016 2022 OP01 ALTERNATE ART "
                    "ROMANCE DAWN PSA 10 ENGLISH"
                ),
            }
        ),
        product,
        ImageEvidence(
            available=True, usable=True, content_type="image/jpeg", cache_path=listing
        ),
        CatalogEvidence(
            product_id_verified=True,
            image=ImageEvidence(
                available=True,
                usable=True,
                content_type="image/jpeg",
                cache_path=assigned,
            ),
        ),
        replacement_candidates=[
            ProductCandidate(
                product_id="6235275",
                product_name="Nami OP01-016",
                console_name="One Piece Romance Dawn",
                retrieval_score=70,
            )
        ],
    ).model_copy(
        update={
            "finish_resolution": FinishResolution(
                applicable=False,
                verification_required=False,
                rationale_codes=["finish_not_applicable_test"],
            )
        }
    )
    assert packet.derived.identity_warnings == [
        "language_catalog_unspecified:sale=english",
        "catalog_variant_family_ambiguous:dimensions=printing:siblings=6235275",
    ]
    result = OpenAICompatibleReviewer(
        api_key="secret", base_url="https://example.test", model="m", opener=opener
    ).review(packet)
    assert not result.needs_modification
    assert not any(
        code.startswith("catalog_variant_family_ambiguous:")
        for code in result.rationale_codes
    )
    assert not any(
        code.startswith("language_catalog_unspecified:")
        for code in result.rationale_codes
    )


def test_non_card_product_skips_finish_identity_gate(sale, tmp_path) -> None:
    listing = tmp_path / "listing.jpg"
    assigned = tmp_path / "assigned.jpg"
    listing.write_bytes(b"image")
    assigned.write_bytes(b"image")
    output = {
        "decision": "ignored",
        "needs_modification": False,
        "reason": "The sealed booster pack matches the assigned product.",
        "catalog_comparison": "match",
        "identity_comparison": {"finish": "mismatch"},
        "rationale_codes": ["finish_mismatch"],
    }

    def opener(request, timeout):
        return FakeResponse(_envelope(json.dumps(output)))

    packet = build_evidence_packet(
        sale.model_copy(update={"sale_title": "Base Set 2 Foil Booster Pack"}),
        ProductEvidence(product_id="3269421", product_name="Booster Pack", source="test"),
        ImageEvidence(
            available=True, usable=True, content_type="image/jpeg", cache_path=listing
        ),
        CatalogEvidence(
            product_id_verified=True,
            image=ImageEvidence(
                available=True,
                usable=True,
                content_type="image/jpeg",
                cache_path=assigned,
            ),
        ),
    ).model_copy(
        update={
            "finish_resolution": FinishResolution(
                policy_version="test",
                applicable=False,
                rationale_codes=["finish_not_applicable_non_single_card"],
            )
        }
    )
    result = OpenAICompatibleReviewer(
        api_key="secret", base_url="https://example.test", model="m", opener=opener
    ).review(packet)
    assert not result.needs_modification
    assert result.identity_comparison.finish == "uncertain"
    assert "finish_mismatch" not in result.rationale_codes


def test_generic_booster_pack_artwork_is_not_a_product_mismatch(sale, tmp_path) -> None:
    listing = tmp_path / "listing.jpg"
    assigned = tmp_path / "assigned.jpg"
    listing.write_bytes(b"image")
    assigned.write_bytes(b"image")
    output = {
        "decision": "condition_change",
        "predicted_condition_id": 7,
        "needs_modification": True,
        "reason": "The pack art differs, but the PSA 10 condition is explicit.",
        "catalog_comparison": "match",
        "identity_comparison": {"artwork": "mismatch", "finish": "uncertain"},
        "rationale_codes": ["condition_mismatch", "artwork_mismatch"],
    }

    def opener(request, timeout):
        return FakeResponse(_envelope(json.dumps(output)))

    packet = build_evidence_packet(
        sale.model_copy(update={"sale_title": "Base Set 2 Gyarados Booster Pack PSA 10"}),
        ProductEvidence(product_id="3269421", product_name="Booster Pack", source="test"),
        ImageEvidence(
            available=True, usable=True, content_type="image/jpeg", cache_path=listing
        ),
        CatalogEvidence(
            product_id_verified=True,
            image=ImageEvidence(
                available=True,
                usable=True,
                content_type="image/jpeg",
                cache_path=assigned,
            ),
        ),
    ).model_copy(
        update={
            "finish_resolution": FinishResolution(
                policy_version="test",
                applicable=False,
                verification_required=False,
                rationale_codes=["finish_not_applicable_non_single_card"],
            )
        }
    )
    result = OpenAICompatibleReviewer(
        api_key="secret", base_url="https://example.test", model="m", opener=opener
    ).review(packet)
    assert not result.needs_modification
    assert result.identity_comparison.artwork == "uncertain"
    assert "artwork_mismatch" not in result.rationale_codes
    assert "generic_sealed_artwork_not_catalog_identity" in result.rationale_codes


def test_no_finish_signal_does_not_manufacture_modification(sale, tmp_path) -> None:
    listing = tmp_path / "listing.jpg"
    assigned = tmp_path / "assigned.jpg"
    listing.write_bytes(b"image")
    assigned.write_bytes(b"image")
    output = {
        "decision": "ignored",
        "needs_modification": False,
        "reason": "The product and condition match.",
        "catalog_comparison": "match",
        "identity_comparison": {"finish": "uncertain"},
    }

    def opener(request, timeout):
        return FakeResponse(_envelope(json.dumps(output)))

    packet = build_evidence_packet(
        sale,
        ProductEvidence(product_id="1", product_name="Zapdos EX #204", source="test"),
        ImageEvidence(
            available=True, usable=True, content_type="image/jpeg", cache_path=listing
        ),
        CatalogEvidence(
            product_id_verified=True,
            image=ImageEvidence(
                available=True,
                usable=True,
                content_type="image/jpeg",
                cache_path=assigned,
            ),
        ),
    ).model_copy(
        update={
            "finish_resolution": FinishResolution(
                policy_version="test",
                verification_required=False,
            )
        }
    )
    result = OpenAICompatibleReviewer(
        api_key="secret", base_url="https://example.test", model="m", opener=opener
    ).review(packet)
    assert not result.needs_modification
    assert "finish_not_verified" not in result.rationale_codes


def test_provider_rejects_ai_generated_confidence_and_repairs(sale) -> None:
    requests = []
    clean = {
        "decision": "ignored",
        "predicted_condition_id": None,
        "needs_modification": False,
        "reason": "The observable evidence matches.",
    }

    def opener(request, timeout):
        requests.append(json.loads(request.data))
        payload = clean | {"raw_confidence": 0.99} if len(requests) == 1 else clean
        return FakeResponse(_envelope(json.dumps(payload)))

    reviewer = OpenAICompatibleReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="m",
        opener=opener,
    )
    product = ProductEvidence(
        product_id=sale.product_id,
        product_name=sale.product_title,
        source="test",
    )
    result = reviewer.review(build_evidence_packet(sale, product))
    assert len(requests) == 2
    assert "confidence" in requests[1]["messages"][-1]["content"]
    assert "raw_confidence" not in result.model_dump()
    assert result.route.value == "human_review"


def test_provider_contract_rejects_condition_without_id(sale) -> None:
    invalid = {
        "decision": "condition_change",
        "needs_modification": False,
        "reason": "Missing ID",
    }
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        return FakeResponse(_envelope(json.dumps(invalid)))

    reviewer = OpenAICompatibleReviewer(
        api_key="x", base_url="https://example.test", model="m", opener=opener
    )
    product = ProductEvidence(product_id=sale.product_id, product_name=sale.product_title, source="test")
    try:
        reviewer.review(build_evidence_packet(sale, product))
    except Exception as exc:
        assert "predicted_condition_id" in str(exc)
    else:
        raise AssertionError("invalid output should fail after repair")
    assert calls == 2


def test_provider_discards_condition_id_for_non_condition_action(sale) -> None:
    requests = []
    output = {
        "decision": "ignored",
        "predicted_condition_id": 1,
        "needs_modification": False,
        "reason": "The product appears to match but finish is uncertain.",
        "catalog_comparison": "match",
        "identity_comparison": {"finish": "uncertain"},
    }

    def opener(request, timeout):
        requests.append(json.loads(request.data))
        return FakeResponse(_envelope(json.dumps(output)))

    reviewer = OpenAICompatibleReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="m",
        opener=opener,
    )
    product = ProductEvidence(
        product_id=sale.product_id,
        product_name=sale.product_title,
        source="test",
    )
    result = reviewer.review(build_evidence_packet(sale, product))
    assert len(requests) == 1
    assert result.predicted_condition_id is None
    assert "discarded_irrelevant_predicted_condition_id" in result.rationale_codes


def test_provider_only_accepts_replacement_from_candidates(sale, tmp_path) -> None:
    candidate_image_path = tmp_path / "candidate.jpg"
    candidate_image_path.write_bytes(b"candidate-image")
    outputs = [
        {
            "decision": "ignored",
            "needs_modification": True,
            "replacement_product_id": "8506909",
            "replacement_comparison": "match",
            "reason": "The listing is the alternate-art printing.",
        },
        {
            "decision": "ignored",
            "needs_modification": True,
            "replacement_product_id": "9999999",
            "reason": "An unsupported product was invented.",
        },
    ]
    requests = []

    def opener(request, timeout):
        requests.append(json.loads(request.data))
        return FakeResponse(_envelope(json.dumps(outputs.pop(0))))

    product = ProductEvidence(
        product_id="8506907", product_name="Buggy OP09-042", source="test"
    )
    packet = build_evidence_packet(
        sale.model_copy(update={"product_id": "8506907"}),
        product,
        replacement_candidates=[
                ProductCandidate(
                product_id="8506909",
                product_name="Buggy [Alternate Art] OP09-042",
                    retrieval_score=88,
                    catalog=CatalogEvidence(
                        product_id_verified=True,
                        image=ImageEvidence(
                            available=True,
                            usable=True,
                            content_type="image/jpeg",
                            cache_path=candidate_image_path,
                        ),
                    ),
                )
        ],
    )
    reviewer = OpenAICompatibleReviewer(
        api_key="secret", base_url="https://example.test", model="m", opener=opener
    )
    accepted = reviewer.review(packet)
    discarded = reviewer.review(packet)
    assert accepted.replacement_product_id == "8506909"
    assert "verified_replacement_candidate_selected" in accepted.rationale_codes
    assert discarded.replacement_product_id is None
    assert "unverified_replacement_product_id_discarded" in discarded.rationale_codes
    first_content = requests[0]["messages"][1]["content"]
    assert "IMAGE 3: REPLACEMENT CANDIDATE 8506909" in json.dumps(first_content)


def test_provider_preserves_sanitized_quota_error(sale) -> None:
    def opener(request, timeout):
        raise HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {},
            BytesIO(
                json.dumps(
                    {"error": {"message": "Free-tier requests per day exceeded"}}
                ).encode()
            ),
        )

    reviewer = OpenAICompatibleReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="m",
        opener=opener,
    )
    product = ProductEvidence(
        product_id=sale.product_id,
        product_name=sale.product_title,
        source="test",
    )
    with pytest.raises(ProviderHTTPError, match="requests per day exceeded"):
        reviewer.review(build_evidence_packet(sale, product))


def test_provider_handles_list_shaped_error_payload(sale) -> None:
    def opener(request, timeout):
        raise HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {},
            BytesIO(
                json.dumps(
                    [{"error": {"message": "Per-model request quota exceeded"}}]
                ).encode()
            ),
        )

    reviewer = OpenAICompatibleReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="m",
        opener=opener,
    )
    product = ProductEvidence(
        product_id=sale.product_id,
        product_name=sale.product_title,
        source="test",
    )
    with pytest.raises(ProviderHTTPError, match="request quota exceeded") as raised:
        reviewer.review(build_evidence_packet(sale, product))
    assert raised.value.retry_after_seconds is None


def test_provider_parses_retry_after(sale) -> None:
    def opener(request, timeout):
        raise HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {},
            BytesIO(
                json.dumps(
                    {"error": {"message": "Please retry in 12.75s."}}
                ).encode()
            ),
        )

    reviewer = OpenAICompatibleReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="m",
        opener=opener,
    )
    product = ProductEvidence(
        product_id=sale.product_id,
        product_name=sale.product_title,
        source="test",
    )
    with pytest.raises(ProviderHTTPError) as raised:
        reviewer.review(build_evidence_packet(sale, product))
    assert raised.value.retry_after_seconds == 12.75
