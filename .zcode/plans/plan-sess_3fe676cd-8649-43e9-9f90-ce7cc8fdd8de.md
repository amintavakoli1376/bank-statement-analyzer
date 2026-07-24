
# Plan: REST API for Bank Statement Analyzer

## Goal
Add FastAPI REST API with async + polling. POST PDF → get job_id → poll status → get results. Webhook-ready architecture for future.

## Architecture

```
Client                    API (FastAPI)              Pipeline (existing)
  │                           │                           │
  ├──POST /analyze──────────>│                           │
  │   (PDF file)             ├──save job to DB            │
  │<──{job_id}──────────────┤                           │
  │                           ├──BackgroundTask──────────>│
  │                           │   (full pipeline)         │
  ├──GET /jobs/{id}────────>│                           │
  │<──{status: processing}──┤                           │
  │   ...                    │   ...                     │
  ├──GET /jobs/{id}────────>│                           │
  │<──{status: done, result}┤                           │
```

## Files to Create

### 1. `api.py` (new — main FastAPI app)
- FastAPI app with CORS
- `POST /analyze` — accepts `UploadFile`, returns `{"job_id": int}`
- `GET /jobs/{job_id}` — returns status + result/error
- `GET /jobs` — list all jobs (optional pagination)
- Background task runs the full pipeline (same logic as `app.py` lines 96-241)
- Uses `asyncio.to_thread()` for sync MinIO calls
- On failure: update job status to `"failed"` with error_message

### 2. `db/crud.py` (extend)
- Add `get_report_by_id(db, report_id)` — read single report
- Add `list_reports(db, limit, offset)` — list reports
- Add `get_transactions_by_report_id(db, report_id)` — returns list of dicts (not DataFrame)

### 3. `requirements.txt` (extend)
- Add `fastapi` and `uvicorn[standard]`

### 4. `Dockerfile` / `docker-compose.yml` (extend)
- Add API service running `uvicorn api:app --host 0.0.0.0 --port 8000`
- Keep Streamlit on 8501

## Job Model (reuse AnalysisReport)
- `status` field: `"processing"` → `"completed"` / `"failed"`
- `report_json` stores the final result
- `error_message` stores failure reason
- New report created immediately on POST with `status="processing"`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/analyze` | Upload PDF, returns `{job_id}` |
| `GET` | `/jobs/{job_id}` | Job status + result |
| `GET` | `/jobs` | List all jobs |
| `GET` | `/health` | Health check |

## POST /analyze Response
```json
{"job_id": 42, "status": "processing", "message": "Analysis started"}
```

## GET /jobs/{id} Response (processing)
```json
{"id": 42, "status": "processing", "filename": "statement.pdf"}
```

## GET /jobs/{id} Response (completed)
```json
{
  "id": 42,
  "status": "completed",
  "filename": "statement.pdf",
  "account_holder_name": "...",
  "account_type": "BUSINESS",
  "features": {...},
  "result": {...},
  "transactions": [...]
}
```

## Key Decisions
- **No new DB model** — reuse `AnalysisReport` as job record (add `status="processing"` on create, update on finish)
- **Sync pipeline in BackgroundTask** — same code from `app.py`, wrapped in `asyncio.to_thread()`
- **MinIO calls wrapped** — `asyncio.to_thread()` for sync minio_client calls
- **Future webhook** — `AnalysisReport` gets optional `webhook_url` column when needed

## Execution Order
1. Add `fastapi`, `uvicorn` to requirements.txt
2. Extend `db/crud.py` with new read operations
3. Create `api.py` with FastAPI app
4. Update Dockerfile/docker-compose for API service
