"""Нормализация текста для поиска по сайту (db.search, гайды).

Сравниваем не строки как есть, а «сжатую» форму: нижний регистр, ё→е, латиница,
похожая на кириллицу, сведена к кириллице (M4A1 и «м4» — одно и то же), всё, кроме
букв и цифр, выброшено (АК-12 = «ак 12» = «ак12», 9x39 = «9*39»). Где начинались и
кончались слова, запоминаем отдельно: по этому совпадение с начала слова идёт выше
совпадения внутри слова («ухо» — сначала «Ухо …», потом «Кухонный стол»).

Откуда правила: промахи поиска из Метрики (июль–октябрь 2026, ~1600 разных
запросов). Помимо «ак12», «м4», «калаш» там сотни запросов в английской раскладке
(«cjk» = «сол», «c[hj» = «схро») и опечаток («сывортка», «колиматор») — для них
подмена раскладки и нечёткое сравнение, но только когда прямой поиск не нашёл.
"""
import re
from typing import NamedTuple

# тиры совпадения: меньше — выше в выдаче. Опечатка с начала слова (FUZZY) выше
# подстроки из середины слова (INNER): «кефлар» — это «Кевлар», а не что-то с «фла».
EXACT, PREFIX, WORD, WORDS, SYN, FUZZY, INNER = range(7)

# латиница, которая на вид как кириллица: в названиях встречается «Tяжелый» с
# латинской T, а в запросах — «m4» и «м4» вперемешку. Сводим к кириллице.
_LOOKALIKE = str.maketrans("abcehkmoptxyё", "авсенкмортхуе")
_WORD_RE = re.compile(r"[^\W_]+")
_DIGIT_X_RE = re.compile(r"(?<=\d)х(?=\d)")   # 9х39, 12х76 — «х» как разделитель

# раскладка: набрали по-русски на английской (и наоборот)
_EN = "`qwertyuiop[]asdfghjkl;'zxcvbnm,./{}:\"<>"
_RU = "ёйцукенгшщзхъфывапролджэячсмитьбю.хъжэбю"
_EN2RU = str.maketrans(_EN, _RU)
_RU2EN = str.maketrans(dict(zip(_RU[:34], _EN[:34])))
_LAT_RE = re.compile(r"[a-z]")
_CYR_RE = re.compile(r"[а-яё]")

# Сленг и игровые прозвища → как предмет называется в базе. Ключ — начало запроса
# (калаш, калашников, калаши); значения ищутся ЦЕЛЫМ словом (иначе «ак» поймает
# «Аккумулятор»), «*» в конце — началом слова (mp7 → «MP7A2»).
SLANG: dict[str, tuple[str, ...]] = {
    "калаш": ("ак", "акс", "акм"),
    "ксюх": ("акс 74у",),
    "ксюш": ("акс 74у",),
    "весло": ("свд",),
    "мосинк": ("мосина",),
    "трехлин": ("мосина",),
    "стечкин": ("апс",),
    "макаров": ("пм", "пмм"),
    "макарыч": ("пм", "пмм"),
    "токарев": ("тт",),
    "граник": ("рпг 7",),
    "дигл": ("desert eagle",),
    "глок": ("glock",),
    "узи": ("uzi",),
    "скар": ("scar",),
    "ауг": ("aug",),
    "вектор": ("vector",),
    "фамас": ("famas*",),
    "мп5": ("mp5*",),
    "мп7": ("mp7*",),
    "умп": ("ump*",),
    "кольт": ("colt",),
    "питон": ("python",),
    "спас": ("spas*",),
    "моссберг": ("mossberg",),
    "винчестер": ("winchester",),
    "беретт": ("beretta",),
    "маузер": ("mauser",),
    "скорпион": ("scorpion", "skorpion"),
    "броник": ("бронежилетом", "бронекостюм"),
    "комбез": ("комбинезон",),
    "экзач": ("экзоброня", "экзоскелет"),
    "глушак": ("глушитель",),
    "ночник": ("пнв", "nvg"),
    "нвг": ("пнв", "nvg"),
    "водяр": ("водка",),
}


class Text(NamedTuple):
    """Подготовленная к сравнению строка: сжатая форма + границы слов в ней."""
    compact: str
    words: tuple[str, ...]
    starts: frozenset[int]
    ends: frozenset[int]


def words(s: str) -> list[str]:
    """Слова строки в нормальной форме (регистр, ё, латиница-двойник, 9x39)."""
    s = (s or "").lower().translate(_LOOKALIKE)
    return _WORD_RE.findall(_DIGIT_X_RE.sub(" ", s))


