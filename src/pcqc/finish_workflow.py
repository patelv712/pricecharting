"""Composite reviewer that applies targeted finish resolution before general review."""

from __future__ import annotations

from pathlib import Path

from pcqc.finish import (
    FINISH_RESOLUTION_POLICY_VERSION,
    extract_image_features,
    resolve_finish,
)
from pcqc.models import (
    EvidencePacket,
    FinishEvidenceFact,
    FinishMatch,
    FinishType,
    ReviewResult,
)


class FinishAwareReviewer:
    def __init__(self, *, main_reviewer, finish_reviewer, cache_dir: Path) -> None:
        self.main_reviewer = main_reviewer
        self.finish_reviewer = finish_reviewer
        self.cache_dir = cache_dir
        self.model = f"{main_reviewer.model}+finish:{finish_reviewer.model}"
        self.prompt_version = (
            f"{main_reviewer.prompt_version}+{finish_reviewer.prompt_version}"
            f"+{FINISH_RESOLUTION_POLICY_VERSION}"
        )
        self.include_image = True
        self.inference_mode = "multimodal_finish_aware"

    def review(self, packet: EvidencePacket) -> ReviewResult:
        image = packet.image
        metadata_resolution = resolve_finish(packet)
        needs_visual_finish = bool(
            metadata_resolution.applicable
            and metadata_resolution.verification_required
        )
        features = None
        visual = None
        provider_metadata = None
        finish_error: str | None = None
        if image and image.usable and image.cache_path and needs_visual_finish:
            features = extract_image_features(image.cache_path, self.cache_dir)
            if not features.error:
                try:
                    finish_response = self.finish_reviewer.review(packet, features)
                    visual = finish_response.visual
                    provider_metadata = finish_response.metadata
                except Exception as exc:
                    # A specialist outage must fail closed, not abort the entire sale review.
                    finish_error = f"finish_reviewer_error:{type(exc).__name__}"
        resolution = resolve_finish(
            packet, visual=visual, image_features=features
        )
        if provider_metadata:
            resolution = resolution.model_copy(
                update={"provider_metadata": provider_metadata}
            )
        if finish_error:
            resolution_update = {
                "evidence": resolution.evidence
                + [
                    FinishEvidenceFact(
                        source="targeted_finish_reviewer",
                        fact="Targeted finish review failed; no visual finish claim was used.",
                    )
                ],
                "rationale_codes": list(
                    dict.fromkeys(resolution.rationale_codes + [finish_error])
                ),
            }
            if resolution.finish_match == FinishMatch.MATCH:
                resolution_update["finish_match"] = FinishMatch.UNKNOWN
                resolution_update["rationale_codes"] = [
                    code
                    for code in resolution_update["rationale_codes"]
                    if code != "finish_match"
                ] + ["finish_match_requires_visual_verification"]
            resolution = resolution.model_copy(
                update=resolution_update
            )
        visual_confirms_match = bool(
            visual
            and visual.visually_determinable
            and resolution.observed_finish == resolution.assigned_finish
        )
        if (
            needs_visual_finish
            and resolution.finish_match == FinishMatch.MATCH
            and not visual_confirms_match
        ):
            resolution = resolution.model_copy(
                update={
                    "finish_match": FinishMatch.UNKNOWN,
                    "rationale_codes": [
                        code
                        for code in resolution.rationale_codes
                        if code != "finish_match"
                    ]
                    + ["finish_match_requires_visual_verification"],
                }
            )
        enriched_packet = packet.model_copy(
            update={"finish_resolution": resolution}
        )
        return self.main_reviewer.review(enriched_packet)
