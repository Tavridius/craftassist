#!/usr/bin/env python3
"""Проверка фикса пиков на реальных сценариях из данных прода.

Берём настоящие наблюдённые выбросы (замер 30.07.2026) и гоняем через
finalize_buckets + агрегацию окна: старое поведение против нового.
"""
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, r"d:\stalzone craft\backend")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import config                                    # noqa: E402
from app.services.artefact_watch import finalize_buckets   # noqa: E402

K = (2, 0)          # (qlt, ptn) — ключ корзины, для теста неважно
OK = FAIL = 0


def check(name, got, want, tol=0.15):
    global OK, FAIL
    good = abs(got - want) <= abs(want) * tol
    print(f"  {'OK  ' if good else 'FAIL'} {name}: получили {got:,.0f}, ждали ~{want:,.0f}")
    if good:
        OK += 1
    else:
        FAIL += 1


def window_avg(slots):
    """Агрегация окна как в market.AVG_SQL: средневзвешенная по медианам слотов."""
    num = sum(s["med"] * s["n"] for s in slots)
    den = sum(s["n"] for s in slots)
    return num / den


def old_window_avg(slots):
    """Прежняя агрегация: SUM(sum)/SUM(n)."""
    return sum(s["sum"] for s in slots) / sum(s["n"] for s in slots)


print("=== 1. «Репях»: одна сделка 15.5 млн при устоявшейся цене 10 185 ===")
ref = {K: 10_185.0}
b_old = finalize_buckets({K: [15_497_892.0]})            # опоры нет — резерв по минимуму
b_new = finalize_buckets({K: [15_497_892.0]}, ref)       # опора есть — коридор
print(f"  без опоры (как было): med={b_old[K]['med']:,.0f}  n={b_old[K]['n']}")
print(f"  с опорой (как стало): корзина в слот НЕ записана" if K not in b_new
      else f"  с опорой: med={b_new[K]['med']:,.0f}")
check("разовая сделка вне коридора не пишется вовсе", 0 if K not in b_new else 1, 0, tol=0.01)
week = [{"med": 10_185.0, "sum": 10_185.0 * 300, "n": 300}] * 6
spike_old = {"med": b_old[K]["med"], "sum": b_old[K]["sum"], "n": b_old[K]["n"]}
check("окно после фикса (выброса в данных нет)", window_avg(week), 10_185, tol=0.01)
check("то же прежним поведением (для сравнения)",
      old_window_avg(week + [spike_old]), 18_785, tol=0.05)

print("\n=== 2. Перевод валюты: 3 завышенные сделки в слоте, цена корзины 70 000 ===")
ref = {K: 70_000.0}
units = [69_500.0, 71_000.0, 70_200.0, 20_000_000.0, 20_100_000.0, 19_900_000.0]
b_old = finalize_buckets({K: units})
b_new = finalize_buckets({K: units}, ref)
print(f"  было: n={b_old[K]['n']} med={b_old[K]['med']:,.0f} (кап = min×{config.ART_OUTLIER_FACTOR:g})")
print(f"  стало: n={b_new[K]['n']} med={b_new[K]['med']:,.0f}")
check("новое: завышенные отброшены, медиана корзины", b_new[K]["med"], 70_200, tol=0.02)
check("новое: осталось только 3 честные сделки", b_new[K]["n"], 3, tol=0.01)

print("\n=== 3. Дешёвый слив (низкий выброс) не должен тянуть цену вниз ===")
ref = {K: 70_000.0}
units = [70_000.0, 69_000.0, 71_000.0, 500.0]     # 500 — подарок/ошибка
b_old = finalize_buckets({K: units})
b_new = finalize_buckets({K: units}, ref)
print(f"  было: n={b_old[K]['n']} med={b_old[K]['med']:,.0f}  (кап от min=500 -> {500*config.ART_OUTLIER_FACTOR:,.0f})")
print(f"  стало: n={b_new[K]['n']} med={b_new[K]['med']:,.0f}")
check("новое: слив отброшен снизу", b_new[K]["med"], 70_000, tol=0.02)

print("\n=== 4. Реальный сдвиг цены (патч): вся выборка ушла — должна пройти ===")
ref = {K: 10_000.0}
units = [80_000.0, 82_000.0, 79_000.0, 81_000.0]      # все вне коридора
b_new = finalize_buckets({K: units}, ref)
check("выборка сохранена целиком", b_new[K]["n"], 4, tol=0.01)
check("медиана = новая цена", b_new[K]["med"], 80_500, tol=0.02)

print("\n=== 5. Медиана внутри слота устойчива к одной сделке ===")
ref = {K: 8_500.0}
units = [8_400.0, 8_600.0, 8_500.0, 8_450.0, 33_000.0]   # 33k внутри коридора (×4)
b = finalize_buckets({K: units}, ref)
print(f"  n={b[K]['n']}  med={b[K]['med']:,.0f}  "
      f"средняя слота={b[K]['sum'] / b[K]['n']:,.0f}")
check("медиана слота не сдвинулась", b[K]["med"], 8_500, tol=0.02)
print("  (средняя слота при этом уехала бы — поэтому окно считается по медианам)")

print("\n=== 6. Перевод валюты в 4 сделки: объём есть, но масштаб выдаёт ===")
# наблюдённый случай: «Комета» x104 при n=4 — объёма мало, чтобы поверить в сдвиг
ref = {K: 100_000.0}
units = [10_400_000.0, 10_500_000.0, 10_300_000.0, 10_450_000.0]
b = finalize_buckets({K: units}, ref)
check("слот не записан несмотря на n=4", 0 if K not in b else 1, 0, tol=0.01)

print("\n=== 7. Умеренный сдвиг с объёмом — принимается ===")
ref = {K: 100_000.0}
units = [600_000.0, 610_000.0, 590_000.0, 605_000.0]      # x6: вне коридора, но < x10
b = finalize_buckets({K: units}, ref)
check("сдвиг x6 при n=4 принят", b[K]["n"] if K in b else 0, 4, tol=0.01)
check("медиана = новый уровень", b[K]["med"] if K in b else 0, 602_500, tol=0.02)

print(f"\n{'='*60}\nOK: {OK}   FAIL: {FAIL}")
sys.exit(1 if FAIL else 0)
