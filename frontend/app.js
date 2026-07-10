// StalZone Craft — фронт только рисует, вся логика на бэке.
const BASE = location.pathname.replace(/\/[^/]*$/, "");   // "" или "/mvp"
const api = (p) => `${BASE}/api${p}`;
const asset = (p) => (p ? `${BASE}/${p}` : "");

const RARITY = {
  RANK_NEWBIE: "var(--r-newbie)", RANK_STALKER: "var(--r-stalker)",
  RANK_VETERAN: "var(--r-veteran)", RANK_MASTER: "var(--r-master)",
  RANK_LEGEND: "var(--r-legend)", QUEST_ITEM: "var(--r-quest)",
  DEFAULT: "var(--r-default)",
};
const rarity = (c) => RARITY[c] || "var(--r-default)";

const fmt = (n) => (n == null ? "—" : Math.round(n).toLocaleString("ru-RU"));

const $ = (id) => document.getElementById(id);
const results = $("results"), detail = $("detail"), hint = $("hint"),
      home = $("home"), input = $("searchInput");

// ---------- поиск ----------
let searchTimer = null, lastQuery = "";
input.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(doSearch, 250);
});

async function doSearch() {
  const q = input.value.trim();
  if (q === lastQuery) return;
  lastQuery = q;
  detail.classList.add("hidden");
  if (!q) { results.innerHTML = ""; hint.classList.remove("hidden"); loadHome(); return; }
  hint.classList.add("hidden");
  home.classList.add("hidden");
  results.innerHTML = `<div class="spinner">Ищу…</div>`;
  try {
    const r = await fetch(api(`/search?q=${encodeURIComponent(q)}&limit=48`));
    const data = await r.json();
    renderResults(data.results || []);
  } catch (e) {
    results.innerHTML = `<div class="empty">Ошибка сети</div>`;
  }
}

function renderResults(items) {
  if (!items.length) { results.innerHTML = `<div class="empty">Ничего не найдено</div>`; return; }
  results.innerHTML = "";
  for (const it of items) {
    const cell = document.createElement("div");
    cell.className = "cell";
    cell.style.borderLeftColor = rarity(it.color);
    cell.innerHTML = `<img loading="lazy" src="${asset(it.icon)}" alt="">
                      <div class="nm">${escapeHtml(it.name)}</div>`;
    cell.addEventListener("click", () => { location.hash = `item=${it.id}`; });
    results.appendChild(cell);
  }
}

// ---------- карточка предмета ----------
async function openItem(id) {
  results.innerHTML = "";
  hint.classList.add("hidden");
  home.classList.add("hidden");
  detail.classList.remove("hidden");
  detail.innerHTML = `<div class="spinner">Считаю выгоду…</div>`;
  window.scrollTo(0, 0);
  try {
    const r = await fetch(api(`/craft/${id}`));
    renderDetail(await r.json());
  } catch (e) {
    detail.innerHTML = `<div class="empty">Ошибка загрузки</div>`;
  }
}

