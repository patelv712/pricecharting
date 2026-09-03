from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .models import FigureRecord, SeriesRecord


SPACE_RE = re.compile(r"\s+")
COUNT_RE = re.compile(r"\s*\[(\d+)]\s*$")
ITEMS_FOUND_RE = re.compile(r"([\d,]+)\s+Items?\s+Found", re.I)
YEAR_RANGE_RE = re.compile(r"(\d{4})\s*-\s*(\d{4})")
RELEASE_YEAR_RE = re.compile(r"Released\s+in\s*(\d{4})?\s*by\b", re.I)
DIRECT_CHECKLIST_TITLE_RE = re.compile(r"^(.*?)\s+\(([^()]*)\)\s+Checklist$", re.I)
DETAIL_RE = re.compile(
    r"^(Name|Series|Subseries|Manufacturer|Manufacturer\s*#|Year Released|UPC|Exclusive):\s*(.*)$",
    re.I,
)


class ParseError(ValueError):
    """Raised when a page no longer matches the expected public catalog structure."""


@dataclass(slots=True, frozen=True)
class ChecklistPage:
    figures: tuple[FigureRecord, ...]
    next_url: str | None


@dataclass(slots=True, frozen=True)
class IndexEntry:
    source_name: str
    source_url: str
    kind: str


def clean_text(value: str) -> str:
    return SPACE_RE.sub(" ", value.replace("\xa0", " ")).strip()


def query_value(url: str, key: str) -> str:
    return parse_qs(urlparse(url).query).get(key, [""])[0]


def _without_item_count(value: str) -> tuple[str, int | None]:
    match = COUNT_RE.search(value)
    if not match:
        return clean_text(value), None
    return clean_text(value[: match.start()]), int(match.group(1))


def _find_universe_name(soup: BeautifulSoup) -> str:
    title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    suffix = " Universe - Toy Series"
    if title.endswith(suffix):
        return title[: -len(suffix)]
    heading = soup.find(string=re.compile(r"Universe$"))
    if heading:
        return clean_text(str(heading)).removesuffix(" Universe")
    raise ParseError("could not determine universe name")


def parse_universe_index_page(html: str, source_url: str) -> tuple[IndexEntry, ...]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[IndexEntry] = []
    for anchor in soup.select('a[href*="action=serieslist"], a[href*="action=seriesitemlist"]'):
        href = urljoin(source_url, str(anchor.get("href", "")))
        source_name, _ = _without_item_count(anchor.get_text(" ", strip=True))
        if not source_name:
            continue
        kind = "universe" if "action=serieslist" in href else "series"
        records.append(IndexEntry(source_name=source_name, source_url=href, kind=kind))
    unique = {record.source_url: record for record in records}
    if not unique:
        raise ParseError("universe index page contained no universe or checklist links")
    return tuple(unique.values())


def parse_direct_series_page(
    html: str,
    source_url: str,
    *,
    universe_name: str = "",
) -> SeriesRecord:
    soup = BeautifulSoup(html, "html.parser")
    title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    match = DIRECT_CHECKLIST_TITLE_RE.match(title)
    if not match:
        heading = soup.select_one(".pagesectionhdr")
        heading_text = clean_text(heading.get_text(" ", strip=True) if heading else "")
        match = DIRECT_CHECKLIST_TITLE_RE.match(heading_text)
    if not match:
        raise ParseError("could not determine direct checklist series and manufacturer")

    source_name = clean_text(match.group(1))
    manufacturer = clean_text(match.group(2))
    page_text = clean_text(soup.get_text(" ", strip=True))
    count_match = ITEMS_FOUND_RE.search(page_text)
    years = sorted(set(re.findall(r"Released\s+in\s+(\d{4})\s+by\b", page_text, re.I)))
    series_id = query_value(source_url, "id")
    if not series_id:
        raise ParseError("direct checklist URL contained no series id")
    return SeriesRecord(
        universe_name=universe_name or source_name,
        universe_id="",
        series_id=series_id,
        source_name=source_name,
        manufacturer=manufacturer,
        year_start=years[0] if years else "",
        year_end=years[-1] if years else "",
        expected_items=int(count_match.group(1).replace(",", "")) if count_match else None,
        source_url=source_url,
    )


