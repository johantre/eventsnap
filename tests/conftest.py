"""
Shared pytest fixtures voor EventSnap tests.

Elke test krijgt een verse in-memory SQLite DB zodat tests
elkaar nooit beïnvloeden en de echte drafts.db onaangeroerd blijft.
"""

import re
import pytest
import sqlite3
from unittest.mock import patch, MagicMock

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

import app.server  # noqa: F401 — ensures module is imported before mock_mail patches it


TEST_EMAIL = "test@example.com"
TEST_PASSWORD = "testpassword123"


@pytest.fixture(autouse=True)
def mock_mail():
    """Voorkom dat tests echte mails sturen via Mailgun."""
    with patch("app.server.send_verification_email", return_value=None), \
         patch("app.server.send_password_reset", return_value=None):
        yield


def _extract_csrf(html: str) -> str:
    """Parse _csrf_token value from a rendered HTML page."""
    m = re.search(r'name="_csrf_token" value="([a-f0-9]+)"', html)
    return m.group(1) if m else ""


class _CSRFClient:
    """
    Thin wrapper around httpx.AsyncClient that automatically
    includes the CSRF token in form POST requests.
    """
    def __init__(self, client: AsyncClient):
        self._c = client
        self._csrf = ""

    async def get(self, url, **kwargs):
        resp = await self._c.get(url, **kwargs)
        token = _extract_csrf(resp.text)
        if token:
            self._csrf = token
        return resp

    async def post(self, url, *, data=None, **kwargs):
        d = dict(data or {})
        d.setdefault("_csrf_token", self._csrf)
        return await self._c.post(url, data=d, **kwargs)


def make_test_db():
    """Maak een in-memory SQLite connectie met het volledige schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            totp_secret TEXT,
            email_verified INTEGER NOT NULL DEFAULT 0,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE settings (
            user_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (user_id, key)
        )
    """)
    conn.execute("""
        CREATE TABLE drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            event_title TEXT NOT NULL,
            event_date TEXT,
            post_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'draft',
            llm TEXT DEFAULT '',
            provider TEXT DEFAULT '',
            prompt_text TEXT DEFAULT '',
            generation_ms INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_type TEXT NOT NULL,
            properties TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            prompt_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE email_verification_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


class _NoCloseConn:
    """
    Wrapper rond een sqlite3.Connection die .close() negeert.
    De routes roepen conn.close() aan na elke query; in tests willen
    we dat de in-memory DB open blijft voor de hele testduur.
    """
    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass  # no-op

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture()
def test_db():
    """Geeft een verse in-memory DB terug. Wordt na elke test weggegooid."""
    conn = make_test_db()
    yield conn
    conn.close()


def _make_patched_app(test_db):
    """Helper: geef de FastAPI app terug met DB en providers gepatcht."""
    import app.db as db_module
    import app.server as server_module

    wrapped = _NoCloseConn(test_db)

    def fake_get_db():
        return wrapped

    return server_module.app, db_module, server_module, fake_get_db


@pytest_asyncio.fixture()
async def app_client(test_db):
    """
    Unauthenticated client — gebruikt voor auth-tests (login, register, redirect).
    """
    import app.db as db_module
    import app.server as server_module

    wrapped = _NoCloseConn(test_db)

    def fake_get_db():
        return wrapped

    with patch.object(db_module, "get_db", fake_get_db), \
         patch.object(server_module, "get_db", fake_get_db), \
         patch.object(server_module, "get_tickets_for_user", return_value=([], [])), \
         patch.object(server_module, "get_providers_for_user", return_value={}):

        async with AsyncClient(
            transport=ASGITransport(app=server_module.app),
            base_url="http://test",
        ) as raw_client:
            client = _CSRFClient(raw_client)
            await client.get("/login")   # seed CSRF token in session
            yield client


@pytest_asyncio.fixture()
async def authed_client(test_db):
    """
    Authenticated client — registreert een testgebruiker en logt in.
    Gebruikt voor alle functionele tests (homepage, drafts, prompts, settings).
    """
    import app.db as db_module
    import app.server as server_module

    wrapped = _NoCloseConn(test_db)

    def fake_get_db():
        return wrapped

    with patch.object(db_module, "get_db", fake_get_db), \
         patch.object(server_module, "get_db", fake_get_db), \
         patch.object(server_module, "get_tickets_for_user", return_value=([], [])), \
         patch.object(server_module, "get_providers_for_user", return_value={}):

        async with AsyncClient(
            transport=ASGITransport(app=server_module.app),
            base_url="http://test",
        ) as raw_client:
            client = _CSRFClient(raw_client)
            # GET register page to seed CSRF token, then POST with it
            await client.get("/register")
            await client.post(
                "/register",
                data={
                    "email": TEST_EMAIL,
                    "password": TEST_PASSWORD,
                    "password2": TEST_PASSWORD,
                },
                follow_redirects=True,
            )
            yield client