function renderDetail(d) {
  const it = d.item;
  const v = d.verdict || {};
  const vClass = v.status === "profitable" ? "profitable"
              : v.status === "unprofitable" ? "unprofitable" : "neutral";

  let html = `<button class="back">← Назад к поиску</button>`;
  html += `<div class="item-head" style="border-left-color:${rarity(it.color)}">
             <img src="${asset(it.icon)}" alt="">
             <div><div class="title">${escapeHtml(it.name)}</div>
                  <div class="sub">${escapeHtml(it.name_en || "")}</div></div>
           </div>`;

  // вердикт
  let money = "";
  if (v.craft_cost != null && v.buy_price != null)
    money = `<span class="money">Крафт ${fmt(v.craft_cost)} ₽ · Купить ${fmt(v.buy_price)} ₽</span>`;
  else if (v.craft_cost != null)
    money = `<span class="money">Стоимость крафта ${fmt(v.craft_cost)} ₽</span>`;
  html += `<div class="verdict ${vClass}">${escapeHtml(v.text || "—")}${money}</div>`;

  if (v.status === "unknown")
    html += `<div class="demo-note">⏳ Цены части предметов сейчас считаются в фоне — обнови страницу через 1–2 минуты.</div>`;

  if (!d.craftable) {
    html += `<div class="empty">Этот предмет не крафтится — его можно только найти, выбить или купить.</div>`;
    detail.innerHTML = html;
    wireBack();
    return;
  }

  const tree = d.tree;
  const chosen = tree.recipe;
  if (!chosen) {
    html += `<div class="empty">Рецепт есть, но дерево не раскрылось (слишком глубоко или цикл).</div>`;
    detail.innerHTML = html; wireBack(); return;
  }

  html += `<div class="section-title">Рецепт — ${recipeWhere(chosen)}</div>`;
  html += `<div class="tree">
    <div class="node">
      <div class="ing root" style="border-left-color:${rarity(it.color)}">
        <img src="${asset(it.icon)}" alt="">
        <div class="info">
          <div class="nm">${escapeHtml(it.name)}${chosen.result_amount > 1 ? ` <span class="x">×${chosen.result_amount}</span>` : ""}</div>
          <div class="meta">результат крафта</div>
        </div>
        <div class="price"><div class="line">${d.craft_cost != null ? fmt(d.craft_cost) + " ₽" : "—"}</div>${chosen.result_amount > 1 ? `<div class="unit">за 1 шт</div>` : ""}</div>
      </div>
      <div class="children">${renderRecipe(chosen)}</div>
    </div>
  </div>`;

  html += `<div class="total-row"><span>Итого крафт${chosen.result_amount > 1 ? " (за 1 шт)" : ""}</span>
             <span class="val">${d.craft_cost != null ? fmt(d.craft_cost) + " ₽" : "неизвестно"}</span></div>`;
  if (d.buy_price != null)
    html += `<div class="total-row"><span>Купить готовое на ауке</span>
               <span class="val">${fmt(d.buy_price)} ₽</span></div>`;

  if (tree.alternatives && tree.alternatives.length)
    html += renderAlts(tree.alternatives);

  if (API_IS_DEMO)
    html += `<div class="demo-note">⚠️ Демо-режим: цены аукциона тестовые (не реальные). Подключи prod-токен для настоящих цен.</div>`;

  detail.innerHTML = html;
  wireBack();
  wireTree();
}

// ---------- рекурсивная отрисовка дерева крафта ----------
let _uid = 0;
const uid = () => "t" + (++_uid);

function recipeWhere(r) {
  return `Верстак · ${escapeHtml(r.category || "")}${r.subcategory ? " / " + escapeHtml(r.subcategory) : ""}`;
}

function srcTag(n) {
  if (n.best_source === "craft") return `<span class="tag craft">крафт</span>`;
  if (n.best_source === "market") return `<span class="tag market">аук</span>`;
  if (n.craftable) return `<span class="tag none">только крафт</span>`;
  return `<span class="tag none">нет цены</span>`;
}

function renderRecipe(recipe) {
  let h = "";
  for (const ing of recipe.ingredients) h += renderIng(ing);
  return h;
}

function renderIng(ing) {
  const n = ing.node;
  const hasSub = !!n.recipe;                            // крафт-путь раскрыт
  const canCraftDearer = !hasSub && n.craftable && n.craft_cost != null && n.best_source === "market";
  const tId = hasSub ? uid() : "";

  let meta = n.best_cost != null ? fmt(n.best_cost) + " ₽/шт" : "цена неизвестна";
  if (canCraftDearer) meta += ` · крафт ${fmt(n.craft_cost)} ₽ (дороже)`;
  if (n.n_variants > 1) meta += ` · вариантов: ${n.n_variants}`;

  let h = `<div class="node">
    <div class="ing">
      <img loading="lazy" src="${asset(n.icon)}" alt="">
      <div class="info">
        <div class="nm">${hasSub ? `<button class="tw" data-t="${tId}">▾</button> ` : ""}${escapeHtml(n.name)} <span class="x">×${ing.amount}</span> ${srcTag(n)}</div>
        <div class="meta">${meta}</div>
      </div>
      <div class="price"><div class="line">${ing.line_cost != null ? fmt(ing.line_cost) + " ₽" : "—"}</div></div>
    </div>`;
  if (hasSub)
    h += `<div class="children" id="${tId}">${renderRecipe(n.recipe)}</div>`;
  h += `</div>`;
  return h;
}

