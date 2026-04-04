# Multi-user refactor — plan van aanpak

## Overzicht

Vijf fasen, elke fase eindigt met een werkende app die volledig getest kan worden voor we verdergaan.
Alles is per-user: provider accounts, LLM keys, stijl/prompts, drafts, settings. Geen gedeelde data.

---

## Fase 0: Veiligheidsnet ✅

- DB backup (`drafts.db.bak`)
- pytest setup met in-memory SQLite
- Baseline happy-path tests (11 tests groen)

---

## Fase 1: Authenticatie (login/logout) ✅

- `users` tabel (`id`, `email`, `password_hash`, `created_at`)
- Wachtwoord hashing met `bcrypt` (rechtstreeks, niet via passlib)
- Login- en registratiepagina
- Session-cookies via `itsdangerous` (Starlette `SessionMiddleware`)
- `get_current_user()` dependency — alle routes beschermd
- Uitlogknop in hamburger menu

**Checkpunt**: 28/28 tests groen. Login/logout werkt op live omgeving.

---

## Fase 1b: 2FA (TOTP)

Na de basis-auth, voor we data-isolatie bouwen — een stevige auth-laag is de fundering voor alles wat volgt.

**Aanpak: TOTP via Google Authenticator / Authy**
- Library: `pyotp` + `qrcode`
- `users` tabel uitbreiden: `totp_secret TEXT` (NULL = 2FA niet ingeschakeld)
- Instellen via settings-pagina:
  1. Server genereert een TOTP secret + QR-code
  2. User scant QR met Authenticator-app
  3. User voert de 6-cijferige code in ter bevestiging
  4. Secret wordt opgeslagen → 2FA actief
- Login flow na activatie:
  1. Wachtwoord correct → sessie nog NIET volledig
  2. Redirect naar `/login/2fa` — voer code in
  3. Code correct → sessie volledig, redirect naar `/`
- Uitschakelen: via settings, na herbevestiging met huidige code
- "Remember this device" (optioneel, later): cookie met 30 dagen geldigheid

**DB-wijziging**: enkel `ALTER TABLE users ADD COLUMN totp_secret TEXT` — minimale impact.

**Checkpunt**: 2FA kan ingeschakeld/uitgeschakeld worden. Login zonder geldige code is onmogelijk als 2FA aan staat. Geautomatiseerde tests met `pyotp.TOTP(secret).now()`.

---

## Fase 2: Settings per user

Zwaarste stap — raakt de providers en de ticket cache.

- `user_id` kolom toevoegen aan `settings`
- `get_setting(key, user_id)` / `set_setting(key, value, user_id)` aanpassen
- Provider loading (`_load_providers`) wordt per-user: globale `_providers` dict wordt `_providers[user_id]`, idem voor ticket cache
- Alle routes die settings lezen geven de ingelogde user mee

**Checkpunt**: user A en user B kunnen elk hun eigen Collective/Eventbrite configureren zonder elkaar te beïnvloeden. Provider errors zijn per-user.

---

## Fase 3: Data per user (drafts & prompts)

- `user_id` FK toevoegen aan `drafts` en `prompts`
- Alle queries krijgen `WHERE user_id = ?`
- IDOR-bescherming: andermans draft-URL openen geeft 403
- Bestaande data koppelen aan de eerste admin-user

**Checkpunt**: volledige data-isolatie. Geautomatiseerde test verifieert dat user B de drafts van user A niet kan zien of bewerken.

---

## Fase 4: Security afwerking

- CSRF-tokens op alle formulieren
- Rate limiting op de login route (max. X pogingen per minuut)
- Show/hide toggle op wachtwoordvelden (bestaande minor todo)

**Checkpunt**: CSRF-aanval geblokkeerd (testbaar via pytest), login brute-force throttled.

---

## Volgorde binnen elke fase

1. DB-migratie (schema uitbreiden zonder data te verliezen)
2. Backend aanpassen (`db.py` → `server.py`)
3. Templates aanpassen
4. Tests schrijven + groen krijgen
5. Manueel testen op de live omgeving (`eventsnap.dreamlead.be`)

---

## Aandachtspunten

- **Fase 2 is het riskantst**: de provider cache is een module-level global die gerefactord wordt. Hier is de kans op regressie het grootst.
- **Wachtwoord opslag**: bcrypt rechtstreeks (niet passlib — incompatibel met bcrypt 5.x). Enkel de hash opslaan, nooit plaintext.
- **IDOR**: elke query op drafts/prompts checkt altijd zowel `id` als `user_id`.
- **CSRF**: relevant vanaf Fase 1 maar pas afgewerkt in Fase 4 — laag risico zolang de app enkel via Cloudflare/Google SSO bereikbaar is.
- **2FA secret opslag**: TOTP secret is gevoelig — zit in de DB naast het wachtwoord. Bij een DB-lek kan een aanvaller beide combineren. Overweging voor later: secrets encrypteren met een app-level key uit `.env`.
