from pathlib import Path

from figure_realm_importer.cli import build_parser, index_workbook_filename


def test_index_workbook_filename_uses_letter_category() -> None:
    assert (
        index_workbook_filename("https://example.test/universe?index=z")
        == "figure-realm-Z.xlsx"
    )


def test_index_workbook_filename_names_number_category() -> None:
    assert (
        index_workbook_filename("https://example.test/universe?index=1")
        == "figure-realm-number.xlsx"
    )


def test_index_workbooks_default_to_central_master_directory() -> None:
    args = build_parser().parse_args([])

    assert args.master_workbook_dir == Path("output/master-workbooks")
