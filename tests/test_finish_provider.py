from __future__ import annotations

import json

from pcqc.evidence import build_evidence_packet
from pcqc.finish_provider import TargetedFinishReviewer
from pcqc.models import (
    CatalogEvidence,
    FinishImageFeatures,
    FinishType,
    ImageEvidence,
    ProductCandidate,
    ProductEvidence,
)

from conftest import FakeResponse


def test_targeted_finish_reviewer_sends_only_finish_evidence(sale, tmp_path) -> None:
    listing = tmp_path / "listing.jpg"
    body = tmp_path / "body.jpg"
    illustration = tmp_path / "illustration.jpg"
    border = tmp_path / "border.jpg"
    assigned = tmp_path / "assigned.jpg"
    reverse = tmp_path / "reverse.jpg"
    for path in (listing, body, illustration, border, assigned, reverse):
        path.write_bytes(b"image")
    requests = []
    response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "visually_determinable": True,
                            "observed_finish": "reverse_holo",
                            "matching_candidate_id": "12385647",
                            "evidence_regions": ["card_body", "border"],
                            "reason": "Foil pattern appears outside the illustration.",
                        }
                    )
                }
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 150,
        },
    }

    def opener(request, timeout):
        requests.append(json.loads(request.data))
        return FakeResponse(response)

    product = ProductEvidence(
        product_id="12584352", product_name="Tyrantrum #45", source="test"
    )
    packet = build_evidence_packet(
        sale.model_copy(update={"product_id": "12584352"}),
        product,
        catalog=CatalogEvidence(
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
                product_id="12385647",
                product_name="Tyrantrum [Reverse Holo] #45",
                retrieval_score=80,
                catalog=CatalogEvidence(
                    product_id_verified=True,
                    image=ImageEvidence(
                        available=True,
                        usable=True,
                        content_type="image/jpeg",
                        cache_path=reverse,
                    ),
                ),
            )
        ],
    )
    features = FinishImageFeatures(
        width=700,
        height=1000,
        aspect_ratio=0.7,
        card_like_aspect=True,
        saturation_mean=0.4,
        saturation_stdev=0.2,
        luminance_stdev=0.2,
        highlight_fraction=0.03,
        crop_paths={
            "full": listing,
            "card_body": body,
            "illustration": illustration,
            "outer_border": border,
        },
    )
    response = TargetedFinishReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="finish-model",
        opener=opener,
    ).review(packet, features)
    result = response.visual
    assert result.observed_finish == FinishType.REVERSE_HOLO
    assert result.matching_candidate_id == "12385647"
    content = requests[0]["messages"][1]["content"]
    labels = [item["text"] for item in content if item["type"] == "text"]
    assert any("CARD BODY DETAIL" in label for label in labels)
    assert any("ILLUSTRATION DETAIL" in label for label in labels)
    assert any("OUTER BORDER STRIPS" in label for label in labels)
    assert any("ELIGIBLE reverse_holo CANDIDATE 12385647" in label for label in labels)
    assert "sale_amount" not in json.dumps(requests[0])
    assert '"confidence":' not in json.dumps(requests[0]).lower()
    assert response.metadata.model == "finish-model"
    assert response.metadata.latency_ms >= 0
    assert response.metadata.billable_output_tokens == 50
    assert response.metadata.estimated_cost_usd is None


def test_targeted_finish_reviewer_cannot_prove_regular_from_absence(
    sale, tmp_path
) -> None:
    listing = tmp_path / "listing.jpg"
    sibling = tmp_path / "sibling.jpg"
    for path in (listing, sibling):
        path.write_bytes(b"image")
    provider_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "visually_determinable": True,
                            "observed_finish": "regular",
                            "matching_candidate_id": None,
                            "evidence_regions": ["card_body"],
                            "reason": "No reflection was visible.",
                        }
                    )
                }
            }
        ]
    }

    def opener(request, timeout):
        return FakeResponse(provider_payload)

    packet = build_evidence_packet(
        sale,
        ProductEvidence(
            product_id="1", product_name="Pikachu #42", source="test"
        ),
        replacement_candidates=[
            ProductCandidate(
                product_id="2",
                product_name="Pikachu [Reverse Holo] #42",
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
    )
    features = FinishImageFeatures(
        width=700,
        height=1000,
        aspect_ratio=0.7,
        card_like_aspect=True,
        saturation_mean=0.4,
        saturation_stdev=0.2,
        luminance_stdev=0.2,
        highlight_fraction=0.03,
        crop_paths={"full": listing},
    )
    result = TargetedFinishReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="finish-model",
        opener=opener,
    ).review(packet, features).visual
    assert not result.visually_determinable
    assert result.observed_finish == FinishType.UNKNOWN
    assert "cannot prove regular" in result.reason


def test_targeted_finish_reviewer_retries_timeout_once(sale, tmp_path) -> None:
    listing = tmp_path / "listing.jpg"
    listing.write_bytes(b"image")
    calls = 0
    sleeps = []
    provider_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "visually_determinable": False,
                            "observed_finish": "unknown",
                            "matching_candidate_id": None,
                            "evidence_regions": [],
                            "reason": "Lighting is inconclusive.",
                        }
                    )
                }
            }
        ]
    }

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary timeout")
        return FakeResponse(provider_payload)

    packet = build_evidence_packet(
        sale,
        ProductEvidence(product_id="1", product_name="Card #1", source="test"),
    )
    features = FinishImageFeatures(
        width=700,
        height=1000,
        aspect_ratio=0.7,
        card_like_aspect=True,
        saturation_mean=0.4,
        saturation_stdev=0.2,
        luminance_stdev=0.2,
        highlight_fraction=0.03,
        crop_paths={"full": listing},
    )
    response = TargetedFinishReviewer(
        api_key="secret",
        base_url="https://example.test",
        model="finish-model",
        opener=opener,
        retry_delay_seconds=60,
        sleeper=sleeps.append,
    ).review(packet, features)
    assert calls == 2
    assert sleeps == [60]
    assert response.metadata.attempt_count == 2
    assert response.visual.observed_finish == FinishType.UNKNOWN
