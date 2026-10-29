"""Retrieve + answer for one mode. Shared by the API and the benchmark runner."""

import time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError

from .answer import GroundedAnswer, generate_answer
from .config import RetrievalConfig
from .db import user_tx
from .errors import AppError
from .llm import LLM, Ledger, LLMError
from .retrieval.common import RetrievalResult, RoutingFailed
from .retrieval.hybrid import retrieve_hybrid
from .retrieval.structure import retrieve_structure
from .retrieval.vector import retrieve_vector

Mode = Literal["vector", "structure", "hybrid"]
ENGINES = {"vector": retrieve_vector, "structure": retrieve_structure, "hybrid": retrieve_hybrid}


class ModeResult(BaseModel):
    mode: str
    retrieval: RetrievalResult | None = None
    answer: GroundedAnswer | None = None
    error: dict | None = None
    retrieval_latency_ms: float | None = None
    total_latency_ms: float
    usage: dict[str, Any]


async def effective_config(user_id: UUID, overrides: dict | None) -> RetrievalConfig:
    """Defaults <- the user's saved settings <- this request's overrides."""
    async with user_tx(user_id) as conn:
        row = await (await conn.execute("select config from user_settings")).fetchone()
    try:
        return RetrievalConfig(**{**(row["config"] if row else {}), **(overrides or {})})
    except ValidationError as e:
        raise AppError(422, "bad_config", "invalid retrieval config", e.errors(include_url=False)) from e


async def run_mode(mode: str, query: str, cfg: RetrievalConfig, user_id: UUID, llm: LLM, ledger: Ledger,
                   document_ids=None, metadata=None, answer: bool = True) -> ModeResult:
    t0 = time.perf_counter()
    res = ans = err = None
    try:
        res = await ENGINES[mode](query, cfg, user_id, llm, ledger, document_ids, metadata)
        if answer:
            ans = await generate_answer(query, res.evidence, cfg, llm, ledger)
    except RoutingFailed as e:
        err = {"code": "routing_failed", "message": str(e), "trace": e.trace}
    except LLMError as e:
        err = {"code": "llm_error", "message": str(e)[:500], "status": e.status}
    return ModeResult(mode=mode, retrieval=res, answer=ans, error=err,
                      retrieval_latency_ms=res.latency_ms if res else None,
                      total_latency_ms=(time.perf_counter() - t0) * 1000, usage=ledger.totals())


async def log_query(conn, user_id: UUID, query: str, r: ModeResult) -> None:
    await conn.execute(
        """insert into query_log (owner_id, mode, query, ok, error, retrieval_latency_ms, total_latency_ms,
                                  input_tokens, output_tokens, cost_usd) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (user_id, r.mode, query[:2000], r.error is None, r.error["code"] if r.error else None,
         r.retrieval_latency_ms, r.total_latency_ms, r.usage["input_tokens"], r.usage["output_tokens"],
         r.usage["cost_usd"]))
