"""Baseline: query embedding -> pgvector nearest chunks. Uses no structural information."""

import time
from uuid import UUID

from ..config import RetrievalConfig
from ..db import user_tx, vec
from ..llm import LLM, Ledger
from .common import HYDRATE, RetrievalResult, doc_filter_sql, fit_budget, ranked_sections, to_evidence

# operator, and how to turn its distance into "higher is more similar"
METRICS = {"cosine": ("<=>", "1 - dist"), "inner_product": ("<#>", "-dist"), "l2": ("<->", "-dist")}


async def vector_candidates(query: str, k: int, cfg: RetrievalConfig, user_id: UUID, llm: LLM, ledger: Ledger,
                            document_ids=None, metadata=None, qvec: list[float] | None = None) -> list[dict]:
    qv = qvec or (await llm.embed([query], purpose="embed_query", ledger=ledger))[0]
    op, score = METRICS[cfg.similarity]
    where, params = doc_filter_sql(document_ids, metadata)
    async with user_tx(user_id) as conn:
        # RLS filters after the index scan; iterative scan keeps going until k rows survive.
        await conn.execute("set local hnsw.iterative_scan = relaxed_order")
        await conn.execute(f"set local hnsw.ef_search = {max(40, 2 * k)}")
        return await (await conn.execute(
            f"""with near as materialized (
                    select c.id, c.embedding {op} %s::vector as dist from chunks c
                    where c.embedding is not null {where} order by dist limit %s)
                select h.*, {score} as score from near n join ({HYDRATE}) h on h.chunk_id = n.id
                order by n.dist""",
            [vec(qv), *params, k])).fetchall()


async def retrieve_vector(query: str, cfg: RetrievalConfig, user_id: UUID, llm: LLM, ledger: Ledger,
                          document_ids=None, metadata=None) -> RetrievalResult:
    t0 = time.perf_counter()
    rows = await vector_candidates(query, cfg.top_k, cfg, user_id, llm, ledger, document_ids, metadata)
    evidence = fit_budget([to_evidence(r, score=float(r["score"]),
                                       provenance={"source": "vector", "vector_rank": i})
                           for i, r in enumerate(rows, 1)], cfg.context_token_budget)
    return RetrievalResult(mode="vector", query=query, evidence=evidence, ranked_sections=ranked_sections(evidence),
                           latency_ms=(time.perf_counter() - t0) * 1000, usage=ledger.totals(),
                           trace={"candidates": len(rows), "similarity": cfg.similarity})
