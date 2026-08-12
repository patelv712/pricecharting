"""Transparent deterministic baseline for the reviewer POC."""

from __future__ import annotations

from pcqc.evidence import deterministic_evidence_summary
from pcqc.models import (
    ConsistencyObservations,
    Decision,
    EvidencePacket,
    ReviewResult,
    Route,
    VisualObservations,
)


class RulesReviewer:
    """Relationship-first baseline; price is corroboration, never sole evidence."""

    provider = "deterministic"
    model = "relationship-rules-v1"
    include_image = False
    inference_mode = "rules"
    prompt_version = "relationship-rules-v1"

    def review(self, packet: EvidencePacket) -> ReviewResult:
        derived = packet.derived
        reason: str
        codes: list[str]
        predicted_condition_id: int | None = None

        needs_modification = False
        if derived.identity_conflicts:
            decision = Decision.IGNORED
            needs_modification = True
            codes = derived.identity_conflicts
            reason = "Explicit sale and catalog identity fields conflict."
        elif derived.identity_warnings:
            decision = Decision.IGNORED
            needs_modification = True
            codes = derived.identity_warnings
            reason = "The sale states product-identity details missing from catalog metadata."
        elif derived.deletion_flags:
            decision = Decision.DELETED
            codes = [f"title_{flag}" for flag in derived.deletion_flags]
            reason = "Sale title contains an exclusion signal."
        elif (
            derived.title_supported_condition_id is not None
            and derived.title_supported_condition_id != packet.sale.original_condition_id
        ):
            decision = Decision.CONDITION_CHANGE
            predicted_condition_id = derived.title_supported_condition_id
            codes = ["title_grade_conflicts_with_condition"]
            reason = "An explicit title grade maps to a different condition."
        else:
            decision = Decision.IGNORED
            codes = ["no_deterministic_conflict"]
            reason = "No deterministic deletion or condition-conflict signal was found."
            if derived.title_product_overlap >= 0.65:
                codes.append("strong_title_product_match")
            if (
                derived.nearest_condition_id == packet.sale.original_condition_id
                and derived.nearest_condition_ratio is not None
                and derived.nearest_condition_ratio <= 1.5
            ):
                codes.append("price_supports_condition")

        price_consistency = "unknown"
        if derived.nearest_condition_id is not None:
            price_consistency = (
                "consistent"
                if derived.nearest_condition_id == packet.sale.original_condition_id
                else "possible_conflict"
            )
        return ReviewResult(
            decision=decision,
            predicted_condition_id=predicted_condition_id,
            needs_modification=needs_modification,
            route=Route.HUMAN_REVIEW,
            reason=reason,
            rationale_codes=codes,
            consistency=ConsistencyObservations(price_vs_condition=price_consistency),
            visual=VisualObservations(image_usable=bool(packet.image and packet.image.usable)),
            deterministic_evidence=deterministic_evidence_summary(packet),
            provider=self.provider,
            model=self.model,
        )
