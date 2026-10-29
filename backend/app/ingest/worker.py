"""Durable ingestion queue on Postgres: claim with SKIP LOCKED, retry with backoff.

Runs inside the API process by default; `python -m app.ingest.worker` runs it alone.
A job left `running` by a crashed process is reclaimed after 15 minutes.
"""

import asyncio
import logging

from ..config import Settings
from ..db import service_tx, user_tx
from ..llm import LLM
from ..storage import Storage
from .pipeline import index_document

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


class Worker:
    def __init__(self, llm: LLM, storage: Storage, settings: Settings):
        self.llm, self.storage, self.s = llm, storage, settings
        self.wake = asyncio.Event()

    async def claim(self) -> dict | None:
        async with service_tx() as conn:
            return await (await conn.execute(
                """update ingest_jobs set status = 'running', attempts = attempts + 1, updated_at = now()
                   where id = (select id from ingest_jobs
                               where (status = 'queued' and run_after <= now())
                                  or (status = 'running' and updated_at < now() - interval '15 minutes')
                               order by id for update skip locked limit 1)
                   returning id, document_id, owner_id, attempts""")).fetchone()

    async def process(self, job: dict) -> None:
        doc_id, owner = job["document_id"], job["owner_id"]
        async with user_tx(owner) as conn:
            doc = await (await conn.execute(
                "update documents set status = 'processing', updated_at = now() where id = %s "
                "returning filename, storage_path", (doc_id,))).fetchone()
        try:
            if doc is None:
                raise RuntimeError("document no longer exists")
            data = await self.storage.get(doc["storage_path"])
            await index_document(doc_id, owner, data, doc["filename"], self.llm, self.s)
        except Exception as e:
            log.exception("ingest job %s failed (attempt %d)", job["id"], job["attempts"])
            final = job["attempts"] >= MAX_ATTEMPTS or isinstance(e, ValueError)  # bad file: retrying won't help
            async with service_tx() as conn:
                await conn.execute(
                    """update ingest_jobs set status = %s, error = %s, updated_at = now(),
                              run_after = now() + make_interval(secs => 10 * power(2, attempts)) where id = %s""",
                    ("failed" if final else "queued", str(e)[:2000], job["id"]))
            if doc is not None:
                async with user_tx(owner) as conn:
                    await conn.execute(
                        "update documents set status = %s, error = %s, updated_at = now() where id = %s",
                        ("failed" if final else "pending", str(e)[:2000], doc_id))
            return
        async with service_tx() as conn:
            await conn.execute("update ingest_jobs set status = 'done', error = null, updated_at = now() "
                               "where id = %s", (job["id"],))

    async def run_once(self) -> bool:
        job = await self.claim()
        if job:
            await self.process(job)
        return job is not None

    async def run(self) -> None:
        while True:
            try:
                if await self.run_once():
                    continue
            except Exception:
                log.exception("worker loop error")
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=2)
            except TimeoutError:
                pass


async def _main() -> None:
    from ..config import get_settings
    from ..db import open_pool
    from ..logs import setup_logging

    s = get_settings()
    setup_logging(s.log_level)
    await open_pool()
    await Worker(LLM(s), await Storage.connect(s), s).run()


if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main())
