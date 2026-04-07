import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import secrets as _secrets
import time as _time
from fastapi import FastAPI, Form, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from providers.collective import CollectiveProvider
from providers.eventbrite import EventbriteProvider
from providers.meetup import MeetupProvider
from summary.generator import generate_linkedin_post, test_llm
from app.mail import send_password_reset, send_verification_email
from app.translations import TRANSLATIONS
from app.db import (
    init_db, get_db, get_setting, set_setting,
    get_user_by_id, get_user_by_email, create_user, verify_password,
    update_user_password, update_user_email, delete_user,
    create_password_reset_token, get_password_reset_token, consume_password_reset_token,
    create_email_verification_token, get_email_verification_token,
    consume_email_verification_token, mark_email_verified,
    get_all_users_with_stats, set_user_verified, log_event,
    get_admin_kpis, get_posts_per_day, get_llm_stats, get_fail_stats, get_user_activity_stats,
    get_llm_cost_per_user,
)

SECRET_KEY = os.environ.get("SECRET_KEY", "changeme-set-SECRET_KEY-in-env")

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=False)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

def _get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = _secrets.token_hex(32)
        request.session["csrf_token"] = token
    return token


def csrf_field(request: Request) -> str:
    return f'<input type="hidden" name="_csrf_token" value="{_get_csrf_token(request)}">'


templates.env.globals["csrf_field"] = csrf_field


def get_lang(request: Request, user_id: int = None) -> str:
    """Return active language ('nl' or 'en') for this request."""
    if user_id:
        db = get_db()
        lang = get_setting("language", user_id, default="")
        db.close()
        if lang in ("nl", "en"):
            return lang
    lang = request.session.get("language", "nl")
    return lang if lang in ("nl", "en") else "nl"


def _tctx(request: Request, user_id: int = None) -> dict:
    """Return base template context with translations and lang."""
    lang = get_lang(request, user_id)
    return {"t": TRANSLATIONS[lang], "lang": lang}


async def verify_csrf(request: Request):
    form = await request.form()
    token = form.get("_csrf_token", "")
    expected = request.session.get("csrf_token", "")
    if not expected or not _secrets.compare_digest(str(token), str(expected)):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Ongeldige CSRF token")


# ---------------------------------------------------------------------------
# Rate limiting (login)
# ---------------------------------------------------------------------------

_login_attempts: dict = {}  # {ip: [timestamp, ...]}
_LOGIN_MAX = 5
_LOGIN_WINDOW = 60  # seconds

init_db()

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class NotAuthenticatedException(Exception):
    pass


@app.exception_handler(NotAuthenticatedException)
async def not_authenticated_handler(request: Request, exc: NotAuthenticatedException):
    return RedirectResponse("/login", status_code=303)


async def get_current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise NotAuthenticatedException()
    db = get_db()
    user = get_user_by_id(db, user_id)
    db.close()
    if not user:
        request.session.clear()
        raise NotAuthenticatedException()
    return user


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", _tctx(request))


@app.post("/login")
async def login(request: Request, _csrf=Depends(verify_csrf), email: str = Form(...), password: str = Form(...)):
    ip = request.client.host if request.client else "unknown"
    now = _time.time()
    recent = [t for t in _login_attempts.get(ip, []) if now - t < _LOGIN_WINDOW]
    tr = TRANSLATIONS[get_lang(request)]
    if len(recent) >= _LOGIN_MAX:
        return templates.TemplateResponse(
            request, "login.html",
            {**_tctx(request), "error": tr["err_too_many_attempts"]},
            status_code=429,
        )
    db = get_db()
    user = get_user_by_email(db, email.strip().lower())
    db.close()
    if not user or not verify_password(password, user["password_hash"]):
        recent.append(now)
        _login_attempts[ip] = recent
        return templates.TemplateResponse(
            request, "login.html",
            {**_tctx(request), "error": tr["err_invalid_credentials"]},
            status_code=401,
        )
    _login_attempts.pop(ip, None)
    if user["totp_secret"]:
        request.session["pending_2fa_user_id"] = user["id"]
        return RedirectResponse("/login/2fa", status_code=303)
    request.session["user_id"] = user["id"]
    return RedirectResponse("/", status_code=303)


@app.get("/login/2fa", response_class=HTMLResponse)
async def login_2fa_page(request: Request):
    user_id = request.session.get("pending_2fa_user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    db = get_db()
    user = get_user_by_id(db, user_id)
    db.close()
    return templates.TemplateResponse(request, "login_2fa.html", {
        **_tctx(request),
        "email": user["email"] if user else "",
    })


@app.post("/login/2fa")
async def login_2fa(request: Request, _csrf=Depends(verify_csrf), code: str = Form(...)):
    user_id = request.session.get("pending_2fa_user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    db = get_db()
    user = get_user_by_id(db, user_id)
    db.close()
    if not user or not user["totp_secret"]:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    import pyotp
    totp = pyotp.TOTP(user["totp_secret"])
    if not totp.verify(code.strip(), valid_window=1):
        tr = TRANSLATIONS[get_lang(request)]
        return templates.TemplateResponse(
            request, "login_2fa.html",
            {**_tctx(request), "email": user["email"], "error": tr["err_invalid_code"]},
            status_code=401,
        )
    request.session.pop("pending_2fa_user_id", None)
    request.session["user_id"] = user["id"]
    return RedirectResponse("/", status_code=303)


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "forgot_password.html", _tctx(request))


@app.post("/forgot-password")
async def forgot_password(request: Request, _csrf=Depends(verify_csrf), email: str = Form(...)):
    db = get_db()
    user = get_user_by_email(db, email.strip().lower())
    if user:
        token = _secrets.token_urlsafe(32)
        expires_at = _time.strftime(
            "%Y-%m-%d %H:%M:%S",
            _time.gmtime(_time.time() + 3600),
        )
        create_password_reset_token(db, user["id"], token, expires_at)
        base_url = str(request.base_url).rstrip("/")
        reset_url = f"{base_url}/reset-password?token={token}"
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: send_password_reset(user["email"], reset_url)
            )
        except Exception as e:
            print(f"[mail] send failed: {e}")
    db.close()
    # Altijd dezelfde boodschap tonen — ook als e-mail niet bestaat
    return templates.TemplateResponse(request, "forgot_password.html", {
        **_tctx(request), "sent": True,
    })


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str = ""):
    if not token:
        return RedirectResponse("/login", status_code=303)
    db = get_db()
    row = get_password_reset_token(db, token)
    db.close()
    if not row or row["expires_at"] < _time.strftime("%Y-%m-%d %H:%M:%S", _time.gmtime()):
        return templates.TemplateResponse(request, "reset_password.html", {**_tctx(request), "invalid": True})
    return templates.TemplateResponse(request, "reset_password.html", {**_tctx(request), "token": token})


