"""Targeted multimodal finish reviewer; outputs observations, never routing or confidence."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request

from pcqc.finish import (
    candidate_finish,
    catalog_finish_text,
    finish_family_candidates,
    finishes_from_text,
)
from pcqc.http import trusted_urlopen
from pcqc.models import (
    EvidencePacket,
    FinishImageFeatures,
    FinishProviderMetadata,
    FinishType,
    FinishVisualOutput,
)
from pcqc.provider import ProviderHTTPError, _extract_json


FINISH_PROMPT_VERSION = "2026-08-10-targeted-finish-v2"
PRICING_VERSION = "google-gemini-api-2026-08-10"
MODEL_PRICING_PER_MILLION = {
    "gemini-3.1-pro-preview": (2.0, 12.0),
}

SYSTEM_PROMPT = """You perform one narrow visual task: determine a trading card's physical finish.
The listing and verified PriceCharting candidates can use identical artwork, so artwork identity is
not finish identity. Inspect where reflective treatment appears:
- regular: no observable reflective foil treatment;
- holo: reflective treatment primarily inside the illustration window;
- reverse_holo: reflective treatment or repeating pattern outside the illustration window, across
  the card body/background;
- cosmos_holo: star/circle cosmos pattern;
- foil or special_foil: another explicitly visible reflective treatment.
Regular requires positive evidence such as an explicit NON-HOLO label; absence of visible shine in
one still image is not proof of regular. Do not infer finish from price, rarity, or the assigned
product. If lighting/resolution does not reveal the treatment, use unknown and set
visually_determinable=false. The listing detail crop is evidence from the same listing, not another
candidate. Candidate metadata is identity context, not proof of what the listing shows.
Return JSON matching the schema. Never return confidence, probability, routing, or an ID not listed
as an eligible candidate. Evidence regions must name concrete visible regions such as card_body,
illustration, border, or slab_label.
"""


@dataclass(frozen=True)
class TargetedFinishResponse:
    visual: FinishVisualOutput
    metadata: FinishProviderMetadata


def _image_item(path, media_type: str = "image/jpeg") -> dict[str, object]:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{encoded}"},
    }


class TargetedFinishReviewer:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        opener: Callable[..., object] = trusted_urlopen,
        timeout_seconds: float = 90,
        max_attempts: int = 2,
        retry_delay_seconds: float = 60,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.opener = opener
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self.retry_delay_seconds = max(0, retry_delay_seconds)
        self.sleeper = sleeper
        self.prompt_version = FINISH_PROMPT_VERSION

    def review(
        self, packet: EvidencePacket, features: FinishImageFeatures
    ) -> TargetedFinishResponse:
        eligible = []
        for candidate in packet.replacement_candidates:
            finish = candidate_finish(candidate)
            image = candidate.catalog.image if candidate.catalog else None
            if (
                finish != FinishType.UNKNOWN
                and candidate.catalog
                and candidate.catalog.product_id_verified
                and image
                and image.usable
                and image.cache_path
            ):
                eligible.append((candidate, finish, image))

        assigned_text = catalog_finish_text(packet.product.product_name, packet.catalog)
        evidence = {
            "listing_title": packet.sale.sale_title,
            "assigned_product": {
                "product_id": packet.product.product_id,
                "product_name": packet.product.product_name,
                "catalog_finish_text": assigned_text,
            },
            "eligible_candidates": [
                {
                    "product_id": candidate.product_id,
                    "product_name": candidate.product_name,
                    "finish": finish.value,
                }
                for candidate, finish, _ in eligible
            ],
            "deterministic_image_observations": features.model_dump(
                mode="json", exclude={"crop_paths"}
            ),
        }
        content: list[dict[str, object]] = [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "evidence": evidence,
                        "output_schema": FinishVisualOutput.model_json_schema(),
                    },
                    separators=(",", ":"),
                ),
            }
        ]
        full_crop = features.crop_paths.get("full")
        body_crop = features.crop_paths.get("card_body")
        if full_crop and full_crop.exists():
            content.extend(
                [
                    {"type": "text", "text": "IMAGE 1: EBAY LISTING - FULL CARD"},
                    _image_item(full_crop),
                ]
            )
        if body_crop and body_crop.exists():
            content.extend(
                [
                    {
                        "type": "text",
                        "text": "IMAGE 2: EBAY LISTING - CARD BODY DETAIL",
                    },
                    _image_item(body_crop),
                ]
            )
        illustration_crop = features.crop_paths.get("illustration")
        if illustration_crop and illustration_crop.exists():
            content.extend(
                [
                    {
                        "type": "text",
                        "text": "IMAGE 3: EBAY LISTING - ILLUSTRATION DETAIL",
                    },
                    _image_item(illustration_crop),
                ]
            )
        border_crop = features.crop_paths.get("outer_border")
        if border_crop and border_crop.exists():
            content.extend(
                [
                    {
                        "type": "text",
                        "text": "IMAGE 4: EBAY LISTING - OUTER BORDER STRIPS",
                    },
                    _image_item(border_crop),
                ]
            )
        assigned_image = packet.catalog.image if packet.catalog else None
        if assigned_image and assigned_image.usable and assigned_image.cache_path:
            content.extend(
                [
                    {
                        "type": "text",
                        "text": (
                            "IMAGE 5: ASSIGNED PRICECHARTING PRODUCT "
                            f"{packet.product.product_id}"
                        ),
                    },
                    _image_item(
                        assigned_image.cache_path,
                        assigned_image.content_type or "image/jpeg",
                    ),
                ]
            )
        image_number = 6
        for candidate, finish, image in eligible:
            content.extend(
                [
                    {
                        "type": "text",
                        "text": (
                            f"IMAGE {image_number}: ELIGIBLE {finish.value} CANDIDATE "
                            f"{candidate.product_id}"
                        ),
                    },
                    _image_item(image.cache_path, image.content_type or "image/jpeg"),
                ]
            )
            image_number += 1

        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
        ).encode()
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
        started = time.perf_counter()
        envelope = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    envelope = json.loads(response.read().decode())
                break
            except HTTPError as exc:
                message = exc.read().decode(errors="replace")
                retryable = exc.code == 429 or exc.code >= 500
                if not retryable or attempt == self.max_attempts:
                    raise ProviderHTTPError(exc.code, message or exc.reason) from exc
            except (TimeoutError, URLError):
                if attempt == self.max_attempts:
                    raise
            self.sleeper(self.retry_delay_seconds)
        if envelope is None:
            raise RuntimeError("Finish provider exhausted retries without a response")
        choices = envelope.get("choices") if isinstance(envelope, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ValueError("Finish provider response has no choices")
        raw = choices[0].get("message", {}).get("content")
        if not isinstance(raw, str):
            raise ValueError("Finish provider response has no text")
        result = FinishVisualOutput.model_validate(_extract_json(raw))
        eligible_by_id = {
            candidate.product_id: finish for candidate, finish, _ in eligible
        }
        if result.matching_candidate_id is not None:
            candidate_finish_value = eligible_by_id.get(result.matching_candidate_id)
            if candidate_finish_value != result.observed_finish:
                result = result.model_copy(
                    update={
                        "visually_determinable": False,
                        "observed_finish": FinishType.UNKNOWN,
                        "matching_candidate_id": None,
                        "reason": (
                            "Provider candidate selection contradicted verified candidate finish. "
                            + result.reason
                        ),
                    }
                )
        if result.visually_determinable and not result.evidence_regions:
            result = result.model_copy(
                update={
                    "visually_determinable": False,
                    "observed_finish": FinishType.UNKNOWN,
                    "matching_candidate_id": None,
                    "reason": "No concrete finish region was supplied. " + result.reason,
                }
            )
        reflective_siblings = any(
            candidate_finish(candidate)
            not in {FinishType.REGULAR, FinishType.UNKNOWN}
            for candidate in finish_family_candidates(packet)
        )
        explicit_regular = FinishType.REGULAR in finishes_from_text(
            packet.sale.sale_title
        )
        if (
            result.visually_determinable
            and result.observed_finish == FinishType.REGULAR
            and reflective_siblings
            and not explicit_regular
        ):
            result = result.model_copy(
                update={
                    "visually_determinable": False,
                    "observed_finish": FinishType.UNKNOWN,
                    "matching_candidate_id": None,
                    "reason": (
                        "Image-only absence of reflection cannot prove regular finish when "
                        "verified reflective siblings exist. "
                        + result.reason
                    ),
                }
            )
        usage = envelope.get("usage", {}) if isinstance(envelope, dict) else {}
        input_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        output_tokens = (
            usage.get("completion_tokens") if isinstance(usage, dict) else None
        )
        total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        billable_output_tokens = None
        if isinstance(total_tokens, int) and isinstance(input_tokens, int):
            billable_output_tokens = max(0, total_tokens - input_tokens)
        estimated_cost = None
        rates = MODEL_PRICING_PER_MILLION.get(self.model)
        if rates and isinstance(input_tokens, int) and billable_output_tokens is not None:
            estimated_cost = round(
                input_tokens * rates[0] / 1_000_000
                + billable_output_tokens * rates[1] / 1_000_000,
                8,
            )
        return TargetedFinishResponse(
            visual=result,
            metadata=FinishProviderMetadata(
                provider="google-gemini-openai-compatible-transport",
                model=self.model,
                prompt_version=self.prompt_version,
                latency_ms=round((time.perf_counter() - started) * 1000),
                attempt_count=attempt,
                input_tokens=input_tokens if isinstance(input_tokens, int) else None,
                output_tokens=output_tokens if isinstance(output_tokens, int) else None,
                billable_output_tokens=billable_output_tokens,
                total_tokens=total_tokens if isinstance(total_tokens, int) else None,
                estimated_cost_usd=estimated_cost,
                pricing_version=PRICING_VERSION if estimated_cost is not None else None,
                cost_estimate_scope=(
                    "successful_response_only; prior timed-out attempts may also be billed"
                    if estimated_cost is not None and attempt > 1
                    else "successful_response"
                    if estimated_cost is not None
                    else None
                ),
            ),
        )