function renderAlts(alts) {
  let h = `<div class="section-title">Другие варианты рецепта: ${alts.length}</div>`;
  for (const a of alts) {
    const cost = a.recipe_cost != null ? fmt(a.recipe_cost) + " ₽" : "цена неизвестна";
    h += `<details class="alt"><summary><b>${cost}</b> · верстак${a.result_amount > 1 ? " · ×" + a.result_amount : ""}</summary>`;
    for (const i of a.ingredients)
      h += `<div class="alt-ing">${escapeHtml(i.name)} <span class="x">×${i.amount}</span>${i.unit_price != null ? ` — ${fmt(i.unit_price)} ₽/шт` : ""}</div>`;
    h += `</details>`;
  }
  return h;
}

function wireTree() {
  detail.querySelectorAll(".tw").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sub = document.getElementById(btn.dataset.t);
      if (!sub) return;
      const collapsed = sub.classList.toggle("collapsed");
      btn.textContent = collapsed ? "▸" : "▾";
    });
  });
}

function wireBack() {
  const b = detail.querySelector(".back");
  if (b) b.addEventListener("click", () => {
    location.hash = lastQuery ? `q=${encodeURIComponent(lastQuery)}` : "";
  });
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

// демо/прод определим по региональному бэйджу (обновит health)
let API_IS_DEMO = true;
fetch(api("/health")).then(r => r.json()).then(h => {
  API_IS_DEMO = !!h.demo;
  $("regionBadge").textContent = `${h.region || "RU"} · ${h.demo ? "demo" : "prod"}`;
}).catch(() => {});

// ---------- главная: подборки крафтов ----------
async function loadHome() {
  home.classList.remove("hidden");
  // не дёргаем чаще раза в минуту — на бэке рейтинги тоже кэшируются
  if (home.dataset.ts && Date.now() - +home.dataset.ts < 60000) return;
  if (!home.innerHTML) home.innerHTML = `<div class="spinner">Загружаю подборки…</div>`;
  try {
    const r = await fetch(api("/top"));
    const d = await r.json();
    home.dataset.ts = Date.now();
    renderHome(d);
  } catch (e) {
    home.innerHTML = `<div class="empty">Не удалось загрузить подборки</div>`;
  }
}

function topRow(e) {
  const badge = e.pct == null ? ""
    : `<span class="pct ${e.pct > 0 ? "up" : "down"}">${e.pct > 0 ? "+" : ""}${e.pct}%</span>`;
  const meta = [];
  if (e.craft_cost != null) meta.push(`крафт ${fmt(e.craft_cost)} ₽`);
  if (e.buy_price != null) meta.push(`аук ${fmt(e.buy_price)} ₽`);
  if (e.sales_per_hour != null) meta.push(`${e.sales_per_hour} прод/ч`);
  if (e.opens) meta.push(`${e.opens} 👁`);
  return `<div class="ing top-row" data-id="${e.id}" style="border-left:3px solid ${rarity(e.color)}">
    <img loading="lazy" src="${asset(e.icon)}" alt="">
    <div class="info"><div class="nm">${escapeHtml(e.name)}</div>
      <div class="meta">${meta.join(" · ")}</div></div>
    <div class="price">${badge}</div></div>`;
}

function renderHome(d) {
  let h = "";
  const sec = (title, list, empty) => {
    h += `<div class="section-title">${title}</div>`;
    h += (list && list.length) ? list.map(topRow).join("")
                               : `<div class="empty-sm">${empty}</div>`;
  };
  sec("🔥 Популярные крафты", d.popular,
      "Пока нет статистики — открывай карточки предметов!");
  sec("💰 Самые выгодные крафты", d.profitable,
      "Цены ещё считаются в фоне — загляни через пару минут.");
  sec(`⚡ Профитные крафты — продажи ${d.liquid_threshold || 10}+/ч`, d.liquid,
      "Нет предметов с такой частотой продаж (или цены ещё считаются).");
  home.innerHTML = h;
  home.querySelectorAll(".top-row").forEach((r) =>
    r.addEventListener("click", () => { location.hash = `item=${r.dataset.id}`; }));
}

// ---------- диплинки: #item=ID открывает карточку, #q=... запускает поиск ----------
function routeFromHash() {
  const h = location.hash.slice(1);
  const m = new URLSearchParams(h);
  if (m.get("item")) { openItem(m.get("item")); return; }
  if (m.get("q")) { input.value = m.get("q"); lastQuery = ""; doSearch(); return; }
  if (!input.value) {
    detail.classList.add("hidden");
    hint.classList.remove("hidden");
    loadHome();
  }
}
window.addEventListener("hashchange", routeFromHash);
routeFromHash();
