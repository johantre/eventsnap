# EventSnap  <img style="vertical-align: bottom" src='app/static/icon-128.png' width='40' height='40' /> — Setup Guide

This guide covers everything you need to get started. You can be up and running in 5 minutes with just a free API key.

---

## Minimal setup (required)

EventSnap needs **at least one AI model configured** before it can generate anything. Everything else is optional.

### Step 1 — Get an API key

Pick one of the options below. Groq is the easiest starting point.

---

#### Groq — free, no credit card

1. Go to [console.groq.com](https://console.groq.com) and create an account
2. In the left menu, click **API Keys**
3. Click **Create API Key**, give it a name, copy the key

---

#### Gemini — free, credit card required for activation

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Click **Get API key** in the top bar → **Create API key**
3. Copy the key

> Google requires a credit card to activate the API, even for the free tier.

---

#### Claude (Anthropic) — paid

1. Go to [console.anthropic.com](https://console.anthropic.com) and create an account
2. Go to **API Keys** → **Create Key**
3. Add credits — a minimum purchase applies (around $5, verify on their site)
4. Copy the key

---

#### OpenAI — paid

1. Go to [platform.openai.com](https://platform.openai.com) and create an account
2. Go to **API keys** → **Create new secret key**
3. Add credits — a minimum purchase applies (around $5, verify on their site)
4. Copy the key

---

### Step 2 — Add the key in EventSnap

1. Open EventSnap → go to **Settings** (top right menu)
2. Scroll to **Language model (LLM)**
3. Find your model and paste the key in the input field
4. The key is validated immediately — a green checkmark confirms it works
5. Select that model as active and click **Save active model**

That's it — you can now generate posts.

---

## What works with minimal setup

| Feature | Minimal setup (LLM only) | With event providers |
|---|---|---|
| Generate from any web page | ✅ | ✅ |
| Generate from copied text | ✅ | ✅ |
| Bookmarklet / mobile share | ✅ | ✅ |
| Custom styles | ✅ | ✅ |
| Automatic ticket list on home screen | ❌ | ✅ |

The home screen ticket list requires a connected event provider (Collective or Eventbrite). Without it, use **Generate from page** to paste or share session content manually.

---

## Optional — Connect event providers

Event providers let EventSnap automatically fetch your upcoming tickets and show them on the home screen.

### Collective (Odoo / Wintercircus)

1. Go to **Settings → Event providers → Collective**
2. Enter the URL of your Odoo instance (e.g. `https://wintercircus.odoo.com`)
3. Enter your Odoo email and password
4. Click **Save**

### Eventbrite

1. Go to [eventbrite.com/account-settings/apps](https://www.eventbrite.com/account-settings/apps)
2. Scroll down to **API keys** — copy your **Private token** (not the API key, Public token or Client secret)
3. Go to **Settings → Event providers → Eventbrite**
4. Paste the token and click **Save**

---

## Optional — Install on your device

For the best mobile experience and to use the share sheet integration, install EventSnap as an app.

**Android (Chrome):** open [eventsnap.dreamlead.be](https://eventsnap.dreamlead.be) → three dots → **Add to Home screen**

**iOS (Safari):** open [eventsnap.dreamlead.be](https://eventsnap.dreamlead.be) → Share icon → **Add to Home Screen**

**Desktop bookmarklet:** see [USAGE.md](USAGE.md) for instructions.

---

*Once setup is complete, see [USAGE.md](USAGE.md) for how to generate posts.*
