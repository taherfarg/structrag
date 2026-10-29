import json
from typing import Any

from fastapi import APIRouter

from ..auth import CurrentUser
from ..config import RetrievalConfig, get_settings
from ..db import user_tx
from ..qa import effective_config

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_user_settings(user: CurrentUser):
    s = get_settings()
    cfg = await effective_config(user.id, None)
    return {
        "config": cfg.model_dump(),
        "defaults": RetrievalConfig().model_dump(),
        # Index-bound: changing these needs a migration and a re-index, so they are read-only here.
        "index": {"embedding_model": s.embedding_model, "embedding_dim": s.embedding_dim,
                  "chunk_max_tokens": s.chunk_max_tokens},
        "models": {"router": s.router_model, "answer": s.answer_model, "judge": s.judge_model},
    }


@router.put("/settings")
async def put_user_settings(body: dict[str, Any], user: CurrentUser):
    cfg = await effective_config(user.id, body)  # validates
    changed = {k: v for k, v in cfg.model_dump().items() if v != RetrievalConfig().model_dump()[k]}
    async with user_tx(user.id) as conn:
        await conn.execute(
            """insert into user_settings (owner_id, config) values (%s, %s::jsonb)
               on conflict (owner_id) do update set config = excluded.config, updated_at = now()""",
            (user.id, json.dumps(changed)))
    return {"config": cfg.model_dump()}
