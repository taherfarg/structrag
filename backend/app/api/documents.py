import json
from datetime import datetime
from pathlib import PurePath
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status
from pydantic import BaseModel

from ..auth import CurrentUser
from ..config import get_settings
from ..db import user_tx
from ..errors import AppError, not_found
from ..ingest.parse import SUPPORTED
from ..ingest.pipeline import DOC_SELECT, register_document

router = APIRouter(tags=["documents"])


class DocumentOut(BaseModel):
    id: UUID
    title: str
    filename: str
    mime: str
    size_bytes: int
    status: str
    version: int
    parse_method: str | None
    parse_confidence: float | None
    page_count: int | None
    metadata: dict[str, Any]
    error: str | None
    timings: dict[str, Any]
    created_at: datetime
    indexed_at: datetime | None
    section_count: int = 0
    chunk_count: int = 0
    duplicate: bool = False


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload(request: Request, response: Response, user: CurrentUser, file: UploadFile = File(...),
                 title: str | None = Form(None), metadata: str | None = Form(None)):
    s = get_settings()
    name = PurePath(file.filename or "").name
    if PurePath(name).suffix.lower() not in SUPPORTED:
        raise AppError(415, "unsupported_type", f"supported types: {', '.join(sorted(SUPPORTED))}")
    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise AppError(413, "too_large", f"limit is {s.max_upload_mb} MB")
    if not data:
        raise AppError(400, "empty_file", "file is empty")
    try:
        meta = json.loads(metadata) if metadata else {}
        assert isinstance(meta, dict)
    except (ValueError, AssertionError):
        raise AppError(422, "bad_metadata", "metadata must be a JSON object")
    row, duplicate = await register_document(user.id, name, data, request.app.state.storage, title, meta)
    if duplicate:
        response.status_code = status.HTTP_200_OK
    else:
        request.app.state.worker.wake.set()
    return DocumentOut(**row, duplicate=duplicate)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(user: CurrentUser):
    async with user_tx(user.id) as conn:
        rows = await (await conn.execute(DOC_SELECT + " order by d.created_at desc")).fetchall()
    return [DocumentOut(**r) for r in rows]


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: UUID, user: CurrentUser):
    async with user_tx(user.id) as conn:
        row = await (await conn.execute(DOC_SELECT + " where d.id = %s", (doc_id,))).fetchone()
    if not row:
        raise not_found("document")
    return DocumentOut(**row)


@router.get("/documents/{doc_id}/structure")
async def structure(doc_id: UUID, user: CurrentUser):
    """The section tree in the shape of the spec's example, plus per-section stats."""
    async with user_tx(user.id) as conn:
        doc = await (await conn.execute("select id, title, filename, parse_method, parse_confidence "
                                        "from documents where id = %s", (doc_id,))).fetchone()
        if not doc:
            raise not_found("document")
        rows = await (await conn.execute(
            """select s.id, s.parent_id, s.level, s.heading, s.path, s.page_start, s.page_end, s.token_count,
                      s.heading_source, (select count(*) from chunks c where c.section_id = s.id) as chunk_count
               from sections s where s.document_id = %s order by s.ordinal""", (doc_id,))).fetchall()
    nodes = {r["id"]: {"id": r["id"], "heading": r["heading"], "level": r["level"], "page": r["page_start"],
                       "page_end": r["page_end"], "path": r["path"], "token_count": r["token_count"],
                       "chunk_count": r["chunk_count"], "heading_source": r["heading_source"], "children": []}
             for r in rows}
    roots = []
    for r in rows:
        (nodes[r["parent_id"]]["children"] if r["parent_id"] in nodes else roots).append(nodes[r["id"]])
    return {"document_id": doc["id"], "title": doc["title"], "filename": doc["filename"],
            "parse_method": doc["parse_method"], "parse_confidence": doc["parse_confidence"], "sections": roots}


@router.get("/sections/{section_id}")
async def section(section_id: str, user: CurrentUser):
    async with user_tx(user.id) as conn:
        sec = await (await conn.execute("select * from sections where id = %s", (section_id,))).fetchone()
        if not sec:
            raise not_found("section")
        chunks = await (await conn.execute(
            "select id, ordinal, text, page, char_start, char_end, token_count from chunks "
            "where section_id = %s order by ordinal", (section_id,))).fetchall()
    return {**sec, "chunks": chunks}


@router.post("/documents/{doc_id}/reindex", status_code=202)
async def reindex(doc_id: UUID, request: Request, user: CurrentUser):
    async with user_tx(user.id) as conn:
        if not await (await conn.execute("select 1 from documents where id = %s", (doc_id,))).fetchone():
            raise not_found("document")
        pending = await (await conn.execute(
            "select id from ingest_jobs where document_id = %s and status in ('queued', 'running')",
            (doc_id,))).fetchone()
        if not pending:
            await conn.execute("insert into ingest_jobs (document_id, owner_id) values (%s, %s)", (doc_id, user.id))
    request.app.state.worker.wake.set()
    return {"queued": not pending, "already_pending": bool(pending)}


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: UUID, request: Request, user: CurrentUser):
    async with user_tx(user.id) as conn:
        row = await (await conn.execute("delete from documents where id = %s returning storage_path",
                                        (doc_id,))).fetchone()
    if not row:
        raise not_found("document")
    await request.app.state.storage.delete(row["storage_path"])
