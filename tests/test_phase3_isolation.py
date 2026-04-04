"""
Fase 3 — data-isolatie: drafts en prompts per user.

Verifieert dat user B de data van user A niet kan zien of bewerken (IDOR).
"""

import pytest
from app.db import hash_password
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


def _make_user(test_db, email, password="testpass99"):
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (email, hash_password(password)),
    )
    test_db.commit()
    return test_db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

async def test_user_only_sees_own_drafts(authed_client, test_db):
    """Homepagina toont enkel eigen drafts."""
    uid_a = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()["id"]
    uid_b = _make_user(test_db, "b@example.com")

    test_db.execute(
        "INSERT INTO drafts (user_id, event_id, event_title, post_text, llm, provider) VALUES (?, ?, ?, ?, ?, ?)",
        (uid_a, "e1", "Event van A", "Post A", "groq", "collective"),
    )
    test_db.execute(
        "INSERT INTO drafts (user_id, event_id, event_title, post_text, llm, provider) VALUES (?, ?, ?, ?, ?, ?)",
        (uid_b, "e2", "Event van B", "Post B", "groq", "collective"),
    )
    test_db.commit()

    resp = await authed_client.get("/")
    assert "Event van A" in resp.text
    assert "Event van B" not in resp.text


async def test_user_cannot_read_other_users_draft(authed_client, test_db):
    """IDOR: draft van user B openen als user A → 404."""
    uid_b = _make_user(test_db, "b2@example.com")
    test_db.execute(
        "INSERT INTO drafts (user_id, event_id, event_title, post_text, llm, provider) VALUES (?, ?, ?, ?, ?, ?)",
        (uid_b, "eb", "Geheim event B", "Geheime post", "groq", "collective"),
    )
    test_db.commit()
    draft_id = test_db.execute("SELECT id FROM drafts WHERE event_id = 'eb'").fetchone()["id"]

    resp = await authed_client.get(f"/draft/{draft_id}")
    assert resp.status_code == 404


async def test_user_cannot_update_other_users_draft(authed_client, test_db):
    """IDOR: draft van user B overschrijven als user A → geen effect."""
    uid_b = _make_user(test_db, "b3@example.com")
    test_db.execute(
        "INSERT INTO drafts (user_id, event_id, event_title, post_text, llm, provider) VALUES (?, ?, ?, ?, ?, ?)",
        (uid_b, "ec", "Event C", "Origineel", "groq", "collective"),
    )
    test_db.commit()
    draft_id = test_db.execute("SELECT id FROM drafts WHERE event_id = 'ec'").fetchone()["id"]

    await authed_client.post(f"/draft/{draft_id}", data={"post_text": "Gehackt!"}, follow_redirects=True)

    unchanged = test_db.execute("SELECT post_text FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert unchanged["post_text"] == "Origineel"


async def test_user_cannot_delete_other_users_draft(authed_client, test_db):
    """IDOR: draft van user B verwijderen als user A → draft blijft bestaan."""
    uid_b = _make_user(test_db, "b4@example.com")
    test_db.execute(
        "INSERT INTO drafts (user_id, event_id, event_title, post_text, llm, provider) VALUES (?, ?, ?, ?, ?, ?)",
        (uid_b, "ed", "Event D", "Mag niet weg", "groq", "collective"),
    )
    test_db.commit()
    draft_id = test_db.execute("SELECT id FROM drafts WHERE event_id = 'ed'").fetchone()["id"]

    await authed_client.post(f"/draft/{draft_id}/delete", follow_redirects=True)

    still_there = test_db.execute("SELECT id FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert still_there is not None


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

async def test_user_only_sees_own_prompts(authed_client, test_db):
    """Prompts pagina toont enkel eigen stijlen."""
    uid_a = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()["id"]
    uid_b = _make_user(test_db, "pb@example.com")

    test_db.execute(
        "INSERT INTO prompts (user_id, title, prompt_text) VALUES (?, ?, ?)",
        (uid_a, "Stijl van A", "Schrijf als A."),
    )
    test_db.execute(
        "INSERT INTO prompts (user_id, title, prompt_text) VALUES (?, ?, ?)",
        (uid_b, "Stijl van B", "Schrijf als B."),
    )
    test_db.commit()

    resp = await authed_client.get("/prompts")
    assert "Stijl van A" in resp.text
    assert "Stijl van B" not in resp.text


async def test_user_cannot_delete_other_users_prompt(authed_client, test_db):
    """IDOR: prompt van user B verwijderen als user A → prompt blijft bestaan."""
    uid_b = _make_user(test_db, "pd@example.com")
    test_db.execute(
        "INSERT INTO prompts (user_id, title, prompt_text) VALUES (?, ?, ?)",
        (uid_b, "B's stijl", "Niet te verwijderen."),
    )
    test_db.commit()
    prompt_id = test_db.execute("SELECT id FROM prompts WHERE title = \"B's stijl\"").fetchone()["id"]

    await authed_client.post(f"/prompts/{prompt_id}/delete", follow_redirects=True)

    still_there = test_db.execute("SELECT id FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
    assert still_there is not None
