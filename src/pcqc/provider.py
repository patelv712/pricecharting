"""OpenAI-compatible multimodal provider with strict JSON validation."""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request

from pydantic import ValidationError

from pcqc.conditions import CONDITIONS
from pcqc.http import trusted_urlopen
from pcqc.evidence import deterministic_evidence_summary
from pcqc.models import Decision, EvidencePacket, ModelReviewOutput, ReviewResult, Route


PROMPT_VERSION = "2026-08-10-candidate-ambiguity-v7"
GENERIC_SEALED_PRODUCT_PATTERN = re.compile(r"^(?:booster|blister) pack$", re.I)


SYSTEM_PROMPT = """You review a single eBay trading-card sale for PriceCharting.
Decide whether to: ignored (product and condition are correct), deleted (the listing should
not be tracked as a valid comparable sale), or condition_change (same product, wrong condition).
If the listing is a valid single-item sale but appears assigned to the wrong product, set
needs_modification=true so a human can reassign the product; do not delete it merely because the
variant, set, language, or product identity differs from the assignment.
When replacement_candidates are supplied, replacement_product_id may contain only one of those
candidate IDs. Select one only when the listing evidence positively identifies it; otherwise
return null. Candidate retrieval_score is a transparent text-ranking feature, not confidence or
proof, and must not override contradictory image or metadata evidence.
Replacement-candidate images follow the assigned catalog image. If selecting a replacement ID,
compare IMAGE 1 directly with that candidate image and set replacement_comparison to match. Use
mismatch, uncertain, or not_available otherwise.
Also use needs_modification when evidence is insufficient or internally contradictory.
Card finish is product identity, not condition. Explicitly inspect non-foil, holo, reverse holo,
foil, and special-foil possibilities. Never treat uncertain finish as a match; use
needs_modification=true when the assigned finish is missing, ambiguous, or conflicts with the
listing. Do not infer finish from price.
Inspect relationships among listing title, catalog metadata, image, assigned condition, and
price anchors. Price alone is never proof. Never infer invisible card details. Condition IDs
are domain-specific: use only the supplied condition_catalog and never invent an ID mapping.
When two images are supplied, IMAGE 1 is the eBay listing and IMAGE 2 is the assigned
PriceCharting catalog product. Compare artwork, event/set year, card number, language, finish,
and printing. Set catalog_comparison to match only when product-defining visual details align;
otherwise use mismatch or uncertain. Never claim an artwork match when IMAGE 2 is absent.
When the assigned catalog product is generically named Booster Pack or Blister Pack and does not
encode a named pack-art variant, differing wrapper artwork alone is not a product mismatch; mark
artwork uncertain and compare the set, packaging, quantity, and object type instead.
For every identity_comparison field, return exactly match, mismatch, or uncertain. A match requires
positive evidence from both the listing and assigned catalog product; absence of a label is not
proof of a base/non-foil printing. Reflections alone are not proof of foil. If finish cannot be
distinguished from the supplied images and metadata, return uncertain.
Do not output a confidence score or routing decision. The application routes every recommendation
to a human and records deterministic evidence separately. Return only one JSON object matching the
supplied schema, with a short evidence-grounded reason.
"""


def public_packet(
    packet: EvidencePacket, *, include_image: bool = True
) -> dict[str, object]:
    """Return only inference-time evidence; historical review fields are removed."""
    payload = packet.model_dump(mode="json", exclude_none=True)
    payload["condition_catalog"] = {
        str(condition_id): definition.name
        for condition_id, definition in sorted(CONDITIONS.items())
    }
    sale = payload["sale"]
    for label_field in (
        "target",
        "target_condition_id",
        "review_action_condition_id",
        "status_raw",
        "review_date",
        "most_recent_report",
        "score",
    ):
        sale.pop(label_field, None)
    if include_image:
        image = payload.get("image")
        if image:
            image.pop("cache_path", None)
        catalog = payload.get("catalog")
        if catalog and catalog.get("image"):
            catalog["image"].pop("cache_path", None)
    else:
        payload.pop("image", None)
        payload.pop("catalog", None)
        for candidate in payload.get("replacement_candidates", []):
            candidate.pop("catalog", None)
    product = payload.get("product")
    if product:
        product.pop("source", None)
    for candidate in payload.get("replacement_candidates", []):
        candidate_catalog = candidate.get("catalog")
        if candidate_catalog and candidate_catalog.get("image"):
            candidate_catalog["image"].pop("cache_path", None)
    finish_resolution = payload.get("finish_resolution")
    if finish_resolution and finish_resolution.get("image_features"):
        finish_resolution["image_features"].pop("crop_paths", None)
    return payload