@app.post("/reset-password")
async def reset_password(request: Request, _csrf=Depends(verify_csrf), token: str = Form(...), new_password: str = Form(...), new_password2: str = Form(...)):
    db = get_db()
    row = get_password_reset_token(db, token)
    tr = TRANSLATIONS[get_lang(request)]
    if not row or row["expires_at"] < _time.strftime("%Y-%m-%d %H:%M:%S", _time.gmtime()):
        db.close()
        return templates.TemplateResponse(request, "reset_password.html", {**_tctx(request), "invalid": True})
    if new_password != new_password2:
        db.close()
        return templates.TemplateResponse(request, "reset_password.html", {
            **_tctx(request), "token": token, "error": tr["err_passwords_mismatch"],
        }, status_code=400)
    if len(new_password) < 8:
        db.close()
        return templates.TemplateResponse(request, "reset_password.html", {
            **_tctx(request), "token": token, "error": tr["err_password_too_short"],
        }, status_code=400)
    consume_password_reset_token(db, token)
    update_user_password(db, row["user_id"], new_password)
    db.close()
    return RedirectResponse("/login?reset=1", status_code=303)


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "register.html", _tctx(request))


@app.post("/register")
async def register(request: Request, _csrf=Depends(verify_csrf), email: str = Form(...), password: str = Form(...), password2: str = Form(...)):
    email = email.strip().lower()
    tr = TRANSLATIONS[get_lang(request)]
    if password != password2:
        return templates.TemplateResponse(
            request, "register.html",
            {**_tctx(request), "error": tr["err_passwords_mismatch"]},
            status_code=400,
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request, "register.html",
            {**_tctx(request), "error": tr["err_password_too_short"]},
            status_code=400,
        )
    db = get_db()
    existing = get_user_by_email(db, email)
    if existing:
        db.close()
        return templates.TemplateResponse(
            request, "register.html",
            {**_tctx(request), "error": tr["err_email_in_use"]},
            status_code=400,
        )
    user = create_user(db, email, password)
    token = _secrets.token_urlsafe(32)
    expires_at = _time.strftime("%Y-%m-%d %H:%M:%S", _time.gmtime(_time.time() + 86400))
    create_email_verification_token(db, user["id"], token, expires_at)
    db.close()
    base_url = str(request.base_url).rstrip("/")
    verify_url = f"{base_url}/verify-email?token={token}"
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: send_verification_email(email, verify_url)
        )
    except Exception as e:
        print(f"[mail] verification send failed: {e}")
    request.session["user_id"] = user["id"]
    return RedirectResponse("/", status_code=303)


@app.get("/verify-email", response_class=HTMLResponse)
async def verify_email(request: Request, token: str = ""):
    if not token:
        return RedirectResponse("/login", status_code=303)
    db = get_db()
    row = get_email_verification_token(db, token)
    if not row or row["expires_at"] < _time.strftime("%Y-%m-%d %H:%M:%S", _time.gmtime()):
        db.close()
        return templates.TemplateResponse(request, "verify_email.html", {**_tctx(request), "invalid": True})
    consume_email_verification_token(db, token)
    mark_email_verified(db, row["user_id"])
    db.close()
    return RedirectResponse("/?verified=1", status_code=303)


@app.post("/resend-verification")
async def resend_verification(request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf)):
    if current_user["email_verified"]:
        return RedirectResponse("/", status_code=303)
    token = _secrets.token_urlsafe(32)
    expires_at = _time.strftime("%Y-%m-%d %H:%M:%S", _time.gmtime(_time.time() + 86400))
    db = get_db()
    create_email_verification_token(db, current_user["id"], token, expires_at)
    db.close()
    base_url = str(request.base_url).rstrip("/")
    verify_url = f"{base_url}/verify-email?token={token}"
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: send_verification_email(current_user["email"], verify_url)
        )
    except Exception as e:
        print(f"[mail] resend verification failed: {e}")
    return RedirectResponse("/?resent=1", status_code=303)


@app.post("/logout")
async def logout(request: Request, _csrf=Depends(verify_csrf)):
    # Keep csrf_token in session so the login page works immediately after logout
    csrf = request.session.get("csrf_token")
    request.session.clear()
    if csrf:
        request.session["csrf_token"] = csrf
    return RedirectResponse("/login", status_code=303)


