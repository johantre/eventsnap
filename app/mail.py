import os
import requests

MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = "mg.dreamlead.be"
MAILGUN_FROM = "EventSnap <eventsnap@mg.dreamlead.be>"
MAILGUN_API_URL = f"https://api.eu.mailgun.net/v3/{MAILGUN_DOMAIN}/messages"


def send_verification_email(to_email: str, verify_url: str) -> None:
    html = f"""
<body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f4f4f5;">
  <div style="max-width: 560px; margin: 0 auto; background: white; border-radius: 12px; padding: 2rem; box-shadow: 0 1px 4px rgba(0,0,0,0.08);">
    <h2 style="margin: 0 0 0.5rem; color: #18181b;">Bevestig je e-mailadres</h2>
    <p style="color: #52525b; margin: 0 0 1.5rem;">
      Welkom bij EventSnap! Klik op de knop hieronder om je e-mailadres te bevestigen en je account te activeren.
    </p>
    <a href="{verify_url}"
       style="display: inline-block; background: #0a66c2; color: white; text-decoration: none;
              padding: 0.75rem 1.5rem; border-radius: 8px; font-weight: 600; font-size: 0.95rem;">
      E-mailadres bevestigen
    </a>
    <p style="color: #a1a1aa; font-size: 0.8rem; margin: 1.5rem 0 0;">
      Deze link is 24 uur geldig. Heb je je niet geregistreerd? Dan hoef je niets te doen.
    </p>
  </div>
</body>
"""
    response = requests.post(
        MAILGUN_API_URL,
        auth=("api", MAILGUN_API_KEY),
        data={
            "from": MAILGUN_FROM,
            "to": to_email,
            "subject": "Bevestig je e-mailadres – EventSnap",
            "html": html,
        },
        timeout=10,
    )
    response.raise_for_status()


def send_password_reset(to_email: str, reset_url: str) -> None:
    html = f"""
<body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f4f4f5;">
  <div style="max-width: 560px; margin: 0 auto; background: white; border-radius: 12px; padding: 2rem; box-shadow: 0 1px 4px rgba(0,0,0,0.08);">
    <h2 style="margin: 0 0 0.5rem; color: #18181b;">Wachtwoord opnieuw instellen</h2>
    <p style="color: #52525b; margin: 0 0 1.5rem;">
      We ontvingen een aanvraag om het wachtwoord van je EventSnap-account te resetten.
      Klik op de knop hieronder om een nieuw wachtwoord in te stellen.
    </p>
    <a href="{reset_url}"
       style="display: inline-block; background: #0a66c2; color: white; text-decoration: none;
              padding: 0.75rem 1.5rem; border-radius: 8px; font-weight: 600; font-size: 0.95rem;">
      Wachtwoord opnieuw instellen
    </a>
    <p style="color: #a1a1aa; font-size: 0.8rem; margin: 1.5rem 0 0;">
      Deze link is 1 uur geldig. Heb je geen aanvraag gedaan? Dan hoef je niets te doen.
    </p>
  </div>
</body>
"""
    response = requests.post(
        MAILGUN_API_URL,
        auth=("api", MAILGUN_API_KEY),
        data={
            "from": MAILGUN_FROM,
            "to": to_email,
            "subject": "Wachtwoord opnieuw instellen – EventSnap",
            "html": html,
        },
        timeout=10,
    )
    response.raise_for_status()
