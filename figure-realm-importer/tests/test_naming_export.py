import csv
from pathlib import Path

from figure_realm_importer.export import PRODUCT_COLUMNS, export_all
from figure_realm_importer.models import FigureRecord, SeriesRecord
from figure_realm_importer.naming import apply_naming, canonical_subseries, proposed_set_name


def make_figure(figure_id: str, subseries: str, *, year: str = "2021") -> FigureRecord:
    return FigureRecord(
        universe_name="Scooby-Doo",
        series_id="7091",
        figure_id=figure_id,
        source_name="Scooby-Doo",
        series_name="Scooby-Doo!",
        subseries=subseries,
        manufacturer="Playmobil",
        release_year=year,
        model_number="",
        upc="",
        source_url=f"https://example.test/{figure_id}",
        image_url="",
    )


def test_set_name_uses_manufacturer_and_subseries() -> None:
    series = SeriesRecord("Scooby-Doo", "2400", "7091", "Scooby-Doo!", "Playmobil", "2020", "2021", 40, "https://example.test")
    assert proposed_set_name(series) == "Scooby-Doo! (Playmobil)"
    assert proposed_set_name(series, "Basic Series") == "Scooby-Doo! - Basic Series (Playmobil)"


def test_set_name_does_not_repeat_universe_or_subseries_already_in_series() -> None:
    series = SeriesRecord(
        "X-Men",
        "3106",
        "3236",
        "Video Game Super Stars Presents - X-Men vs. Street Fighter - Series 1",
        "Toy Biz",
        "1998",
        "1998",
        10,
        "https://example.test/?id=3236&ssid=10",
    )
    assert proposed_set_name(series, "X-Men vs. Street Fighter - Series 1") == (
        "X-Men - Video Game Super Stars Presents - X-Men vs. Street Fighter - Series 1 "
        "(Toy Biz)"
    )

    sequel = SeriesRecord(
        "Xyber 9",
        "",
        "6306",
        "Xyber 9 - New Dawn",
        "Bandai",
        "1999",
        "1999",
        17,
        "https://example.test/?id=6306",
    )
    assert proposed_set_name(sequel, "Basic Series") == (
        "Xyber 9 - New Dawn - Basic Series (Bandai)"
    )


def test_pop_towns_aliases_to_pop_town() -> None:
    series = SeriesRecord("Scooby-Doo", "2400", "4581", "Scooby-Doo!", "Funko", "2016", "2026", 2, "https://example.test")

    assert canonical_subseries("Pop! Town") == "Pop! Town"
    assert canonical_subseries("Pop! Towns") == "Pop! Town"
    assert proposed_set_name(series, "Pop! Town") == "Scooby-Doo! - Pop! Town (Funko)"
    assert proposed_set_name(series, "Pop! Towns") == "Scooby-Doo! - Pop! Town (Funko)"


def test_subseries_creates_distinct_sets_without_product_variants() -> None:
    series = SeriesRecord("Scooby-Doo", "2400", "7091", "Scooby-Doo!", "Playmobil", "2020", "2021", 2, "https://example.test")
    figures = [make_figure("1", "Basic Series"), make_figure("2", "Mystery Monsters")]

    apply_naming(figures, {"7091": series})

    assert figures[0].proposed_set_name == "Scooby-Doo! - Basic Series (Playmobil)"
    assert figures[1].proposed_set_name == "Scooby-Doo! - Mystery Monsters (Playmobil)"
    assert figures[0].proposed_product_name == "Scooby-Doo"
    assert figures[1].proposed_product_name == "Scooby-Doo"
    assert not any(item.review_required for item in figures)


def test_same_series_and_manufacturer_split_into_different_subseries_sets() -> None:
    series = SeriesRecord("Scooby-Doo", "2400", "4581", "Scooby-Doo!", "Funko", "2016", "2026", 2, "https://example.test")
    dorbz = make_figure("171072", "Dorbz")
    dorbz.series_id = "4581"
    dorbz.manufacturer = "Funko"
    dorbz.source_name = "Scooby-Doo #135"
    dorbz.model_number = "135"
    pop = make_figure("112671", "Pop! Vinyl Figures")
    pop.series_id = "4581"
    pop.manufacturer = "Funko"
    pop.source_name = "Scooby-Doo #149"
    pop.model_number = "149"

    apply_naming([dorbz, pop], {"4581": series})

    assert dorbz.proposed_product_name == "Scooby-Doo"
    assert dorbz.proposed_set_name == "Scooby-Doo! - Dorbz (Funko)"
    assert pop.proposed_product_name == "Scooby-Doo"
    assert pop.proposed_set_name == "Scooby-Doo! - Pop! Vinyl Figures (Funko)"
    assert dorbz.proposed_set_name != pop.proposed_set_name