@app.post("/language")
async def set_language(request: Request, _csrf=Depends(verify_csrf), lang: str = Form(...)):
    if lang not in ("nl", "en"):
        lang = "nl"
    request.session["language"] = lang
    user_id = request.session.get("user_id")
    if user_id:
        db = get_db()
        set_setting("language", lang, user_id)
        db.close()
    referer = request.headers.get("referer", "/")
    return RedirectResponse(referer, status_code=303)


def _totp_qr_b64(email: str, secret: str) -> str:
    import pyotp, qrcode, io, base64
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="EventSnap")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@app.get("/settings/2fa", response_class=HTMLResponse)
async def settings_2fa_page(request: Request, current_user=Depends(get_current_user)):
    import pyotp
    if not current_user["totp_secret"]:
        pending = request.session.get("pending_totp_secret")
        if not pending:
            pending = pyotp.random_base32()
            request.session["pending_totp_secret"] = pending
        qr_b64 = _totp_qr_b64(current_user["email"], pending)
    else:
        qr_b64 = None
        request.session.pop("pending_totp_secret", None)
    uid = current_user["id"]
    return templates.TemplateResponse(request, "settings_2fa.html", {
        **_tctx(request, uid),
        "current_user": current_user,
        "totp_enabled": bool(current_user["totp_secret"]),
        "qr_b64": qr_b64,
    })


@app.post("/settings/2fa/enable")
async def settings_2fa_enable(request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf), code: str = Form(...)):
    import pyotp
    secret = request.session.get("pending_totp_secret")
    if not secret:
        return RedirectResponse("/settings/2fa?error=session_expired", status_code=303)
    totp = pyotp.TOTP(secret)
    if not totp.verify(code.strip(), valid_window=1):
        uid = current_user["id"]
        tr = TRANSLATIONS[get_lang(request, uid)]
        return templates.TemplateResponse(request, "settings_2fa.html", {
            **_tctx(request, uid),
            "current_user": current_user,
            "totp_enabled": False,
            "qr_b64": _totp_qr_b64(current_user["email"], secret),
            "error": tr["err_invalid_2fa_setup"],
        }, status_code=400)
    db = get_db()
    db.execute("UPDATE users SET totp_secret = ? WHERE id = ?", (secret, current_user["id"]))
    db.commit()
    db.close()
    request.session.pop("pending_totp_secret", None)
    return RedirectResponse("/settings/2fa?enabled=1", status_code=303)


@app.post("/settings/2fa/disable")
async def settings_2fa_disable(request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf), code: str = Form(...)):
    import pyotp
    if not current_user["totp_secret"]:
        return RedirectResponse("/settings/2fa", status_code=303)
    totp = pyotp.TOTP(current_user["totp_secret"])
    if not totp.verify(code.strip(), valid_window=1):
        uid = current_user["id"]
        tr = TRANSLATIONS[get_lang(request, uid)]
        return templates.TemplateResponse(request, "settings_2fa.html", {
            **_tctx(request, uid),
            "current_user": current_user,
            "totp_enabled": True,
            "qr_b64": None,
            "error": tr["err_invalid_2fa_disable"],
        }, status_code=400)
    db = get_db()
    db.execute("UPDATE users SET totp_secret = NULL WHERE id = ?", (current_user["id"],))
    db.commit()
    db.close()
    return RedirectResponse("/settings/2fa?disabled=1", status_code=303)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

def _friendly_error(e: Exception, llm_id: str = None, lang: str = "nl") -> str:
    tr = TRANSLATIONS.get(lang, TRANSLATIONS["nl"])
    raw = str(e).lower()
    prefix = f"{llm_id}: " if llm_id else ""
    if "503" in raw or "unavailable" in raw or "high demand" in raw:
        return f"{prefix}{tr['err_model_overloaded']}"
    if "429" in raw or "quota" in raw or "rate limit" in raw:
        return f"{prefix}{tr['err_credits_exceeded']}"
    if "401" in raw or "unauthorized" in raw or "invalid api key" in raw:
        return f"{prefix}{tr['err_invalid_api_key']}"
    if "403" in raw or "billing" in raw or "payment" in raw:
        return f"{prefix}{tr['err_payment_required']}"
    if "timeout" in raw:
        return f"{prefix}{tr['err_connection_timeout']}"
    import re
    clean = re.sub(r"\{.*\}", "", str(e), flags=re.DOTALL).strip(" .-\n")
    return f"{prefix}{clean}" if clean else f"{prefix}{tr['err_unknown']}"


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return templates.TemplateResponse(request, "error.html", {
        **_tctx(request, request.session.get("user_id")),
        "status": exc.status_code,
        "message": str(exc.detail),
    }, status_code=exc.status_code)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return templates.TemplateResponse(request, "error.html", {
        **_tctx(request, request.session.get("user_id")),
        "status": 500,
        "message": str(exc),
    }, status_code=500)


# ---------------------------------------------------------------------------
# Providers & ticket cache — per user (user_id als sleutel)
# ---------------------------------------------------------------------------

_providers: dict = {}         # {user_id: {name: provider}}
_tickets_cache: dict = {}     # {user_id: [tickets]}
_tickets_cache_time: dict = {}  # {user_id: float}
_provider_load_errors: dict = {}  # {user_id: [str]}
TICKETS_CACHE_TTL = 300


