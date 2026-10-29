import asyncio
import os
import secrets
import sys
import time

import httpx
import pytest

if sys.platform == "win32":  # psycopg's async driver needs the selector loop on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ.setdefault("WORKER_ENABLED", "true")


def _stack_up() -> bool:
    from app.config import get_settings

    try:
        return httpx.get(f"{get_settings().supabase_url}/auth/v1/health", timeout=2,
                         headers={"apikey": get_settings().supabase_publishable_key}).status_code == 200
    except httpx.HTTPError:
        return False


def pytest_collection_modifyitems(config, items):
    if any("integration" in i.keywords for i in items) and not _stack_up():
        skip = pytest.mark.skip(reason="local Supabase stack not running (npx supabase start)")
        for i in items:
            if "integration" in i.keywords:
                i.add_marker(skip)


def make_user() -> tuple[str, str]:
    """Create a confirmed throwaway user on the LOCAL stack and return (user id, access token)."""
    from app.config import get_settings

    s = get_settings()
    assert "127.0.0.1" in s.supabase_url or "localhost" in s.supabase_url, "test users are only made locally"
    email, password = f"test-{secrets.token_hex(6)}@example.test", secrets.token_urlsafe(18)
    admin = {"apikey": s.supabase_secret_key.get_secret_value(),
             "Authorization": f"Bearer {s.supabase_secret_key.get_secret_value()}"}
    r = httpx.post(f"{s.supabase_url}/auth/v1/admin/users", headers=admin,
                   json={"email": email, "password": password, "email_confirm": True})
    r.raise_for_status()
    r = httpx.post(f"{s.supabase_url}/auth/v1/token?grant_type=password",
                   headers={"apikey": s.supabase_publishable_key}, json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["user"]["id"], r.json()["access_token"]


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    from .fakes import FakeLLM

    with TestClient(app) as c:
        fake = FakeLLM()
        app.state.llm = fake
        app.state.worker.llm = fake
        c.fake = fake
        yield c


@pytest.fixture(scope="session")
def alice():
    return make_user()


@pytest.fixture(scope="session")
def bob():
    return make_user()


def auth(user) -> dict:
    return {"Authorization": f"Bearer {user[1]}"}


def wait_ready(client, user, doc_id, timeout=30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = client.get(f"/api/documents/{doc_id}", headers=auth(user)).json()
        if d["status"] in ("ready", "failed"):
            return d
        time.sleep(0.2)
    raise AssertionError(f"document {doc_id} not indexed in {timeout}s: {d}")
