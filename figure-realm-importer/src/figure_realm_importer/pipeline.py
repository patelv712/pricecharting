from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import FigureRecord, SeriesRecord
from .browser import FetchError
from .naming import apply_naming
from .parsers import (
    ParseError,
    enrich_from_detail,
    parse_checklist_page,
    parse_detail_page,
    parse_direct_series_page,
    parse_universe_index_page,
    parse_universe_page,
)


Progress = Callable[[str], None]


def with_gallery_all(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    # Universe pages can link to one specific subseries with ``ssid``. Replacing
    # that value with -1 expands the request to the manufacturer's entire line
    # and pulls unrelated universes into the export. Only request all subseries
    # when the source URL did not already provide an explicit scope.
    query.setdefault("ssid", "-1")
    query["mode"] = "1"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


async def collect_universe(
    universe_url: str,
    fetcher,
    *,
    detail_mode: str = "required",
    limit_figures: int | None = None,
    detail_concurrency: int = 1,
    progress: Progress | None = None,
) -> tuple[tuple[SeriesRecord, ...], list[FigureRecord]]:
    report = progress or (lambda message: None)
    report(f"Loading universe: {universe_url}")
    universe_html = await fetcher.get(universe_url)
    universe_name, _, series_records = parse_universe_page(universe_html, universe_url)
    report(f"Found {len(series_records)} series in {universe_name}")

    return await collect_series_records(
        series_records,
        fetcher,
        detail_mode=detail_mode,
        limit_figures=limit_figures,
        detail_concurrency=detail_concurrency,
        progress=progress,
    )


async def collect_index(
    index_url: str,
    fetcher,
    *,
    detail_mode: str = "required",
    limit_figures: int | None = None,
    detail_concurrency: int = 1,
    progress: Progress | None = None,
) -> tuple[tuple[SeriesRecord, ...], list[FigureRecord]]:
    report = progress or (lambda message: None)
    report(f"Loading universe index: {index_url}")
    entries = parse_universe_index_page(await fetcher.get(index_url), index_url)
    universe_entries = sum(item.kind == "universe" for item in entries)
    direct_entries = len(entries) - universe_entries
    report(
        f"Found {len(entries)} index entries: {universe_entries} universes and "
        f"{direct_entries} direct checklists"
    )

    all_series: list[SeriesRecord] = []
    for position, entry in enumerate(entries, start=1):
        report(f"Discovering {position}/{len(entries)}: {entry.source_name}")
        if entry.kind == "universe":
            _, _, series_records = parse_universe_page(
                await fetcher.get(entry.source_url), entry.source_url
            )
            all_series.extend(series_records)
        else:
            checklist_url = with_gallery_all(entry.source_url)
            all_series.append(
                parse_direct_series_page(
                    await fetcher.get(checklist_url),
                    checklist_url,
                    universe_name=entry.source_name,
                )
            )

    unique_series = {item.identity: item for item in all_series}
    report(f"Discovered {len(unique_series)} series across {len(entries)} index entries")
    return await collect_series_records(
        tuple(unique_series.values()),
        fetcher,
        detail_mode=detail_mode,
        limit_figures=limit_figures,
        detail_concurrency=detail_concurrency,
        progress=progress,
    )


async def collect_series_records(
    series_records: tuple[SeriesRecord, ...],
    fetcher,
    *,
    detail_mode: str = "required",
    limit_figures: int | None = None,
    detail_concurrency: int = 1,
    progress: Progress | None = None,
) -> tuple[tuple[SeriesRecord, ...], list[FigureRecord]]:
    report = progress or (lambda message: None)

    figures_by_id: dict[str, FigureRecord] = {}
    for position, series in enumerate(series_records, start=1):
        report(
            f"Series {position}/{len(series_records)}: {series.universe_name} / "
            f"{series.source_name} ({series.manufacturer})"
        )
        next_url = with_gallery_all(series.source_url)
        seen_pages: set[str] = set()
        while next_url and next_url not in seen_pages:
            seen_pages.add(next_url)
            page = parse_checklist_page(await fetcher.get(next_url), next_url, series)
            for figure in page.figures:
                figures_by_id[figure.figure_id] = figure
                if limit_figures is not None and len(figures_by_id) >= limit_figures:
                    next_url = None
                    break
            else:
                next_url = page.next_url
                continue
            break
        if limit_figures is not None and len(figures_by_id) >= limit_figures:
            break

    figures = list(figures_by_id.values())
    report(f"Collected {len(figures)} checklist records")
    if detail_mode != "none":
        missing_details = 0
        if detail_concurrency > 1 and hasattr(fetcher, "get_many"):
            batch_size = detail_concurrency * 20
            for start in range(0, len(figures), batch_size):
                batch = figures[start : start + batch_size]
                report(f"Details {start + 1}/{len(figures)}")
                try:
                    html_pages = await fetcher.get_many(
                        [figure.source_url for figure in batch],
                        concurrency=detail_concurrency,
                    )
                except FetchError:
                    if detail_mode == "required":
                        raise
                    missing_details += len(batch)
                    continue
                for figure, html in zip(batch, html_pages, strict=True):
                    try:
                        fields = parse_detail_page(html, figure.source_url)
                    except ParseError:
                        if detail_mode == "required":
                            raise
                        missing_details += 1
                        continue
                    enrich_from_detail(figure, fields)
            if figures:
                report(f"Details {len(figures)}/{len(figures)}")
        else:
            for position, figure in enumerate(figures, start=1):
                if position == 1 or position % 20 == 0 or position == len(figures):
                    report(f"Details {position}/{len(figures)}")
                try:
                    fields = parse_detail_page(
                        await fetcher.get(figure.source_url), figure.source_url
                    )
                except (FetchError, ParseError):
                    if detail_mode == "required":
                        raise
                    missing_details += 1
                    continue
                enrich_from_detail(figure, fields)
        if missing_details:
            report(f"Detail pages unavailable for {missing_details}/{len(figures)} figures")

    series_by_identity = {item.identity: item for item in series_records}
    apply_naming(figures, series_by_identity)
    return series_records, figures
