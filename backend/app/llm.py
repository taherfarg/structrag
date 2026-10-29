"""One OpenAI-compatible client for chat and embeddings, with retries and cost accounting.

Retries cover transport errors, 408/429/5xx, and OpenRouter's habit of
returning HTTP 200 with an upstream error in the body. Every attempt that
reached the provider is recorded in the caller's Ledger, so failed attempts
still show up in cost.
"""

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar
from uuid import UUID

import httpx
from psycopg import AsyncConnection
from pydantic import BaseModel, ValidationError

from .config import Settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529}


class LLMError(RuntimeError):
    pass


@dataclass
class Call:
    purpose: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    latency_ms: float
    ok: bool = True


@dataclass
class Ledger:
    """Collects the LLM calls made while serving one request or one benchmark query."""

    owner_id: UUID | str | None = None
    mode: str | None = None
    document_id: UUID | str | None = None
    run_id: UUID | str | None = None
    calls: list[Call] = field(default_factory=list)

    def totals(self, purposes: set[str] | None = None) -> dict[str, Any]:
        calls = [c for c in self.calls if purposes is None or c.purpose in purposes]
        costs = [c.cost_usd for c in calls]
        return {
            "calls": len(calls),
            "input_tokens": sum(c.input_tokens for c in calls),
            "output_tokens": sum(c.output_tokens for c in calls),
            # None if any call's cost is unknown: a partial sum would understate it.
            "cost_usd": None if any(c is None for c in costs) else sum(costs),
            "by_purpose": {
                p: {
                    "calls": sum(1 for c in calls if c.purpose == p),
                    "input_tokens": sum(c.input_tokens for c in calls if c.purpose == p),
                    "output_tokens": sum(c.output_tokens for c in calls if c.purpose == p),
                }
                for p in sorted({c.purpose for c in calls})
            },
        }

    async def flush(self, conn: AsyncConnection) -> None:
        if not self.calls or self.owner_id is None:
            return
        async with conn.cursor() as cur:
            await cur.executemany(
                """insert into llm_calls (owner_id, purpose, model, mode, input_tokens, output_tokens,
                                          cost_usd, latency_ms, ok, document_id, run_id)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (self.owner_id, c.purpose, c.model, self.mode, c.input_tokens, c.output_tokens,
                     c.cost_usd, c.latency_ms, c.ok, self.document_id, self.run_id)
                    for c in self.calls
                ],
            )
        self.calls.clear()


def extract_json(text: str) -> Any:
    """Parse model output that should be JSON but may be fenced or wrapped in prose."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


class LLM:
    is_fake = False

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self.s = settings
        self.http = http or httpx.AsyncClient(timeout=settings.llm_timeout_s)
        self.sem = asyncio.Semaphore(settings.llm_max_concurrency)
        self._prices: dict[str, tuple[float, float]] | None = None

    async def aclose(self) -> None:
        await self.http.aclose()

    # ------------------------------------------------------------------ transport
    async def _post(self, base: str, key: str, path: str, body: dict) -> tuple[dict, float]:
        delay = 1.0
        last: Exception | None = None
        for attempt in range(5):
            if attempt:
                await asyncio.sleep(delay + random.random() * 0.5)
                delay = min(delay * 2, 20)
            started = time.perf_counter()
            try:
                async with self.sem:
                    r = await self.http.post(
                        f"{base.rstrip('/')}/{path}",
                        json=body,
                        headers={"Authorization": f"Bearer {key}", "X-Title": "StructRAG"},
                    )
            except httpx.TransportError as e:
                last = e
                log.warning("llm transport error (%s), attempt %d", e, attempt + 1)
                continue
            ms = (time.perf_counter() - started) * 1000
            if r.status_code in RETRYABLE:
                last = LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
                retry_after = r.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    delay = min(float(retry_after), 30)
                log.warning("llm %s, attempt %d", last, attempt + 1)
                continue
            if r.status_code >= 400:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:500]}")
            try:
                data = r.json()
            except ValueError:
                last = LLMError(f"non-JSON 200 body: {r.text[:200]}")
                continue
            err = data.get("error") if isinstance(data, dict) else None
            if err:
                code = str(err.get("code", "")) if isinstance(err, dict) else ""
                msg = err.get("message", err) if isinstance(err, dict) else err
                last = LLMError(f"provider error {code}: {msg}")
                if code.isdigit() and int(code) in RETRYABLE:
                    log.warning("llm %s, attempt %d", last, attempt + 1)
                    continue
                raise last
            return data, ms
        raise LLMError(f"gave up after retries: {last}")

    async def _price(self, model: str, inp: int, out: int) -> float | None:
        """Fallback when the provider does not report cost: OpenRouter's public price list."""
        if self._prices is None:
            self._prices = {}
            try:
                r = await self.http.get(f"{self.s.llm_base_url.rstrip('/')}/models", timeout=20)
                for m in r.json().get("data", []):
                    p = m.get("pricing") or {}
                    self._prices[m["id"]] = (float(p.get("prompt") or 0), float(p.get("completion") or 0))
                r = await self.http.get(f"{self.s.llm_base_url.rstrip('/')}/embeddings/models", timeout=20)
                for m in r.json().get("data", []):
                    self._prices[m["id"]] = (float((m.get("pricing") or {}).get("prompt") or 0), 0.0)
            except (httpx.HTTPError, ValueError, KeyError) as e:
                log.info("price list unavailable: %s", e)
        if model not in self._prices:
            return None
        pin, pout = self._prices[model]
        return inp * pin + out * pout

    async def _record(self, ledger: Ledger, purpose: str, model: str, data: dict, ms: float, ok=True) -> None:
        u = data.get("usage") or {}
        inp = int(u.get("prompt_tokens") or 0)
        out = int(u.get("completion_tokens") or 0)
        cost = u.get("cost")
        cost = float(cost) if cost is not None else await self._price(model, inp, out)
        ledger.calls.append(Call(purpose, model, inp, out, cost, ms, ok))

    # ------------------------------------------------------------------ chat
    async def chat_json(
        self,
        schema: type[T],
        messages: list[dict],
        *,
        model: str,
        purpose: str,
        ledger: Ledger,
        max_tokens: int = 1000,
    ) -> T:
        """Chat call whose reply must validate against `schema`. One repair retry on bad JSON."""
        body: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            },
        }
        key = self.s.llm_api_key.get_secret_value()
        for attempt in range(3):
            data, ms = await self._post(self.s.llm_base_url, key, "chat/completions", body)
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if not content:
                # Reasoning models can spend the whole budget thinking; give them room once.
                await self._record(ledger, purpose, model, data, ms, ok=False)
                body["max_tokens"] = max_tokens * 2
                continue
            try:
                parsed = schema.model_validate(extract_json(content))
            except (ValueError, ValidationError) as e:
                await self._record(ledger, purpose, model, data, ms, ok=False)
                body["messages"] = list(messages) + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"That was not valid JSON for the schema: {str(e)[:400]}. "
                                                "Reply with the JSON object only."},
                ]
                continue
            await self._record(ledger, purpose, model, data, ms)
            return parsed
        raise LLMError(f"{purpose}: no valid structured output from {model}")

    # ------------------------------------------------------------------ embeddings
    async def embed(self, texts: list[str], *, purpose: str, ledger: Ledger, batch: int = 64) -> list[list[float]]:
        base = self.s.embed_base_url or self.s.llm_base_url
        key = (self.s.embed_api_key or self.s.llm_api_key).get_secret_value()
        model = self.s.embedding_model

        async def one(chunk: list[str]) -> list[list[float]]:
            data, ms = await self._post(base, key, "embeddings", {"model": model, "input": chunk})
            await self._record(ledger, purpose, model, data, ms)
            rows = sorted(data["data"], key=lambda d: d["index"])
            vecs = [r["embedding"] for r in rows]
            if len(vecs) != len(chunk) or any(len(v) != self.s.embedding_dim for v in vecs):
                raise LLMError(f"embedding shape mismatch: expected {len(chunk)}x{self.s.embedding_dim}")
            return vecs

        parts = await asyncio.gather(*(one(texts[i : i + batch]) for i in range(0, len(texts), batch)))
        return [v for p in parts for v in p]
