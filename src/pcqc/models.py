"""Shared schemas for normalized data, evidence, and reviewer outputs."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TargetLabel(StrEnum):
    IGNORED = "ignored"
    DELETED = "deleted"
    CONDITION_CHANGE = "condition_change"
    NEEDS_MODIFICATION = "needs_modification"


class Decision(StrEnum):
    IGNORED = "ignored"
    DELETED = "deleted"
    CONDITION_CHANGE = "condition_change"


class Route(StrEnum):
    ACCEPT = "accept"
    HUMAN_REVIEW = "human_review"


class FinishType(StrEnum):
    REGULAR = "regular"
    HOLO = "holo"
    REVERSE_HOLO = "reverse_holo"
    COSMOS_HOLO = "cosmos_holo"
    FOIL = "foil"
    SPECIAL_FOIL = "special_foil"
    UNKNOWN = "unknown"


class FinishMatch(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class NormalizedSale(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str
    target: TargetLabel | None = None
    target_condition_id: int | None = None
    review_action_condition_id: int | None = None
    status_raw: str | None = None
    review_date: str | None = None
    most_recent_report: str | None = None
    product_id: str
    product_title: str
    sale_title: str
    sale_amount_pennies: int = Field(ge=0)
    score: int
    broad_category: str
    original_condition_id: int
    picture_url: str | None = None


class ProductEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: str
    product_name: str
    console_name: str | None = None
    genre: str | None = None
    release_date: str | None = None
    sales_volume: int | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    price_anchors: dict[int, int] = Field(default_factory=dict)
    source: str


class ImageEvidence(BaseModel):
    available: bool
    usable: bool
    content_type: str | None = None
    byte_length: int | None = None
    sha256: str | None = None
    cache_path: Path | None = None
    error: str | None = None


class DerivedEvidence(BaseModel):
    title_product_overlap: float = Field(ge=0, le=1)
    missing_product_tokens: list[str] = Field(default_factory=list)
    deletion_flags: list[str] = Field(default_factory=list)
    identity_conflicts: list[str] = Field(default_factory=list)
    identity_warnings: list[str] = Field(default_factory=list)
    sale_identity_markers: dict[str, list[str]] = Field(default_factory=dict)
    catalog_identity_markers: dict[str, list[str]] = Field(default_factory=dict)
    extracted_grading_company: str | None = None
    extracted_grade: float | None = None
    title_supported_condition_id: int | None = None
    original_condition_price: int | None = None
    nearest_condition_id: int | None = None
    nearest_condition_ratio: float | None = None
    second_nearest_condition_ratio: float | None = None
    evidence_count: int = 0


class CatalogEvidence(BaseModel):
    schema_version: int = 2
    page_url: str | None = None
    image_url: str | None = None
    product_id_verified: bool = False
    description: str | None = None
    notes: str | None = None
    card_number: str | None = None
    image: ImageEvidence | None = None
    error: str | None = None


class FinishEvidenceFact(BaseModel):
    source: str
    fact: str
    finish: FinishType = FinishType.UNKNOWN


class FinishImageFeatures(BaseModel):
    image_sha256: str | None = None
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    aspect_ratio: float = Field(ge=0)
    card_like_aspect: bool = False
    saturation_mean: float = Field(ge=0, le=1)
    saturation_stdev: float = Field(ge=0, le=1)
    luminance_stdev: float = Field(ge=0, le=1)
    highlight_fraction: float = Field(ge=0, le=1)
    crop_paths: dict[str, Path] = Field(default_factory=dict)
    error: str | None = None


class FinishVisualOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visually_determinable: bool
    observed_finish: FinishType
    matching_candidate_id: str | None = None
    evidence_regions: list[str] = Field(default_factory=list)
    reason: str


class FinishProviderMetadata(BaseModel):
    provider: str
    model: str
    prompt_version: str
    latency_ms: int = Field(ge=0)
    attempt_count: int = Field(default=1, ge=1)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    billable_output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    pricing_version: str | None = None
    cost_estimate_scope: str | None = None


class FinishResolution(BaseModel):
    policy_version: str = "unknown"
    applicable: bool = True
    verification_required: bool = True
    assigned_finish: FinishType = FinishType.UNKNOWN
    observed_finish: FinishType = FinishType.UNKNOWN
    finish_match: FinishMatch = FinishMatch.UNKNOWN
    replacement_product_id: str | None = None
    requires_human_review: bool = True
    evidence: list[FinishEvidenceFact] = Field(default_factory=list)
    rationale_codes: list[str] = Field(default_factory=list)
    visual: FinishVisualOutput | None = None
    image_features: FinishImageFeatures | None = None
    provider_metadata: FinishProviderMetadata | None = None


class ProductCandidate(BaseModel):
    product_id: str
    product_name: str
    console_name: str | None = None
    retrieval_score: int = Field(ge=0, le=100)
    score_components: list[str] = Field(default_factory=list)
    catalog: CatalogEvidence | None = None


class EvidencePacket(BaseModel):
    sale: NormalizedSale
    product: ProductEvidence
    derived: DerivedEvidence
    image: ImageEvidence | None = None
    catalog: CatalogEvidence | None = None
    replacement_candidates: list[ProductCandidate] = Field(default_factory=list)
    enrichment_warnings: list[str] = Field(default_factory=list)
    finish_resolution: FinishResolution | None = None


class VisualObservations(BaseModel):
    cards_visible_count: int | None = Field(default=None, ge=0)
    is_lot_or_bundle: bool | None = None
    is_graded_slab: bool | None = None
    grading_company: str | None = None
    visible_grade: str | None = None
    language_markers: list[str] = Field(default_factory=list)
    finish: str | None = None
    damage_signs: bool | None = None
    is_custom_or_proxy: bool | None = None
    image_usable: bool = False


class ConsistencyObservations(BaseModel):
    title_vs_image: str = "unknown"
    image_vs_metadata: str = "unknown"
    price_vs_condition: str = "unknown"


class IdentityComparison(BaseModel):
    artwork: str = "uncertain"
    event_or_release: str = "uncertain"
    set_and_card_number: str = "uncertain"
    language: str = "uncertain"
    finish: str = "uncertain"
    printing_or_parallel: str = "uncertain"
    quantity_and_packaging: str = "uncertain"
    object_type: str = "uncertain"


class ModelReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision | None
    predicted_condition_id: int | None = None
    replacement_product_id: str | None = None
    replacement_comparison: str = "not_available"
    needs_modification: bool = False
    reason: str
    rationale_codes: list[str] = Field(default_factory=list)
    catalog_comparison: str = "not_available"
    identity_comparison: IdentityComparison = Field(default_factory=IdentityComparison)
    visual: VisualObservations = Field(default_factory=VisualObservations)
    consistency: ConsistencyObservations = Field(default_factory=ConsistencyObservations)

    @model_validator(mode="after")
    def validate_decision_contract(self) -> "ModelReviewOutput":
        if not self.needs_modification and self.decision is None:
            raise ValueError("decision is required unless needs_modification is true")
        if self.decision == Decision.CONDITION_CHANGE:
            if self.predicted_condition_id is None:
                raise ValueError("condition_change requires predicted_condition_id")
        elif self.predicted_condition_id is not None:
            raise ValueError("predicted_condition_id is only valid for condition_change")
        return self


class DeterministicEvidenceSummary(BaseModel):
    image_available: bool = False
    image_usable: bool = False
    title_product_overlap: float = Field(default=0, ge=0, le=1)
    deletion_flags: list[str] = Field(default_factory=list)
    identity_conflicts: list[str] = Field(default_factory=list)
    identity_warnings: list[str] = Field(default_factory=list)
    sale_identity_markers: dict[str, list[str]] = Field(default_factory=dict)
    catalog_identity_markers: dict[str, list[str]] = Field(default_factory=dict)
    title_supported_condition_id: int | None = None
    catalog_price_anchor_count: int = Field(default=0, ge=0)
    catalog_image_available: bool = False
    catalog_product_id_verified: bool = False
    enrichment_warnings: list[str] = Field(default_factory=list)


class ReviewResult(ModelReviewOutput):
    model_config = ConfigDict(extra="forbid")

    route: Route
    deterministic_evidence: DeterministicEvidenceSummary = Field(
        default_factory=DeterministicEvidenceSummary
    )
    provider: str
    model: str
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    finish_resolution: FinishResolution | None = None

    @model_validator(mode="after")
    def validate_human_review_policy(self) -> "ReviewResult":
        if self.route != Route.HUMAN_REVIEW:
            raise ValueError("active POC policy requires human_review")
        return self

    def predicted_label(self) -> TargetLabel:
        if self.needs_modification:
            return TargetLabel.NEEDS_MODIFICATION
        assert self.decision is not None
        return TargetLabel(self.decision.value)


class EvaluationSummary(BaseModel):
    labels: list[str]
    sample_count: int
    accuracy: float
    macro_f1: float
    per_class: dict[str, dict[str, float | int]]
    confusion_matrix: dict[str, dict[str, int]]
    coverage: float | None = None
    covered_accuracy: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
