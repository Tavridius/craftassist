"""Авторизация пользователей: локальная (email+пароль) и EXBO OAuth 2.0.

Локальная (форма на сайте, AJAX):
  POST /auth/register        → регистрация email+пароль → сессия (+ письмо-подтверждение)
  POST /auth/signin          → вход по email/нику + пароль → сессия
  POST /auth/reset           → запрос ссылки сброса пароля на email
  POST /auth/reset/confirm   → задать новый пароль по токену из письма
  GET  /auth/verify          → подтверждение email по ссылке из письма

EXBO OAuth (редиректы, аккаунт создаётся автоматически, без регистрации):
  GET  /auth/login           → редирект на exbo.net/oauth/authorize (state в куке)
  GET  /auth/callback        → код → user-токен → /oauth/user → upsert + сессия

Общее:
  POST /auth/logout          → удалить сессию, погасить куку
  GET  /api/me               → кто я + флаги (auth_enabled/oauth_enabled/mail_enabled)

EXBO использует те же клиентские креды, что и app-токен (API_CLIENT_ID/SECRET).
Токены EXBO пользователя НЕ храним. Локальная авторизация работает всегда,
даже без кред EXBO.
"""
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from app import config
from app.db import users
from app.services import mailer

logger = logging.getLogger(__name__)
router = APIRouter()

SESSION_COOKIE = "sz_session"
STATE_COOKIE = "sz_oauth_state"

# --- простой антибрутфорс по IP (в памяти, окно 15 мин) ---
_ATTEMPTS: dict[str, list[float]] = {}
_ATTEMPT_WINDOW = 900
_ATTEMPT_MAX = 10


def oauth_enabled() -> bool:
    """EXBO-вход доступен только при заданных клиентских кредах."""
    return bool(config.API_CLIENT_ID and config.API_CLIENT_SECRET)


def current_user(request: Request) -> dict | None:
    """Пользователь текущей сессии (по куке) — для других роутеров."""
    return users.user_by_session(request.cookies.get(SESSION_COOKIE, ""))


def is_admin(user: dict | None) -> bool:
    """Админ по exbo_id (ADMIN_USER_IDS) или по email (ADMIN_EMAILS)."""
    if not user:
        return False
    return (user.get("exbo_id") in config.ADMIN_USER_IDS
            or (user.get("email") or "").lower() in config.ADMIN_EMAILS)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _rate_ok(key: str) -> bool:
    now = time.time()
    hits = [t for t in _ATTEMPTS.get(key, []) if now - t < _ATTEMPT_WINDOW]
    hits.append(now)
    _ATTEMPTS[key] = hits
    return len(hits) <= _ATTEMPT_MAX


def _redirect_uri(request: Request) -> str:
    """Внешний адрес callback: из конфига (прод, за прокси) или из запроса (локально)."""
    return config.OAUTH_REDIRECT_URI or str(request.url_for("auth_callback"))


def _app_root() -> str:
    return (config.PUBLIC_BASE_URL + "/") if config.PUBLIC_BASE_URL else "/"


def _base_url(request: Request) -> str:
    return config.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")


def _secure(request: Request) -> bool:
    base = config.PUBLIC_BASE_URL or str(request.base_url)
    return base.startswith("https://")


def _set_session(resp, request: Request, user_id: int) -> None:
    token = users.create_session(user_id)
    resp.set_cookie(SESSION_COOKIE, token, max_age=config.SESSION_TTL_DAYS * 86400,
                    httponly=True, samesite="lax", secure=_secure(request), path="/")


def _me_payload(user: dict | None) -> dict:
    base = {"auth_enabled": True, "oauth_enabled": oauth_enabled(),
            "mail_enabled": mailer.enabled()}
    if not user:
        return {**base, "authenticated": False}
    prof = users.get_profile(user["id"])
    return {**base, "authenticated": True, "user": user, "is_admin": is_admin(user),
            "email_verified": user.get("email_verified", True),
            "profile_empty": not (prof.get("perks") or prof.get("features"))}


# ---------- локальная авторизация ----------

class RegisterIn(BaseModel):
    email: str
    password: str
    login: str


class SigninIn(BaseModel):
    ident: str
    password: str


class ResetReqIn(BaseModel):
    email: str


class ResetConfirmIn(BaseModel):
    token: str
    password: str


async def _send_verify_email(request: Request, user_id: int, email: str) -> None:
    if not mailer.enabled():
        return
    token = users.create_email_token(user_id, "verify")
    link = f"{_base_url(request)}/auth/verify?token={token}"
    await mailer.send_verify(email, link)


@router.post("/auth/register")
async def register(request: Request, body: RegisterIn):
    if not _rate_ok("reg:" + _client_ip(request)):
        return JSONResponse({"error": "Слишком много попыток, попробуйте позже"}, 429)
    try:
        uid = users.create_local_user(body.email, body.password, body.login)
    except users.AuthError as e:
        return JSONResponse({"error": str(e)}, 400)
    await _send_verify_email(request, uid, body.email.strip().lower())
    resp = JSONResponse({"ok": True, "new": True,
                         "user": {"login": body.login.strip(),
                                  "display_login": body.login.strip()},
                         "mail_sent": mailer.enabled()})
    _set_session(resp, request, uid)
    logger.info("auth: local register ok (%s)", body.login.strip())
    return resp


