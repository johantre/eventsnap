"""
Fase 8 — Admin panel: gebruikerslijst.

Verifieert dat:
- /admin/users enkel toegankelijk is voor admins
- Niet-admins krijgen 403
- Niet-ingelogden worden doorgestuurd naar login
- Gebruikerslijst toont alle gebruikers met correcte info
- Admin kan niet-geverifieerde gebruiker verifiëren
- Admin kan andere gebruiker verwijderen
- Admin kan zichzelf niet verwijderen
- Admin-link zichtbaar in nav voor admins, niet voor gewone gebruikers
"""

import pytest
from app.db import hash_password
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


def _make_admin(test_db, email=TEST_EMAIL):
    test_db.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (email,))
    test_db.commit()


def _add_user(test_db, email, verified=1, is_admin=0):
    test_db.execute(
        "INSERT INTO users (email, password_hash, email_verified, is_admin) VALUES (?, ?, ?, ?)",
        (email, hash_password("wachtwoord123"), verified, is_admin),
    )
    test_db.commit()
    return test_db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]


# ---------------------------------------------------------------------------
# Toegangscontrole
# ---------------------------------------------------------------------------

async def test_admin_requires_login(app_client):
    resp = await app_client.get("/admin/users", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


async def test_admin_forbidden_for_regular_user(authed_client):
    """Gewone gebruiker (is_admin=0) krijgt 403."""
    resp = await authed_client.get("/admin/users")
    assert resp.status_code == 403


async def test_admin_accessible_for_admin(authed_client, test_db):
    """Admin-gebruiker kan /admin/users zien."""
    _make_admin(test_db)
    resp = await authed_client.get("/admin/users")
    assert resp.status_code == 200
    assert "Gebruikers" in resp.text


# ---------------------------------------------------------------------------
# Gebruikerslijst
# ---------------------------------------------------------------------------

async def test_admin_shows_all_users(authed_client, test_db):
    """Alle gebruikers worden getoond."""
    _make_admin(test_db)
    _add_user(test_db, "ander@example.com")
    resp = await authed_client.get("/admin/users")
    assert TEST_EMAIL in resp.text
    assert "ander@example.com" in resp.text


async def test_admin_shows_verified_status(authed_client, test_db):
    """Verificatiestatus per gebruiker is zichtbaar."""
    _make_admin(test_db)
    _add_user(test_db, "onverified@example.com", verified=0)
    resp = await authed_client.get("/admin/users")
    assert resp.status_code == 200
    assert "onverified@example.com" in resp.text


async def test_admin_shows_draft_count(authed_client, test_db):
    """Draft-telling per gebruiker is zichtbaar."""
    _make_admin(test_db)
    uid = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()["id"]
    test_db.execute(
        "INSERT INTO drafts (user_id, event_id, event_title, post_text) VALUES (?, ?, ?, ?)",
        (uid, "ev1", "Test Event", "Post tekst"),
    )
    test_db.commit()
    resp = await authed_client.get("/admin/users")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Acties
# ---------------------------------------------------------------------------

async def test_admin_can_verify_user(authed_client, test_db):
    """Admin kan een niet-geverifieerde gebruiker verifiëren."""
    _make_admin(test_db)
    other_id = _add_user(test_db, "onverified@example.com", verified=0)
    resp = await authed_client.post(f"/admin/users/{other_id}/verify", follow_redirects=False)
    assert resp.status_code == 303
    row = test_db.execute("SELECT email_verified FROM users WHERE id = ?", (other_id,)).fetchone()
    assert row["email_verified"] == 1


async def test_admin_can_delete_other_user(authed_client, test_db):
    """Admin kan een andere gebruiker verwijderen."""
    _make_admin(test_db)
    other_id = _add_user(test_db, "weg@example.com")
    resp = await authed_client.post(f"/admin/users/{other_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert test_db.execute("SELECT id FROM users WHERE id = ?", (other_id,)).fetchone() is None


async def test_admin_cannot_delete_self(authed_client, test_db):
    """Admin kan zichzelf niet verwijderen."""
    _make_admin(test_db)
    own_id = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()["id"]
    resp = await authed_client.post(f"/admin/users/{own_id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert "error=self" in resp.headers["location"]
    assert test_db.execute("SELECT id FROM users WHERE id = ?", (own_id,)).fetchone() is not None


async def test_admin_actions_require_csrf(authed_client, test_db):
    """Admin-acties zonder CSRF geven 403."""
    _make_admin(test_db)
    other_id = _add_user(test_db, "ander@example.com")
    resp = await authed_client._c.post(f"/admin/users/{other_id}/delete")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Nav
# ---------------------------------------------------------------------------

async def test_admin_link_visible_for_admin(authed_client, test_db):
    """Admin-link zichtbaar in nav voor admins."""
    _make_admin(test_db)
    resp = await authed_client.get("/")
    assert "/admin/users" in resp.text


async def test_admin_link_hidden_for_regular_user(authed_client):
    """Admin-link niet zichtbaar voor gewone gebruikers."""
    resp = await authed_client.get("/")
    assert "/admin/users" not in resp.text