def parse_universe_page(html: str, source_url: str) -> tuple[str, str, tuple[SeriesRecord, ...]]:
    soup = BeautifulSoup(html, "html.parser")
    universe_name = _find_universe_name(soup)
    universe_id = query_value(source_url, "universeid")
    records: list[SeriesRecord] = []

    for anchor in soup.select('a[href*="action=seriesitemlist"]'):
        href = urljoin(source_url, str(anchor.get("href", "")))
        series_id = query_value(href, "id")
        row = anchor.find_parent("tr")
        if not series_id or not row:
            continue
        cells = row.find_all("td", recursive=False)
        if len(cells) < 2:
            cells = row.find_all("td")
        if len(cells) < 2:
            continue

        source_name, expected_items = _without_item_count(anchor.get_text(" ", strip=True))
        manufacturer = clean_text(cells[1].get_text(" ", strip=True))
        year_text = clean_text(cells[2].get_text(" ", strip=True)) if len(cells) > 2 else ""
        year_match = YEAR_RANGE_RE.search(year_text)
        year_start = year_match.group(1) if year_match else ""
        year_end = year_match.group(2) if year_match else ""
        records.append(
            SeriesRecord(
                universe_name=universe_name,
                universe_id=universe_id,
                series_id=series_id,
                source_name=source_name,
                manufacturer=manufacturer,
                year_start=year_start,
                year_end=year_end,
                expected_items=expected_items,
                source_url=href,
            )
        )

    unique = {record.identity: record for record in records}
    if not unique:
        raise ParseError("universe page contained no series/checklist links")
    return universe_name, universe_id, tuple(unique.values())


def _metadata_from_block(block: Tag, fallback_manufacturer: str) -> tuple[str, str, str]:
    text = clean_text(block.get_text(" ", strip=True))
    match = RELEASE_YEAR_RE.search(text)
    release_year = match.group(1) or "" if match else ""
    # The universe table is the authoritative manufacturer source. Checklist item blocks can
    # append descriptions immediately after the manufacturer with no reliable text delimiter.
    manufacturer = fallback_manufacturer

    subseries = ""
    for anchor in block.select('a[href*="ssid="]'):
        candidate = clean_text(anchor.get_text(" ", strip=True))
        if candidate and "browse all" not in candidate.casefold():
            subseries = candidate
            break
    return subseries, manufacturer, release_year


def parse_checklist_page(html: str, source_url: str, series: SeriesRecord) -> ChecklistPage:
    soup = BeautifulSoup(html, "html.parser")
    records: list[FigureRecord] = []

    for block in soup.select('div[group="checkitem"]'):
        name_anchor = block.select_one('.checkminihdr a[href*="action=actionfigure"]')
        if name_anchor is None:
            name_anchor = block.select_one('a[href*="action=actionfigure"]')
        if name_anchor is None:
            continue

        href = urljoin(source_url, str(name_anchor.get("href", "")))
        figure_id = query_value(href, "id")
        source_name = clean_text(name_anchor.get_text(" ", strip=True))
        if not source_name:
            image = name_anchor.find("img")
            source_name = clean_text(str(image.get("alt", ""))) if image else ""
        if not figure_id or not source_name:
            continue

        subseries, manufacturer, release_year = _metadata_from_block(block, series.manufacturer)
        image = block.select_one('img[src*="galleries/"]')
        image_url = urljoin(source_url, str(image.get("src", ""))) if image else ""
        records.append(
            FigureRecord(
                universe_name=series.universe_name,
                series_id=series.series_id,
                figure_id=figure_id,
                source_name=source_name,
                series_name=series.source_name,
                subseries=subseries,
                manufacturer=manufacturer,
                release_year=release_year,
                model_number="",
                upc="",
                source_url=href,
                image_url=image_url,
                series_identity=series.identity,
            )
        )

    unique = {record.figure_id: record for record in records}
    next_anchor = soup.find("a", string=re.compile(r"^\s*Next(?:\s+Page)?\s*$", re.I))
    next_url = urljoin(source_url, str(next_anchor.get("href", ""))) if next_anchor else None
    if not unique and "0 Items Found" not in soup.get_text(" ", strip=True):
        raise ParseError("checklist page contained no figure records")
    return ChecklistPage(figures=tuple(unique.values()), next_url=next_url)


def parse_detail_page(html: str, source_url: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}
    for row in soup.find_all("tr"):
        text = clean_text(row.get_text(" ", strip=True))
        match = DETAIL_RE.match(text)
        if match:
            key = clean_text(match.group(1)).casefold().replace(" ", "_").replace("#", "number")
            fields[key] = clean_text(match.group(2))

    if "name" not in fields:
        raise ParseError("detail page did not contain a Name field")

    for image in soup.select('img[src*="galleries/"]'):
        alt = clean_text(str(image.get("alt", "")))
        if fields["name"].casefold() in alt.casefold():
            fields["image_url"] = urljoin(source_url, str(image.get("src", "")))
            break
    return fields


def enrich_from_detail(figure: FigureRecord, fields: dict[str, str]) -> FigureRecord:
    figure.model_number = fields.get("manufacturer_number", figure.model_number)
    figure.upc = fields.get("upc", figure.upc)
    figure.release_year = fields.get("year_released", figure.release_year)
    figure.manufacturer = fields.get("manufacturer", figure.manufacturer)
    figure.subseries = fields.get("subseries", figure.subseries)
    figure.exclusive = fields.get("exclusive", figure.exclusive)
    figure.image_url = fields.get("image_url", figure.image_url)
    figure.detail_fetched = True
    return figure
