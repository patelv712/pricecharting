from urllib.parse import parse_qs, urlparse

from figure_realm_importer.pipeline import with_gallery_all


def test_gallery_all_preserves_explicit_subseries_scope() -> None:
    result = with_gallery_all(
        "https://example.test/actionfigure?action=seriesitemlist&id=3857&ssid=1"
    )

    query = parse_qs(urlparse(result).query)
    assert query["ssid"] == ["1"]
    assert query["mode"] == ["1"]


def test_gallery_all_adds_all_subseries_when_scope_is_missing() -> None:
    result = with_gallery_all(
        "https://example.test/actionfigure?action=seriesitemlist&id=4&figures=100"
    )

    query = parse_qs(urlparse(result).query)
    assert query["ssid"] == ["-1"]
    assert query["mode"] == ["1"]
