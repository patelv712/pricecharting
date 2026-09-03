from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit


@dataclass(slots=True, frozen=True)
class SeriesRecord:
    universe_name: str
    universe_id: str
    series_id: str
    source_name: str
    manufacturer: str
    year_start: str
    year_end: str
    expected_items: int | None
    source_url: str

    @property
    def identity(self) -> str:
        """Identify a checklist, including its optional Figure Realm subseries."""
        query = parse_qs(urlsplit(self.source_url).query)
        subseries_id = query.get("ssid", [""])[0]
        return f"{self.series_id}:ssid={subseries_id}" if subseries_id else self.series_id


@dataclass(slots=True)
class FigureRecord:
    universe_name: str
    series_id: str
    figure_id: str
    source_name: str
    series_name: str
    subseries: str
    manufacturer: str
    release_year: str
    model_number: str
    upc: str
    source_url: str
    image_url: str
    exclusive: str = ""
    detail_fetched: bool = False
    proposed_set_name: str = ""
    proposed_product_name: str = ""
    naming_reason: str = "source name"
    review_required: bool = False
    series_identity: str = ""
