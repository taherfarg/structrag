"""Types and helpers shared by the three retrieval modes."""

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from pydantic import BaseModel, Field


class Evidence(BaseModel):
    rank: int = 0
    chunk_id: str
    section_id: str
    document_id: UUID
    document_title: str
    filename: str
    heading_path: list[str]
    page: int | None
    text: str
    token_count: int
    content_hash: str
    score: float | None = None  # the mode's own ranking score; not comparable across modes
    provenance: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    mode: str
    query: str
    evidence: list[Evidence]
    ranked_sections: list[str]  # distinct section ids in evidence order: what retrieval metrics score
    latency_ms: float
    usage: dict[str, Any] = Field(default_factory=dict)
    trace: dict[str, Any] = Field(default_factory=dict)


class RoutingFailed(Exception):
    def __init__(self, message: str, trace: dict):
        super().__init__(message)
        self.trace = trace


HYDRATE = """
select c.id as chunk_id, c.section_id, c.document_id, d.title as document_title, d.filename,
       s.path as heading_path, c.page, c.text, c.token_count, c.content_hash, c.ordinal, s.ordinal as section_ordinal
from chunks c join sections s on s.id = c.section_id join documents d on d.id = c.document_id
"""


async def chunks_for_sections(conn: AsyncConnection, section_ids: list[str]) -> list[dict]:
    if not section_ids:
        return []
    return await (await conn.execute(
        HYDRATE + " where c.section_id = any(%s) order by s.ordinal, c.ordinal", (section_ids,))).fetchall()


def to_evidence(row: dict, **extra) -> Evidence:
    fields = {k: row[k] for k in Evidence.model_fields if k in row}
    return Evidence(**(fields | extra))


def fit_budget(items: list[Evidence], budget: int) -> list[Evidence]:
    """Keep items in rank order while they fit; skip any that would overflow. Re-ranks 1..n."""
    out, used = [], 0
    for e in items:
        if used + e.token_count <= budget:
            out.append(e)
            used += e.token_count
    for i, e in enumerate(out, 1):
        e.rank = i
    return out


def ranked_sections(items: list[Evidence]) -> list[str]:
    return list(dict.fromkeys(e.section_id for e in items))


def doc_filter_sql(document_ids: list[UUID] | None, metadata: dict | None, alias: str = "c") -> tuple[str, list]:
    sql, params = "", []
    if document_ids:
        sql += f" and {alias}.document_id = any(%s)"
        params.append(document_ids)
    if metadata:
        import json

        sql += f" and {alias}.document_id in (select id from documents where metadata @> %s::jsonb)"
        params.append(json.dumps(metadata))
    return sql, params
