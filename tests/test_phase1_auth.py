"""
Fase 1 auth tests — login, register, logout, redirect-bescherming.
"""

import pytest
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


# ---------------------------------------------------------------------------
# Login pagina
# ---------------------------------------------------------------------------

async def test_login_page_loads(app_client):
    resp = await app_client.get("/login")
    assert resp.status_code == 200
    assert "Inloggen" in resp.text


async def test_register_page_loads(app_client):
    resp = await app_client.get("/register")
    assert resp.status_code == 200
    assert "Account aanmaken" in resp.text


# ---------------------------------------------------------------------------
# Unauthenticated redirect
# ---------------------------------------------------------------------------

async def test_homepage_redirects_when_not_logged_in(app_client):
    resp = await app_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


async def test_drafts_redirect_when_not_logged_in(app_client):
    resp = await app_client.get("/draft/1", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


async def test_prompts_redirect_when_not_logged_in(app_client):
    resp = await app_client.get("/prompts", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


async def test_settings_redirect_when_not_logged_in(app_client):
    resp = await app_client.get("/settings", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


# ---------------------------------------------------------------------------
# Registreren
# ---------------------------------------------------------------------------

async def test_register_creates_user_and_logs_in(app_client, test_db):
    resp = await app_client.post(
        "/register",
        data={"email": "nieuw@example.com", "password": "geheim123", "password2": "geheim123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    user = test_db.execute("SELECT * FROM users WHERE email = 'nieuw@example.com'").fetchone()
    assert user is not None
    assert user["password_hash"] != "geheim123"  # moet gehasht zijn


async def test_register_rejects_short_password(app_client):
    resp = await app_client.post(
        "/register",
        data={"email": "kort@example.com", "password": "abc", "password2": "abc"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "8 tekens" in resp.text


async def test_register_rejects_mismatched_passwords(app_client):
    resp = await app_client.post(
        "/register",
        data={"email": "mis@example.com", "password": "wachtwoord1", "password2": "wachtwoord2"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "overeen" in resp.text


async def test_register_rejects_duplicate_email(app_client, test_db):
    # Eerste registratie
    await app_client.post(
        "/register",
        data={"email": "dubbel@example.com", "password": "wachtwoord1", "password2": "wachtwoord1"},
    )
    # Tweede keer met hetzelfde e-mail
    resp = await app_client.post(
        "/register",
        data={"email": "dubbel@example.com", "password": "wachtwoord2", "password2": "wachtwoord2"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "al in gebruik" in resp.text


# ---------------------------------------------------------------------------
# Inloggen
# ---------------------------------------------------------------------------

async def test_login_correct_credentials(app_client, test_db):
    # Maak eerst een user aan
    await app_client.post(
        "/register",
        data={"email": TEST_EMAIL, "password": TEST_PASSWORD, "password2": TEST_PASSWORD},
    )
    # Log uit (sessie wissen door nieuw client gedrag — registratie logt al in)
    await app_client.post("/logout")

    # Nu opnieuw inloggen
    resp = await app_client.post(
        "/login",
        data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


async def test_login_wrong_password(app_client, test_db):
    await app_client.post(
        "/register",
        data={"email": "fout@example.com", "password": "juistwachtwoord", "password2": "juistwachtwoord"},
    )
    await app_client.post("/logout")

    resp = await app_client.post(
        "/login",
        data={"email": "fout@example.com", "password": "foutpassword"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert "Ongeldig" in resp.text


async def test_login_unknown_email(app_client):
    resp = await app_client.post(
        "/login",
        data={"email": "bestaat_niet@example.com", "password": "whatever"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Uitloggen
# ---------------------------------------------------------------------------

async def test_logout_clears_session(authed_client):
    # Ingelogde client kan homepage bereiken
    resp = await authed_client.get("/", follow_redirects=False)
    assert resp.status_code == 200

    # Na uitloggen wordt doorgestuurd naar login
    await authed_client.post("/logout")
    resp = await authed_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


# ---------------------------------------------------------------------------
# Na login toegang tot beschermde pagina's
# ---------------------------------------------------------------------------

async def test_logged_in_user_can_access_homepage(authed_client):
    resp = await authed_client.get("/")
    assert resp.status_code == 200


async def test_logged_in_user_sees_email_in_nav(authed_client):
    resp = await authed_client.get("/")
    assert TEST_EMAIL in resp.text


async def test_login_page_redirects_if_already_logged_in(authed_client):
    resp = await authed_client.get("/login", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
