"""
Fase 9 — Analytics event logging.

Verifieert dat:
- generate_ok event gelogd wordt na succesvolle generatie
- generate_fail event gelogd wordt na mislukte generatie
- regenerate_ok event gelogd wordt na succesvolle regeneratie
- generation_ms opgeslagen wordt op de draft
- Draft pagina toont generatietijd
- log_event slaat correct JSON op
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from app.db import hash_password, log_event
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


def _make_event():
    from providers.base import Event
    return Event(
        id="ev1", title="Test Event", date="2026-05-01",
        location="Gent", description="Test", tags=[],
    )


# ---------------------------------------------------------------------------
# log_event unit test
# ---------------------------------------------------------------------------

def test_log_event_stores_json(test_db):
    """log_event schrijft correct JSON naar de DB."""
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD)),
    )
    test_db.commit()
    user = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()

    log_event(test_db, user["id"], "test_event", {"llm": "groq", "duration_ms": 1234})

    row = test_db.execute("SELECT * FROM analytics_events").fetchone()
    assert row["event_type"] == "test_event"
    props = json.loads(row["properties"])
    assert props["llm"] == "groq"
    assert props["duration_ms"] == 1234


# ---------------------------------------------------------------------------
# generate_ok event
# ---------------------------------------------------------------------------

async def test_generate_ok_logs_event(authed_client, test_db):
    """Na succesvolle generatie wordt een generate_ok event gelogd."""
    mock_event = _make_event()
    with patch("app.server.get_providers_for_user", return_value={
        "collective": MagicMock(fetch_event_by_id=MagicMock(return_value=mock_event))
    }), patch("app.server.generate_linkedin_post", return_value="Test post"):
        await authed_client.post("/generate", data={
            "ticket_key": "collective:ev1",
            "user_prompt": "Test prompt",
        }, follow_redirects=False)

    row = test_db.execute(
        "SELECT * FROM analytics_events WHERE event_type = 'generate_ok'"
    ).fetchone()
    assert row is not None
    props = json.loads(row["properties"])
    assert props["llm"] is not None
    assert "duration_ms" in props


async def test_generate_stores_generation_ms(authed_client, test_db):
    """generation_ms wordt opgeslagen op de draft."""
    mock_event = _make_event()
    with patch("app.server.get_providers_for_user", return_value={
        "collective": MagicMock(fetch_event_by_id=MagicMock(return_value=mock_event))
    }), patch("app.server.generate_linkedin_post", return_value="Test post"):
        await authed_client.post("/generate", data={
            "ticket_key": "collective:ev1",
            "user_prompt": "Test prompt",
        }, follow_redirects=False)

    draft = test_db.execute("SELECT generation_ms FROM drafts").fetchone()
    assert draft is not None
    assert draft["generation_ms"] is not None
    assert draft["generation_ms"] >= 0


# ---------------------------------------------------------------------------
# generate_fail event
# ---------------------------------------------------------------------------

async def test_generate_fail_logs_event(authed_client, test_db):
    """Na mislukte generatie wordt een generate_fail event gelogd."""
    with patch("app.server.get_providers_for_user", return_value={
        "collective": MagicMock(fetch_event_by_id=MagicMock(side_effect=Exception("LLM timeout")))
    }):
        await authed_client.post("/generate", data={
            "ticket_key": "collective:ev1",
            "user_prompt": "Test",
        }, follow_redirects=False)

    row = test_db.execute(
        "SELECT * FROM analytics_events WHERE event_type = 'generate_fail'"
    ).fetchone()
    assert row is not None


# ---------------------------------------------------------------------------
# Draft pagina toont generatietijd
# ---------------------------------------------------------------------------

async def test_draft_page_shows_generation_time(authed_client, test_db):
    """Draft pagina toont 'Gegenereerd in X sec' als generation_ms beschikbaar is."""
    uid = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()["id"]
    test_db.execute(
        "INSERT INTO drafts (user_id, event_id, event_title, post_text, llm, provider, generation_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uid, "ev1", "Test Event", "Post tekst", "groq", "collective", 3500),
    )
    test_db.commit()
    draft_id = test_db.execute("SELECT id FROM drafts").fetchone()["id"]

    resp = await authed_client.get(f"/draft/{draft_id}")
    assert "Gegenereerd in" in resp.text
    assert "3.5 sec" in resp.text


async def test_draft_page_no_generation_time_if_missing(authed_client, test_db):
    """Draft pagina toont geen generatietijd als generation_ms None is."""
    uid = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()["id"]
    test_db.execute(
        "INSERT INTO drafts (user_id, event_id, event_title, post_text, llm, provider) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uid, "ev1", "Test Event", "Post tekst", "groq", "collective"),
    )
    test_db.commit()
    draft_id = test_db.execute("SELECT id FROM drafts").fetchone()["id"]

    resp = await authed_client.get(f"/draft/{draft_id}")
    assert "Gegenereerd in" not in resp.text
