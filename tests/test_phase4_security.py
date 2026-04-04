"""
Fase 4 — CSRF-beveiliging en rate limiting.

Verifieert dat:
- POST-routes een geldig CSRF-token vereisen
- /login rate limiting activeert na 5 mislukte pogingen
- Wachtwoordvelden een show/hide-toggle hebben
"""

import pytest
from app.db import hash_password
from tests.conftest import TEST_EMAIL, TEST_PASSWORD, _extract_csrf


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

async def test_post_without_csrf_is_rejected(app_client):
    """POST zonder CSRF-token geeft 403."""
    resp = await app_client._c.post("/login", data={
        "email": "x@x.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 403


async def test_post_with_wrong_csrf_is_rejected(app_client):
    """POST met verkeerde CSRF-token geeft 403."""
    resp = await app_client._c.post("/login", data={
        "email": "x@x.com",
        "password": "wrongpassword",
        "_csrf_token": "deadbeef" * 8,
    })
    assert resp.status_code == 403


async def test_login_with_valid_csrf_succeeds(app_client, test_db):
    """POST /login met correct CSRF-token wordt verwerkt (niet afgewezen)."""
    # Registreer een gebruiker direct in de DB
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD)),
    )
    test_db.commit()

    resp = await app_client.post("/login", data={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
    }, follow_redirects=False)
    # Succesvol inloggen → redirect naar homepage (303)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


async def test_logout_without_csrf_is_rejected(authed_client):
    """POST /logout zonder CSRF-token geeft 403."""
    resp = await authed_client._c.post("/logout")
    assert resp.status_code == 403


async def test_logout_with_csrf_works(authed_client):
    """POST /logout met CSRF-token geeft redirect naar login."""
    resp = await authed_client.post("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


async def test_register_without_csrf_is_rejected(app_client):
    """POST /register zonder CSRF-token geeft 403."""
    resp = await app_client._c.post("/register", data={
        "email": "new@example.com",
        "password": "validpass1",
        "password2": "validpass1",
    })
    assert resp.status_code == 403


async def test_settings_post_without_csrf_is_rejected(authed_client):
    """POST /settings zonder CSRF-token geeft 403."""
    resp = await authed_client._c.post("/settings", data={"active_llm": "groq"})
    assert resp.status_code == 403


async def test_csrf_token_present_in_login_page(app_client):
    """Login-pagina bevat een verborgen CSRF-token input."""
    resp = await app_client.get("/login")
    assert '_csrf_token' in resp.text
    assert _extract_csrf(resp.text) != ""


async def test_csrf_token_present_in_register_page(app_client):
    """Register-pagina bevat een verborgen CSRF-token input."""
    resp = await app_client.get("/register")
    assert '_csrf_token' in resp.text


async def test_csrf_token_present_in_settings_page(authed_client):
    """Settings-pagina bevat verborgen CSRF-token inputs."""
    resp = await authed_client.get("/settings")
    assert '_csrf_token' in resp.text


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

async def test_rate_limit_triggers_after_5_failures(app_client, test_db):
    """Na 5 mislukte inlogpogingen komt een 429-foutmelding."""
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD)),
    )
    test_db.commit()

    for _ in range(5):
        await app_client.post("/login", data={
            "email": TEST_EMAIL,
            "password": "foutpassword",
        })

    resp = await app_client.post("/login", data={
        "email": TEST_EMAIL,
        "password": "foutpassword",
    })
    assert resp.status_code == 429
    assert "Te veel" in resp.text


async def test_rate_limit_resets_on_success(app_client, test_db):
    """Na een geslaagde login wordt de pogingen-teller gereset."""
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD)),
    )
    test_db.commit()

    # 4 mislukte pogingen
    for _ in range(4):
        await app_client.post("/login", data={
            "email": TEST_EMAIL,
            "password": "fout",
        })

    # Geslaagde login → teller gereset
    await app_client.post("/login", data={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
    }, follow_redirects=True)

    # Nu opnieuw 5 mislukte pogingen — mag nog geen 429 geven
    for _ in range(5):
        resp = await app_client.post("/login", data={
            "email": TEST_EMAIL,
            "password": "fout",
        })

    # De 6e poging ná de reset geeft pas 429
    resp = await app_client.post("/login", data={
        "email": TEST_EMAIL,
        "password": "fout",
    })
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Show/hide password toggle
# ---------------------------------------------------------------------------

async def test_password_toggle_in_login_page(app_client):
    """Login-pagina heeft een show/hide-knop bij het wachtwoordveld."""
    resp = await app_client.get("/login")
    assert 'pw-toggle' in resp.text
    assert 'pw-wrap' in resp.text


async def test_password_toggle_in_register_page(app_client):
    """Register-pagina heeft show/hide-knoppen bij de wachtwoordvelden."""
    resp = await app_client.get("/register")
    assert resp.text.count('pw-toggle') >= 2