def _extract_json(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Provider response did not contain a JSON object")
    value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Provider response JSON must be an object")
    return value


@dataclass(frozen=True)
class ProviderResponse:
    result: ReviewResult
    raw_text: str


class ProviderHTTPError(RuntimeError):
    """Sanitized provider error that preserves quota/status details."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"provider_http_{status_code}:{message[:500]}")
        self.status_code = status_code
        retry_match = re.search(r"retry in\s+([\d.]+)s", message, re.I)
        self.retry_after_seconds = (
            float(retry_match.group(1)) if retry_match else None
        )


def _generic_sealed_artwork_not_encoded(packet: EvidencePacket) -> bool:
    return bool(
        GENERIC_SEALED_PRODUCT_PATTERN.fullmatch(packet.product.product_name.strip())
        and packet.catalog
        and packet.catalog.product_id_verified
    )


class OpenAICompatibleReviewer:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        opener: Callable[..., object] = trusted_urlopen,
        timeout_seconds: float = 90,
        include_image: bool = True,
    ) -> None:
        if not api_key or not model:
            raise ValueError("LLM API key and model are required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.opener = opener
        self.timeout_seconds = timeout_seconds
        self.include_image = include_image
        self.inference_mode = "multimodal" if include_image else "text_only"
        self.prompt_version = f"{PROMPT_VERSION}:{self.inference_mode}"

    def review(self, packet: EvidencePacket) -> ReviewResult:
        started = time.monotonic()
        response = self._request(packet, repair_message=None)
        try:
            result = self._validate(response, packet)
        except (ValidationError, ValueError, json.JSONDecodeError) as first_error:
            repair = f"Your prior response was invalid: {first_error}. Return corrected JSON only."
            response = self._request(packet, repair_message=repair)
            result = self._validate(response, packet)
        result.latency_ms = round((time.monotonic() - started) * 1000)
        return result

    def _request(self, packet: EvidencePacket, repair_message: str | None) -> dict[str, object]:
        content: list[dict[str, object]] = [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "evidence": public_packet(
                            packet, include_image=self.include_image
                        ),
                        "output_schema": ModelReviewOutput.model_json_schema(),
                    },
                    separators=(",", ":"),
                ),
            }
        ]
        if (
            self.include_image
            and packet.image
            and packet.image.usable
            and packet.image.cache_path
        ):
            content.append({"type": "text", "text": "IMAGE 1: EBAY LISTING IMAGE"})
            media_type = packet.image.content_type or "image/jpeg"
            encoded = base64.b64encode(packet.image.cache_path.read_bytes()).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                }
            )
        catalog_image = packet.catalog.image if packet.catalog else None
        if (
            self.include_image
            and packet.catalog
            and packet.catalog.product_id_verified
            and catalog_image
            and catalog_image.usable
            and catalog_image.cache_path
        ):
            content.append(
                {
                    "type": "text",
                    "text": (
                        "IMAGE 2: ASSIGNED PRICECHARTING CATALOG IMAGE "
                        f"(product ID {packet.product.product_id})"
                    ),
                }
            )
            media_type = catalog_image.content_type or "image/jpeg"
            encoded = base64.b64encode(
                catalog_image.cache_path.read_bytes()
            ).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                }
            )
        if self.include_image:
            image_number = 3
            for candidate in packet.replacement_candidates:
                candidate_image = (
                    candidate.catalog.image if candidate.catalog else None
                )
                if not (
                    candidate.catalog
                    and candidate.catalog.product_id_verified
                    and candidate_image
                    and candidate_image.usable
                    and candidate_image.cache_path
                ):
                    continue
                content.append(
                    {
                        "type": "text",
                        "text": (
                            f"IMAGE {image_number}: REPLACEMENT CANDIDATE "
                            f"{candidate.product_id} - {candidate.product_name}"
                        ),
                    }
                )
                media_type = candidate_image.content_type or "image/jpeg"
                encoded = base64.b64encode(
                    candidate_image.cache_path.read_bytes()
                ).decode("ascii")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                    }
                )
                image_number += 1
        system_prompt = SYSTEM_PROMPT
        if not self.include_image:
            system_prompt += (
                "\nThis is a controlled text-only evaluation. No listing image or image metadata "
                "is supplied. Do not claim visual observations; set visual.image_usable=false."
            )
        messages: list[dict[str, object]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]
        if repair_message:
            messages.append({"role": "user", "content": repair_message})
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "pcqc/0.1",
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = body
            try:
                error_payload = json.loads(body)
                if isinstance(error_payload, list) and error_payload:
                    error_payload = error_payload[0]
                error = (
                    error_payload.get("error", {})
                    if isinstance(error_payload, dict)
                    else {}
                )
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("status") or body)
            except json.JSONDecodeError:
                pass
            raise ProviderHTTPError(exc.code, message or exc.reason) from exc
        if not isinstance(parsed, dict):
            raise ValueError("Provider response envelope must be an object")
        return parsed

    def _validate(
        self, envelope: dict[str, object], packet: EvidencePacket
    ) -> ReviewResult:
        choices = envelope.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("Provider response has no choices")
        message = choices[0].get("message", {})
        raw_text = message.get("content")
        if not isinstance(raw_text, str):
            raise ValueError("Provider response has no text content")
        payload = _extract_json(raw_text)
        discarded_condition_id = False
        if (
            payload.get("decision") != Decision.CONDITION_CHANGE
            and payload.get("predicted_condition_id") is not None
        ):
            # Gemini sometimes fills this nullable field despite choosing a non-condition action.
            # It carries no meaning for that action, so normalize it instead of paying for repair.
            payload["predicted_condition_id"] = None
            discarded_condition_id = True
        model_output = ModelReviewOutput.model_validate(payload)
        result_payload = model_output.model_dump(mode="json")
        rationale_codes = list(result_payload["rationale_codes"])
        if discarded_condition_id:
            rationale_codes.append("discarded_irrelevant_predicted_condition_id")
        replacement_id = result_payload.get("replacement_product_id")
        candidates_by_id = {
            candidate.product_id: candidate
            for candidate in packet.replacement_candidates
        }
        if replacement_id is not None:
            candidate = candidates_by_id.get(replacement_id)
            candidate_verified = bool(
                candidate
                and candidate.catalog
                and candidate.catalog.product_id_verified
                and candidate.catalog.image
                and candidate.catalog.image.usable
            )
            if (
                replacement_id == packet.product.product_id
                or not candidate_verified
                or result_payload["replacement_comparison"] != "match"
            ):
                result_payload["replacement_product_id"] = None
                rationale_codes.append("unverified_replacement_product_id_discarded")
            else:
                result_payload["needs_modification"] = True
                rationale_codes.append("verified_replacement_candidate_selected")
        conflicts = packet.derived.identity_conflicts
        if conflicts:
            result_payload["needs_modification"] = True
            rationale_codes.extend(conflicts)
            result_payload["reason"] = (
                "Deterministic product identity conflict: "
                + "; ".join(conflicts)
                + ". "
                + result_payload["reason"]
            )
        warnings = packet.derived.identity_warnings
        finish_resolution = packet.finish_resolution
        finish_verified = bool(
            finish_resolution
            and finish_resolution.applicable
            and finish_resolution.finish_match.value != "unknown"
        )
        catalog_ready = bool(
            packet.catalog
            and packet.catalog.product_id_verified
            and packet.catalog.image
            and packet.catalog.image.usable
        )
        comparisons = result_payload["identity_comparison"]
        resolved_variant_dimensions: set[str] = set()
        if finish_verified or (finish_resolution and not finish_resolution.applicable):
            resolved_variant_dimensions.add("finish")
        if catalog_ready and result_payload["catalog_comparison"] == "match":
            comparison_dimensions = {
                "printing": "printing_or_parallel",
                "language": "language",
                "packaging": "quantity_and_packaging",
                "card_code": "set_and_card_number",
            }
            resolved_variant_dimensions.update(
                dimension
                for dimension, comparison in comparison_dimensions.items()
                if comparisons[comparison] == "match"
            )
        warnings = [
            warning
            for warning in warnings
            if not (
                (match := re.match(
                    r"catalog_variant_family_ambiguous:dimensions=([^:]+):",
                    warning,
                ))
                and set(match.group(1).split(",")) <= resolved_variant_dimensions
            )
            and not (
                (match := re.match(r"([a-z_]+)_catalog_unspecified:", warning))
                and match.group(1) in resolved_variant_dimensions
            )
        ]
        if finish_verified or (finish_resolution and not finish_resolution.applicable):
            warnings = [
                warning
                for warning in warnings
                if not warning.startswith("finish_catalog_unspecified:")
                and not warning.startswith(
                    "catalog_variant_family_ambiguous:dimensions=finish:"
                )
            ]
        if warnings:
            result_payload["needs_modification"] = True
            rationale_codes.extend(warnings)
            result_payload["reason"] = (
                "Deterministic identity evidence requires verification: "
                + "; ".join(warnings)
                + ". "
                + result_payload["reason"]
            )
        if (
            self.include_image
            and result_payload["decision"] in {"ignored", "condition_change"}
            and not result_payload["needs_modification"]
            and (
                not catalog_ready
                or result_payload["catalog_comparison"] != "match"
            )
        ):
            result_payload["needs_modification"] = True
            code = (
                "catalog_image_unavailable"
                if not catalog_ready
                else "catalog_artwork_not_verified"
            )
            rationale_codes.append(code)
            result_payload["reason"] = (
                f"{code}: an assigned-product match was not established. "
                + result_payload["reason"]
            )
        if finish_resolution:
            if not finish_resolution.applicable:
                comparisons["finish"] = "uncertain"
                rationale_codes = [
                    code for code in rationale_codes if code != "finish_mismatch"
                ]
            elif finish_resolution.finish_match.value == "match":
                comparisons["finish"] = "match"
            elif finish_resolution.finish_match.value == "mismatch":
                comparisons["finish"] = "mismatch"
                result_payload["needs_modification"] = True
                rationale_codes.append("targeted_finish_mismatch")
                if finish_resolution.replacement_product_id:
                    result_payload["replacement_product_id"] = (
                        finish_resolution.replacement_product_id
                    )
                    rationale_codes.append("targeted_finish_replacement")
                result_payload["reason"] = (
                    "Targeted finish resolver found a product-identity mismatch. "
                    + result_payload["reason"]
                )
            else:
                comparisons["finish"] = "uncertain"
        generic_sealed_artwork_only = bool(
            comparisons["artwork"] == "mismatch"
            and _generic_sealed_artwork_not_encoded(packet)
        )
        if generic_sealed_artwork_only:
            comparisons["artwork"] = "uncertain"
            rationale_codes = [
                code for code in rationale_codes if code != "artwork_mismatch"
            ]
            rationale_codes.append("generic_sealed_artwork_not_catalog_identity")
        invalid_dimensions = [
            dimension
            for dimension, value in comparisons.items()
            if value not in {"match", "mismatch", "uncertain"}
        ]
        if invalid_dimensions:
            raise ValueError(
                "identity_comparison values must be match, mismatch, or uncertain: "
                + ", ".join(invalid_dimensions)
            )
        mismatches = [
            dimension for dimension, value in comparisons.items() if value == "mismatch"
        ]
        if mismatches:
            result_payload["needs_modification"] = True
            rationale_codes.extend(f"{dimension}_mismatch" for dimension in mismatches)
            result_payload["reason"] = (
                "Assigned-product identity mismatch: "
                + ", ".join(mismatches)
                + ". "
                + result_payload["reason"]
            )
        elif (
            generic_sealed_artwork_only
            and result_payload["decision"] in {"ignored", "condition_change"}
            and result_payload["catalog_comparison"] == "match"
            and not conflicts
            and not warnings
            and result_payload.get("replacement_product_id") is None
            and finish_resolution
            and not finish_resolution.applicable
        ):
            # A generic PriceCharting pack record aggregates wrapper art. Do not preserve a
            # model-supplied modification flag when wrapper art was its only identity conflict.
            result_payload["needs_modification"] = False
        if (
            self.include_image
            and result_payload["decision"] in {"ignored", "condition_change"}
            and (not finish_resolution or finish_resolution.applicable)
            and (not finish_resolution or finish_resolution.verification_required)
            and not finish_verified
            and comparisons["finish"] != "match"
        ):
            result_payload["needs_modification"] = True
            rationale_codes.append("finish_not_verified")
            result_payload["reason"] = (
                "finish_not_verified: foil treatment is product identity and was not "
                "positively matched. "
                + result_payload["reason"]
            )
        result_payload["rationale_codes"] = list(dict.fromkeys(rationale_codes))
        result_payload["route"] = Route.HUMAN_REVIEW
        result_payload["deterministic_evidence"] = deterministic_evidence_summary(
            packet
        ).model_dump(mode="json")
        result_payload["provider"] = "google-gemini-openai-compatible-transport"
        result_payload["model"] = self.model
        result_payload["finish_resolution"] = (
            finish_resolution.model_dump(mode="json")
            if finish_resolution
            else None
        )
        usage = envelope.get("usage", {})
        if isinstance(usage, dict):
            result_payload["input_tokens"] = usage.get("prompt_tokens")
            result_payload["output_tokens"] = usage.get("completion_tokens")
        return ReviewResult.model_validate(result_payload)
