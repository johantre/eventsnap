"""
Fase 5 — Account management.

Verifieert dat:
- /account pagina toegankelijk is voor ingelogde gebruikers
- Wachtwoord wijzigen werkt (correct huidig wachtwoord vereist)
- E-mail wijzigen werkt (correct huidig wachtwoord vereist, geen duplicaat)
- Account verwijderen werkt (correct huidig wachtwoord vereist, alles weg)
- Alle POST-routes CSRF-beschermd zijn
"""

import pytest
from app.db import hash_password, verify_password
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


# ---------------------------------------------------------------------------
# Toegang
# ---------------------------------------------------------------------------

async def test_account_page_requires_login(app_client):
    """GET /account zonder sessie geeft redirect naar login."""
    resp = await app_client.get("/account", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


async def test_account_page_loads_for_logged_in_user(authed_client):
    """GET /account toont de accountpagina."""
    resp = await authed_client.get("/account")
    assert resp.status_code == 200
    assert "Account" in resp.text
    assert TEST_EMAIL in resp.text


# ---------------------------------------------------------------------------
# Wachtwoord wijzigen
# ---------------------------------------------------------------------------

async def test_change_password_requires_csrf(authed_client):
    """POST /account/change-password zonder CSRF geeft 403."""
    resp = await authed_client._c.post("/account/change-password", data={
        "current_password": TEST_PASSWORD,
        "new_password": "nieuwwachtwoord1",
        "new_password2": "nieuwwachtwoord1",
    })
    assert resp.status_code == 403


async def test_change_password_success(authed_client, test_db):
    """Wachtwoord succesvol wijzigen → redirect naar /account?pw_saved=1."""
    resp = await authed_client.post("/account/change-password", data={
        "current_password": TEST_PASSWORD,
        "new_password": "nieuwwachtwoord1",
        "new_password2": "nieuwwachtwoord1",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "pw_saved=1" in resp.headers["location"]

    # Verifieer dat het nieuwe wachtwoord in de DB staat
    user = test_db.execute("SELECT password_hash FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()
    assert verify_password("nieuwwachtwoord1", user["password_hash"])


async def test_change_password_wrong_current(authed_client):
    """Fout huidig wachtwoord → 400 met foutmelding."""
    resp = await authed_client.post("/account/change-password", data={
        "current_password": "foutpassword",
        "new_password": "nieuwwachtwoord1",
        "new_password2": "nieuwwachtwoord1",
    })
    assert resp.status_code == 400
    assert "onjuist" in resp.text


async def test_change_password_mismatch(authed_client):
    """Nieuwe wachtwoorden komen niet overeen → 400."""
    resp = await authed_client.post("/account/change-password", data={
        "current_password": TEST_PASSWORD,
        "new_password": "nieuwwachtwoord1",
        "new_password2": "anderewachtwoord",
    })
    assert resp.status_code == 400
    assert "overeen" in resp.text


async def test_change_password_too_short(authed_client):
    """Nieuw wachtwoord te kort → 400."""
    resp = await authed_client.post("/account/change-password", data={
        "current_password": TEST_PASSWORD,
        "new_password": "kort",
        "new_password2": "kort",
    })
    assert resp.status_code == 400
    assert "8 tekens" in resp.text


# ---------------------------------------------------------------------------
# E-mail wijzigen
# ---------------------------------------------------------------------------

async def test_change_email_requires_csrf(authed_client):
    """POST /account/change-email zonder CSRF geeft 403."""
    resp = await authed_client._c.post("/account/change-email", data={
        "current_password": TEST_PASSWORD,
        "new_email": "nieuw@example.com",
    })
    assert resp.status_code == 403


async def test_change_email_success(authed_client, test_db):
    """E-mail succesvol wijzigen → redirect naar /account?email_saved=1."""
    resp = await authed_client.post("/account/change-email", data={
        "current_password": TEST_PASSWORD,
        "new_email": "nieuw@example.com",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "email_saved=1" in resp.headers["location"]

    user = test_db.execute("SELECT email FROM users WHERE email = ?", ("nieuw@example.com",)).fetchone()
    assert user is not None


async def test_change_email_wrong_password(authed_client):
    """Fout wachtwoord bij e-mail wijzigen → 400."""
    resp = await authed_client.post("/account/change-email", data={
        "current_password": "foutpassword",
        "new_email": "nieuw@example.com",
    })
    assert resp.status_code == 400
    assert "onjuist" in resp.text


async def test_change_email_same_email(authed_client):
    """Zelfde e-mail als huidig → 400."""
    resp = await authed_client.post("/account/change-email", data={
        "current_password": TEST_PASSWORD,
        "new_email": TEST_EMAIL,
    })
    assert resp.status_code == 400
    assert "huidige" in resp.text


async def test_change_email_duplicate(authed_client, test_db):
    """E-mail al in gebruik door ander account → 400."""
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        ("bezet@example.com", hash_password("wachtwoord123")),
    )
    test_db.commit()

    resp = await authed_client.post("/account/change-email", data={
        "current_password": TEST_PASSWORD,
        "new_email": "bezet@example.com",
    })
    assert resp.status_code == 400
    assert "gebruik" in resp.text


# ---------------------------------------------------------------------------
# Account verwijderen
# ---------------------------------------------------------------------------

async def test_delete_account_requires_csrf(authed_client):
    """POST /account/delete zonder CSRF geeft 403."""
    resp = await authed_client._c.post("/account/delete", data={
        "current_password": TEST_PASSWORD,
    })
    assert resp.status_code == 403


async def test_delete_account_wrong_password(authed_client):
    """Fout wachtwoord bij verwijderen → 400, account blijft bestaan."""
    resp = await authed_client.post("/account/delete", data={
        "current_password": "foutpassword",
    })
    assert resp.status_code == 400
    assert "onjuist" in resp.text


async def test_delete_account_success(authed_client, test_db):
    """Account verwijderen → redirect naar /login?deleted=1, user weg uit DB."""
    # Voeg ook wat data toe om te verifiëren dat die ook weg is
    user = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()
    uid = user["id"]
    test_db.execute("INSERT INTO drafts (user_id, event_id, event_title, post_text) VALUES (?, ?, ?, ?)",
                    (uid, "ev1", "Test Event", "Post tekst"))
    test_db.execute("INSERT INTO prompts (user_id, title, prompt_text) VALUES (?, ?, ?)",
                    (uid, "Stijl", "Prompt tekst"))
    test_db.commit()

    resp = await authed_client.post("/account/delete", data={
        "current_password": TEST_PASSWORD,
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "deleted=1" in resp.headers["location"]

    # User weg
    assert test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone() is None
    # Data weg
    assert test_db.execute("SELECT id FROM drafts WHERE user_id = ?", (uid,)).fetchone() is None
    assert test_db.execute("SELECT id FROM prompts WHERE user_id = ?", (uid,)).fetchone() is None


async def test_account_inaccessible_after_delete(authed_client, test_db):
    """Na verwijderen is sessie leeg → /account redirect naar login."""
    await authed_client.post("/account/delete", data={
        "current_password": TEST_PASSWORD,
    }, follow_redirects=True)

    resp = await authed_client.get("/account", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]
