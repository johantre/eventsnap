# EventSnap

Generate LinkedIn post drafts from event agendas and conference session pages — in seconds.

EventSnap connects to your ticket platforms (Collective, Eventbrite), pulls your upcoming events, and uses an AI language model of your choice to draft a ready-to-post LinkedIn update. It also lets you generate posts directly from any conference agenda page by sharing or pasting session text.

Self-hosted web app, publicly accessible via Cloudflare tunnel, with multi-user support and 2FA.

## Features

- **Ticket-based generation** — fetch events from Collective (Odoo) and Eventbrite, generate a LinkedIn post per event
- **Generate from any page** — share a URL or paste/select session text from any agenda page (Sessionize, Sched, custom sites); EventSnap scrapes or receives the text and generates a post
- **Multiple LLMs** — Groq (Llama 3.3 70B), Claude (Sonnet 4.6), OpenAI (GPT-4o mini), Gemini (2.5 Flash)
- **Styles (prompts)** — save reusable prompt styles (e.g. "formal", "personal", "English") and apply them per generation
- **Cost tracking** — token usage and estimated cost per LLM shown in settings
- **PWA + share target** — installable as a home screen app on Android and iOS; share pages directly to EventSnap
- **Bookmarklet** — one-click text selection or URL sharing from desktop browsers
- **Multi-user** — per-user settings, LLM keys, prompts, and drafts; admin panel for user management
- **2FA** — TOTP-based two-factor authentication
- **Encrypted settings** — API keys and credentials encrypted at rest using Fernet symmetric encryption
- **DB backup** — automatic backup to a private GitHub repo on each change

## Architecture

```
eventsnap/
├── app/
│   ├── server.py          # FastAPI app — routes, auth, generation logic
│   ├── db.py              # SQLite: users, drafts, prompts, settings, analytics
│   ├── static/            # CSS, icons, PWA manifest
│   └── templates/         # Jinja2 HTML templates
├── providers/
│   ├── base.py            # EventProvider (abstract), Event, Ticket models
│   ├── collective.py      # Odoo JSON-RPC
│   └── eventbrite.py      # Eventbrite REST API
├── summary/
│   └── generator.py       # LLM post generation (Groq / Claude / OpenAI / Gemini)
├── tests/
└── scripts/
    ├── backup_db.sh        # Checksum-based DB backup to private repo
    └── restore_db.sh       # Restore DB from backup
```

## Infrastructure

- **Server**: self-hosted on a ChromeBox (Ubuntu Linux)
- **Public URL**: `eventsnap.dreamlead.be` via Cloudflare tunnel
- **Process**: systemd service (`eventsnap.service`)
- **Secrets**: injected at deploy time via GitHub Secrets, stored server-side as a systemd `EnvironmentFile`
- **CI/CD**: GitHub Actions with a self-hosted runner — runs tests on every push, deploys to main

## Setup

### Requirements

```bash
pip install -r requirements.txt
```

### Environment variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | Session signing key (any random string) |
| `ENCRYPTION_KEY` | Fernet key for encrypting sensitive DB values |
| `MAILGUN_API_KEY` | Mailgun API key for email verification |

Generate a Fernet key:

```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

### Run locally

```bash
uvicorn app.server:app --reload
```

### Systemd (production)

```bash
sudo systemctl start eventsnap
sudo systemctl status eventsnap
sudo journalctl -u eventsnap -f
```

## Testing

Run the full test suite:

```bash
pytest tests/ -q
```

## Test Status

![Test & Deploy](https://github.com/johantre/eventsnap/actions/workflows/deploy.yml/badge.svg?branch=main)

## License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International License (CC BY-NC 4.0). This means you can:

- Share: copy and redistribute the material in any medium or format
- Adapt: remix, transform, and build upon the material

Under the following terms:
- Attribution: you must give appropriate credit, provide a link to the license, and indicate if changes were made
- NonCommercial: you may not use the material for commercial purposes
- No additional restrictions: you may not apply legal terms or technological measures that legally restrict others from doing anything the license permits

See the [LICENSE](LICENSE) file for details.

---

**Made with ❤️ for efficiency and automation**
