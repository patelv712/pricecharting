"""Price-guide CSV indexing and rate-limited API enrichment."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request

from pcqc.conditions import CONDITIONS
from pcqc.http import trusted_urlopen
from pcqc.models import ProductEvidence


IDENTIFIER_KEYS = ("tcg-id", "upc", "epid", "asin")


def _read_cached_object(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_cached_object(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def parse_price(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(round(value)) if value > 0 else None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    if text.startswith("$"):
        return int(round(float(text[1:]) * 100))
    parsed = int(float(text))
    return parsed if parsed > 0 else None


def product_from_mapping(
    payload: dict[str, object], *, source: str, fallback_name: str = ""
) -> ProductEvidence:
    anchors: dict[int, int] = {}
    for condition_id, definition in CONDITIONS.items():
        if not definition.price_key:
            continue
        price = parse_price(payload.get(definition.price_key))
        if price is not None:
            anchors[condition_id] = price
    identifiers = {
        key: str(payload[key]).strip()
        for key in IDENTIFIER_KEYS
        if payload.get(key) not in (None, "", 0, "0")
    }
    sales_volume = payload.get("sales-volume")
    try:
        parsed_volume = int(str(sales_volume)) if sales_volume not in (None, "") else None
    except ValueError:
        parsed_volume = None
    return ProductEvidence(
        product_id=str(payload.get("id") or "").strip(),
        product_name=str(payload.get("product-name") or fallback_name).strip(),
        console_name=str(payload.get("console-name") or "").strip() or None,
        genre=str(payload.get("genre") or "").strip() or None,
        release_date=str(payload.get("release-date") or "").strip() or None,
        sales_volume=parsed_volume,
        identifiers=identifiers,
        price_anchors=anchors,
        source=source,
    )


class PriceGuideIndex:
    def __init__(self) -> None:
        self._products: dict[str, ProductEvidence] = {}

    def load(self, path: Path) -> int:
        loaded = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                product_id = (row.get("id") or "").strip()
                if not product_id:
                    continue
                self._products[product_id] = product_from_mapping(
                    row, source=f"price-guide:{path.name}"
                )
                loaded += 1
        return loaded

    def get(self, product_id: str) -> ProductEvidence | None:
        return self._products.get(product_id)

    def products(self) -> list[ProductEvidence]:
        return list(self._products.values())

    def __len__(self) -> int:
        return len(self._products)


class PriceChartingClient:
    def __init__(
        self,
        token: str,
        cache_dir: Path,
        *,
        minimum_interval_seconds: float = 1.05,
        opener: Callable[..., object] = trusted_urlopen,
    ) -> None:
        if not token:
            raise ValueError("PriceCharting API token is required")
        self._token = token
        self._cache_dir = cache_dir
        self._minimum_interval_seconds = minimum_interval_seconds
        self._opener = opener
        self._last_request_at = 0.0

    def get_product(self, product_id: str, *, fallback_name: str = "") -> ProductEvidence:
        if not re.fullmatch(r"\d+", product_id):
            raise ValueError(f"Invalid product id: {product_id!r}")
        cache_path = self._cache_dir / "products" / f"{product_id}.json"
        if cache_path.exists():
            payload = _read_cached_object(cache_path)
            if payload and payload.get("status") == "success":
                return product_from_mapping(
                    payload, source="api-cache", fallback_name=fallback_name
                )

        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._minimum_interval_seconds:
            time.sleep(self._minimum_interval_seconds - elapsed)
        url = "https://www.pricecharting.com/api/product?" + urlencode(
            {"t": self._token, "id": product_id}
        )
        request = Request(url, headers={"User-Agent": "pcqc/0.1"})
        with self._opener(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self._last_request_at = time.monotonic()
        if not isinstance(payload, dict):
            raise RuntimeError("PriceCharting product API returned an invalid object")
        if payload.get("status") != "success":
            raise RuntimeError(payload.get("error-message") or "PriceCharting API error")
        _write_cached_object(cache_path, payload)
        return product_from_mapping(payload, source="api", fallback_name=fallback_name)

    def search_products(self, query: str) -> list[ProductEvidence]:
        cleaned = " ".join(query.split()).strip()
        if not cleaned:
            return []
        cache_key = hashlib.sha256(cleaned.lower().encode()).hexdigest()[:24]
        cache_path = self._cache_dir / "product-searches" / f"{cache_key}.json"
        if cache_path.exists():
            payload = _read_cached_object(cache_path)
        else:
            payload = None
        if payload is None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._minimum_interval_seconds:
                time.sleep(self._minimum_interval_seconds - elapsed)
            url = "https://www.pricecharting.com/api/products?" + urlencode(
                {"t": self._token, "q": cleaned}
            )
            request = Request(url, headers={"User-Agent": "pcqc/0.1"})
            with self._opener(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self._last_request_at = time.monotonic()
            if not isinstance(payload, dict):
                raise RuntimeError("PriceCharting product search returned an invalid object")
            if payload.get("status") not in (None, "success"):
                raise RuntimeError(
                    payload.get("error-message") or "PriceCharting product search error"
                )
            _write_cached_object(cache_path, payload)
        products = payload.get("products", [])
        if not isinstance(products, list):
            raise RuntimeError("PriceCharting product search returned invalid products")
        return [
            product_from_mapping(item, source="api-search")
            for item in products
            if isinstance(item, dict) and item.get("id")
        ]


def fallback_product(product_id: str, product_title: str) -> ProductEvidence:
    return ProductEvidence(
        product_id=product_id,
        product_name=product_title,
        source="sales-export",
    )
