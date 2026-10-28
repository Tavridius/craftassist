"""Поиск по сайту: нормализация запроса (search_text) и выдача db.search.

    cd backend && python -m pytest tests/test_search.py

Тесты нормализации — без данных. Тесты выдачи берут игровую БД из DATA_DIR
(как приложение); если её нет, пропускаются. Запросы — реальные промахи из
Метрики, ради которых поиск переписан (октябрь 2026).
"""
import logging

import pytest

from app import config
from app.db import search_text as st


# ---------- нормализация ----------

@pytest.mark.parametrize("a, b", [
    ("АК-12", "ак12"),
    ("АК-12", "ак 12"),
    ("M4A1", "м4а1"),             # латинские M, A — как кириллица
    ("Tяжелый", "тяжелый"),       # латинская T в названии из игры
    ("Ёж", "еж"),
    ("9x39", "9*39"),             # калибр: x / х / * — разделитель
    ("12х76", "12x76"),
    ("5.45", "5,45"),
    ("Коктейль «Незабываемый»", "коктейль незабываемый"),
])
def test_compact_equal(a, b):
    assert st.compact(a) == st.compact(b)


def test_words_and_bounds():
    t = st.prepare("АКС-74У «Блаженный»")
    assert t.words == ("акс", "74у", "блаженный")
    assert t.compact == "акс74ублаженный"
    assert t.starts == {0, 3, 6}
    assert t.ends == {3, 6, 15}


@pytest.mark.parametrize("query, name, want", [
    ("ак12", "АК-12", st.EXACT),
    ("ак 12", "АК-12 (А)", st.PREFIX),
    ("м4", "M4A1", st.PREFIX),
    ("нез", "Таинственный незнакомец", st.WORD),
    ("ухо", "Кухонный стол", st.INNER),
    ("сумка спортивная", "Спортивная сумка", st.WORDS),
    ("545", "Патрон 5.45 мм", st.WORD),
    ("броник", "Краска для брони «Красная»", None),   # не склеиваем «брони|к…»
    ("с", "Касса", None),                             # одна буква — только с начала слова
])
def test_tier(query, name, want):
    assert st.tier(st.query(query), st.prepare(name)) == want


def test_tier_order():
    assert st.EXACT < st.PREFIX < st.WORD < st.WORDS < st.SYN < st.FUZZY < st.INNER


def test_has_word():
    assert st.has_word("ак", st.prepare("АК-74М"))
    assert not st.has_word("ак", st.prepare("Аккумулятор"))
    assert st.has_word(st.compact("mp7") + "*", st.prepare("HK MP7A2"))
    assert not st.has_word(st.compact("mp7"), st.prepare("HK MP7A2"))


def test_slang():
    assert "ак" in st.slang_targets(st.compact("калашников"))
    assert st.slang_targets(st.compact("кала")) == []


@pytest.mark.parametrize("typed, meant", [
    ("cjk", "сол"), ("c[hj", "схро"), ("elfh", "удар"), (",bj", "био"),
    ("'gb", "эпи"), ("пдщсл", "glock"),
])
def test_other_layout(typed, meant):
    assert st.other_layout(typed) == meant


def test_other_layout_mixed():
    assert st.other_layout("магазин 5.56 nato") is None
    assert st.other_layout("545") is None


@pytest.mark.parametrize("q, w, k, want", [
    ("сывортка", "сыворотка", 1, 1),    # перестановка
    ("кефлар", "кевлар", 1, 1),
    ("колиматор", "коллиматорный", 2, 1),
    ("незаебываемый", "незабываемый", 2, 1),
    ("сыв", "сыворотка", 1, 0),         # начало слова — без штрафа
    ("кевлар", "контейнер", 1, 2),      # далеко — k+1
])
def test_prefix_distance(q, w, k, want):
    assert st.prefix_distance(st.compact(q), st.compact(w), k) == want


# ---------- выдача по реальной базе ----------

@pytest.fixture(scope="module")
def gamedb():
    if not (config.DATA_DIR / "listing.json").exists():
        pytest.skip(f"нет игровой БД в {config.DATA_DIR}")
    from app.db.index import GameDB
    logging.disable(logging.INFO)
    g = GameDB()
    g._load_items()
    return g


def _names(g, q, n=10):
    return [g.items[i]["name"] for _, i in g.search_ranked(q, n)]


@pytest.mark.parametrize("q", ["ак12", "ак 12", "АК-12", "ak12"])
def test_ak12(gamedb, q):
    assert _names(gamedb, q)[0] == "АК-12"


def test_m4(gamedb):
    assert {"M4A1", "M4 LB"} <= set(_names(gamedb, "м4"))


def test_kalash(gamedb):
    names = _names(gamedb, "калаш", 30)
    assert {"АК-12", "АКМ", "АК-74М", "АКС-74У"} <= set(names)
    assert not any(n.startswith("Аккумулятор") for n in names)


def test_word_start_before_substring(gamedb):
    names = _names(gamedb, "ухо")
    assert names[0].startswith("Уха")
    assert names.index("Кухонный стол") > 0


def test_one_letter_no_substring(gamedb):
    ranked = gamedb.search_ranked("с", 500)
    assert ranked and all(t <= st.WORD for t, _ in ranked)


@pytest.mark.parametrize("q, want", [
    ("cjk", "Солянка"),
    ("сывортка", "Кровяная сыворотка"),
    ("кефлар", "Кевлар"),
    ("колиматор", "Прицел коллиматорный DM"),
    ("экзоброня мул", "Экзоброня «Мул»"),
    ("9*39", "Патрон 9x39 мм СП-5"),
    ("дигл", "Desert Eagle Mark VII"),
    ("ксюха", "АКС-74У"),
])
def test_misses_from_metrika(gamedb, q, want):
    assert want in _names(gamedb, q, 50)


def test_slang_targets_exist(gamedb):
    """Каждое сленговое слово что-то находит — иначе цель в SLANG устарела."""
    dead = [stem for stem in st.SLANG
            if not any(t == st.SYN for t, _ in gamedb.search_ranked(stem, 500))]
    assert dead == []