def _load_providers_for_user(user_id: int) -> tuple[dict, list]:
    errors = []
    providers = {}

    url      = get_setting("collective_url",      user_id)
    email    = get_setting("collective_email",     user_id)
    password = get_setting("collective_password",  user_id)
    if url and email and password:
        try:
            p = CollectiveProvider(url, email, password)
            p.authenticate()
            providers["collective"] = p
        except Exception as e:
            print(f"[Collective] auth failed: {e}")
            errors.append("Collective: inloggen mislukt — controleer je e-mail en wachtwoord")

    token = get_setting("eventbrite_token", user_id)
    if token:
        providers["eventbrite"] = EventbriteProvider(token)

    token = get_setting("meetup_token", user_id)
    if token:
        providers["meetup"] = MeetupProvider(token)

    return providers, errors


def get_providers_for_user(user_id: int) -> dict:
    if user_id not in _providers:
        _providers[user_id], _provider_load_errors[user_id] = _load_providers_for_user(user_id)
    return _providers[user_id]


def reset_providers_for_user(user_id: int):
    _providers.pop(user_id, None)
    _tickets_cache.pop(user_id, None)
    _tickets_cache_time.pop(user_id, None)
    _provider_load_errors.pop(user_id, None)


def get_tickets_for_user(user_id: int) -> tuple[list, list]:
    import time
    if user_id in _tickets_cache and (time.time() - _tickets_cache_time.get(user_id, 0)) < TICKETS_CACHE_TTL:
        return _tickets_cache[user_id], list(_provider_load_errors.get(user_id, []))
    get_providers_for_user(user_id)
    all_tickets = []
    errors = list(_provider_load_errors.get(user_id, []))
    for name, p in _providers.get(user_id, {}).items():
        try:
            all_tickets.extend(p.fetch_tickets())
        except Exception as e:
            print(f"[provider] fetch_tickets failed: {e}")
            errors.append(f"{name}: ophalen mislukt — {e}")
    all_tickets.sort(key=lambda t: t.event_date or "9999")
    _tickets_cache[user_id] = all_tickets
    _tickets_cache_time[user_id] = time.time()
    return all_tickets, errors


# ---------------------------------------------------------------------------
# LLM opties
# ---------------------------------------------------------------------------

LLM_OPTIONS = [
    {"id": "groq",   "label": "Groq",   "sublabel": "Llama 3.3 70B",    "env": "GROQ_API_KEY",
     "color": "#6366f1", "cost": "free", "cost_tip": "Volledig gratis",
     "url": "https://console.groq.com/keys"},
    {"id": "claude", "label": "Claude", "sublabel": "Sonnet 4.6",        "env": "ANTHROPIC_API_KEY",
     "color": "#d97706", "cost": "coin", "cost_tip": "~0.01€/post · min. $5 opladen",
     "url": "https://console.anthropic.com/settings/keys"},
    {"id": "openai", "label": "OpenAI", "sublabel": "GPT-4o mini",       "env": "OPENAI_API_KEY",
     "color": "#16a34a", "cost": "coin", "cost_tip": "~0.01€/post · min. $5 opladen",
     "url": "https://platform.openai.com/api-keys"},
    {"id": "gemini", "label": "Gemini", "sublabel": "2.5 Flash",         "env": "GEMINI_API_KEY",
     "color": "#2563eb", "cost": "card", "cost_tip": "Gratis tier · credit card info nodig",
     "url": "https://aistudio.google.com/app/apikey"},
]

# Cost per 1M tokens in USD (input, output)
LLM_COSTS_PER_1M = {
    "groq":   (0.0,  0.0),    # free
    "claude": (3.0,  15.0),   # claude-sonnet-4-6
    "openai": (0.15, 0.60),   # gpt-4o-mini
    "gemini": (0.0,  0.0),    # free tier
}


def calc_cost_usd(llm: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = LLM_COSTS_PER_1M.get(llm, (0.0, 0.0))
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, current_user=Depends(get_current_user)):
    uid = current_user["id"]
    all_tickets, provider_errors = get_tickets_for_user(uid)
    db = get_db()
    drafts = db.execute("SELECT * FROM drafts WHERE user_id = ? ORDER BY updated_at DESC", (uid,)).fetchall()
    prompts = db.execute("SELECT * FROM prompts WHERE user_id = ? ORDER BY id", (uid,)).fetchall()
    db.close()
    active_providers = sorted(set(t.provider for t in all_tickets))
    active_llm_id = get_setting("active_llm", uid) or "groq"
    active_llm_opt = next((o for o in LLM_OPTIONS if o["id"] == active_llm_id), LLM_OPTIONS[0])
    return templates.TemplateResponse(request, "index.html", {
        **_tctx(request, uid),
        "tickets": all_tickets,
        "drafts": drafts,
        "prompts": prompts,
        "active_providers": active_providers,
        "active_llm": active_llm_opt,
        "provider_errors": provider_errors,
        "current_user": current_user,
    })


