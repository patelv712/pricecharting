"""Verified PriceCharting catalog-page and artwork enrichment."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from urllib.request import Request

from pcqc.http import trusted_urlopen
from pcqc.image import ImageFetcher
from pcqc.models import CatalogEvidence, ProductCandidate, ProductEvidence


def _slug(value: str) -> str:
    normalized = value.lower().replace("&", " & ")
    # PriceCharting concatenates dot-separated names such as Portgas.D.Ace.
    normalized = normalized.replace(".", "").replace("’", "'")
    # Apostrophes remain part of PriceCharting slugs and are URL encoded as %27.
    normalized = re.sub(r"[^a-z0-9&']+", "-", normalized).strip("-")
    return quote(normalized, safe="-")


def catalog_page_url(product: ProductEvidence) -> str | None:
    if not product.console_name or not product.product_name:
        return None
    return (
        "https://www.pricecharting.com/game/"
        f"{_slug(product.console_name)}/{_slug(product.product_name)}"
    )


class _CatalogParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.image_url: str | None = None
        self.text: list[str] = []
        self.details: dict[str, str] = {}
        self._cell_parts: list[str] | None = None
        self._row_cells: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag in {"td", "th"}:
            self._cell_parts = []
        if (
            tag == "meta"
            and attributes.get("property") == "og:image"
            and attributes.get("content")
        ):
            self.image_url = attributes["content"]
        if tag == "img" and self.image_url is None:
            alt = attributes.get("alt") or ""
            src = attributes.get("src")
            if src and alt.endswith("Prices") and "pricecharting.com" not in alt.lower():
                self.image_url = src

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self.text.append(stripped)
            if self._cell_parts is not None:
                self._cell_parts.append(stripped)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell_parts is not None:
            self._row_cells.append(" ".join(self._cell_parts).strip())
            self._cell_parts = None
        elif tag == "tr":
            if len(self._row_cells) >= 2:
                key = self._row_cells[0].rstrip(":").strip().lower()
                value = " ".join(self._row_cells[1:]).strip()
                if key and value:
                    self.details[key] = value
            self._row_cells = []


class CatalogFetcher:
    def __init__(
        self,
        cache_dir: Path,
        *,
        opener: Callable[..., object] = trusted_urlopen,
        image_fetcher: ImageFetcher | None = None,
    ) -> None:
        self._cache_dir = cache_dir
        self._opener = opener
        self._image_fetcher = image_fetcher or ImageFetcher(cache_dir, opener=opener)

    def fetch(self, product: ProductEvidence) -> CatalogEvidence:
        page_url = catalog_page_url(product)
        if page_url is None:
            return CatalogEvidence(error="missing_catalog_identity")
        cache_path = self._cache_dir / "catalog" / f"{product.product_id}.json"
        if cache_path.exists():
            try:
                metadata = json.loads(cache_path.read_text(encoding="utf-8"))
                if (
                    isinstance(metadata, dict)
                    and metadata.get("schema_version") == 2
                    and metadata.get("page_url") == page_url
                ):
                    image = self._image_fetcher.fetch(
                        f"catalog-{product.product_id}", metadata.get("image_url")
                    )
                    return CatalogEvidence(image=image, **metadata)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        try:
            request = Request(page_url, headers={"User-Agent": "Mozilla/5.0 pcqc/0.1"})
            with self._opener(request, timeout=30) as response:
                html = response.read().decode("utf-8", errors="replace")
            parser = _CatalogParser()
            parser.feed(html)
            page_text = " ".join(parser.text)
            id_match = re.search(r"PriceCharting ID:\s*(\d+)", page_text, re.I)
            verified = bool(id_match and id_match.group(1) == product.product_id)
            if not verified:
                return CatalogEvidence(
                    page_url=page_url,
                    image_url=parser.image_url,
                    product_id_verified=False,
                    error="catalog_product_id_mismatch",
                )
            metadata = {
                "schema_version": 2,
                "page_url": page_url,
                "image_url": parser.image_url,
                "product_id_verified": True,
                "description": parser.details.get("description"),
                "notes": parser.details.get("notes"),
                "card_number": parser.details.get("card number"),
                "error": None if parser.image_url else "missing_catalog_image",
            }
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
            )
            temporary.replace(cache_path)
            image = self._image_fetcher.fetch(
                f"catalog-{product.product_id}", parser.image_url
            )
            return CatalogEvidence(image=image, **metadata)
        except Exception as exc:
            return CatalogEvidence(
                page_url=page_url,
                error=f"catalog_fetch_error:{type(exc).__name__}",
            )


def enrich_candidate_catalogs(
    candidates: list[ProductCandidate],
    fetcher: CatalogFetcher,
    *,
    assigned_product_id: str,
    limit: int = 4,
) -> list[ProductCandidate]:
    """Attach verified artwork to the highest-ranked alternatives, never the assigned product."""
    enriched: list[ProductCandidate] = []
    remaining = limit
    for candidate in candidates:
        catalog = candidate.catalog
        if candidate.product_id != assigned_product_id and remaining > 0:
            catalog = fetcher.fetch(
                ProductEvidence(
                    product_id=candidate.product_id,
                    product_name=candidate.product_name,
                    console_name=candidate.console_name,
                    source="candidate-search",
                )
            )
            remaining -= 1
        enriched.append(candidate.model_copy(update={"catalog": catalog}))
    return enriched
