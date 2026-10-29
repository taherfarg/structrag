from fastapi import APIRouter, Query

from ..auth import CurrentUser
from ..db import user_tx

router = APIRouter(tags=["analytics"])


@router.get("/analytics")
async def analytics(user: CurrentUser, days: int = Query(30, ge=1, le=365)):
    """Latency, tokens and cost of real traffic (playground/API), LLM spend by purpose, and index footprint."""
    since = f"{days} days"
    async with user_tx(user.id) as conn:
        modes = await (await conn.execute(
            """select mode, count(*) as queries, avg((not ok)::int) as error_rate,
                      percentile_cont(0.5) within group (order by retrieval_latency_ms) as retrieval_p50_ms,
                      percentile_cont(0.95) within group (order by retrieval_latency_ms) as retrieval_p95_ms,
                      percentile_cont(0.5) within group (order by total_latency_ms) as total_p50_ms,
                      percentile_cont(0.95) within group (order by total_latency_ms) as total_p95_ms,
                      avg(input_tokens) as avg_input_tokens, avg(output_tokens) as avg_output_tokens,
                      avg(cost_usd) as avg_cost_usd, count(cost_usd) as cost_measured
               from query_log where created_at > now() - %s::interval group by mode order by mode""",
            (since,))).fetchall()
        spend = await (await conn.execute(
            """select purpose, model, count(*) as calls, sum(input_tokens) as input_tokens,
                      sum(output_tokens) as output_tokens, sum(cost_usd) as cost_usd,
                      count(*) - count(cost_usd) as cost_unknown, avg(latency_ms) as avg_latency_ms,
                      avg((not ok)::int) as retry_rate
               from llm_calls where created_at > now() - %s::interval
               group by purpose, model order by purpose, model""", (since,))).fetchall()
        daily = await (await conn.execute(
            """select date_trunc('day', created_at)::date as day, mode, count(*) as queries,
                      sum(cost_usd) as cost_usd, avg(total_latency_ms) as avg_total_ms
               from query_log where created_at > now() - %s::interval group by 1, 2 order by 1, 2""",
            (since,))).fetchall()
        index = await (await conn.execute(
            """select d.id, d.filename, d.status, d.page_count, d.timings,
                      (select count(*) from sections s where s.document_id = d.id) as sections,
                      (select count(*) from chunks c where c.document_id = d.id) as chunks,
                      (select coalesce(sum(pg_column_size(c.*)), 0) from chunks c where c.document_id = d.id)
                    + (select coalesce(sum(pg_column_size(s.*)), 0) from sections s where s.document_id = d.id)
                      as stored_bytes
               from documents d order by d.created_at""")).fetchall()
    return {"days": days, "modes": modes, "spend": spend, "daily": daily, "index": index}
