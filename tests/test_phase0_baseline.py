"""
Fase 0 baseline tests — huidige happy paths vastleggen.

Deze tests moeten GROEN zijn voor we aan Fase 1 beginnen,
en na elke fase opnieuw groen blijven (regressiecheck).
"""

import pytest
from tests.conftest import TEST_EMAIL


def _uid(test_db):
    """Haal de user_id van de testgebruiker op."""
    return test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()["id"]


# ---------------------------------------------------------------------------
# Homepage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_homepage_loads(authed_client):
    resp = await authed_client.get("/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_homepage_contains_expected_elements(authed_client):
    resp = await authed_client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert "EventSnap" in body or "event" in body.lower()


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_draft_not_found_returns_error(authed_client):
    resp = await authed_client.get("/draft/99999")
    assert resp.status_code in (404, 500)


@pytest.mark.asyncio
async def test_draft_save_and_retrieve(authed_client, test_db):
    uid = _uid(test_db)
    test_db.execute(
        "INSERT INTO drafts (user_id, event_id, event_title, post_text, llm, provider) VALUES (?, ?, ?, ?, ?, ?)",
        (uid, "evt_1", "Test Event", "Dit is een test post.", "groq", "collective"),
    )
    test_db.commit()

    draft_id = test_db.execute("SELECT id FROM drafts WHERE event_id = 'evt_1'").fetchone()["id"]
    resp = await authed_client.get(f"/draft/{draft_id}")
    assert resp.status_code == 200
    assert "Test Event" in resp.text


@pytest.mark.asyncio
async def test_draft_text_update(authed_client, test_db):
    uid = _uid(test_db)
    test_db.execute(
        "INSERT INTO drafts (user_id, event_id, event_title, post_text, llm, provider) VALUES (?, ?, ?, ?, ?, ?)",
        (uid, "evt_2", "Update Test", "Originele tekst.", "groq", "collective"),
    )
    test_db.commit()
    draft_id = test_db.execute("SELECT id FROM drafts WHERE event_id = 'evt_2'").fetchone()["id"]

    resp = await authed_client.post(
        f"/draft/{draft_id}",
        data={"post_text": "Aangepaste tekst."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    updated = test_db.execute("SELECT post_text FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert updated["post_text"] == "Aangepaste tekst."


@pytest.mark.asyncio
async def test_draft_delete(authed_client, test_db):
    uid = _uid(test_db)
    test_db.execute(
        "INSERT INTO drafts (user_id, event_id, event_title, post_text, llm, provider) VALUES (?, ?, ?, ?, ?, ?)",
        (uid, "evt_3", "Te verwijderen", "Weg ermee.", "groq", "collective"),
    )
    test_db.commit()
    draft_id = test_db.execute("SELECT id FROM drafts WHERE event_id = 'evt_3'").fetchone()["id"]

    resp = await authed_client.post(f"/draft/{draft_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert test_db.execute("SELECT id FROM drafts WHERE id = ?", (draft_id,)).fetchone() is None


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prompts_page_loads(authed_client):
    resp = await authed_client.get("/prompts")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_create_prompt(authed_client, test_db):
    resp = await authed_client.post(
        "/prompts",
        data={"title": "Mijn stijl", "prompt_text": "Schrijf in het Nederlands."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    row = test_db.execute("SELECT * FROM prompts WHERE title = 'Mijn stijl'").fetchone()
    assert row is not None
    assert row["prompt_text"] == "Schrijf in het Nederlands."


@pytest.mark.asyncio
async def test_delete_prompt(authed_client, test_db):
    uid = _uid(test_db)
    test_db.execute(
        "INSERT INTO prompts (user_id, title, prompt_text) VALUES (?, ?, ?)",
        (uid, "Weg", "Te verwijderen prompt."),
    )
    test_db.commit()
    prompt_id = test_db.execute("SELECT id FROM prompts WHERE title = 'Weg'").fetchone()["id"]

    resp = await authed_client.post(f"/prompts/{prompt_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert test_db.execute("SELECT id FROM prompts WHERE id = ?", (prompt_id,)).fetchone() is None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_settings_page_loads(authed_client):
    resp = await authed_client.get("/settings")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_settings_save_active_llm(authed_client, test_db):
    resp = await authed_client.post(
        "/settings",
        data={"active_llm": "groq", "system_prompt": "Test prompt."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    row = test_db.execute("SELECT user_id, value FROM settings WHERE key = 'active_llm'").fetchone()
    assert row is not None
    assert row["value"] == "groq"
    assert row["user_id"] is not None