@router.post("/auth/signin")
async def signin(request: Request, body: SigninIn):
    if not _rate_ok("login:" + _client_ip(request)):
        return JSONResponse({"error": "Слишком много попыток, попробуйте позже"}, 429)
    user = users.authenticate_local(body.ident, body.password)
    if not user:
        return JSONResponse({"error": "Неверный логин или пароль"}, 401)
    resp = JSONResponse({"ok": True, "new": False,
                         "user": {"login": user["login"],
                                  "display_login": user["display_login"]}})
    _set_session(resp, request, user["id"])
    logger.info("auth: local signin ok (%s)", user["login"])
    return resp


@router.post("/auth/reset")
async def reset_request(request: Request, body: ResetReqIn):
    """Запрос сброса. Ответ всегда 200 (не раскрываем, есть ли такой email)."""
    if not _rate_ok("reset:" + _client_ip(request)):
        return JSONResponse({"error": "Слишком много попыток, попробуйте позже"}, 429)
    if not mailer.enabled():
        return JSONResponse({"error": "Сброс пароля временно недоступен"}, 503)
    user = users.user_by_email(body.email)
    if user:
        token = users.create_email_token(user["id"], "reset")
        link = f"{_app_root()}?reset={token}"
        await mailer.send_reset(user["email"], link)
    return {"ok": True}


@router.post("/auth/reset/confirm")
async def reset_confirm(request: Request, body: ResetConfirmIn):
    uid = users.consume_email_token(body.token, "reset")
    if not uid:
        return JSONResponse({"error": "Ссылка недействительна или устарела"}, 400)
    try:
        users.set_password(uid, body.password)
    except users.AuthError as e:
        return JSONResponse({"error": str(e)}, 400)
    users.mark_email_verified(uid)  # доступ к почте доказан
    resp = JSONResponse({"ok": True})
    _set_session(resp, request, uid)
    logger.info("auth: password reset ok (user %s)", uid)
    return resp


@router.get("/auth/verify")
async def verify_email(request: Request, token: str = ""):
    uid = users.consume_email_token(token, "verify")
    if uid:
        users.mark_email_verified(uid)
        return RedirectResponse(_app_root() + "#auth=verified", status_code=302)
    return RedirectResponse(_app_root() + "#auth=verify_failed", status_code=302)


# ---------- EXBO OAuth ----------

def _fail() -> RedirectResponse:
    return RedirectResponse(_app_root() + "#auth=error", status_code=302)


@router.get("/auth/login")
async def auth_login(request: Request):
    if not oauth_enabled():
        return JSONResponse(
            {"error": "вход через EXBO выключен: не заданы API_CLIENT_ID/API_CLIENT_SECRET"},
            status_code=503)
    state = secrets.token_urlsafe(16)
    q = urlencode({
        "client_id": config.API_CLIENT_ID,
        "redirect_uri": _redirect_uri(request),
        "scope": "",
        "response_type": "code",
        "state": state,
    })
    resp = RedirectResponse(f"{config.OAUTH_AUTHORIZE_URL}?{q}", status_code=302)
    resp.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True,
                    samesite="lax", secure=_secure(request), path="/")
    return resp


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, code: str = "", state: str = ""):
    saved = request.cookies.get(STATE_COOKIE, "")
    if not (oauth_enabled() and code and state and saved
            and secrets.compare_digest(saved, state)):
        logger.warning("auth: callback rejected (bad state or no code)")
        return _fail()
    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            tok = await client.post(config.OAUTH_TOKEN_URL, data={
                "client_id": config.API_CLIENT_ID,
                "client_secret": config.API_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": _redirect_uri(request),
            })
            if tok.status_code != 200:
                logger.error("auth: token exchange -> HTTP %s: %s",
                             tok.status_code, tok.text[:200])
                return _fail()
            access = tok.json().get("access_token", "")
            info = await client.get(config.OAUTH_USERINFO_URL,
                                    headers={"Authorization": f"Bearer {access}"})
            if info.status_code != 200:
                logger.error("auth: userinfo -> HTTP %s: %s",
                             info.status_code, info.text[:200])
                return _fail()
            profile = info.json()
    except Exception:
        logger.exception("auth: callback failed")
        return _fail()

    uid, created = users.upsert_user(profile)
    logger.info("auth: EXBO login ok %s (exbo id=%s, new=%s)",
                profile.get("login"), profile.get("id"), created)
    # маркер для фронта: цель Я.Метрики (signup для новых, login для вернувшихся)
    resp = RedirectResponse(
        _app_root() + ("#auth=signup" if created else "#auth=login"), status_code=302)
    resp.delete_cookie(STATE_COOKIE, path="/")
    _set_session(resp, request, uid)
    return resp


# ---------- общее ----------

@router.post("/auth/logout")
async def auth_logout(request: Request):
    users.delete_session(request.cookies.get(SESSION_COOKIE, ""))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/api/me")
async def me(request: Request):
    return _me_payload(current_user(request))