@app.post("/generate")
async def generate(
    request: Request,
    current_user=Depends(get_current_user),
    _csrf=Depends(verify_csrf),
    ticket_key: str = Form(...),
    prompt_id: int = Form(None),
    user_prompt: str = Form(""),
):
    uid = current_user["id"]
    active_llm = None
    try:
        provider_name, event_id = ticket_key.split(":", 1)
        provider = get_providers_for_user(uid)[provider_name]
        event = provider.fetch_event_by_id(event_id)

        prompt_text = ""
        if prompt_id:
            db = get_db()
            row = db.execute("SELECT prompt_text FROM prompts WHERE id = ? AND user_id = ?", (prompt_id, uid)).fetchone()
            db.close()
            prompt_text = row["prompt_text"] if row else ""
        if user_prompt.strip():
            prompt_text = (prompt_text + "\n" + user_prompt).strip() if prompt_text else user_prompt

        active_llm = get_setting("active_llm", uid) or "groq"
        env_map = {"groq": "GROQ_API_KEY", "claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
        for llm_name, env_key in env_map.items():
            stored_key = get_setting(f"{llm_name}_api_key", uid)
            if stored_key:
                os.environ[env_key] = stored_key

        custom_system_prompt = get_setting("system_prompt", uid) or None
        t0 = _time.time()
        post_text, input_tokens, output_tokens = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: generate_linkedin_post(
                event,
                prompt_text or "Schrijf een professionele maar persoonlijke post in het Nederlands.",
                llm=active_llm,
                system_prompt=custom_system_prompt,
            )
        )
        generation_ms = int((_time.time() - t0) * 1000)
        cost_usd = calc_cost_usd(active_llm, input_tokens, output_tokens)
        db = get_db()
        cursor = db.execute(
            "INSERT INTO drafts (user_id, event_id, event_title, event_date, post_text, llm, provider, prompt_text, generation_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, event.id, event.title, event.date, post_text, active_llm or "groq", provider_name, prompt_text or "", generation_ms),
        )
        draft_id = cursor.lastrowid
        log_event(db, uid, "generate_ok", {
            "llm": active_llm, "provider": provider_name,
            "duration_ms": generation_ms, "draft_id": draft_id,
            "event_title": event.title,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        })
        db.commit()
        db.close()
        return RedirectResponse(f"/draft/{draft_id}", status_code=303)
    except Exception as e:
        duration_ms = int((_time.time() - t0) * 1000) if 't0' in dir() else 0
        try:
            db = get_db()
            log_event(db, uid, "generate_fail", {
                "llm": active_llm, "duration_ms": duration_ms, "error": str(e)[:200],
            })
            db.close()
        except Exception:
            pass
        from urllib.parse import quote
        return RedirectResponse(f"/?error={quote(_friendly_error(e, active_llm, get_lang(request, uid)))}", status_code=303)


@app.get("/draft/{draft_id}", response_class=HTMLResponse)
async def edit_draft(request: Request, draft_id: int, current_user=Depends(get_current_user)):
    uid = current_user["id"]
    db = get_db()
    draft = db.execute("SELECT * FROM drafts WHERE id = ? AND user_id = ?", (draft_id, uid)).fetchone()
    db.close()
    if draft is None:
        from fastapi import HTTPException
        tr = TRANSLATIONS[get_lang(request, uid)]
        raise HTTPException(status_code=404, detail=tr["err_draft_not_found"])
    llm_id = draft["llm"] or "groq"
    configured = []
    for opt in LLM_OPTIONS:
        if get_setting(f"{opt['id']}_api_key", uid):
            configured.append(opt)
    llm_opt = next((o for o in configured if o["id"] == llm_id), configured[0] if configured else LLM_OPTIONS[0])
    return templates.TemplateResponse(request, "draft.html", {
        **_tctx(request, uid),
        "draft": draft,
        "llm": llm_opt,
        "llm_options": configured,
        "current_user": current_user,
    })


@app.post("/draft/{draft_id}")
async def save_draft(draft_id: int, request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf), post_text: str = Form(...)):
    uid = current_user["id"]
    db = get_db()
    db.execute(
        "UPDATE drafts SET post_text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
        (post_text, draft_id, uid),
    )
    db.commit()
    db.close()
    return RedirectResponse(f"/draft/{draft_id}?saved=1", status_code=303)


@app.get("/prompts", response_class=HTMLResponse)
async def prompts_page(request: Request, current_user=Depends(get_current_user)):
    uid = current_user["id"]
    db = get_db()
    prompts = db.execute("SELECT * FROM prompts WHERE user_id = ? ORDER BY id", (uid,)).fetchall()
    db.close()
    return templates.TemplateResponse(request, "prompts.html", {
        **_tctx(request, uid),
        "prompts": prompts,
        "current_user": current_user,
    })


@app.post("/prompts")
async def create_prompt(request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf), title: str = Form(...), prompt_text: str = Form(...)):
    uid = current_user["id"]
    db = get_db()
    db.execute("INSERT INTO prompts (user_id, title, prompt_text) VALUES (?, ?, ?)", (uid, title, prompt_text))
    db.commit()
    db.close()
    return RedirectResponse("/prompts", status_code=303)


@app.post("/prompts/{prompt_id}")
async def update_prompt(prompt_id: int, request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf), title: str = Form(...), prompt_text: str = Form(...)):
    uid = current_user["id"]
    db = get_db()
    db.execute("UPDATE prompts SET title = ?, prompt_text = ? WHERE id = ? AND user_id = ?", (title, prompt_text, prompt_id, uid))
    db.commit()
    db.close()
    return RedirectResponse("/prompts", status_code=303)


@app.post("/prompts/{prompt_id}/delete")
async def delete_prompt(prompt_id: int, request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf)):
    uid = current_user["id"]
    db = get_db()
    db.execute("DELETE FROM prompts WHERE id = ? AND user_id = ?", (prompt_id, uid))
    db.commit()
    db.close()
    return RedirectResponse("/prompts", status_code=303)


@app.get("/account", response_class=HTMLResponse)
async def account_page(request: Request, current_user=Depends(get_current_user)):
    uid = current_user["id"]
    return templates.TemplateResponse(request, "account.html", {
        **_tctx(request, uid),
        "current_user": current_user,
    })


