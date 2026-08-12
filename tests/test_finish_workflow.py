from __future__ import annotations

from PIL import Image

from pcqc.evidence import build_evidence_packet
from pcqc.finish_provider import TargetedFinishResponse
from pcqc.finish_workflow import FinishAwareReviewer
from pcqc.models import (
    CatalogEvidence,
    FinishProviderMetadata,
    FinishType,
    FinishVisualOutput,
    ImageEvidence,
    ProductEvidence,
)


class CapturingMainReviewer:
    model = "main"
    prompt_version = "main-v1"

    def __init__(self) -> None:
        self.packet = None

    def review(self, packet):
        self.packet = packet
        return packet


class RaisingFinishReviewer:
    model = "finish"
    prompt_version = "finish-v1"

    def review(self, packet, features):
        raise RuntimeError("temporary provider outage")


class StaticFinishReviewer:
    model = "finish"
    prompt_version = "finish-v1"

    def review(self, packet, features):
        return TargetedFinishResponse(
            visual=FinishVisualOutput(
                visually_determinable=True,
                observed_finish=FinishType.HOLO,
                evidence_regions=["illustration"],
                reason="Reflection is confined to the illustration window.",
            ),
            metadata=FinishProviderMetadata(
                provider="test",
                model=self.model,
                prompt_version=self.prompt_version,
                latency_ms=5,
            ),
        )


def _packet(sale, image_path):
    return build_evidence_packet(
        sale,
        ProductEvidence(
            product_id="920639", product_name="Typhlosion [Holo] #16", source="test"
        ),
        ImageEvidence(
            available=True,
            usable=True,
            content_type="image/jpeg",
            cache_path=image_path,
        ),
        CatalogEvidence(
            product_id_verified=True,
            description="Holo",
            image=ImageEvidence(available=True, usable=True, content_type="image/jpeg"),
        ),
    )


def test_finish_workflow_triggers_for_finish_in_assigned_catalog(sale, tmp_path) -> None:
    image_path = tmp_path / "listing.jpg"
    Image.new("RGB", (700, 1000), color=(100, 120, 140)).save(image_path)
    main = CapturingMainReviewer()
    result = FinishAwareReviewer(
        main_reviewer=main,
        finish_reviewer=StaticFinishReviewer(),
        cache_dir=tmp_path,
    ).review(_packet(sale, image_path))
    assert result.finish_resolution.finish_match.value == "match"
    assert result.finish_resolution.observed_finish == FinishType.HOLO
    assert result.finish_resolution.provider_metadata.latency_ms == 5


def test_finish_workflow_fails_closed_when_specialist_errors(sale, tmp_path) -> None:
    image_path = tmp_path / "listing.jpg"
    Image.new("RGB", (700, 1000), color=(100, 120, 140)).save(image_path)
    main = CapturingMainReviewer()
    result = FinishAwareReviewer(
        main_reviewer=main,
        finish_reviewer=RaisingFinishReviewer(),
        cache_dir=tmp_path,
    ).review(_packet(sale, image_path))
    resolution = result.finish_resolution
    assert resolution.finish_match.value == "unknown"
    assert resolution.observed_finish == FinishType.UNKNOWN
    assert "finish_reviewer_error:RuntimeError" in resolution.rationale_codes


def test_specialist_error_cannot_preserve_title_only_finish_match(
    sale, tmp_path
) -> None:
    image_path = tmp_path / "listing.jpg"
    Image.new("RGB", (700, 1000), color=(100, 120, 140)).save(image_path)
    main = CapturingMainReviewer()
    packet = _packet(
        sale.model_copy(update={"sale_title": "Typhlosion #16 Holo PSA 10"}),
        image_path,
    )
    result = FinishAwareReviewer(
        main_reviewer=main,
        finish_reviewer=RaisingFinishReviewer(),
        cache_dir=tmp_path,
    ).review(packet)
    resolution = result.finish_resolution
    assert resolution.observed_finish == FinishType.HOLO
    assert resolution.finish_match.value == "unknown"
    assert "finish_match_requires_visual_verification" in resolution.rationale_codes
