"""Авторизация пользователей: OAuth 2.0 (authorization code) через аккаунт EXBO.

GET  /auth/login     → редирект на exbo.net/oauth/authorize (+ state в куке от CSRF)
GET  /auth/callback  → код → user-токен → GET /oauth/user → upsert в БД + сессия в куке
POST /auth/logout    → удалить сессию, погасить куку
GET  /api/me         → кто я (шапка фронта)

Использует те же клиентские креды, что и app-токен (API_CLIENT_ID/SECRET).
Токены EXBO пользователя НЕ храним — после получения профиля они выбрасываются,
живёт только наша серверная сессия (db/users.py).
"""
import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import config
from app.db import users

logger = logging.getLogger(__name__)
router = APIRouter()

SESSION_COOKIE = "sz_session"
STATE_COOKIE = "sz_oauth_state"


def enabled() -> bool:
    return bool(config.API_CLIENT_ID and config.API_CLIENT_SECRET)


def current_user(request: Request) -> dict | None:
    """Пользователь текущей сессии (по куке) — для других роутеров."""
    return users.user_by_session(request.cookies.get(SESSION_COOKIE, ""))


def _redirect_uri(request: Request) -> str:
    """Внешний адрес callback: из конфига (прод, за прокси) или из запроса (локально)."""
    return config.OAUTH_REDIRECT_URI or str(request.url_for("auth_callback"))


def _app_root() -> str:
    return (config.PUBLIC_BASE_URL + "/") if config.PUBLIC_BASE_URL else "/"


def _secure(request: Request) -> bool:
    base = config.PUBLIC_BASE_URL or str(request.base_url)
    return base.startswith("https://")


def _fail() -> RedirectResponse:
    return RedirectResponse(_app_root() + "#auth=error", status_code=302)


@router.get("/auth/login")
async def auth_login(request: Request):
    if not enabled():
        return JSONResponse(
            {"error": "авторизация выключена: не заданы API_CLIENT_ID/API_CLIENT_SECRET"},
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
    if not (enabled() and code and state and saved
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

    uid = users.upsert_user(profile)
    token = users.create_session(uid)
    logger.info("auth: login ok %s (exbo id=%s)", profile.get("login"), profile.get("id"))
    resp = RedirectResponse(_app_root(), status_code=302)
    resp.delete_cookie(STATE_COOKIE, path="/")
    resp.set_cookie(SESSION_COOKIE, token, max_age=config.SESSION_TTL_DAYS * 86400,
                    httponly=True, samesite="lax", secure=_secure(request), path="/")
    return resp


@router.post("/auth/logout")
async def auth_logout(request: Request):
    users.delete_session(request.cookies.get(SESSION_COOKIE, ""))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/api/me")
async def me(request: Request):
    user = users.user_by_session(request.cookies.get(SESSION_COOKIE, ""))
    if not user:
        return {"authenticated": False, "auth_enabled": enabled()}
    prof = users.get_profile(user["id"])
    return {"authenticated": True, "auth_enabled": True, "user": user,
            "is_admin": user["exbo_id"] in config.ADMIN_USER_IDS,
            "profile_empty": not (prof.get("perks") or prof.get("features"))}
