"""
Tests voor LLM_OPTIONS URL-veld.

Regressietest voor de bug waarbij de 'Get key'-links in de settings pagina
naar de EventSnap settings-URL wezen in plaats van naar de externe API-provider,
omdat het 'url'-veld ontbrak in LLM_OPTIONS (Jinja2 rendert ontbrekende
dict-sleutels als lege string, waardoor href="" de huidige pagina aanwijst).
"""

import pytest
from app.server import LLM_OPTIONS

EVENTSNAP_HOST = "eventsnap.dreamlead.be"


# ---------------------------------------------------------------------------
# Unit-tests op LLM_OPTIONS definitie (geen HTTP nodig)
# ---------------------------------------------------------------------------

def test_all_llm_options_have_url():
    """Elke LLM-optie moet een niet-leeg 'url' veld hebben."""
    for opt in LLM_OPTIONS:
        assert "url" in opt, f"LLM '{opt['id']}' mist het 'url' veld"
        assert opt["url"], f"LLM '{opt['id']}' heeft een lege URL"


def test_all_llm_urls_are_external_https():
    """Alle API-key URLs moeten extern zijn (https://) en niet naar EventSnap wijzen."""
    for opt in LLM_OPTIONS:
        url = opt.get("url", "")
        assert url.startswith("https://"), (
            f"LLM '{opt['id']}': URL '{url}' is geen https-URL"
        )
        assert EVENTSNAP_HOST not in url, (
            f"LLM '{opt['id']}': URL wijst naar EventSnap in plaats van de API-provider"
        )
        assert not url.startswith("/"), (
            f"LLM '{opt['id']}': URL '{url}' is relatief — wijst naar de huidige pagina"
        )


def test_llm_urls_point_to_known_providers():
    """Elke bekende LLM wijst naar het juiste API-dashboard van de provider."""
    expected = {
        "groq":   "console.groq.com",
        "claude": "console.anthropic.com",
        "openai": "platform.openai.com",
        "gemini": "aistudio.google.com",
    }
    for opt in LLM_OPTIONS:
        llm_id = opt["id"]
        if llm_id in expected:
            url = opt.get("url", "")
            assert expected[llm_id] in url, (
                f"LLM '{llm_id}': verwacht '{expected[llm_id]}' in URL, maar kreeg '{url}'"
            )


# ---------------------------------------------------------------------------
# Integratietest: settings-pagina HTML bevat externe URLs (geen lege href)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_settings_page_llm_key_links_are_external(authed_client):
    """
    De 'Get key'-links in de settings-pagina mogen niet leeg zijn of naar
    de EventSnap-domeinnaam wijzen.
    """
    resp = await authed_client.get("/settings")
    assert resp.status_code == 200

    html = resp.text

    # href="" of href="/" zou de bug zijn
    assert 'href=""' not in html, (
        "Settings-pagina bevat href=\"\" — een LLM 'url' veld is leeg of ontbreekt"
    )

    for opt in LLM_OPTIONS:
        url = opt["url"]
        assert url in html, (
            f"URL '{url}' voor LLM '{opt['id']}' niet gevonden in de settings-pagina"
        )
