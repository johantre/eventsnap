"""
Fase 2 — settings per user.

Verifieert dat instellingen volledig geïsoleerd zijn per gebruiker:
user A z'n provider config heeft geen invloed op user B.
"""

import pytest
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _register_and_login(client, email, password="testpass99"):
    await client.post(
        "/register",
        data={"email": email, "password": password, "password2": password},
        follow_redirects=True,
    )
    return client


# ---------------------------------------------------------------------------
# Settings worden opgeslagen met de juiste user_id
# ---------------------------------------------------------------------------

async def test_settings_saved_with_user_id(authed_client, test_db):
    """Opgeslagen settings hebben de user_id van de ingelogde user."""
    await authed_client.post(
        "/settings",
        data={"active_llm": "groq", "system_prompt": "Test."},
        follow_redirects=True,
    )
    user = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()
    row = test_db.execute(
        "SELECT value FROM settings WHERE key = 'active_llm' AND user_id = ?",
        (user["id"],),
    ).fetchone()
    assert row is not None
    assert row["value"] == "groq"


async def test_settings_not_visible_to_other_user(authed_client, test_db):
    """Settings van user A zijn niet zichtbaar voor user B."""
    # User A (authed_client) slaat een system_prompt op
    await authed_client.post(
        "/settings",
        data={"active_llm": "groq", "system_prompt": "Prompt van user A."},
        follow_redirects=True,
    )

    user_a = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()

    # Maak user B rechtstreeks in de DB aan
    from app.db import hash_password
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        ("userb@example.com", hash_password("passb9999")),
    )
    test_db.commit()
    user_b = test_db.execute("SELECT id FROM users WHERE email = 'userb@example.com'").fetchone()

    # User B heeft geen settings
    row_b = test_db.execute(
        "SELECT value FROM settings WHERE key = 'system_prompt' AND user_id = ?",
        (user_b["id"],),
    ).fetchone()
    assert row_b is None

    # User A's settings zijn ongewijzigd
    row_a = test_db.execute(
        "SELECT value FROM settings WHERE key = 'system_prompt' AND user_id = ?",
        (user_a["id"],),
    ).fetchone()
    assert row_a is not None
    assert row_a["value"] == "Prompt van user A."


async def test_two_users_can_have_different_active_llm(test_db):
    """Twee users kunnen elk een ander actief LLM hebben."""
    from app.db import hash_password, set_setting

    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?), (?, ?)",
        ("alice@x.com", hash_password("alicepass1"), "bob@x.com", hash_password("bobpass11")),
    )
    test_db.commit()
    alice = test_db.execute("SELECT id FROM users WHERE email = 'alice@x.com'").fetchone()
    bob   = test_db.execute("SELECT id FROM users WHERE email = 'bob@x.com'").fetchone()

    # Schrijf via de wrapper (die de _NoCloseConn niet gebruikt — rechtstreeks op test_db)
    test_db.execute(
        "INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?)",
        (alice["id"], "active_llm", "groq"),
    )
    test_db.execute(
        "INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?)",
        (bob["id"], "active_llm", "claude"),
    )
    test_db.commit()

    alice_llm = test_db.execute(
        "SELECT value FROM settings WHERE user_id = ? AND key = 'active_llm'", (alice["id"],)
    ).fetchone()["value"]
    bob_llm = test_db.execute(
        "SELECT value FROM settings WHERE user_id = ? AND key = 'active_llm'", (bob["id"],)
    ).fetchone()["value"]

    assert alice_llm == "groq"
    assert bob_llm   == "claude"
    assert alice_llm != bob_llm


# ---------------------------------------------------------------------------
# Provider config per user
# ---------------------------------------------------------------------------

async def test_provider_config_saved_per_user(authed_client, test_db):
    """Provider instellingen worden opgeslagen onder de juiste user_id."""
    await authed_client.post(
        "/settings",
        data={
            "active_llm": "groq",
            "collective_url":   "https://mijn.odoo.com",
            "collective_email": "ik@bedrijf.be",
            "collective_password": "geheim123",
        },
        follow_redirects=True,
    )
    user = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()

    for key, expected in [
        ("collective_url",   "https://mijn.odoo.com"),
        ("collective_email", "ik@bedrijf.be"),
    ]:
        row = test_db.execute(
            "SELECT value FROM settings WHERE user_id = ? AND key = ?",
            (user["id"], key),
        ).fetchone()
        assert row is not None, f"Setting '{key}' niet gevonden"
        assert row["value"] == expected


async def test_no_global_settings_remain(test_db):
    """Er mogen geen settings in de DB staan zonder user_id."""
    # Zet een setting zonder user_id zou moeten falen door de NOT NULL constraint
    import sqlite3
    with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
        test_db.execute("INSERT INTO settings (key, value) VALUES ('orphan', 'waarde')")
        test_db.commit()
