"""Postgres access. User-scoped work always runs under RLS.

`user_tx` switches the transaction to the `structrag_api` role and sets the
JWT claims Supabase's `auth.uid()` reads, so policies filter every statement.
`service_tx` keeps the connecting role (bypasses RLS) and exists only for the
job queue, which must see every user's jobs to claim one.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import get_settings

_pool: AsyncConnectionPool | None = None


async def open_pool(dsn: str | None = None, max_size: int = 10) -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            dsn or get_settings().database_url,
            min_size=1,
            max_size=max_size,
            kwargs={"row_factory": dict_row, "options": "-c search_path=public,extensions"},
            open=False,
        )
        await _pool.open(wait=True)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("database pool is not open")
    return _pool


@asynccontextmanager
async def user_tx(user_id: UUID | str) -> AsyncIterator[AsyncConnection]:
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    async with pool().connection() as conn, conn.transaction():
        await conn.execute("select set_config('request.jwt.claims', %s, true)", (claims,))
        await conn.execute("set local role structrag_api")
        yield conn


@asynccontextmanager
async def service_tx() -> AsyncIterator[AsyncConnection]:
    async with pool().connection() as conn, conn.transaction():
        yield conn


def vec(values: list[float]) -> str:
    """pgvector text literal; pass with a ::vector cast."""
    return "[" + ",".join(f"{v:.7g}" for v in values) + "]"
