"""The customer web chat service (runs next to the API, never inside it).

    uvicorn app.webchat.server:app --port 8100

Routes (public, no key in the browser). {code} is the company's QR code, a random string that is made,
replaced and revoked like a staff key (python -m app.webchat.qr new/revoke). The company name is never in the address:
    GET  /c/{code}            the chat page
    POST /c/{code}/session    starts a chat
    POST /c/{code}/message    one customer message in, one reply out
    GET  /c/{code}/qr.svg     the QR code that opens this page
    GET  /c/{code}/poster     a printable poster with the QR code

Each company's QR codes are listed in CHAT_CODE_<SLUG> (comma separated, in .env.chat). A code that is not listed
gives the same 404 as a wrong one, and guessing is rate limited. The company's own key (JARVIS_KEY_<SLUG>) stays on
this server. A chat can only ever use the key of the company its code belongs to, so one company's chat can never
reach another company's data. The service has no database password: it talks to the API like any other client.
"""
import hmac
import logging
import os
import re
import secrets
import threading
import time
import uuid
from datetime import date
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from app.agent import ChatSession, TurnFailed, find_phone, handoff, handoff_message
from app.privacy import install_log_redaction
from app.ratelimit import RateLimiter, reject
from app.webchat import qr
from app import languages
from app.webchat.guard import WEB_RULES, language_rules, parse_reply, web_tools
from app.webchat.page import PAGE

load_dotenv()
install_log_redaction()
log = logging.getLogger("webchat")

API_BASE = os.getenv("API_BASE_URL", os.getenv("JARVIS_API_BASE", "http://127.0.0.1:8000"))
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
CODE = re.compile(r"^[A-Za-z0-9_-]{12,64}$")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

message_limiter = RateLimiter("CHAT_MESSAGES_PER_MINUTE", 12, 60)
session_limiter = RateLimiter("CHAT_SESSIONS_PER_HOUR", 20, 3600)
bad_code_limiter = RateLimiter("CHAT_BAD_CODES_PER_MINUTE", 10, 60)
_lock = threading.Lock()
SESSIONS: dict = {}
DAILY: dict = {}
COMPANIES: dict = {}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def client_ip(request: Request) -> str:
    """Same rule as the API: only trust X-Forwarded-For from the right, as many hops as you own."""
    import ipaddress
    peer = request.client.host if request.client else "unknown"
    trusted = env_int("TRUSTED_PROXY_COUNT", 0)
    if trusted <= 0:
        return peer
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if len(parts) < trusted:
        return peer
    try:
        ipaddress.ip_address(parts[-trusted])
    except ValueError:
        return peer
    return parts[-trusted]


def company_key(slug: str):
    return os.getenv("JARVIS_KEY_" + slug.upper().replace("-", "_")) or None


def load_company(slug: str) -> dict:
    """The company's public settings, fetched with its own key. Cached for five minutes."""
    cached = COMPANIES.get(slug)
    if cached and cached[0] > time.time():
        return cached[1]
    key = company_key(slug)
    if not SLUG.match(slug) or not key:
        raise HTTPException(status_code=404, detail="This chat is not available.")
    try:
        r = httpx.get(API_BASE + "/company/me", headers={"X-API-Key": key}, timeout=10)
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="We could not start the chat. Please try again in a minute.") from None
    if r.status_code != 200:
        raise HTTPException(status_code=404, detail="This chat is not available.")
    COMPANIES[slug] = (time.time() + 300, r.json())
    return COMPANIES[slug][1]


def make_ai_session(company: dict, key: str, session_id: str) -> ChatSession:
    """Builds the AI for one chat. Tests replace this with a fake."""
    from google import genai
    from google.genai import types
    from app.agent import MODEL_TIMEOUT_MS, build_system_prompt

    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(timeout=MODEL_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)),
    )
    models = [os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()]
    for name in os.getenv("GEMINI_FALLBACK_MODELS", "").split(","):
        if name.strip() and name.strip() not in models:
            models.append(name.strip())
    log: list = []
    return ChatSession(
        client, build_system_prompt(company) + WEB_RULES + language_rules(company.get("chat_language") or "en-IN", company.get("chat_languages") or ["en-IN"]),
        web_tools(key, session_id, log), log, models,
        os.getenv("GEMINI_THINKING_LEVEL", "LOW").strip().upper(),
    )


