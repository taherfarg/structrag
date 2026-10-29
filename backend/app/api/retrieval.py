import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..auth import CurrentUser
from ..db import user_tx
from ..errors import AppError
from ..llm import Ledger
from ..qa import Mode, ModeResult, effective_config, log_query, run_mode
from ..retrieval.common import RetrievalResult

router = APIRouter(tags=["retrieval"])


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    document_ids: list[UUID] | None = None
    metadata_filter: dict[str, Any] | None = None
    config: dict[str, Any] = Field(default_factory=dict, description="Overrides for RetrievalConfig fields")


class AskRequest(RetrieveRequest):
    modes: list[Mode] = Field(default_factory=lambda: ["vector", "structure", "hybrid"], min_length=1)


@router.post("/retrieve/{mode}", response_model=RetrievalResult)
async def retrieve(mode: Mode, body: RetrieveRequest, request: Request, user: CurrentUser):
    """Retrieval only, no answer: what each engine returns for the query."""
    cfg = await effective_config(user.id, body.config)
    ledger = Ledger(owner_id=user.id, mode=mode)
    r = await run_mode(mode, body.query, cfg, user.id, request.app.state.llm, ledger,
                       body.document_ids, body.metadata_filter, answer=False)
    async with user_tx(user.id) as conn:
        await ledger.flush(conn)
        await log_query(conn, user.id, body.query, r)
    if r.error:
        raise AppError(422 if r.error["code"] == "routing_failed" else 502, r.error["code"], r.error["message"],
                       r.error.get("trace"))
    return r.retrieval


@router.post("/ask", response_model=dict[str, ModeResult])
async def ask(body: AskRequest, request: Request, user: CurrentUser):
    """Retrieve and answer with each requested mode. Modes run concurrently; one failing does not hide the others."""
    cfg = await effective_config(user.id, body.config)
    modes = list(dict.fromkeys(body.modes))
    ledgers = {m: Ledger(owner_id=user.id, mode=m) for m in modes}
    results = await asyncio.gather(*(run_mode(m, body.query, cfg, user.id, request.app.state.llm, ledgers[m],
                                              body.document_ids, body.metadata_filter) for m in modes))
    async with user_tx(user.id) as conn:
        for r in results:
            await ledgers[r.mode].flush(conn)
            await log_query(conn, user.id, body.query, r)
    return {r.mode: r for r in results}
