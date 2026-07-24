import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from extractors.pdf_splitter import extract_page_data, split_pages_with_context, compute_file_hash
from extractors.llm_extractor import extract_all_pages
from processing.merger import run_merge_pipeline
from processing.validator import verify_balance_continuity
from processing.feature_engine import compute_features
from analysis.narrative_llm import generate_narrative
from analysis.account_router import route_and_analyze
from db.session import init_db, get_session
from db import crud as db_crud
from storage import minio_client as storage_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database tables initialized")
    yield


app = FastAPI(title="Bank Statement Analyzer API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Response models ──────────────────────────────────────────────────────────

class AnalyzeResponse(BaseModel):
    job_id: int
    status: str
    message: str


class JobResponse(BaseModel):
    id: int
    status: str
    filename: str
    account_holder_name: str | None = None
    account_type: str | None = None
    features: dict | None = None
    result: dict | None = None
    transactions: list[dict] | None = None
    error: str | None = None


class JobListItem(BaseModel):
    id: int
    status: str
    filename: str
    account_type: str | None = None


# ── Pipeline (sync, runs in background thread) ──────────────────────────────

def _run_pipeline_sync(report_id: int, file_bytes: bytes, file_hash: str, filename: str):
    """Full analysis pipeline, runs synchronously in a background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run_pipeline(report_id, file_bytes, file_hash, filename))
    except Exception as e:
        logger.exception(f"Pipeline failed for report {report_id}")
        loop.run_until_complete(_fail_report(report_id, str(e)))
    finally:
        loop.close()


async def _fail_report(report_id: int, error: str):
    async with get_session() as db:
        await db_crud.update_report_status(db, report_id, "failed", error)


async def _run_pipeline(report_id: int, file_bytes: bytes, file_hash: str, filename: str):
    # Step 0: MinIO upload (sync client → thread)
    await asyncio.to_thread(storage_client.ensure_bucket)
    await asyncio.to_thread(storage_client.upload_pdf, file_hash, file_bytes, filename)

    # Step 1: Extract pages
    pages_data = await asyncio.to_thread(extract_page_data, file_bytes)
    chunks = await asyncio.to_thread(split_pages_with_context, pages_data, config.OVERLAP_LINES)

    # Step 2: LLM extraction (parallel, already threaded internally)
    page_results = await asyncio.to_thread(
        extract_all_pages, chunks, config.OPENROUTER_API_KEY, file_hash, None,
    )

    # Step 3: Merge + validate
    df, merge_metadata = await asyncio.to_thread(run_merge_pipeline, page_results)
    if df.empty:
        raise RuntimeError("No transactions extracted from PDF")

    df, balance_report = await asyncio.to_thread(verify_balance_continuity, df)
    quality_report = {**merge_metadata, **balance_report}

    # Step 4: Features
    features = await asyncio.to_thread(compute_features, df)

    # Step 5: Route + analyze
    routing_result = await asyncio.to_thread(
        route_and_analyze, features, config.OPENROUTER_API_KEY,
    )

    # Step 6: Narrative
    final_result = await asyncio.to_thread(
        generate_narrative,
        features, quality_report,
        merge_metadata.get("account_holder_name"),
        config.OPENROUTER_API_KEY,
        routing_result,
    )

    final_result["transactional_power_score"] = (
        routing_result.get("analysis", {}).get("transactional_power_score", "-")
    )

    # Step 7: Save to DB
    txns = df.to_dict("records")
    for t in txns:
        for key in ["parsed_date", "month", "expected_balance", "balance_diff", "balance_mismatch", "_quality"]:
            t.pop(key, None)

    async with get_session() as db:
        # Update existing report with results
        from sqlalchemy import update
        from db.models import AnalysisReport

        await db.execute(
            update(AnalysisReport)
            .where(AnalysisReport.id == report_id)
            .values(
                status="completed",
                account_holder_name=merge_metadata.get("account_holder_name"),
                account_type=routing_result.get("account_type"),
                features_json=json.dumps(features, ensure_ascii=False, default=str),
                report_json=json.dumps(final_result, ensure_ascii=False, default=str),
            )
        )
        await db.commit()
        await db_crud.save_transactions_bulk(db, report_id, txns)

    logger.info(f"Report {report_id} completed successfully")


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    if not config.OPENROUTER_API_KEY:
        raise HTTPException(500, "API key not configured")

    file_bytes = await file.read()
    file_hash = compute_file_hash(file_bytes)

    # Check cache
    async with get_session() as db:
        existing = await db_crud.get_report_by_hash(db, file_hash)
        if existing and existing.status == "completed":
            return AnalyzeResponse(
                job_id=existing.id,
                status="completed",
                message="File was already analyzed. Use GET /jobs/{id} to retrieve results.",
            )

        # Create job record
        report = await db_crud.create_report(
            db,
            file_hash=file_hash,
            original_filename=file.filename,
            status="processing",
        )

    # Launch background pipeline
    background_tasks.add_task(_run_pipeline_sync, report.id, file_bytes, file_hash, file.filename)

    return AnalyzeResponse(
        job_id=report.id,
        status="processing",
        message="Analysis started. Poll GET /jobs/{id} for status.",
    )


@app.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: int):
    async with get_session() as db:
        report = await db_crud.get_report_by_id(db, job_id)

    if not report:
        raise HTTPException(404, "Job not found")

    resp = JobResponse(
        id=report.id,
        status=report.status,
        filename=report.original_filename,
        account_holder_name=report.account_holder_name,
        account_type=report.account_type,
        error=report.error_message,
    )

    if report.status == "completed":
        resp.features = json.loads(report.features_json) if report.features_json else None
        resp.result = json.loads(report.report_json) if report.report_json else None

        # حذف فیلدهای سنگین از features
        if resp.features:
            for key in ["outlier_transactions", "outlier_count", "monthly_breakdown"]:
                resp.features.pop(key, None)

        async with get_session() as db:
            resp.transactions = await db_crud.get_transactions_by_report_id(db, report.id)

    return resp


@app.get("/jobs", response_model=list[JobListItem])
async def list_jobs(limit: int = 50, offset: int = 0):
    async with get_session() as db:
        reports = await db_crud.list_reports(db, limit, offset)

    return [
        JobListItem(
            id=r.id,
            status=r.status,
            filename=r.original_filename,
            account_type=r.account_type,
        )
        for r in reports
    ]