def prepare(s: str) -> Text:
    ws = words(s)
    starts, ends, pos = [], [], 0
    for w in ws:
        starts.append(pos)
        pos += len(w)
        ends.append(pos)
    return Text("".join(ws), tuple(ws), frozenset(starts), frozenset(ends))


def compact(s: str) -> str:
    return "".join(words(s))


class Query(NamedTuple):
    compact: str
    words: list[str]
    bounds: frozenset[int]   # где в compact кончаются слова запроса


def query(s: str) -> Query:
    ws = words(s)
    bounds, pos = set(), 0
    for w in ws:
        pos += len(w)
        bounds.add(pos)
    return Query("".join(ws), ws, frozenset(bounds))


def _clean_span(q: Query, t: Text, pos: int) -> bool:
    """Совпадение в t с позиции pos не склеивает слова, которых в запросе нет:
    «ак12» = «АК-12» (буква|цифра), «545» = «5.45» (цифра|цифра), а «броник»
    ≠ «брони|Красная» (буква|буква без границы в запросе)."""
    c = t.compact
    for b in range(pos + 1, pos + len(q.compact)):
        if (b in t.starts and b - pos not in q.bounds
                and c[b - 1].isalpha() and c[b].isalpha()):
            return False
    return True


def tier(q: Query, t: Text) -> int | None:
    """Насколько хорошо запрос совпал со строкой t (None — не совпал)."""
    qc, c = q.compact, t.compact
    pos, inner = c.find(qc), False
    while pos != -1:
        if _clean_span(q, t, pos):
            if pos == 0:
                return EXACT if len(qc) == len(c) else PREFIX
            if pos in t.starts:
                return WORD
            inner = True
        pos = c.find(qc, pos + 1)
    if inner and len(qc) >= 2:
        return INNER
    # «сумка спортивная» → «Спортивная сумка»: каждое слово запроса — начало слова
    # (сначала дешёвая проверка подстрокой — она отсекает почти всю базу)
    if (len(q.words) > 1 and all(w in c for w in q.words)
            and all(any(tw.startswith(w) for tw in t.words) for w in q.words)):
        return WORDS
    return None


def has_word(target: str, t: Text) -> bool:
    """target (сжатый; «*» в конце — можно продолжение) стоит в t отдельным словом."""
    prefix = target.endswith("*")
    target = target.rstrip("*")
    pos = t.compact.find(target)
    while pos != -1:
        if pos in t.starts and (prefix or pos + len(target) in t.ends):
            return True
        pos = t.compact.find(target, pos + 1)
    return False


def slang_targets(qc: str) -> list[str]:
    """Во что раскрывается сленговый запрос (сжатые цели для has_word)."""
    return [x for stem, targets in _SLANG_C if qc.startswith(stem) for x in targets]


_SLANG_C = [(compact(stem), [compact(x) + ("*" if x.endswith("*") else "") for x in targets])
            for stem, targets in SLANG.items()]


def other_layout(query: str) -> str | None:
    """Тот же набор клавиш в другой раскладке: «cjk» → «сол», «пдщсл» → «glock».
    None — если в запросе смешаны алфавиты (это не промах раскладки)."""
    q = query.lower()
    lat, cyr = bool(_LAT_RE.search(q)), bool(_CYR_RE.search(q))
    if lat and not cyr:
        return q.translate(_EN2RU)
    if cyr and not lat:
        return q.translate(_RU2EN)
    return None


def prefix_distance(q: str, w: str, k: int) -> int:
    """Расстояние Дамерау–Левенштейна от q до ближайшего НАЧАЛА слова w
    (с перестановкой соседних букв). Больше k — возвращаем k+1, не досчитывая."""
    n = len(q)
    w = w[:n + k]
    prev2 = None
    prev = list(range(len(w) + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * len(w)
        for j in range(1, len(w) + 1):
            cost = q[i - 1] != w[j - 1]
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if (prev2 is not None and i > 1 and j > 1
                    and q[i - 1] == w[j - 2] and q[i - 2] == w[j - 1]):
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
        if min(cur) > k:
            return k + 1
        prev2, prev = prev, cur
    lo = max(0, n - k)
    return min(prev[lo:], default=k + 1)


def fuzzy_k(q: str) -> int:
    """Сколько опечаток прощаем слову запроса: совсем коротким — ни одной (иначе
    шум), трёхбуквенным — одну («ухо» → «Уха»), длинным — две."""
    return 0 if len(q) < 3 else 1 if len(q) < 8 else 2