@app.post("/account/change-password")
async def change_password(
    request: Request,
    current_user=Depends(get_current_user),
    _csrf=Depends(verify_csrf),
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password2: str = Form(...),
):
    uid = current_user["id"]
    tr = TRANSLATIONS[get_lang(request, uid)]
    error = None
    if not verify_password(current_password, current_user["password_hash"]):
        error = tr["err_current_password"]
    elif new_password != new_password2:
        error = tr["err_new_passwords_mismatch"]
    elif len(new_password) < 8:
        error = tr["err_new_password_too_short"]
    if error:
        return templates.TemplateResponse(request, "account.html", {
            **_tctx(request, uid),
            "current_user": current_user,
            "pw_error": error,
        }, status_code=400)
    db = get_db()
    update_user_password(db, uid, new_password)
    db.close()
    return RedirectResponse("/account?pw_saved=1", status_code=303)


@app.post("/account/change-email")
async def change_email(
    request: Request,
    current_user=Depends(get_current_user),
    _csrf=Depends(verify_csrf),
    current_password: str = Form(...),
    new_email: str = Form(...),
):
    uid = current_user["id"]
    tr = TRANSLATIONS[get_lang(request, uid)]
    new_email = new_email.strip().lower()
    error = None
    if not verify_password(current_password, current_user["password_hash"]):
        error = tr["err_current_password"]
    elif new_email == current_user["email"]:
        error = tr["err_same_email"]
    else:
        db = get_db()
        existing = get_user_by_email(db, new_email)
        db.close()
        if existing:
            error = tr["err_email_in_use"]
    if error:
        return templates.TemplateResponse(request, "account.html", {
            **_tctx(request, uid),
            "current_user": current_user,
            "email_error": error,
        }, status_code=400)
    db = get_db()
    update_user_email(db, uid, new_email)
    db.close()
    request.session["user_id"] = uid  # session blijft geldig
    return RedirectResponse("/account?email_saved=1", status_code=303)


@app.post("/account/delete")
async def delete_account(
    request: Request,
    current_user=Depends(get_current_user),
    _csrf=Depends(verify_csrf),
    current_password: str = Form(...),
):
    uid = current_user["id"]
    tr = TRANSLATIONS[get_lang(request, uid)]
    if not verify_password(current_password, current_user["password_hash"]):
        return templates.TemplateResponse(request, "account.html", {
            **_tctx(request, uid),
            "current_user": current_user,
            "delete_error": tr["err_delete_wrong_password"],
        }, status_code=400)
    db = get_db()
    delete_user(db, current_user["id"])
    db.close()
    request.session.clear()
    return RedirectResponse("/login?deleted=1", status_code=303)


async def _require_admin(current_user):
    from fastapi import HTTPException
    if not current_user["is_admin"]:
        raise HTTPException(status_code=403, detail="Geen toegang")


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request, current_user=Depends(get_current_user)):
    await _require_admin(current_user)
    db = get_db()
    users = get_all_users_with_stats(db)
    kpis = get_admin_kpis(db)
    db.close()
    return templates.TemplateResponse(request, "admin_users.html", {
        **_tctx(request, current_user["id"]),
        "current_user": current_user,
        "users": users,
        "kpis": kpis,
    })


@app.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats(request: Request, current_user=Depends(get_current_user)):
    await _require_admin(current_user)
    db = get_db()
    posts_per_day = get_posts_per_day(db, days=14)
    llm_stats = get_llm_stats(db)
    fail_stats = get_fail_stats(db)
    user_stats = get_user_activity_stats(db)
    kpis = get_admin_kpis(db)
    db.close()
    # Merge fail counts into llm_stats
    fail_map = {r["llm"]: r["fails"] for r in fail_stats}
    llm_merged = [
        {**dict(r), "fails": fail_map.get(r["llm"], 0)}
        for r in llm_stats
    ]
    return templates.TemplateResponse(request, "admin_stats.html", {
        **_tctx(request, current_user["id"]),
        "current_user": current_user,
        "kpis": kpis,
        "posts_per_day": posts_per_day,
        "llm_stats": llm_merged,
        "user_stats": user_stats,
    })


@app.post("/admin/users/{user_id}/verify")
async def admin_verify_user(user_id: int, request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf)):
    await _require_admin(current_user)
    db = get_db()
    set_user_verified(db, user_id, 1)
    db.close()
    return RedirectResponse("/admin/users?saved=1", status_code=303)


@app.post("/admin/users/{user_id}/delete")
async def admin_delete_user(user_id: int, request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf)):
    await _require_admin(current_user)
    if user_id == current_user["id"]:
        return RedirectResponse("/admin/users?error=self", status_code=303)
    db = get_db()
    delete_user(db, user_id)
    db.close()
    return RedirectResponse("/admin/users?saved=1", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, current_user=Depends(get_current_user)):
    uid = current_user["id"]
    active_llm = get_setting("active_llm", uid)
    db = get_db()
    cost_per_llm = get_llm_cost_per_user(db, uid)
    db.close()
    llms = []
    for opt in LLM_OPTIONS:
        has_key = bool(get_setting(f"{opt['id']}_api_key", uid))
        llms.append({**opt, "has_key": has_key, "spent_usd": cost_per_llm.get(opt["id"], 0.0)})

    collective_url_default = "https://wintercircus.odoo.com"

    collective_url      = get_setting("collective_url",      uid)
    collective_email    = get_setting("collective_email",     uid)
    collective_password = get_setting("collective_password",  uid)
    collective_ok       = bool(collective_url and collective_email and collective_password)
    eventbrite_ok       = bool(get_setting("eventbrite_token", uid))
    meetup_ok           = bool(get_setting("meetup_token",      uid))

    from summary.generator import SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT
    current_system_prompt = get_setting("system_prompt", uid)

    return templates.TemplateResponse(request, "settings.html", {
        **_tctx(request, uid),
        "llms": llms,
        "active_llm": active_llm,
        "system_prompt": current_system_prompt,
        "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
        "collective": {
            "url":            collective_url,
            "email":          collective_email,
            "password_set":   bool(collective_password),
            "ok":             collective_ok,
        },
        "eventbrite_ok": eventbrite_ok,
        "meetup_ok":     meetup_ok,
        "current_user":  current_user,
    })


