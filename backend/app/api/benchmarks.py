import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..auth import CurrentUser
from ..db import user_tx
from ..errors import AppError, not_found
from ..evaluation.runner import DatasetIn, create_run, execute_run, save_dataset
from ..qa import Mode, effective_config

router = APIRouter(tags=["evaluation"])


@router.post("/eval/datasets", status_code=201)
async def upload_dataset(body: DatasetIn, user: CurrentUser):
    try:
        return {"id": await save_dataset(user.id, body)}
    except ValueError as e:
        raise AppError(422, "bad_dataset", str(e)) from e


@router.get("/eval/datasets")
async def list_datasets(user: CurrentUser):
    async with user_tx(user.id) as conn:
        return await (await conn.execute(
            """select d.id, d.name, d.version, d.description, d.corpus, d.content_hash, d.created_at,
                      (select count(*) from eval_queries q where q.dataset_id = d.id) as queries
               from eval_datasets d order by d.created_at desc""")).fetchall()


@router.get("/eval/datasets/{dataset_id}")
async def get_dataset(dataset_id: UUID, user: CurrentUser):
    async with user_tx(user.id) as conn:
        ds = await (await conn.execute("select * from eval_datasets where id = %s", (dataset_id,))).fetchone()
        if not ds:
            raise not_found("dataset")
        ds["queries"] = await (await conn.execute(
            "select * from eval_queries where dataset_id = %s order by qid", (dataset_id,))).fetchall()
    return ds


class BenchmarkRequest(BaseModel):
    dataset_id: UUID
    modes: list[Mode] = Field(default_factory=lambda: ["vector", "structure", "hybrid"], min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    label: str | None = None
    judge: bool = True
    seed: int = 0


@router.post("/benchmarks", status_code=202)
async def start_benchmark(body: BenchmarkRequest, request: Request, user: CurrentUser):
    cfg = await effective_config(user.id, body.config)
    run_id = await create_run(user.id, body.dataset_id, list(dict.fromkeys(body.modes)), cfg, body.label, body.judge)
    task = asyncio.create_task(execute_run(run_id, user.id, request.app.state.llm, seed=body.seed))
    tasks = request.app.state.tasks
    tasks.add(task)
    # execute_run already recorded any failure on the run row; retrieving it here keeps asyncio quiet.
    task.add_done_callback(lambda t: (tasks.discard(t), t.cancelled() or t.exception()))
    return {"id": run_id, "status": "queued"}


@router.get("/benchmarks")
async def list_benchmarks(user: CurrentUser):
    async with user_tx(user.id) as conn:
        return await (await conn.execute(
            """select r.id, r.label, r.modes, r.status, r.error, r.config, r.config_hash, r.summary, r.created_at,
                      r.finished_at, d.name as dataset_name, d.version as dataset_version,
                      (select count(*) from benchmark_results b where b.run_id = r.id) as results
               from benchmark_runs r join eval_datasets d on d.id = r.dataset_id
               order by r.created_at desc limit 200""")).fetchall()


@router.get("/benchmarks/{run_id}")
async def get_benchmark(run_id: UUID, user: CurrentUser):
    async with user_tx(user.id) as conn:
        run = await (await conn.execute("select * from benchmark_runs where id = %s", (run_id,))).fetchone()
        if not run:
            raise not_found("benchmark run")
        run["results"] = await (await conn.execute(
            """select b.mode, b.metrics, b.answer, b.retrieved, b.error, b.total_latency_ms, b.cost_usd,
                      q.qid, q.question, q.expected_answer, q.answerable, q.tags, q.gold
               from benchmark_results b join eval_queries q on q.id = b.query_id
               where b.run_id = %s order by q.qid, b.mode""", (run_id,))).fetchall()
    return run
