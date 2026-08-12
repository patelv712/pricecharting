from __future__ import annotations

import json
from pathlib import Path

from pcqc.catalog import CatalogFetcher, catalog_page_url
from pcqc.candidates import candidate_query, rank_candidates
from pcqc.image import ImageFetcher
from pcqc.models import ProductEvidence
from pcqc.pricecharting import PriceChartingClient, PriceGuideIndex, parse_price

from conftest import FakeResponse


def test_price_parsing_and_csv_index(tmp_path: Path) -> None:
    assert parse_price("$12.34") == 1234
    assert parse_price("1,234") == 1234
    path = tmp_path / "guide.csv"
    path.write_text(
        "id,product-name,console-name,loose-price,manual-only-price\n"
        "123,Card Name,Pokemon Cards,100,5000\n",
        encoding="utf-8",
    )
    index = PriceGuideIndex()
    assert index.load(path) == 1
    assert index.get("123").price_anchors == {1: 100, 7: 5000}


def test_api_client_caches_without_exposing_token(tmp_path: Path) -> None:
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(
            {
                "status": "success",
                "id": "123",
                "product-name": "Card Name",
                "console-name": "Pokemon Cards",
                "loose-price": 1200,
            }
        )

    client = PriceChartingClient("secret-token", tmp_path, minimum_interval_seconds=0, opener=opener)
    first = client.get_product("123")
    second = client.get_product("123")
    assert first.product_name == second.product_name == "Card Name"
    assert len(calls) == 1
    cache_text = (tmp_path / "products" / "123.json").read_text(encoding="utf-8")
    assert "secret-token" not in cache_text


def test_api_product_search_caches_without_exposing_token(tmp_path: Path) -> None:
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(
            {
                "products": [
                    {
                        "id": "8506909",
                        "product-name": "Buggy [Alternate Art] OP09-042",
                        "console-name": "One Piece Japanese Emperors in the New World",
                    }
                ]
            }
        )

    client = PriceChartingClient(
        "secret-token", tmp_path, minimum_interval_seconds=0, opener=opener
    )
    first = client.search_products("Buggy alternate art OP09-042")
    second = client.search_products("Buggy alternate art OP09-042")
    assert [product.product_id for product in first] == ["8506909"]
    assert [product.product_id for product in second] == ["8506909"]
    assert len(calls) == 1
    cache_text = next((tmp_path / "product-searches").glob("*.json")).read_text()
    assert "secret-token" not in cache_text


def test_candidate_ranking_prefers_matching_parallel(sale) -> None:
    changed = sale.model_copy(
        update={
            "product_id": "8506907",
            "sale_title": "One Piece Buggy Alternate Art OP09-042 Japanese Card PSA 10",
        }
    )
    products = [
        ProductEvidence(
            product_id="8506907",
            product_name="Buggy OP09-042",
            console_name="One Piece Japanese Emperors in the New World",
            source="test",
        ),
        ProductEvidence(
            product_id="8506909",
            product_name="Buggy [Alternate Art] OP09-042",
            console_name="One Piece Japanese Emperors in the New World",
            source="test",
        ),
    ]
    ranked = rank_candidates(changed, products)
    assert candidate_query(changed) == (
        "One Piece Buggy Alternate Art OP09-042 Japanese Card"
    )
    assert ranked[0].product_id == "8506909"
    assert "printing_match=+8" in ranked[0].score_components


def test_image_fetch_validates_and_caches(tmp_path: Path) -> None:
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        return FakeResponse(b"\xff\xd8fake-jpeg", "image/jpeg")

    fetcher = ImageFetcher(tmp_path, opener=opener)
    first = fetcher.fetch("sale", "https://example.test/image.jpg")
    second = fetcher.fetch("sale", "https://example.test/image.jpg")
    assert first.usable and second.usable
    assert first.sha256 == second.sha256
    assert calls == 1


def test_image_cache_hash_mismatch_forces_refetch(tmp_path: Path) -> None:
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        return FakeResponse(b"\xff\xd8trusted-image", "image/jpeg")

    fetcher = ImageFetcher(tmp_path, opener=opener)
    first = fetcher.fetch("sale", "https://example.test/image.jpg")
    assert first.cache_path
    first.cache_path.write_bytes(b"tampered")
    second = fetcher.fetch("sale", "https://example.test/image.jpg")
    assert second.usable
    assert second.cache_path.read_bytes() == b"\xff\xd8trusted-image"
    assert calls == 2


def test_image_rejects_non_image(tmp_path: Path) -> None:
    fetcher = ImageFetcher(
        tmp_path,
        opener=lambda request, timeout: FakeResponse(b"not an image", "text/html"),
    )
    result = fetcher.fetch("sale", "https://example.test/error")
    assert not result.usable
    assert result.error == "unsupported_content_type"


def test_catalog_fetcher_verifies_product_id_and_caches_artwork(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    product = ProductEvidence(
        product_id="10538863",
        product_name="DON!! Card [Championship 2024]",
        console_name="One Piece Promo",
        source="test",
    )
    html = b"""
    <html><body>
      <img src="https://images.example/catalog.jpg"
           alt="DON!! Card [Championship 2024] One Piece Promo Prices">
      <table><tr><td>PriceCharting ID:</td><td>10538863</td></tr></table>
      <table><tr><td>Description:</td><td>Special Foil</td></tr></table>
    </body></html>
    """

    def opener(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith(".jpg"):
            return FakeResponse(b"\xff\xd8catalog", "image/jpeg")
        return FakeResponse(html, "text/html")

    fetcher = CatalogFetcher(tmp_path, opener=opener)
    first = fetcher.fetch(product)
    second = fetcher.fetch(product)
    assert catalog_page_url(product) == (
        "https://www.pricecharting.com/game/"
        "one-piece-promo/don-card-championship-2024"
    )
    assert first.product_id_verified and second.product_id_verified
    assert first.description == second.description == "Special Foil"
    assert first.image and first.image.usable
    assert len(calls) == 2


def test_catalog_page_url_matches_pricecharting_dot_name_slug() -> None:
    product = ProductEvidence(
        product_id="13159364",
        product_name="Portgas.D.Ace [Alternate Art] OP16-118",
        console_name="One Piece Japanese The Time of Battle",
        source="test",
    )
    assert catalog_page_url(product) == (
        "https://www.pricecharting.com/game/one-piece-japanese-the-time-of-battle/"
        "portgasdace-alternate-art-op16-118"
    )


def test_catalog_page_url_preserves_encoded_apostrophe() -> None:
    product = ProductEvidence(
        product_id="10656758",
        product_name="Premium Card Collection One Piece Day '25",
        console_name="One Piece Japanese Promo",
        source="test",
    )
    assert catalog_page_url(product) == (
        "https://www.pricecharting.com/game/one-piece-japanese-promo/"
        "premium-card-collection-one-piece-day-%2725"
    )


def test_product_api_refetches_malformed_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "products" / "123.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("not-json", encoding="utf-8")
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        return FakeResponse(
            {
                "status": "success",
                "id": "123",
                "product-name": "Recovered Product",
                "console-name": "Pokemon Cards",
            }
        )

    client = PriceChartingClient(
        "secret-token", tmp_path, minimum_interval_seconds=0, opener=opener
    )
    assert client.get_product("123").product_name == "Recovered Product"
    assert calls == 1