PROVIDER_SETTINGS = [
    {"id": "collective_url",      "label": "URL"},
    {"id": "collective_email",    "label": "E-mail"},
    {"id": "collective_password", "label": "Wachtwoord"},
    {"id": "eventbrite_token",    "label": "Eventbrite token"},
    {"id": "meetup_token",        "label": "Meetup token"},
]


@app.post("/settings/key/{llm_id}")
async def validate_and_save_key(llm_id: str, request: Request, current_user=Depends(get_current_user)):
    from fastapi.responses import JSONResponse
    uid = current_user["id"]
    env_key_map = {"groq": "GROQ_API_KEY", "claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
    if llm_id not in env_key_map:
        return JSONResponse({"ok": False, "msg": "Onbekende LLM"})

    body = await request.json()
    new_key = body.get("key", "").strip()
    if not new_key:
        return JSONResponse({"ok": False, "msg": "Geen key ingevoerd"})

    env_var = env_key_map[llm_id]
    old_key = os.environ.get(env_var, "")
    os.environ[env_var] = new_key

    ok, msg = test_llm(llm_id)

    if ok:
        set_setting(f"{llm_id}_api_key", new_key, uid)
    else:
        if old_key:
            os.environ[env_var] = old_key
        else:
            os.environ.pop(env_var, None)

    return JSONResponse({"ok": ok, "msg": msg})


@app.post("/settings")
async def save_settings(request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf)):
    uid = current_user["id"]
    form = await request.form()

    system_prompt = form.get("system_prompt", "").strip()
    if system_prompt:
        set_setting("system_prompt", system_prompt, uid)

    active_llm = form.get("active_llm", "")
    set_setting("active_llm", active_llm, uid)

    for opt in LLM_OPTIONS:
        key_val = form.get(f"{opt['id']}_api_key", "").strip()
        if key_val:
            set_setting(f"{opt['id']}_api_key", key_val, uid)

    for ps in PROVIDER_SETTINGS:
        val = form.get(ps["id"], "").strip()
        if val:
            set_setting(ps["id"], val, uid)

    reset_providers_for_user(uid)
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/draft/{draft_id}/regenerate")
async def regenerate_draft(draft_id: int, request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf), llm_id: str = Form(...)):
    uid = current_user["id"]
    try:
        db = get_db()
        draft = db.execute("SELECT * FROM drafts WHERE id = ? AND user_id = ?", (draft_id, uid)).fetchone()
        db.close()
        if draft is None:
            raise ValueError("Draft niet gevonden")

        provider_name = draft["provider"] or "collective"
        provider = get_providers_for_user(uid).get(provider_name)
        if not provider:
            raise ValueError(f"Provider '{provider_name}' is niet geconfigureerd.")

        event = provider.fetch_event_by_id(draft["event_id"])

        stored_key = get_setting(f"{llm_id}_api_key", uid)
        env_map = {"groq": "GROQ_API_KEY", "claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
        if stored_key and llm_id in env_map:
            os.environ[env_map[llm_id]] = stored_key

        custom_system_prompt = get_setting("system_prompt", uid) or None
        saved_prompt = draft["prompt_text"] or "Schrijf een professionele maar persoonlijke post in het Nederlands."
        t0 = _time.time()
        post_text, input_tokens, output_tokens = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: generate_linkedin_post(event, saved_prompt, llm=llm_id, system_prompt=custom_system_prompt)
        )
        generation_ms = int((_time.time() - t0) * 1000)
        cost_usd = calc_cost_usd(llm_id, input_tokens, output_tokens)

        db = get_db()
        db.execute(
            "UPDATE drafts SET post_text = ?, llm = ?, generation_ms = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (post_text, llm_id, generation_ms, draft_id),
        )
        log_event(db, uid, "regenerate_ok", {
            "llm": llm_id, "provider": provider_name,
            "duration_ms": generation_ms, "draft_id": draft_id,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        })
        db.commit()
        db.close()
        return RedirectResponse(f"/draft/{draft_id}", status_code=303)
    except Exception as e:
        duration_ms = int((_time.time() - t0) * 1000) if 't0' in dir() else 0
        try:
            db = get_db()
            log_event(db, uid, "regenerate_fail", {
                "llm": llm_id, "duration_ms": duration_ms, "error": str(e)[:200],
            })
            db.close()
        except Exception:
            pass
        from urllib.parse import quote
        return RedirectResponse(f"/draft/{draft_id}?error={quote(_friendly_error(e, llm_id, get_lang(request, uid)))}", status_code=303)


@app.post("/draft/{draft_id}/delete")
async def delete_draft(draft_id: int, request: Request, current_user=Depends(get_current_user), _csrf=Depends(verify_csrf)):
    uid = current_user["id"]
    db = get_db()
    db.execute("DELETE FROM drafts WHERE id = ? AND user_id = ?", (draft_id, uid))
    db.commit()
    db.close()
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# From URL — scrape any agenda page and generate a post
# ---------------------------------------------------------------------------

