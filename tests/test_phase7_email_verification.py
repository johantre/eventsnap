"""
Fase 7 — E-mailverificatie bij registratie.

Verifieert dat:
- Nieuwe gebruiker krijgt email_verified = 0 na registratie
- Verificatiemail wordt verstuurd bij registratie
- GET /verify-email met geldig token markeert account als verified
- GET /verify-email met ongeldig/verlopen token toont foutmelding
- Token is eenmalig
- Verificatiebanner zichtbaar zolang niet geverifieerd
- POST /resend-verification stuurt nieuwe mail
- Na verificatie is banner weg
"""

import time
import pytest
from unittest.mock import patch
from app.db import hash_password
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


# ---------------------------------------------------------------------------
# Registratie
# ---------------------------------------------------------------------------

async def test_new_user_is_unverified(app_client, test_db):
    """Nieuw geregistreerde gebruiker heeft email_verified = 0."""
    with patch("app.server.send_verification_email"):
        await app_client.post("/register", data={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        })
    user = test_db.execute("SELECT email_verified FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()
    assert user["email_verified"] == 0


async def test_registration_sends_verification_email(app_client, test_db):
    """Bij registratie wordt een verificatiemail verstuurd."""
    with patch("app.server.send_verification_email") as mock_send:
        await app_client.post("/register", data={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        })
    mock_send.assert_called_once()
    assert TEST_EMAIL in mock_send.call_args[0]


async def test_registration_creates_verification_token(app_client, test_db):
    """Bij registratie wordt een verificatie-token aangemaakt in de DB."""
    with patch("app.server.send_verification_email"):
        await app_client.post("/register", data={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        })
    row = test_db.execute("SELECT * FROM email_verification_tokens").fetchone()
    assert row is not None
    assert row["used"] == 0


# ---------------------------------------------------------------------------
# Verificatielink
# ---------------------------------------------------------------------------

def _insert_verification_token(test_db, token="vertoken", offset=86400, verified=0):
    test_db.execute(
        "INSERT INTO users (email, password_hash, email_verified) VALUES (?, ?, ?)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD), verified),
    )
    test_db.commit()
    user = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()
    expires = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + offset))
    test_db.execute(
        "INSERT INTO email_verification_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["id"], token, expires),
    )
    test_db.commit()
    return user["id"]


async def test_verify_email_valid_token(app_client, test_db):
    """Geldig token → account geverifieerd, redirect naar /?verified=1."""
    _insert_verification_token(test_db)
    resp = await app_client.get("/verify-email?token=vertoken", follow_redirects=False)
    assert resp.status_code == 303
    assert "verified=1" in resp.headers["location"]
    user = test_db.execute("SELECT email_verified FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()
    assert user["email_verified"] == 1


async def test_verify_email_invalid_token(app_client):
    """Ongeldig token → foutpagina."""
    resp = await app_client.get("/verify-email?token=ongeldig")
    assert resp.status_code == 200
    assert "ongeldig of verlopen" in resp.text


async def test_verify_email_expired_token(app_client, test_db):
    """Verlopen token → foutpagina."""
    _insert_verification_token(test_db, offset=-10)
    resp = await app_client.get("/verify-email?token=vertoken")
    assert "ongeldig of verlopen" in resp.text


async def test_verify_email_token_consumed(app_client, test_db):
    """Token is eenmalig — tweede gebruik geeft foutmelding."""
    _insert_verification_token(test_db)
    await app_client.get("/verify-email?token=vertoken")
    resp = await app_client.get("/verify-email?token=vertoken")
    assert "ongeldig of verlopen" in resp.text


# ---------------------------------------------------------------------------
# Verificatiebanner
# ---------------------------------------------------------------------------

async def test_unverified_user_sees_banner(authed_client):
    """Niet-geverifieerde gebruiker ziet de verificatiebanner op de homepage."""
    resp = await authed_client.get("/")
    assert "Bevestig je e-mailadres" in resp.text


async def test_verified_user_has_no_banner(authed_client, test_db):
    """Geverifieerde gebruiker ziet geen verificatiebanner."""
    test_db.execute("UPDATE users SET email_verified = 1")
    test_db.commit()
    resp = await authed_client.get("/")
    assert "Bevestig je e-mailadres" not in resp.text


async def test_verified_confirmation_on_homepage(authed_client):
    """Homepage toont bevestigingsmelding bij ?verified=1."""
    resp = await authed_client.get("/?verified=1")
    assert "bevestigd" in resp.text


# ---------------------------------------------------------------------------
# Resend verificatiemail
# ---------------------------------------------------------------------------

async def test_resend_verification_requires_csrf(authed_client):
    """POST /resend-verification zonder CSRF geeft 403."""
    resp = await authed_client._c.post("/resend-verification")
    assert resp.status_code == 403


async def test_resend_verification_sends_mail(authed_client, test_db):
    """POST /resend-verification stuurt een nieuwe verificatiemail."""
    with patch("app.server.send_verification_email") as mock_send:
        resp = await authed_client.post("/resend-verification", follow_redirects=False)
    assert resp.status_code == 303
    assert "resent=1" in resp.headers["location"]
    mock_send.assert_called_once()


async def test_resend_skipped_for_verified_user(authed_client, test_db):
    """Al geverifieerde gebruiker krijgt geen nieuwe mail."""
    test_db.execute("UPDATE users SET email_verified = 1")
    test_db.commit()
    with patch("app.server.send_verification_email") as mock_send:
        await authed_client.post("/resend-verification", follow_redirects=True)
    mock_send.assert_not_called()