FACTORY = make_ai_session




class Message(BaseModel):
    session: str = Field(min_length=10, max_length=80)
    text: str = Field(min_length=1, max_length=500)


def sweep() -> None:
    now = time.time()
    for token in [t for t, s in SESSIONS.items() if s["expires"] < now]:
        SESSIONS.pop(token, None)


def page_headers(nonce: str) -> dict:
    return {
        "Content-Security-Policy": (
            "default-src 'none'; "
            f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        ),
        "Cache-Control": "no-store",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def active_codes() -> list:
    """(code, slug) for every QR code listed in CHAT_CODE_<SLUG>, for companies that have a key."""
    found = []
    for name, value in os.environ.items():
        if not name.startswith("CHAT_CODE_"):
            continue
        slug = name[len("CHAT_CODE_"):].lower().replace("_", "-")
        if not SLUG.match(slug) or not company_key(slug):
            continue
        for item in value.split(","):
            item = item.strip()
            if CODE.match(item):
                found.append((item, slug))
    return found


def resolve(code: str, request: Request) -> str:
    """The company of a QR code. Wrong, revoked and made-up codes all give the same 404, and guessing is limited."""
    ip = client_ip(request)
    wait = bad_code_limiter.retry_after(ip)
    if wait:
        reject(wait)
    match = None
    if CODE.match(code or ""):
        for known, slug in active_codes():                     # compare every code in constant time
            if hmac.compare_digest(known.encode(), code.encode()):
                match = slug
    if match is None:
        bad_code_limiter.hit(ip)
        raise HTTPException(status_code=404, detail="This chat is not available.")
    return match


def offered_languages() -> list:
    """CHAT_LANGUAGES, first = default. A wrong setting is logged and the chat falls back to English instead of breaking."""
    try:
        return languages.chat_languages()
    except SystemExit as exc:
        log.error("%s Falling back to English only.", exc)
        return ["en-IN"]


@app.get("/c/{code}", response_class=HTMLResponse, include_in_schema=False)
def chat_page(code: str, request: Request):
    import html
    import json as _json
    resolve(code, request)
    nonce = secrets.token_urlsafe(16)
    offered = offered_languages()
    listing = html.escape(_json.dumps([[c, languages.native_name(c)] for c in offered]), quote=True)
    page = PAGE.replace("__NONCE__", nonce).replace("__CODE__", code).replace("__LANGS__", listing).replace("__LANG__", offered[0])
    return HTMLResponse(page, headers=page_headers(nonce))


class Start(BaseModel):
    lang: Optional[str] = Field(default=None, max_length=12)


@app.post("/c/{code}/session")
def start_session(code: str, request: Request, body: Optional[Start] = None):
    slug = resolve(code, request)
    ip = client_ip(request)
    wait = session_limiter.retry_after(ip)
    if wait:
        reject(wait)
    session_limiter.hit(ip)
    offered = offered_languages()
    chosen = languages.normalise(body.lang) if body and body.lang else None
    company = {**load_company(slug), "chat_language": chosen if chosen in offered else offered[0], "chat_languages": offered}
    token = secrets.token_urlsafe(24)
    session_id = uuid.uuid4().hex
    try:
        ai = FACTORY(company, company_key(slug), session_id)
    except Exception:                                    # for example GEMINI_API_KEY missing: say so in the log, not to the customer
        log.exception("could not start the AI for %s", slug)
        raise HTTPException(status_code=503, detail="We could not start the chat. Please try again in a minute.") from None
    minutes = env_int("CHAT_SESSION_MINUTES", 30)
    with _lock:
        sweep()
        if len(SESSIONS) > env_int("CHAT_MAX_SESSIONS", 500):
            raise HTTPException(status_code=429, detail="Too many chats right now. Try again in a few minutes.")
        SESSIONS[token] = {
            "slug": slug, "code": code, "ai": ai, "session_id": session_id, "turns": 0, "phone": None,
            "expires": time.time() + minutes * 60, "busy": False,
        }
    call = os.getenv("CHAT_PHONE_" + slug.upper().replace("-", "_"), "")
    return JSONResponse(
        {"session": token, "name": company["name"], "agent": company["agent_name"],
         "country": os.getenv("CHAT_COUNTRY_CODE", "+91"), "phone": call if re.fullmatch(r"\+?[0-9]{6,15}", call) else ""},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/c/{code}/message")
async def message(code: str, body: Message, request: Request):
    slug = resolve(code, request)
    ip = client_ip(request)
    wait = message_limiter.retry_after(ip)
    if wait:
        reject(wait)
    message_limiter.hit(ip)

    with _lock:
        s = SESSIONS.get(body.session)
        # A chat only works on the QR code it was started from, so a token can never be used for another code or company.
        if s is None or s["code"] != code or s["slug"] != slug or s["expires"] < time.time():
            raise HTTPException(status_code=410, detail="This chat has ended.")
        if s["busy"]:
            raise HTTPException(status_code=409, detail="Please wait for the reply first.")
        if s["turns"] >= env_int("CHAT_MAX_TURNS", 40):
            raise HTTPException(status_code=429, detail="This chat is full. Please call us or start a new chat.")
        key = (slug, date.today().isoformat())
        for old in [k for k in DAILY if k[1] != key[1]]:     # yesterday's counters are not needed
            DAILY.pop(old, None)
        if DAILY.get(key, 0) >= env_int("CHAT_DAILY_MESSAGES", 800):
            raise HTTPException(status_code=429, detail="Our chat is very busy today. Please call us instead.")
        DAILY[key] = DAILY.get(key, 0) + 1
        s["busy"] = True
        s["turns"] += 1
        s["expires"] = time.time() + env_int("CHAT_SESSION_MINUTES", 30) * 60

    try:
        found = find_phone(body.text)
        if found:
            s["phone"] = found
        try:
            answer, _model = await run_in_threadpool(s["ai"].send, body.text)
        except TurnFailed:
            result = await run_in_threadpool(handoff, company_key(slug), body.text, s["phone"], s["session_id"])
            answer = handoff_message(result)
        except Exception:                                # a bug must not show the customer an error page or lose their request
            log.exception("chat turn failed for %s", slug)
            result = await run_in_threadpool(handoff, company_key(slug), body.text, s["phone"], s["session_id"])
            answer = handoff_message(result)
    finally:
        s["busy"] = False

    words, ask, choices = parse_reply(answer)
    return JSONResponse({"reply": words, "ask": ask, "choices": choices}, headers={"Cache-Control": "no-store"})


@app.get("/c/{code}/qr.svg", include_in_schema=False)
def qr_svg(code: str, request: Request):
    resolve(code, request)
    try:
        url = qr.public_url(code)
    except ValueError:
        raise HTTPException(status_code=503, detail="PUBLIC_BASE_URL is not set.") from None
    return Response(qr.svg_bytes(url), media_type="image/svg+xml", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/c/{code}/poster", response_class=HTMLResponse, include_in_schema=False)
def poster(code: str, request: Request):
    slug = resolve(code, request)
    try:
        url = qr.public_url(code)
    except ValueError:
        raise HTTPException(status_code=503, detail="PUBLIC_BASE_URL is not set.") from None
    import html
    company = load_company(slug)
    nonce = secrets.token_urlsafe(16)
    svg = qr.svg_bytes(url).decode()
    page = (qr.POSTER.replace("__NONCE__", nonce).replace("__NAME__", html.escape(company["name"]))
            .replace("__URL__", html.escape(url)).replace("__SVG__", svg))
    return HTMLResponse(page, headers=page_headers(nonce))


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
