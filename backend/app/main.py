import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .api import analytics, benchmarks, documents, retrieval, settings_api
from .config import get_settings
from .errors import AppError
from .ingest.worker import Worker
from .llm import LLM, LLMError
from .logs import request_id, setup_logging
from .storage import Storage

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.log_level)
    await db.open_pool()
    async with db.service_tx() as conn:
        row = await (await conn.execute(
            "select atttypmod from pg_attribute where attrelid = 'public.chunks'::regclass "
            "and attname = 'embedding'")).fetchone()
    if row["atttypmod"] != s.embedding_dim:
        raise RuntimeError(f"EMBEDDING_DIM={s.embedding_dim} but chunks.embedding is vector({row['atttypmod']})")
    app.state.llm = LLM(s)
    app.state.storage = await Storage.connect(s)
    app.state.worker = Worker(app.state.llm, app.state.storage, s)
    app.state.tasks = set()
    task = asyncio.create_task(app.state.worker.run()) if s.worker_enabled else None
    yield
    if task:
        task.cancel()
    for t in app.state.tasks:
        t.cancel()
    await app.state.llm.aclose()
    await db.close_pool()


app = FastAPI(title="StructRAG", version="0.1.0", lifespan=lifespan,
              description="Vector vs structure-aware vs hybrid retrieval, measured on the same corpus.")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"],
                   allow_headers=["*"], allow_credentials=False)


@app.middleware("http")
async def access_log(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = request_id.set(rid)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id.reset(token)
    ms = (time.perf_counter() - started) * 1000
    log.info("%s %s %d", request.method, request.url.path, response.status_code,
             extra={"extra_fields": {"ms": round(ms, 1), "request_id": rid}})
    response.headers["x-request-id"] = rid
    return response


def _err(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status)


@app.exception_handler(AppError)
async def app_error(_: Request, e: AppError):
    return _err(e.status, e.code, e.message, e.details)


@app.exception_handler(HTTPException)
async def http_error(_: Request, e: HTTPException):
    return _err(e.status_code, "http_error", str(e.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, e: RequestValidationError):
    return _err(422, "validation_error", "request did not match the schema", e.errors())


@app.exception_handler(LLMError)
async def llm_error(_: Request, e: LLMError):
    log.error("llm failure: %s", e)
    return _err(502, "llm_error", str(e)[:500])


@app.get("/api/health")
async def health():
    async with db.service_tx() as conn:
        await conn.execute("select 1")
    return {"status": "ok"}


for r in (documents.router, retrieval.router, benchmarks.router, analytics.router, settings_api.router):
    app.include_router(r, prefix="/api")
