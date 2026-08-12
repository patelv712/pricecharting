"""FastAPI surface for single-sale review and the POC review console."""

from __future__ import annotations

import random
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pcqc.catalog import CatalogFetcher, enrich_candidate_catalogs
from pcqc.candidates import candidate_query, rank_candidates
from pcqc.config import Settings
from pcqc.console import AdjudicationRequest, ConsoleService, MAX_RUN_ROWS
from pcqc.evidence import build_evidence_packet
from pcqc.image import ImageFetcher
from pcqc.io import read_sales_text
from pcqc.models import NormalizedSale, ReviewResult
from pcqc.pricecharting import PriceChartingClient, fallback_product
from pcqc.provider import OpenAICompatibleReviewer
from pcqc.finish_provider import TargetedFinishReviewer
from pcqc.finish_workflow import FinishAwareReviewer
from pcqc.rules import RulesReviewer
from pcqc.version import REVIEW_POLICY_VERSION


class SaleReviewRequest(BaseModel):
    identifier: str
    product_id: str
    product_title: str
    sale_title: str
    sale_amount_pennies: int = Field(ge=0)
    score: int = 0
    broad_category: str = "trading-cards"
    original_condition_id: int
    picture_url: str | None = None
    use_multimodal_model: bool = False


class CreateRunRequest(BaseModel):
    filename: str = Field(default="sales.csv", max_length=255)
    csv_text: str = Field(min_length=1, max_length=20_000_000)
    mode: Literal["rules", "multimodal"] = "multimodal"
    limit: int = Field(default=15, ge=1, le=MAX_RUN_ROWS)
    random_sample_size: int | None = Field(default=None, ge=1, le=MAX_RUN_ROWS)
    random_seed: int | None = Field(default=None, ge=0)
    selected_identifiers: list[str] | None = Field(
        default=None, min_length=1, max_length=MAX_RUN_ROWS
    )


class PreviewRunRequest(BaseModel):
    csv_text: str = Field(min_length=1, max_length=20_000_000)


@lru_cache
def settings() -> Settings:
    return Settings.from_env()


@lru_cache
def console_service() -> ConsoleService:
    return ConsoleService(settings())


app = FastAPI(title="PriceCharting Sale Quality Checker", version="0.1.0")
STATIC_DIR = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def review_console() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def api_config(config: Settings = Depends(settings)) -> dict[str, object]:
    return {
        "gemini_configured": bool(config.llm_api_key and config.llm_model),
        "pricecharting_configured": bool(config.pricecharting_api_token),
        "main_model": config.llm_model,
        "finish_model": config.finish_llm_model,
        "max_run_rows": MAX_RUN_ROWS,
        "current_policy_version": REVIEW_POLICY_VERSION,
    }


