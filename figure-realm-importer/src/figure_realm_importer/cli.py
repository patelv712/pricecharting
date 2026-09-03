from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .browser import BrowserFetcher, CacheOnlyFetcher, FetchError
from .capture import import_capture_bundle
from .export import export_all
from .pipeline import collect_index, collect_universe
from .workbook import WorkbookExportError, export_universe_workbook


SCOOBY_DOO_URL = (
    "https://www.figurerealm.com/universe?"
    "action=serieslist&universeid=2400&universe=scoobydoo"
)


def index_workbook_filename(index_url: str) -> str:
    category = parse_qs(urlparse(index_url).query).get("index", [""])[0]
    label = "number" if category == "1" else category.upper()
    if not label or not label.isalnum():
        label = "index"
    return f"figure-realm-{label}.xlsx"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="figure-realm-poc",
        description="Collect a Figure Realm universe and produce PriceCharting POC CSV files.",
    )
    parser.add_argument("--universe-url", default=SCOOBY_DOO_URL)
    parser.add_argument(
        "--index-url",
        help="Collect every universe and direct checklist linked from a Figure Realm index page",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output/scooby-doo"))
    parser.add_argument(
        "--master-workbook-dir",
        type=Path,
        default=Path("output/master-workbooks"),
        help="Central directory for category workbooks produced by --index-url",
    )
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/pages"))
    parser.add_argument(
        "--capture-json",
        type=Path,
        help="Import a JSON bundle produced by the included Chrome capture helper",
    )
    parser.add_argument("--delay", type=float, default=1.0, help="Delay after each uncached page")
    parser.add_argument(
        "--request-interval",
        type=float,
        default=0.0,
        help="Minimum seconds between navigation starts shared by all browser pages",
    )
    parser.add_argument("--headed", action="store_true", help="Show the Chrome window")
    parser.add_argument(
        "--stealth",
        action="store_true",
        help="Owner-authorized test mode that masks basic Playwright fingerprint signals",
    )
    parser.add_argument(
        "--patchright",
        action="store_true",
        help="Owner-authorized test using the patched Playwright driver and persistent Chrome",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path(".cache/patchright-profile"),
        help="Dedicated persistent Chrome profile used only by --patchright",
    )
    parser.add_argument(
        "--block-assets",
        action="store_true",
        help="Load HTML documents only; skip scripts, background requests, and page assets",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Read previously browser-captured HTML from --cache-dir without launching Chrome",
    )
    parser.add_argument(
        "--detail-mode",
        choices=("none", "available", "required"),
        default="required",
        help="Detail-page policy: none, enrich cached pages when available, or require every page",
    )
    parser.add_argument("--limit-figures", type=int, help="Stop after this many figures")
    parser.add_argument(
        "--detail-concurrency",
        type=int,
        default=1,
        help="Reusable browser pages for independent detail-page enrichment",
    )
    parser.add_argument(
        "--no-workbook",
        action="store_true",
        help="Skip the products-by-universe.xlsx export",
    )
    return parser


async def run(args: argparse.Namespace) -> int:
    project_dir = Path.cwd()
    output_dir = args.output_dir if args.output_dir.is_absolute() else project_dir / args.output_dir
    master_workbook_dir = (
        args.master_workbook_dir
        if args.master_workbook_dir.is_absolute()
        else project_dir / args.master_workbook_dir
    )
    cache_dir = args.cache_dir if args.cache_dir.is_absolute() else project_dir / args.cache_dir
    profile_dir = (
        args.profile_dir if args.profile_dir.is_absolute() else project_dir / args.profile_dir
    )
    try:
        if args.detail_concurrency < 1:
            print("Collection stopped: --detail-concurrency must be at least 1")
            return 2
        if args.request_interval < 0:
            print("Collection stopped: --request-interval cannot be negative")
            return 2
        if args.stealth and args.patchright:
            print("Collection stopped: choose either --stealth or --patchright, not both")
            return 2
        if args.capture_json:
            capture_path = (
                args.capture_json
                if args.capture_json.is_absolute()
                else project_dir / args.capture_json
            )
            imported = import_capture_bundle(capture_path, cache_dir)
            print(f"Imported {imported} browser-captured pages")
            args.offline = True
        fetcher_context = (
            CacheOnlyFetcher(cache_dir)
            if args.offline
            else BrowserFetcher(
                cache_dir=cache_dir,
                delay_seconds=args.delay,
                headless=not args.headed,
                stealth=args.stealth,
                patchright=args.patchright,
                block_assets=args.block_assets,
                request_interval_seconds=args.request_interval,
                profile_dir=profile_dir,
            )
        )
        async with fetcher_context as fetcher:
            collector = collect_index if args.index_url else collect_universe
            source_url = args.index_url or args.universe_url
            series, figures = await collector(
                source_url,
                fetcher,
                detail_mode=args.detail_mode,
                limit_figures=args.limit_figures,
                detail_concurrency=args.detail_concurrency,
                progress=print,
            )
    except FetchError as exc:
        print(f"Collection stopped: {exc}")
        return 2

    paths = export_all(output_dir, series, figures)
    if not args.no_workbook:
        try:
            workbook_filename = (
                index_workbook_filename(args.index_url)
                if args.index_url
                else "products-by-universe.xlsx"
            )
            workbook_dir = master_workbook_dir if args.index_url else output_dir
            paths["workbook"] = export_universe_workbook(
                workbook_dir, figures, filename=workbook_filename
            )
        except WorkbookExportError as exc:
            print(f"Collection stopped: {exc}")
            return 2
    summary = {
        "universes": len({item.universe_name for item in figures}),
        "series": len(series),
        "figures": len(figures),
        "products_exported": sum(not item.review_required for item in figures),
        "with_model_number": sum(bool(item.model_number) for item in figures),
        "with_release_year": sum(bool(item.release_year) for item in figures),
        "detail_pages": sum(item.detail_fetched for item in figures),
        "review_required": sum(item.review_required for item in figures),
        "outputs": {key: str(path) for key, path in paths.items()},
    }
    print(json.dumps(summary, indent=2))
    return 0


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(run(args)))
