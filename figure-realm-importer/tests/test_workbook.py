from figure_realm_importer.models import FigureRecord
from figure_realm_importer.workbook import build_workbook_payload, safe_sheet_names


def make_figure(figure_id: str, universe: str) -> FigureRecord:
    return FigureRecord(
        universe_name=universe,
        series_id="1",
        figure_id=figure_id,
        source_name="Scooby-Doo",
        series_name="Scooby-Doo!",
        subseries="Domez",
        manufacturer="Zag Toys",
        release_year="2020",
        model_number="001",
        upc="",
        source_url=f"https://example.test/{figure_id}",
        image_url="",
        proposed_set_name=f"{universe} - Domez (Zag Toys)",
        proposed_product_name="Scooby-Doo",
    )


def test_sheet_names_are_safe_short_and_unique() -> None:
    names = safe_sheet_names(
        [
            "A Universe With A Very Long Name / Version One",
            "A Universe With A Very Long Name : Version One",
        ]
    )

    assert len(set(names.values())) == 2
    assert all(len(name) <= 31 for name in names.values())
    assert all(not any(character in name for character in "[]:*?/\\") for name in names.values())


def test_workbook_payload_groups_products_by_universe() -> None:
    scooby = make_figure("1", "Scooby-Doo")
    batman = make_figure("2", "Batman")

    payload = build_workbook_payload([scooby, batman])

    assert payload["columns"] == [
        "product-name",
        "model-number",
        "genre",
        "console-id",
        "release-date",
        "figure-realm-link",
    ]
    assert [item["sheetName"] for item in payload["universes"]] == ["Batman", "Scooby-Doo"]
    scooby_rows = payload["universes"][1]["rows"]
    assert scooby_rows == [
        [
            "Scooby-Doo",
            "001",
            "Action Figures",
            "Scooby-Doo - Domez (Zag Toys)",
            2020,
            "https://example.test/1",
        ]
    ]
