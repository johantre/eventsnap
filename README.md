# EventSnap  <img style="vertical-align: bottom" src='app/static/icon-128.png' width='40' height='40' />

Generate LinkedIn post drafts from event agendas and conference session pages — in seconds.

EventSnap connects to your ticket platforms (Collective, Eventbrite, Meetup), pulls your upcoming events, and uses an AI language model of your choice to draft a ready-to-post LinkedIn update. It also lets you generate posts directly from any conference agenda page by sharing or pasting session text.

Self-hosted web app with multi-user support, 2FA, and PWA capabilities.

## Features

- **Ticket-based generation** — fetch events from Collective (Odoo), Eventbrite and Meetup, generate a LinkedIn post per event
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

## Usage
Check out the [Usage](USAGE.md) page.

## Roadmap

- **LinkedIn API integration** — post or schedule directly from EventSnap without leaving the app (pending LinkedIn API approval)
- **Meetup support** — fetch events from Meetup (requires Meetup Pro subscription)

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

## Deployment

EventSnap is a standard FastAPI app. It can be deployed on any Linux server using systemd, Docker, or a process manager of your choice. A Cloudflare tunnel is a convenient way to expose it publicly without opening firewall ports.

CI/CD via GitHub Actions is included — the workflow runs tests on every push and deploys on merge to main using a self-hosted runner.

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

### Production (systemd)

```bash
sudo systemctl start eventsnap
sudo systemctl status eventsnap
sudo journalctl -u eventsnap -f
```

## Testing

```bash
pytest tests/ -q
```

## Test Status

![Test & Deploy](https://github.com/johantre/eventsnap/actions/workflows/deploy.yml/badge.svg?branch=main)
[![codecov](https://codecov.io/gh/johantre/eventsnap/branch/main/graph/badge.svg)](https://codecov.io/gh/johantre/eventsnap)

## License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International License (CC BY-NC 4.0). This means you can:

- Share: copy and redistribute the material in any medium or format
- Adapt: remix, transform, and build upon the material

Under the following terms:
- Attribution: you must give appropriate credit, provide a link to the license, and indicate if changes were made
- NonCommercial: you may not use the material for commercial purposes
- No additional restrictions**: you may not apply legal terms or technological measures that legally restrict others from doing anything the license permits

See the [LICENSE](LICENSE) file for details.

---

**Made with ❤️ for efficiency and automation**
