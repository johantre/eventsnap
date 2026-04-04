"""
Fase 6 — Wachtwoord reset via e-mail.

Verifieert dat:
- /forgot-password pagina laadt en CSRF-beschermd is
- POST altijd dezelfde boodschap toont (ook bij onbekend e-mail)
- Reset token aangemaakt wordt voor bekende gebruiker
- /reset-password met geldig token werkt
- /reset-password met ongeldig/verlopen token geeft foutmelding
- Token is eenmalig (second use geeft invalid)
- Nieuw wachtwoord validatie werkt
- Na reset kan ingelogd worden met nieuw wachtwoord
"""

import time
import pytest
from unittest.mock import patch
from app.db import hash_password, verify_password
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


# ---------------------------------------------------------------------------
# Forgot password pagina
# ---------------------------------------------------------------------------

async def test_forgot_password_page_loads(app_client):
    resp = await app_client.get("/forgot-password")
    assert resp.status_code == 200
    assert "Wachtwoord vergeten" in resp.text


async def test_forgot_password_redirects_when_logged_in(authed_client):
    resp = await authed_client.get("/forgot-password", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


async def test_forgot_password_requires_csrf(app_client):
    resp = await app_client._c.post("/forgot-password", data={"email": TEST_EMAIL})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /forgot-password
# ---------------------------------------------------------------------------

async def test_forgot_password_unknown_email_shows_same_message(app_client):
    """Onbekend e-mail toont dezelfde boodschap — geen user enumeration."""
    with patch("app.mail.send_password_reset") as mock_send:
        resp = await app_client.post("/forgot-password", data={
            "email": "onbekend@example.com",
        })
    assert resp.status_code == 200
    assert "Als dit e-mailadres" in resp.text
    mock_send.assert_not_called()


async def test_forgot_password_known_email_sends_mail(app_client, test_db):
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD)),
    )
    test_db.commit()

    with patch("app.server.send_password_reset") as mock_send:
        resp = await app_client.post("/forgot-password", data={"email": TEST_EMAIL})

    assert resp.status_code == 200
    assert "Als dit e-mailadres" in resp.text
    mock_send.assert_called_once()
    assert TEST_EMAIL in mock_send.call_args[0]


async def test_forgot_password_creates_token_in_db(app_client, test_db):
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD)),
    )
    test_db.commit()

    with patch("app.server.send_password_reset"):
        await app_client.post("/forgot-password", data={"email": TEST_EMAIL})

    row = test_db.execute("SELECT * FROM password_reset_tokens").fetchone()
    assert row is not None
    assert row["used"] == 0


# ---------------------------------------------------------------------------
# GET /reset-password
# ---------------------------------------------------------------------------

async def test_reset_password_invalid_token(app_client):
    resp = await app_client.get("/reset-password?token=ongeldigtoken")
    assert resp.status_code == 200
    assert "ongeldig of verlopen" in resp.text


async def test_reset_password_valid_token_shows_form(app_client, test_db):
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD)),
    )
    test_db.commit()
    user = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()
    expires = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 3600))
    test_db.execute(
        "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["id"], "geldigtoken123", expires),
    )
    test_db.commit()

    resp = await app_client.get("/reset-password?token=geldigtoken123")
    assert resp.status_code == 200
    assert "Nieuw wachtwoord" in resp.text
    assert "ongeldig" not in resp.text


async def test_reset_password_expired_token(app_client, test_db):
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD)),
    )
    test_db.commit()
    user = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()
    expired = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 10))
    test_db.execute(
        "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["id"], "verlopentoken", expired),
    )
    test_db.commit()

    resp = await app_client.get("/reset-password?token=verlopentoken")
    assert "ongeldig of verlopen" in resp.text


# ---------------------------------------------------------------------------
# POST /reset-password
# ---------------------------------------------------------------------------

def _insert_token(test_db, token="testtoken", offset=3600):
    test_db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD)),
    )
    test_db.commit()
    user = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()
    expires = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + offset))
    test_db.execute(
        "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["id"], token, expires),
    )
    test_db.commit()
    return user["id"]


async def test_reset_password_success(app_client, test_db):
    _insert_token(test_db)
    resp = await app_client.post("/reset-password", data={
        "token": "testtoken",
        "new_password": "nieuwwachtwoord1",
        "new_password2": "nieuwwachtwoord1",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "reset=1" in resp.headers["location"]

    user = test_db.execute("SELECT password_hash FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()
    assert verify_password("nieuwwachtwoord1", user["password_hash"])


async def test_reset_password_token_consumed_after_use(app_client, test_db):
    _insert_token(test_db)
    await app_client.post("/reset-password", data={
        "token": "testtoken",
        "new_password": "nieuwwachtwoord1",
        "new_password2": "nieuwwachtwoord1",
    })
    # Tweede gebruik moet invalid zijn
    resp = await app_client.post("/reset-password", data={
        "token": "testtoken",
        "new_password": "nognieuwerr1",
        "new_password2": "nognieuwerr1",
    })
    assert "ongeldig of verlopen" in resp.text


async def test_reset_password_mismatch(app_client, test_db):
    _insert_token(test_db)
    resp = await app_client.post("/reset-password", data={
        "token": "testtoken",
        "new_password": "wachtwoord1",
        "new_password2": "anders123",
    })
    assert resp.status_code == 400
    assert "overeen" in resp.text


async def test_reset_password_too_short(app_client, test_db):
    _insert_token(test_db)
    resp = await app_client.post("/reset-password", data={
        "token": "testtoken",
        "new_password": "kort",
        "new_password2": "kort",
    })
    assert resp.status_code == 400
    assert "8 tekens" in resp.text


async def test_login_shows_success_after_reset(app_client):
    resp = await app_client.get("/login?reset=1")
    assert "Wachtwoord opgeslagen" in resp.text


async def test_forgot_password_link_on_login_page(app_client):
    resp = await app_client.get("/login")
    assert "Wachtwoord vergeten" in resp.text
    assert "/forgot-password" in resp.text
