from __future__ import annotations

import json
from io import BytesIO

import pytest

from pcqc.models import NormalizedSale, TargetLabel


class FakeResponse:
    def __init__(self, body: bytes | dict[str, object], content_type: str = "application/json") -> None:
        self._body = json.dumps(body).encode() if isinstance(body, dict) else body
        self.headers = {"content-type": content_type}

    def read(self, size: int = -1) -> bytes:
        return BytesIO(self._body).read(size)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


@pytest.fixture
def sale() -> NormalizedSale:
    return NormalizedSale(
        identifier="sale-1",
        target=TargetLabel.IGNORED,
        status_raw="ignored",
        review_date="2026-05-27",
        most_recent_report="2026-05-27",
        product_id="9647987",
        product_title="Broly BR Dragon Ball Super",
        sale_title="Broly BR PSA 10 Dragon Ball Super",
        sale_amount_pennies=382500,
        score=223,
        broad_category="trading-cards",
        original_condition_id=1,
        picture_url="https://example.test/card.jpg",
    )