def test_export_uses_confirmed_pricecharting_contract(tmp_path: Path) -> None:
    series = SeriesRecord("Scooby-Doo", "2400", "7091", "Scooby-Doo!", "Playmobil", "2020", "2021", 1, "https://example.test")
    figure = make_figure("1", "Basic Series")
    figure.source_name = "Adventure with Black Knight Building Set"
    figure.model_number = "70709"
    apply_naming([figure], {"7091": series})

    paths = export_all(tmp_path, (series,), [figure])
    with paths["products"].open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert tuple(reader.fieldnames or ()) == PRODUCT_COLUMNS
    assert rows == [
        {
            "product-name": "Adventure with Black Knight Building Set",
            "model-number": "70709",
            "genre": "Action Figures",
            "console-id": "Scooby-Doo! - Basic Series (Playmobil)",
            "release-date": "2021",
            "figure-realm-link": "https://example.test/1",
        }
    ]

    with paths["sets"].open(encoding="utf-8", newline="") as handle:
        set_rows = list(csv.DictReader(handle))
    assert set_rows[0]["source-subseries-name"] == "Basic Series"
    assert set_rows[0]["proposed-set-name"] == "Scooby-Doo! - Basic Series (Playmobil)"


def test_model_number_is_not_repeated_in_product_name() -> None:
    series = SeriesRecord("Scooby-Doo", "2400", "4581", "Scooby-Doo!", "Funko", "2016", "2026", 1, "https://example.test")
    figure = make_figure("1", "Pop!")
    figure.series_id = "4581"
    figure.source_name = "Black Knight (Metallic) #305"
    figure.model_number = "305"

    apply_naming([figure], {"4581": series})

    assert figure.proposed_product_name == "Black Knight (Metallic)"


def test_non_funko_parenthetical_descriptor_becomes_variant_on_collision() -> None:
    series = SeriesRecord("Scooby-Doo", "2400", "4576", "Scoob!", "Zag Toys", "2020", "2020", 2, "https://example.test")
    base = make_figure("1", "Domez")
    base.series_id = "4576"
    base.manufacturer = "Zag Toys"
    base.source_name = "Scooby-Doo"
    chase = make_figure("2", "Domez")
    chase.series_id = "4576"
    chase.manufacturer = "Zag Toys"
    chase.source_name = "Scooby-Doo (Chase)"

    apply_naming([base, chase], {"4576": series})

    assert base.proposed_set_name == "Scooby-Doo - Scoob! - Domez (Zag Toys)"
    assert chase.proposed_set_name == "Scooby-Doo - Scoob! - Domez (Zag Toys)"
    assert base.proposed_product_name == "Scooby-Doo"
    assert chase.proposed_product_name == "Scooby-Doo [Chase]"


def test_funko_duplicate_uses_exclusive_store_as_variant() -> None:
    series = SeriesRecord("Scooby-Doo", "2400", "4581", "Scooby-Doo!", "Funko", "2016", "2026", 2, "https://example.test")
    base = make_figure("1", "Pop! Vinyl Figures")
    base.series_id = "4581"
    base.manufacturer = "Funko"
    base.source_name = "Scooby-Doo #149"
    base.model_number = "149"
    exclusive = make_figure("2", "Pop! Vinyl Figures")
    exclusive.series_id = "4581"
    exclusive.manufacturer = "Funko"
    exclusive.source_name = "Scooby-Doo (Flocked) #149"
    exclusive.model_number = "149"
    exclusive.exclusive = "Gemini Collectibles"

    apply_naming([base, exclusive], {"4581": series})

    assert base.proposed_product_name == "Scooby-Doo"
    assert exclusive.proposed_product_name == "Scooby-Doo [Gemini Collectibles]"


def test_funko_repeated_store_adds_smallest_visible_descriptor() -> None:
    series = SeriesRecord("Scooby-Doo", "2400", "4581", "Scooby-Doo!", "Funko", "2016", "2026", 2, "https://example.test")
    blue = make_figure("1", "Pop! Vinyl Figures")
    blue.series_id = "4581"
    blue.manufacturer = "Funko"
    blue.source_name = "Scooby-Doo (Flocked) (Blue) #149"
    blue.model_number = "149"
    blue.exclusive = "SDCC"
    lime = make_figure("2", "Pop! Vinyl Figures")
    lime.series_id = "4581"
    lime.manufacturer = "Funko"
    lime.source_name = "Scooby-Doo (Flocked) (Lime) #149"
    lime.model_number = "149"
    lime.exclusive = "SDCC"

    apply_naming([blue, lime], {"4581": series})

    assert blue.proposed_product_name == "Scooby-Doo [SDCC Blue]"
    assert lime.proposed_product_name == "Scooby-Doo [SDCC Lime]"