@app.post("/api/runs", status_code=202)
def create_run(
    request: CreateRunRequest,
    background_tasks: BackgroundTasks,
    service: ConsoleService = Depends(console_service),
) -> dict[str, object]:
    try:
        if (
            request.selected_identifiers is not None
            and request.random_sample_size is not None
        ):
            raise ValueError("Choose either specific listing IDs or a random sample")
        selection_metadata: dict[str, object]
        if request.selected_identifiers is not None:
            requested = request.selected_identifiers
            if len(set(requested)) != len(requested):
                raise ValueError("Selected listing IDs must be unique")
            all_sales = read_sales_text(request.csv_text)
            selected = set(requested)
            sales = [sale for sale in all_sales if sale.identifier in selected]
            missing = selected - {sale.identifier for sale in sales}
            if missing:
                sample = ", ".join(sorted(missing)[:5])
                raise ValueError(f"Selected listing IDs were not found: {sample}")
            selection_metadata = {
                "selection_strategy": "specific_rows",
                "selection_requested_count": len(requested),
            }
        elif request.random_sample_size is not None:
            all_sales = read_sales_text(request.csv_text)
            if not all_sales:
                raise ValueError("The CSV contains no sale rows")
            sample_size = min(request.random_sample_size, len(all_sales))
            seed = request.random_seed
            if seed is None:
                seed = secrets.randbits(63)
            indices = sorted(
                random.Random(seed).sample(range(len(all_sales)), sample_size)
            )
            sales = [all_sales[index] for index in indices]
            selection_metadata = {
                "selection_strategy": "random_sample",
                "selection_requested_count": request.random_sample_size,
                "selection_seed": seed,
                "source_row_count": len(all_sales),
            }
        else:
            sales = read_sales_text(request.csv_text, limit=request.limit)
            selection_metadata = {
                "selection_strategy": "first_rows_legacy",
                "selection_requested_count": request.limit,
            }
        run = service.create_run(
            sales,
            filename=request.filename,
            mode=request.mode,
            selection_metadata=selection_metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(service.process_run, str(run["id"]))
    return run


@app.post("/api/runs/preview")
def preview_run(request: PreviewRunRequest) -> dict[str, object]:
    try:
        sales = read_sales_text(request.csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "total": len(sales),
        "rows": [
            {
                "identifier": sale.identifier,
                "product_id": sale.product_id,
                "product_title": sale.product_title,
                "sale_title": sale.sale_title,
                "sale_amount_pennies": sale.sale_amount_pennies,
                "original_condition_id": sale.original_condition_id,
            }
            for sale in sales
        ],
    }


@app.get("/api/runs")
def list_runs(
    service: ConsoleService = Depends(console_service),
) -> list[dict[str, object]]:
    return service.list_runs()


@app.get("/api/runs/{run_id}")
def get_run(
    run_id: str, service: ConsoleService = Depends(console_service)
) -> dict[str, object]:
    try:
        return service.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.get("/api/runs/{run_id}/reviews")
def list_reviews(
    run_id: str,
    action: str | None = None,
    adjudication: Literal["pending", "reviewed"] | None = None,
    query: str | None = Query(default=None, max_length=200),
    service: ConsoleService = Depends(console_service),
) -> list[dict[str, object]]:
    try:
        return service.list_reviews(
            run_id, action=action, adjudication=adjudication, query=query
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.get("/api/runs/{run_id}/export")
def export_run(
    run_id: str, service: ConsoleService = Depends(console_service)
) -> Response:
    try:
        content = service.export_csv(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return Response(
        content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="pcqc-{run_id}.csv"'
        },
    )


@app.get("/api/runs/{run_id}/reviews/{identifier}")
def get_review(
    run_id: str,
    identifier: str,
    service: ConsoleService = Depends(console_service),
) -> dict[str, object]:
    try:
        return service.get_review(run_id, identifier)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Review not found") from exc


@app.put("/api/runs/{run_id}/reviews/{identifier}/adjudication")
def adjudicate_review(
    run_id: str,
    identifier: str,
    request: AdjudicationRequest,
    service: ConsoleService = Depends(console_service),
) -> dict[str, object]:
    try:
        return service.adjudicate(run_id, identifier, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Review not found") from exc


@app.post("/check-sale", response_model=ReviewResult)
def check_sale(request: SaleReviewRequest) -> ReviewResult:
    config = settings()
    sale = NormalizedSale(
        identifier=request.identifier,
        product_id=request.product_id.removeprefix("G"),
        product_title=request.product_title,
        sale_title=request.sale_title,
        sale_amount_pennies=request.sale_amount_pennies,
        score=request.score,
        broad_category=request.broad_category,
        original_condition_id=request.original_condition_id,
        picture_url=request.picture_url,
    )
    product = fallback_product(sale.product_id, sale.product_title)
    candidates = []
    enrichment_warnings: list[str] = []
    if config.pricecharting_api_token:
        client = PriceChartingClient(
            config.pricecharting_api_token, config.cache_dir
        )
        try:
            product = client.get_product(
                sale.product_id, fallback_name=sale.product_title
            )
        except Exception as exc:
            enrichment_warnings.append(
                f"assigned_product_api_unavailable:{type(exc).__name__}"
            )
        try:
            candidates = rank_candidates(
                sale, client.search_products(candidate_query(sale))
            )
        except Exception as exc:
            enrichment_warnings.append(
                f"candidate_search_unavailable:{type(exc).__name__}"
            )
    image = ImageFetcher(config.cache_dir).fetch(sale.identifier, sale.picture_url)
    catalog_fetcher = CatalogFetcher(config.cache_dir)
    catalog = catalog_fetcher.fetch(product)
    candidates = enrich_candidate_catalogs(
        candidates,
        catalog_fetcher,
        assigned_product_id=product.product_id,
    )
    packet = build_evidence_packet(
        sale,
        product,
        image,
        catalog,
        replacement_candidates=candidates,
        enrichment_warnings=enrichment_warnings,
    )
    if request.use_multimodal_model:
        if not config.llm_api_key or not config.llm_model:
            raise HTTPException(status_code=503, detail="LLM provider is not configured")
        main_reviewer = OpenAICompatibleReviewer(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
        )
        reviewer = FinishAwareReviewer(
            main_reviewer=main_reviewer,
            finish_reviewer=TargetedFinishReviewer(
                api_key=config.llm_api_key,
                base_url=config.llm_base_url,
                model=config.finish_llm_model or config.llm_model,
            ),
            cache_dir=config.cache_dir,
        )
    else:
        reviewer = RulesReviewer()
    return reviewer.review(packet)
