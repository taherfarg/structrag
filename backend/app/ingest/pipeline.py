"""Index one document: parse -> tree -> chunks -> embeddings -> atomic swap.

Everything expensive happens before the write transaction. The transaction
deletes the document's old sections (chunks cascade) and inserts the new ones,
so concurrent readers see the old index or the new one, never a mix. Chunk
embeddings are reused when the same text was embedded with the same model,
which makes re-indexing an unchanged file free and idempotent.
"""

import hashlib
import json
import logging
import re
import time
from pathlib import PurePath
from uuid import UUID, uuid4

from ..config import Settings
from ..db import user_tx, vec
from ..llm import LLM, Ledger
from ..storage import Storage
from .parse import SUPPORTED, parse
from .structure import build_tree, chunk_section, count_tokens

log = logging.getLogger(__name__)


async def index_document(document_id: UUID, owner_id: UUID, data: bytes, filename: str,
                         llm: LLM, settings: Settings) -> dict:
    t0 = time.perf_counter()
    doc = parse(data, filename)
    root, sections, confidence = build_tree(doc, str(document_id))
    chunks = [c for n in sections for c in chunk_section(n, settings.chunk_max_tokens)]
    t_parse = time.perf_counter()

    model = settings.embedding_model
    async with user_tx(owner_id) as conn:
        rows = await (await conn.execute(
            """select distinct on (content_hash) content_hash, embedding::text as e from chunks
               where content_hash = any(%s) and embedding_model = %s and embedding is not null""",
            ([c.content_hash for c in chunks], model),
        )).fetchall()
    known = {r["content_hash"]: r["e"] for r in rows}
    missing = list(dict.fromkeys(c.content_hash for c in chunks if c.content_hash not in known))
    ledger = Ledger(owner_id=owner_id, document_id=document_id)
    if missing:
        texts = {c.content_hash: c.text for c in chunks}
        for h, v in zip(missing, await llm.embed([texts[h] for h in missing], purpose="embed_index", ledger=ledger)):
            known[h] = vec(v)
    t_embed = time.perf_counter()

    async with user_tx(owner_id) as conn:
        await conn.execute("delete from sections where document_id = %s", (document_id,))
        async with conn.cursor() as cur:
            await cur.executemany(
                """insert into sections (id, document_id, owner_id, parent_id, level, ordinal, heading, path,
                                         page_start, page_end, char_start, char_end, content, token_count,
                                         heading_source)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(n.id, document_id, owner_id, n.parent_id, n.level, n.ordinal, n.heading, n.path,
                  n.page_start, n.page_end, n.char_start, n.char_end, n.content, count_tokens(n.content),
                  n.heading_source) for n in sections],
            )
            await cur.executemany(
                """insert into chunks (id, section_id, document_id, owner_id, ordinal, text, page, char_start,
                                       char_end, token_count, content_hash, embedding, embedding_model)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s)""",
                [(c.id, c.section_id, document_id, owner_id, c.ordinal, c.text, c.page, c.char_start,
                  c.char_end, c.token_count, c.content_hash, known[c.content_hash], model) for c in chunks],
            )
        t_store = time.perf_counter()
        timings = {"parse_ms": round((t_parse - t0) * 1000), "embed_ms": round((t_embed - t_parse) * 1000),
                   "store_ms": round((t_store - t_embed) * 1000), "total_ms": round((t_store - t0) * 1000),
                   "embedded_chunks": len(missing), "reused_chunks": len(chunks) - len(missing)}
        await conn.execute(
            """update documents set status = 'ready', version = version + 1, parse_method = %s,
                      parse_confidence = %s, page_count = %s, error = null, timings = %s::jsonb,
                      metadata = metadata || jsonb_build_object('parse_warnings', %s::jsonb),
                      title = case when title = filename then %s else title end,
                      indexed_at = now(), updated_at = now()
               where id = %s""",
            (doc.method, confidence, doc.page_count, json.dumps(timings), json.dumps(doc.warnings), doc.title, document_id),
        )
        await ledger.flush(conn)
    log.info("indexed %s: %d sections, %d chunks, %s", document_id, len(sections), len(chunks), timings)
    return {"sections": len(sections), "chunks": len(chunks), "confidence": confidence, **timings}


DOC_SELECT = """
select d.*, (select count(*) from sections s where s.document_id = d.id) as section_count,
            (select count(*) from chunks c where c.document_id = d.id) as chunk_count
from documents d"""


async def register_document(user_id: UUID, filename: str, data: bytes, storage: Storage,
                            title: str | None = None, metadata: dict | None = None) -> tuple[dict, bool]:
    """Store the file and queue it for indexing. Returns (document row, is_duplicate).

    The same bytes uploaded twice by one owner return the existing document.
    """
    name = PurePath(filename).name
    mime = SUPPORTED[PurePath(name).suffix.lower()]
    sha = hashlib.sha256(data).hexdigest()
    async with user_tx(user_id) as conn:
        existing = await (await conn.execute(DOC_SELECT + " where d.sha256 = %s", (sha,))).fetchone()
    if existing:
        return existing, True
    doc_id = uuid4()
    safe = re.sub(r"[^\w.\-]+", "_", name)[-120:]
    path = f"{user_id}/{doc_id}/{safe}"
    await storage.put(path, data, mime)
    try:
        async with user_tx(user_id) as conn:
            await conn.execute(
                """insert into documents (id, owner_id, title, filename, mime, sha256, size_bytes, storage_path, metadata)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)""",
                (doc_id, user_id, title or name, name, mime, sha, len(data), path, json.dumps(metadata or {})))
            await conn.execute("insert into ingest_jobs (document_id, owner_id) values (%s, %s)", (doc_id, user_id))
            row = await (await conn.execute(DOC_SELECT + " where d.id = %s", (doc_id,))).fetchone()
    except Exception:
        await storage.delete(path)
        raise
    return row, False
