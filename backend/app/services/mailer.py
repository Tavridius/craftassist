"""Отправка транзакционных писем (подтверждение email, сброс пароля) по SMTP.

Пока SMTP не сконфигурирован (SMTP_HOST/MAIL_FROM пусты) — enabled()=False,
письма молча не отправляются: регистрация всё равно работает, аккаунт активен
сразу, просто без подтверждения email и без сброса пароля. Настройка почтового
сервера на домене — см. DEPLOY.md.
"""
import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app import config

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(config.SMTP_HOST and config.MAIL_FROM)


def _send_sync(to: str, subject: str, text: str, html: str | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = formataddr((config.MAIL_FROM_NAME, config.MAIL_FROM))
    msg["To"] = to
    msg["Subject"] = subject
    # Date обязателен по RFC 5322, Message-ID де-факто обязателен. smtplib их не
    # добавляет. Без Date фильтр на MTA (amavis) режет письмо как BAD-HEADER ещё
    # до отправки наружу: проверено 06.08.2026 на своём сервере — письмо без Date
    # ушло в карантин, оно же с Date прошло CLEAN и доехало до Gmail.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=config.MAIL_FROM.split("@")[-1] or None)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    if config.SMTP_SECURITY == "ssl":
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20,
                              context=ctx) as s:
            _auth_send(s, msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.ehlo()
            if config.SMTP_SECURITY == "starttls":
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
            _auth_send(s, msg)


def _auth_send(s: smtplib.SMTP, msg: EmailMessage) -> None:
    if config.SMTP_USER:
        s.login(config.SMTP_USER, config.SMTP_PASS)
    s.send_message(msg)


async def send(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Отправить письмо в пуле потоков (smtplib блокирующий). best-effort."""
    if not enabled():
        logger.info("mailer disabled — письмо '%s' для %s не отправлено", subject, to)
        return False
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, _send_sync, to, subject, text, html)
        logger.info("mailer: sent '%s' -> %s", subject, to)
        return True
    except Exception:
        logger.exception("mailer: send failed -> %s", to)
        return False


# ---------- конкретные письма ----------

async def send_verify(email: str, link: str) -> bool:
    text = (
        "Привет!\n\n"
        "Ты зарегистрировался на StalZone Helper. Подтверди адрес, перейдя по ссылке:\n"
        f"{link}\n\n"
        "Если это был не ты — просто проигнорируй письмо.\n"
        "— StalZone Helper")
    html = (
        f"<p>Привет!</p><p>Ты зарегистрировался на <b>StalZone Helper</b>. "
        f"Подтверди адрес:</p>"
        f'<p><a href="{link}">Подтвердить email</a></p>'
        f"<p style='color:#888;font-size:12px'>Если это был не ты — проигнорируй письмо.</p>")
    return await send(email, "Подтверждение email — StalZone Helper", text, html)


async def send_reset(email: str, link: str) -> bool:
    text = (
        "Запрошен сброс пароля на StalZone Helper.\n\n"
        f"Задай новый пароль по ссылке (действует ограниченное время):\n{link}\n\n"
        "Если ты не запрашивал сброс — просто проигнорируй письмо, пароль не изменится.\n"
        "— StalZone Helper")
    html = (
        "<p>Запрошен сброс пароля на <b>StalZone Helper</b>.</p>"
        f'<p><a href="{link}">Задать новый пароль</a></p>'
        "<p style='color:#888;font-size:12px'>Ссылка действует ограниченное время. "
        "Если это был не ты — проигнорируй письмо.</p>")
    return await send(email, "Сброс пароля — StalZone Helper", text, html)
