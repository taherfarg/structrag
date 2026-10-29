"""Command line: index a corpus folder and run a benchmark without the dashboard.

  structrag ingest ../eval/corpus --email you@example.com
  structrag benchmark ../eval/dataset.json --email you@example.com --label baseline
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import RetrievalConfig, get_settings
from .db import open_pool, service_tx
from .ingest.parse import SUPPORTED
from .ingest.pipeline import register_document
from .ingest.worker import Worker
from .llm import LLM
from .logs import setup_logging
from .storage import Storage


async def _user_id(email: str):
    async with service_tx() as conn:
        row = await (await conn.execute("select id from auth.users where email = %s", (email,))).fetchone()
    if not row:
        sys.exit(f"no user with email {email}; sign up in the dashboard first")
    return row["id"]


async def ingest(args) -> None:
    s = get_settings()
    user = await _user_id(args.email)
    storage, llm = await Storage.connect(s), LLM(s)
    files = sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in SUPPORTED)
    for p in files:
        row, dup = await register_document(user, p.name, p.read_bytes(), storage)
        print(f"{'exists ' if dup else 'queued '} {p.name}")
    worker = Worker(llm, storage, s)
    while await worker.run_once():
        pass
    async with service_tx() as conn:
        for r in await (await conn.execute(
                "select filename, status, parse_method, parse_confidence, error, "
                "(select count(*) from sections s where s.document_id = d.id) as sections, "
                "(select count(*) from chunks c where c.document_id = d.id) as chunks "
                "from documents d where owner_id = %s order by filename", (user,))).fetchall():
            print(f"{r['status']:<8} {r['filename']:<40} {r['parse_method'] or '':<18} "
                  f"conf={r['parse_confidence']} sections={r['sections']} chunks={r['chunks']} {r['error'] or ''}")
    await llm.aclose()


async def benchmark(args) -> None:
    from .evaluation.runner import DatasetIn, create_run, execute_run, save_dataset
    from .qa import effective_config

    user = await _user_id(args.email)
    ds = DatasetIn(**json.loads(Path(args.dataset).read_text(encoding="utf-8")))
    ds_id = await save_dataset(user, ds)
    cfg: RetrievalConfig = await effective_config(user, json.loads(args.config) if args.config else None)
    run_id = await create_run(user, ds_id, args.modes, cfg, args.label, judge=not args.no_judge)
    print(f"run {run_id}: {len(ds.queries)} queries x {args.modes}")
    llm = LLM(get_settings())
    summary = await execute_run(run_id, user, llm, seed=args.seed)
    await llm.aclose()
    out = Path(args.out) / f"{run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    async with service_tx() as conn:
        run = await (await conn.execute("select * from benchmark_runs where id = %s", (run_id,))).fetchone()
    out.write_text(json.dumps(run, default=str, indent=2), encoding="utf-8")
    print_summary(summary)
    if not summary["complete"]:
        print(f"\nWARNING: queries failed {summary['errors']}; quality metrics cover only the queries that ran.")
    print(f"\nfull run record: {out}")


ROWS = ["hit@1", "hit@3", "recall@3", "recall@5", "precision@3", "mrr", "ndcg@5", "correctness", "faithfulness",
        "citation_support", "unsupported_claim_rate", "abstention_correct", "invalid_route_ids",
        "retrieval_latency_ms", "total_latency_ms", "input_tokens", "cost_usd", "error"]


def print_summary(summary: dict) -> None:
    modes = list(summary["modes"])
    print("\n" + f"{'metric':<24}" + "".join(f"{m:>22}" for m in modes))
    for key in ROWS:
        cells = []
        for m in modes:
            a = summary["modes"][m].get(key)
            if not a or a["mean"] is None:
                cells.append("-")
                continue
            val = f"{a['mean']:.4g}"
            if key.endswith("_ms"):
                val += f" p95 {a['p95']:.0f}"
            cells.append(f"{val} ({a['measured']}/{a['n']})")
        print(f"{key:<24}" + "".join(f"{c:>22}" for c in cells))
    totals = [summary["modes"][m]["total_cost_usd"] for m in modes]
    print(f"{'total_cost_usd':<24}" + "".join(f"{'-' if t is None else f'{t:.4f}':>22}" for t in totals))
    if summary.get("judge_cost_usd") is not None:
        print(f"judge cost (not counted above): ${summary['judge_cost_usd']:.4f}")


def main() -> None:
    p = argparse.ArgumentParser(prog="structrag")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest", help="upload and index every supported file in a folder")
    i.add_argument("folder")
    i.add_argument("--email", required=True)
    b = sub.add_parser("benchmark", help="load a dataset and run every mode over it")
    b.add_argument("dataset")
    b.add_argument("--email", required=True)
    b.add_argument("--modes", nargs="+", default=["vector", "structure", "hybrid"],
                   choices=["vector", "structure", "hybrid"])
    b.add_argument("--label")
    b.add_argument("--config", help="JSON overrides for RetrievalConfig")
    b.add_argument("--no-judge", action="store_true", help="skip LLM-judged answer metrics")
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--out", default="../eval/results")
    args = p.parse_args()
    setup_logging("WARNING")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def run():
        await open_pool()
        await (ingest if args.cmd == "ingest" else benchmark)(args)

    asyncio.run(run())


if __name__ == "__main__":
    main()
