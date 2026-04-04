"""
Fase 10 — Admin statistieken pagina.

Verifieert dat:
- /admin/stats enkel toegankelijk is voor admins
- Niet-admins krijgen 403
- Pagina toont KPI-kaartjes op /admin/users
- Pagina toont posts per dag sectie
- Pagina toont per-model tabel
- Pagina toont gebruikersactiviteit tabel
- Lege data toont 'geen data' boodschappen
"""

import json
import pytest
from app.db import hash_password, log_event
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


def _make_admin(test_db, email=TEST_EMAIL):
    test_db.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (email,))
    test_db.commit()


# ---------------------------------------------------------------------------
# Toegangscontrole
# ---------------------------------------------------------------------------

async def test_stats_requires_admin(authed_client):
    """Gewone gebruiker krijgt 403."""
    resp = await authed_client.get("/admin/stats")
    assert resp.status_code == 403


async def test_stats_requires_login(app_client):
    """Niet-ingelogde gebruiker wordt doorgestuurd."""
    resp = await app_client.get("/admin/stats", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Lege stats
# ---------------------------------------------------------------------------

async def test_stats_empty_data(authed_client, test_db):
    """Pagina laadt zonder fouten als er nog geen analytics zijn."""
    _make_admin(test_db)
    resp = await authed_client.get("/admin/stats")
    assert resp.status_code == 200
    assert "Statistieken" in resp.text
    assert "Nog geen data beschikbaar" in resp.text


# ---------------------------------------------------------------------------
# KPI kaartjes op /admin/users
# ---------------------------------------------------------------------------

async def test_admin_users_shows_kpi_cards(authed_client, test_db):
    """KPI kaartjes zichtbaar op /admin/users."""
    _make_admin(test_db)
    resp = await authed_client.get("/admin/users")
    assert resp.status_code == 200
    assert "Posts gegenereerd" in resp.text
    assert "Gem. generatietijd" in resp.text
    assert "Populairste model" in resp.text
    assert "Statistieken →" in resp.text


# ---------------------------------------------------------------------------
# Stats met data
# ---------------------------------------------------------------------------

async def test_stats_shows_posts_per_day(authed_client, test_db):
    """Posts per dag tabel verschijnt als er events zijn."""
    _make_admin(test_db)
    uid = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()["id"]
    log_event(test_db, uid, "generate_ok", {"llm": "groq", "duration_ms": 1200})

    resp = await authed_client.get("/admin/stats")
    assert resp.status_code == 200
    assert "Posts per dag" in resp.text


async def test_stats_shows_llm_table(authed_client, test_db):
    """Per-model tabel toont correcte rij."""
    _make_admin(test_db)
    uid = test_db.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()["id"]
    log_event(test_db, uid, "generate_ok", {"llm": "groq", "duration_ms": 1000})
    log_event(test_db, uid, "generate_fail", {"llm": "groq"})

    resp = await authed_client.get("/admin/stats")
    assert resp.status_code == 200
    assert "Per model" in resp.text
    assert "groq" in resp.text


async def test_stats_shows_user_activity(authed_client, test_db):
    """Gebruikersactiviteit tabel toont de testgebruiker."""
    _make_admin(test_db)
    resp = await authed_client.get("/admin/stats")
    assert resp.status_code == 200
    assert "Gebruikersactiviteit" in resp.text
    assert TEST_EMAIL in resp.text
