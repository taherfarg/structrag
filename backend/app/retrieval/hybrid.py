"""Hybrid: structure candidates + vector candidates -> weighted RRF -> optional cross-encoder -> budget.

Each evidence item keeps where it came from (structure_rank, vector_rank,
vector_score, rrf, rerank_score), so results can be attributed to a source.
If structure routing fails, hybrid continues on vector candidates alone and
says so in the trace; it never hides the failure.
"""

import asyncio
import time
from functools import lru_cache
from uuid import UUID

from ..config import RetrievalConfig
from ..llm import Call, LLM, Ledger
from .common import Evidence, RetrievalResult, RoutingFailed, fit_budget, ranked_sections, to_evidence
from .structure import (chunk_similarity, load_outline, order_by_relevance, round_robin, route,
                        structure_candidates)
from .vector import vector_candidates


def rrf(lists: list[tuple[str, float, list[Evidence]]], k: int) -> list[Evidence]:
    """Weighted reciprocal rank fusion over (name, weight, ranked items); ids are chunk ids."""
    merged: dict[str, Evidence] = {}
    scores: dict[str, float] = {}
    for name, weight, items in lists:
        for rank, e in enumerate(items, 1):
            if e.chunk_id not in merged:
                merged[e.chunk_id] = e.model_copy(update={"provenance": {"sources": []}})
            prov = merged[e.chunk_id].provenance
            prov["sources"].append(name)
            prov[f"{name}_rank"] = rank
            if name == "vector":
                prov["vector_score"] = e.score
            scores[e.chunk_id] = scores.get(e.chunk_id, 0.0) + weight / (k + rank)
    out = sorted(merged.values(), key=lambda e: -scores[e.chunk_id])
    for e in out:
        e.score = e.provenance["rrf"] = round(scores[e.chunk_id], 6)
    return out


@lru_cache(maxsize=2)
def _cross_encoder(model: str):
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=model)


async def rerank(query: str, items: list[Evidence], cfg: RetrievalConfig, ledger: Ledger) -> list[Evidence]:
    head, tail = items[: cfg.rerank_candidates], items[cfg.rerank_candidates :]
    t0 = time.perf_counter()
    enc = await asyncio.to_thread(_cross_encoder, cfg.rerank_model)
    scores = await asyncio.to_thread(lambda: list(enc.rerank(query, [e.text for e in head])))
    ledger.calls.append(Call("rerank", cfg.rerank_model, 0, 0, 0.0, (time.perf_counter() - t0) * 1000))
    for e, s in zip(head, scores):
        e.provenance["rerank_score"] = round(float(s), 4)
        e.score = float(s)
    return sorted(head, key=lambda e: -e.score) + tail


async def retrieve_hybrid(query: str, cfg: RetrievalConfig, user_id: UUID, llm: LLM, ledger: Ledger,
                          document_ids=None, metadata=None) -> RetrievalResult:
    t0 = time.perf_counter()
    trace: dict = {"weights": {"structure": cfg.weight_structure, "vector": cfg.weight_vector}, "rrf_k": cfg.rrf_k}
    # One query embedding, started now and shared by the vector side and relevance ordering.
    qvec_task = (asyncio.create_task(llm.embed([query], purpose="embed_query", ledger=ledger))
                if cfg.weight_vector or cfg.structure_order == "relevance" else None)

    async def structure_side() -> list[Evidence]:
        if cfg.weight_structure == 0:
            return []
        outline = await load_outline(user_id, document_ids, metadata)
        try:
            selected, rtrace = await route(query, cfg, outline, llm, ledger)
        except RoutingFailed as e:
            trace["structure_error"] = str(e)
            rtrace = e.trace
            selected = []
        trace["routing"] = rtrace
        groups = await structure_candidates(user_id, outline, selected, cfg)
        if cfg.structure_order == "relevance":
            groups = order_by_relevance(groups, await chunk_similarity(user_id, groups, (await qvec_task)[0]))
        return round_robin(groups)

    async def vector_side() -> list[Evidence]:
        if cfg.weight_vector == 0:
            return []
        rows = await vector_candidates(query, cfg.vector_candidates, cfg, user_id, llm, ledger, document_ids, metadata,
                                       qvec=(await qvec_task)[0])
        return [to_evidence(r, score=float(r["score"])) for r in rows]

    s_items, v_items = await asyncio.gather(structure_side(), vector_side())
    fused = rrf([("structure", cfg.weight_structure, s_items), ("vector", cfg.weight_vector, v_items)], cfg.rrf_k)
    if cfg.rerank == "cross_encoder" and fused:
        fused = await rerank(query, fused, cfg, ledger)
    seen, unique = set(), []
    for e in fused:
        if e.content_hash not in seen:
            seen.add(e.content_hash)
            unique.append(e)
    trace.update(structure_candidates=len(s_items), vector_candidates=len(v_items), fused=len(fused),
                 duplicates_removed=len(fused) - len(unique))
    evidence = fit_budget(unique, cfg.context_token_budget)
    for e in evidence:
        e.provenance["source"] = "hybrid"
    return RetrievalResult(mode="hybrid", query=query, evidence=evidence, ranked_sections=ranked_sections(evidence),
                           latency_ms=(time.perf_counter() - t0) * 1000, usage=ledger.totals(), trace=trace)
