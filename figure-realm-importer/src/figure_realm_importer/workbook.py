from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from .export import PRODUCT_COLUMNS
from .models import FigureRecord


INVALID_SHEET_CHARS_RE = re.compile(r"[\[\]:*?/\\]+")
SPACE_RE = re.compile(r"\s+")


class WorkbookExportError(RuntimeError):
    """Raised when the Excel workbook cannot be generated."""


def safe_sheet_names(universe_names: list[str]) -> dict[str, str]:
    """Return deterministic, unique Excel sheet names of at most 31 characters."""
    names: dict[str, str] = {}
    used: set[str] = set()
    for universe_name in sorted(set(universe_names), key=str.casefold):
        base = SPACE_RE.sub(" ", INVALID_SHEET_CHARS_RE.sub(" ", universe_name)).strip(" '")
        base = (base or "Universe")[:31].rstrip()
        candidate = base
        counter = 2
        while candidate.casefold() in used:
            suffix = f" ({counter})"
            candidate = f"{base[: 31 - len(suffix)].rstrip()}{suffix}"
            counter += 1
        used.add(candidate.casefold())
        names[universe_name] = candidate
    return names


def build_workbook_payload(figures: list[FigureRecord]) -> dict[str, object]:
    grouped: dict[str, list[FigureRecord]] = defaultdict(list)
    for figure in figures:
        if not figure.review_required:
            grouped[figure.universe_name].append(figure)
    if not grouped:
        raise WorkbookExportError("no importable figures are available for the workbook")

    sheet_names = safe_sheet_names(list(grouped))
    universes: list[dict[str, object]] = []
    for universe_name in sorted(grouped, key=str.casefold):
        ordered = sorted(
            grouped[universe_name],
            key=lambda item: (
                item.proposed_set_name.casefold(),
                item.proposed_product_name.casefold(),
                item.model_number.casefold(),
                int(item.figure_id),
            ),
        )
        rows = [
            [
                item.proposed_product_name,
                item.model_number,
                "Action Figures",
                item.proposed_set_name,
                int(item.release_year) if item.release_year.isdigit() else None,
                item.source_url,
            ]
            for item in ordered
        ]
        universes.append(
            {
                "universeName": universe_name,
                "sheetName": sheet_names[universe_name],
                "rows": rows,
            }
        )
    return {"columns": list(PRODUCT_COLUMNS), "universes": universes}


def export_universe_workbook(
    output_dir: Path,
    figures: list[FigureRecord],
    *,
    filename: str = "products-by-universe.xlsx",
    node_executable: str | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    builder = Path(__file__).resolve().parents[2] / "scripts" / "build_universe_workbook.mjs"
    if not builder.exists():
        raise WorkbookExportError(f"workbook builder is missing: {builder}")

    node_executable = node_executable or os.environ.get(
        "FIGURE_REALM_NODE_EXECUTABLE", "node"
    )
    payload = build_workbook_payload(figures)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="universe-workbook-",
            dir=output_dir,
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False)
            temporary_path = Path(handle.name)
        result = subprocess.run(
            [node_executable, str(builder), str(temporary_path), str(output_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            message = result.stderr.strip() or result.stdout.strip() or "unknown Node.js error"
            raise WorkbookExportError(f"Excel export failed: {message}")
    except OSError as exc:
        raise WorkbookExportError(f"could not run the Excel workbook builder: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return output_path