def _scrape_url(url: str) -> tuple[str, str]:
    """Fetch a URL and return (page_title, clean_text). Raises on failure."""
    import requests
    from bs4 import BeautifulSoup
    headers = {"User-Agent": "Mozilla/5.0 (EventSnap/1.0)"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    # Prefer og:title (clean event name) over <title> (often has site suffix)
    og = soup.find("meta", property="og:title")
    if og and og.get("content", "").strip():
        title = og["content"].strip()
    else:
        title = soup.title.string.strip() if soup.title else url
    # Remove nav, footer, scripts, styles
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Collapse excessive whitespace
    import re
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return title, text[:6000]  # cap at 6000 chars to stay within token limits


@app.get("/from-url", response_class=HTMLResponse)
async def from_url_get(request: Request, current_user=Depends(get_current_user),
                       url: str = "", text: str = "", title: str = ""):
    uid = current_user["id"]
    error = None
    page_title = title or ""
    page_text = ""
    target_url = url or ""

    if text:
        # Selected text shared directly — no scraping needed
        page_text = text[:6000]
        # Use first non-empty line of selected text as title (usually the session name)
        first_line = next((l.strip() for l in text.splitlines() if l.strip()), "")
        page_title = first_line[:120] if first_line else (target_url or "Gedeelde tekst")
    elif target_url:
        try:
            page_title, page_text = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _scrape_url(target_url)
            )
        except Exception as e:
            tr = TRANSLATIONS[get_lang(request, uid)]
            error = f"{tr['err_fetch_failed']} {e}"

    db = get_db()
    prompts = db.execute("SELECT * FROM prompts WHERE user_id = ? ORDER BY id", (uid,)).fetchall()
    db.close()

    return templates.TemplateResponse(request, "from_url.html", {
        **_tctx(request, uid),
        "current_user": current_user,
        "target_url": target_url,
        "page_title": page_title,
        "page_text": page_text,
        "prompts": prompts,
        "error": error,
    })


@app.post("/from-url", response_class=HTMLResponse)
async def from_url_post(
    request: Request,
    current_user=Depends(get_current_user),
    _csrf=Depends(verify_csrf),
    target_url: str = Form(""),
    page_title: str = Form(""),
    page_text: str = Form(""),
    prompt_id: int = Form(None),
    user_prompt: str = Form(""),
):
    uid = current_user["id"]
    active_llm = get_setting("active_llm", uid) or "groq"

    db = get_db()
    prompt_text = ""
    if prompt_id:
        row = db.execute("SELECT prompt_text FROM prompts WHERE id = ? AND user_id = ?",
                         (prompt_id, uid)).fetchone()
        if row:
            prompt_text = row["prompt_text"]
    if user_prompt.strip():
        prompt_text = (prompt_text + "\n" + user_prompt).strip() if prompt_text else user_prompt

    from summary.generator import SYSTEM_PROMPT, html_to_text
    custom_system = get_setting("system_prompt", uid) or SYSTEM_PROMPT

    extra = f"\n\nBelangrijke instructies (hebben voorrang op de standaardinstellingen):\n{prompt_text}" if prompt_text else ""
    user_message = f"""Schrijf een LinkedIn post voor dit event dat ik ga bijwonen of heb bijgewoond.
Haal de relevante informatie (sprekers, thema's, locatie, datum) uit de onderstaande paginatekst.

URL: {target_url}
Paginatekst:
{page_text}{extra}"""

    try:
        t0 = _time.time()
        # Load LLM key into env if needed
        stored_key = get_setting(f"{active_llm}_api_key", uid)
        env_map = {"groq": "GROQ_API_KEY", "claude": "ANTHROPIC_API_KEY",
                   "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
        if stored_key and active_llm in env_map:
            os.environ[env_map[active_llm]] = stored_key

        from summary.generator import _generate_groq, _generate_gemini, _generate_claude, _generate_openai
        generators = {"groq": _generate_groq, "gemini": _generate_gemini,
                      "claude": _generate_claude, "openai": _generate_openai}
        post_text, input_tokens, output_tokens = await asyncio.get_event_loop().run_in_executor(
            None, lambda: generators[active_llm](user_message, custom_system)
        )
        generation_ms = int((_time.time() - t0) * 1000)
        cost_usd = calc_cost_usd(active_llm, input_tokens, output_tokens)

        cursor = db.execute(
            "INSERT INTO drafts (user_id, event_id, event_title, event_date, post_text, llm, provider, prompt_text, generation_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, target_url, page_title or target_url, None, post_text,
             active_llm, "url", prompt_text or "", generation_ms),
        )
        draft_id = cursor.lastrowid
        log_event(db, uid, "generate_ok", {
            "llm": active_llm, "provider": "url", "duration_ms": generation_ms,
            "draft_id": draft_id, "event_title": page_title,
            "input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost_usd,
        })
        db.commit()
        db.close()
        return RedirectResponse(f"/draft/{draft_id}", status_code=303)
    except Exception as e:
        db.close()
        prompts_list = []
        db2 = get_db()
        prompts_list = db2.execute("SELECT * FROM prompts WHERE user_id = ? ORDER BY id", (uid,)).fetchall()
        db2.close()
        lang = get_lang(request, uid)
        tr = TRANSLATIONS[lang]
        return templates.TemplateResponse(request, "from_url.html", {
            **_tctx(request, uid),
            "current_user": current_user,
            "target_url": target_url,
            "page_title": page_title,
            "page_text": page_text,
            "prompts": prompts_list,
            "error": f"{tr['err_generation_failed']} {_friendly_error(e, active_llm, lang)}",
        }, status_code=500)
