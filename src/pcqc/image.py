"""Image preflight and reproducible local caching."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable
from urllib.request import Request

from pcqc.http import trusted_urlopen
from pcqc.models import ImageEvidence


ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


class ImageFetcher:
    def __init__(
        self,
        cache_dir: Path,
        *,
        max_bytes: int = 12_000_000,
        opener: Callable[..., object] = trusted_urlopen,
    ) -> None:
        self._cache_dir = cache_dir
        self._max_bytes = max_bytes
        self._opener = opener

    def fetch(self, identifier: str, url: str | None) -> ImageEvidence:
        if not url:
            return ImageEvidence(available=False, usable=False, error="missing_url")
        digest = hashlib.sha256(url.encode()).hexdigest()
        cache_path = self._cache_dir / "images" / f"{identifier}-{digest[:12]}.img"
        metadata_path = cache_path.with_suffix(".json")
        if cache_path.exists() and metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                content = cache_path.read_bytes()
                if (
                    isinstance(metadata, dict)
                    and metadata.get("sha256") == hashlib.sha256(content).hexdigest()
                    and metadata.get("byte_length") == len(content)
                    and metadata.get("content_type") in ALLOWED_CONTENT_TYPES
                ):
                    return ImageEvidence(cache_path=cache_path, **metadata)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass

        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with self._opener(request, timeout=30) as response:
                content_type = (response.headers.get("content-type") or "").split(";", 1)[0]
                if content_type not in ALLOWED_CONTENT_TYPES:
                    return ImageEvidence(
                        available=True,
                        usable=False,
                        content_type=content_type or None,
                        error="unsupported_content_type",
                    )
                content = response.read(self._max_bytes + 1)
            if len(content) > self._max_bytes:
                return ImageEvidence(
                    available=True,
                    usable=False,
                    content_type=content_type,
                    byte_length=len(content),
                    error="image_too_large",
                )
            content_hash = hashlib.sha256(content).hexdigest()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_image = cache_path.with_suffix(".img.tmp")
            temporary_image.write_bytes(content)
            temporary_image.replace(cache_path)
            evidence = ImageEvidence(
                available=True,
                usable=True,
                content_type=content_type,
                byte_length=len(content),
                sha256=content_hash,
                cache_path=cache_path,
            )
            temporary_metadata = metadata_path.with_suffix(".json.tmp")
            temporary_metadata.write_text(
                evidence.model_dump_json(exclude={"cache_path"}, indent=2), encoding="utf-8"
            )
            temporary_metadata.replace(metadata_path)
            return evidence
        except Exception as exc:
            return ImageEvidence(
                available=False,
                usable=False,
                error=f"fetch_error:{type(exc).__name__}",
            )
