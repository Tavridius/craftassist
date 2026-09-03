"""Таймер Электрошторма на Кузне-11 (событие до 23.09.2026).

Спрос подтверждён Вебмастером и Метрикой: «как часто электрошторм», «какое кд
у электро-шторма», «отслеживание электро штормов» — люди ищут расписание, а не
описание (AUDIT-SEARCH-2026-09.md).

Игровой API события не отдаёт, поэтому считаем от якоря: админ один раз
отмечает момент старта шторма, дальше арифметика.

Цикл подтверждён КМ EXBO (forum.exbo.net/d/194405): «Раз в час — 30 минут
действует, 30 минут КД до следующего». Но там же: «если электрошторм по
длительности может наложиться на Выброс — электрошторм уступит Выбросу и не
начнётся, пока не пройдёт Выброс». Поэтому цикл сдвигается на каждом выбросе,
и на время выброса мы отсчёт прячем (paused), а не показываем неверный.
Игроки как раз из-за этого видели полуторачасовые дыры и решили, что
периодичность случайная.

Осознанно: **без якоря обратный отсчёт не показываем совсем**. Соврать со
временем хуже, чем не показать его — человек придёт на локацию впустую.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from app import config

logger = logging.getLogger(__name__)

PERIOD_SEC = 3600      # «возникает каждый час» — дословно из анонса
DURATION_SEC = 1800    # «и длится 30 минут»
UNTIL = "2026-09-23"   # последний день события


class EStorm:
    def __init__(self) -> None:
        self.anchor: datetime | None = None   # момент НАЧАЛА какого-то шторма, UTC

    @property
    def _path(self):
        return config.DATA_DIR / "estorm.json"

    def load(self) -> None:
        raw = (config.ESTORM_ANCHOR or "").strip()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8")).get("anchor") or raw
        except (OSError, ValueError):
            pass
        self.anchor = _parse(raw)
        if raw and not self.anchor:
            logger.warning("estorm: якорь %r не разобран, таймер выключен", raw)

    def save(self) -> None:
        try:
            self._path.write_text(
                json.dumps({"anchor": self.anchor.isoformat() if self.anchor else None}),
                encoding="utf-8")
        except OSError as e:
            logger.warning("estorm save failed: %s", e)

    def mark(self, iso: str | None = None) -> dict:
        """Отметить старт шторма. Пусто — «прямо сейчас»."""
        self.anchor = _parse(iso) if iso else datetime.now(timezone.utc)
        if iso and not self.anchor:
            raise ValueError("не разобрал время")
        self.save()
        return self.snapshot()

    def snapshot(self, now: datetime | None = None,
                 emission_active: bool = False) -> dict:
        """emission_active — прямо сейчас идёт Выброс. Тогда отсчёт не показываем:
        «если электрошторм по длительности может наложиться на Выброс —
        электрошторм уступит Выбросу и не начнётся, пока не пройдёт Выброс»
        (КМ EXBO, forum.exbo.net/d/194405). Цикл при этом сдвигается, и голая
        арифметика от якоря после каждого выброса врала бы.
        """
        now = now or datetime.now(timezone.utc)
        # событие кончается в конце дня 23.09 по МСК
        over = now > datetime.fromisoformat(UNTIL + "T23:59:59+03:00")
        out = {
            "until": UNTIL,
            "over": over,
            "period_min": PERIOD_SEC // 60,
            "duration_min": DURATION_SEC // 60,
            "known": False,
        }
        out["paused"] = bool(emission_active)
        if over or not self.anchor or emission_active:
            return out
        phase = (now - self.anchor).total_seconds() % PERIOD_SEC
        active = phase < DURATION_SEC
        left = DURATION_SEC - phase if active else PERIOD_SEC - phase
        out.update({
            "known": True,
            "active": active,
            "seconds_left": int(left),
            # абсолютный момент переключения — по нему фронт тикает без дрейфа
            # (полезная нагрузка главной кэшируется на минуту)
            "switch_at": (now + timedelta(seconds=left)).isoformat(),
            "next_start": (now + timedelta(seconds=PERIOD_SEC - phase)).isoformat(),
            "anchor": self.anchor.isoformat(),
        })
        return out


def _parse(raw) -> datetime | None:
    if not raw:
        return None
    try:
        t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


estorm = EStorm()
