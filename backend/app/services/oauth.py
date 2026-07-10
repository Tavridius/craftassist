"""Получение app-токена по client credentials (OAuth-сервер EXBO).

Если заданы API_CLIENT_ID/API_CLIENT_SECRET — бэкенд сам обменивает их на app-токен
и обновляет его до истечения. Статический API_TOKEN остаётся как fallback (демо-режим).
Токен кэшируется в data/app_token.json — переживает рестарт контейнера.
"""
import json
import logging
import time

import httpx

from app import config

logger = logging.getLogger(__name__)

_token: str = ""
_expires_at: float = 0.0
_last_attempt: float = 0.0
_MARGIN = 3600           # обновлять за час до истечения
_RETRY_COOLDOWN = 60     # не долбить token-endpoint чаще раза в минуту при ошибках


def enabled() -> bool:
    return bool(config.API_CLIENT_ID and config.API_CLIENT_SECRET)


def token() -> str:
    """Текущий живой app-токен ("" — не получен или истёк)."""
    return _token if time.time() < _expires_at else ""


def invalidate() -> None:
    """Сбросить токен (напр. после 401) — следующий ensure() получит новый."""
    global _expires_at
    _expires_at = 0.0


def _path():
    return config.DATA_DIR / "app_token.json"


def load() -> None:
    global _token, _expires_at
    try:
        if _path().exists():
            d = json.loads(_path().read_text(encoding="utf-8"))
            _token, _expires_at = d.get("access_token", ""), float(d.get("expires_at", 0))
            if token():
                logger.info("oauth: loaded cached app token, valid %.1fh",
                            (_expires_at - time.time()) / 3600)
    except Exception:
        logger.exception("oauth: failed to load cached token")


async def ensure(client: httpx.AsyncClient) -> None:
    """Убедиться, что app-токен свеж; при необходимости обменять креды на новый."""
    global _token, _expires_at, _last_attempt
    if not enabled() or time.time() < _expires_at - _MARGIN:
        return
    if time.time() - _last_attempt < _RETRY_COOLDOWN:
        return
    _last_attempt = time.time()
    try:
        resp = await client.post(config.OAUTH_TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": config.API_CLIENT_ID,
            "client_secret": config.API_CLIENT_SECRET,
            "scope": "",
        }, timeout=20.0)
        if resp.status_code != 200:
            logger.error("oauth: token request -> HTTP %s: %s",
                         resp.status_code, resp.text[:200])
            return
        d = resp.json()
        _token = d["access_token"]
        _expires_at = time.time() + float(d.get("expires_in", 3600))
        _path().write_text(json.dumps({"access_token": _token, "expires_at": _expires_at}),
                           encoding="utf-8")
        logger.info("oauth: obtained app token, expires in %.1f days",
                    (_expires_at - time.time()) / 86400)
    except Exception:
        logger.exception("oauth: token request failed")
