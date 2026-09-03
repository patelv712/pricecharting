from pathlib import Path

from figure_realm_importer.models import SeriesRecord
from figure_realm_importer.parsers import (
    enrich_from_detail,
    parse_checklist_page,
    parse_detail_page,
    parse_direct_series_page,
    parse_universe_index_page,
    parse_universe_page,
)


FIXTURES = Path(__file__).parent / "fixtures"
UNIVERSE_URL = "https://www.figurerealm.com/universe?action=serieslist&universeid=2400&universe=scoobydoo"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_scooby_universe() -> None:
    name, universe_id, series = parse_universe_page(fixture("universe.html"), UNIVERSE_URL)

    assert name == "Scooby-Doo"
    assert universe_id == "2400"
    assert len(series) == 2
    assert series[0].series_id == "4577"
    assert series[0].source_name == "Movie"
    assert series[0].manufacturer == "Equity Marketing"
    assert series[0].expected_items == 8
    assert series[1].year_end == "2021"


def test_parse_universe_keeps_subseries_that_share_a_series_id() -> None:
    html = """
    <html><head><title>X-Men Universe - Toy Series</title></head><body><table>
      <tr><td><a href="/actionfigure?action=seriesitemlist&id=3236&ssid=10">Series 1 [10]</a></td><td>Toy Biz</td><td>1998</td></tr>
      <tr><td><a href="/actionfigure?action=seriesitemlist&id=3236&ssid=11">Series 2 [10]</a></td><td>Toy Biz</td><td>1998</td></tr>
    </table></body></html>
    """

    _, _, series = parse_universe_page(html, UNIVERSE_URL)

    assert len(series) == 2
    assert [item.identity for item in series] == ["3236:ssid=10", "3236:ssid=11"]


def test_parse_checklist_and_next_page() -> None:
    series = SeriesRecord("Scooby-Doo", "2400", "7091", "Scooby-Doo!", "Playmobil", "2020", "2021", 40, "https://www.figurerealm.com/actionfigure?action=seriesitemlist&id=7091")
    source_url = "https://www.figurerealm.com/actionfigure?action=seriesitemlist&id=7091&ssid=-1&mode=1"

    page = parse_checklist_page(fixture("checklist-page-1.html"), source_url, series)

    assert len(page.figures) == 2
    figure = page.figures[0]
    assert figure.figure_id == "155763"
    assert figure.subseries == "Basic Series"
    assert figure.release_year == "2021"
    assert figure.manufacturer == "Playmobil"
    assert page.figures[1].manufacturer == "Playmobil"
    assert page.next_url == "https://www.figurerealm.com/actionfigure?ns=40&action=seriesitemlist&id=7091&ssid=-1&mode=1"


def test_parse_and_apply_detail() -> None:
    series = SeriesRecord("Scooby-Doo", "2400", "7091", "Scooby-Doo!", "Playmobil", "2020", "2021", 40, "https://example.test/series")
    figure = parse_checklist_page(fixture("checklist-page-1.html"), "https://www.figurerealm.com/actionfigure", series).figures[0]
    fields = parse_detail_page(fixture("detail.html"), figure.source_url)

    enrich_from_detail(figure, fields)

    assert figure.model_number == "70709"
    assert figure.upc == "4 00878 970709 3"
    assert figure.release_year == "2021"
    assert figure.exclusive == "Target"
    assert figure.image_url.endswith("thumb_BlackKnight-70709-Front.jpg")
    assert figure.detail_fetched is True


def test_parse_universe_index_with_universes_and_direct_checklists() -> None:
    entries = parse_universe_index_page(
        fixture("universe-index.html"), "https://www.figurerealm.com/universe?index=1"
    )

    assert [(item.source_name, item.kind) for item in entries] == [
        ("101 Dalmatians", "universe"),
        ("100", "series"),
    ]
    assert entries[1].source_url == (
        "https://www.figurerealm.com/actionfigure?action=seriesitemlist&id=4&figures=100"
    )


def test_parse_direct_checklist_as_single_series_universe() -> None:
    source_url = (
        "https://www.figurerealm.com/actionfigure?"
        "action=seriesitemlist&id=4&figures=100&ssid=-1&mode=1"
    )
    series = parse_direct_series_page(
        fixture("direct-series.html"), source_url, universe_name="100"
    )

    assert series.universe_name == "100"
    assert series.series_id == "4"
    assert series.source_name == "100"
    assert series.manufacturer == "Funko"
    assert series.year_start == "2017"
    assert series.year_end == "2019"
    assert series.expected_items == 1234
