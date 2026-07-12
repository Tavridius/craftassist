// StalZone Craft — фронт «PDA-терминал». Только отрисовка, вся логика на бэке.
const BASE = "";                       // приложение на корне домена
const api = (p) => `${BASE}/api${p}`;
const asset = (p) => (p ? `${BASE}/${p}` : "");

// ---------- History API-роутинг: реальные пути вместо #hash ----------
// navigate(path) — переход по SPA (pushState), route() читает location.pathname.
function navigate(path, { replace = false } = {}) {
  const cur = location.pathname + location.search;
  if (path === cur) { route(); return; }
  history[replace ? "replaceState" : "pushState"](null, "", path);
  route();
}

const RANKS = {
  RANK_NEWBIE:  { label: "НОВИЧОК",  color: "var(--r-newbie)" },
  RANK_STALKER: { label: "СТАЛКЕР",  color: "var(--r-stalker)" },
  RANK_VETERAN: { label: "ВЕТЕРАН",  color: "var(--r-veteran)" },
  RANK_MASTER:  { label: "МАСТЕР",   color: "var(--r-master)" },
  RANK_LEGEND:  { label: "ЛЕГЕНДА",  color: "var(--r-legend)" },
  QUEST_ITEM:   { label: "КВЕСТ",    color: "var(--r-quest)" },
  DEFAULT:      { label: "СТАНДАРТ", color: "var(--r-default)" },
};
const rank = (c) => RANKS[c] || RANKS.DEFAULT;

// русские названия перков/станков убежища (ключи из hideout_recipes.json)
const PERK_RU = {
  ammunition: "Боеприпасы", armorer: "Оружейное дело", brewing: "Варение",
  cooking: "Кулинария", engineering: "Инженерия", materials: "Материалы",
  medicine: "Медицина", pyrotechnics: "Пиротехника",
};
const FEATURE_RU = {
  calipers_kit: "Штангенциркули", centrifuge: "Центрифуга",
  chemical_reactor: "Химический реактор", chromatographic_equipment: "Хроматограф",
  cnc: "Станок ЧПУ", electronics_kit: "Набор электроники",
  fermentation_container: "Ёмкость для брожения", flasks_kit: "Набор колб",
  gauze_filter: "Марлевый фильтр",
  generator_energy_source_anomal: "Генератор: аномальный источник",
  generator_energy_source_battery: "Генератор: аккумулятор",
  hoods: "Вытяжка", kitchen_items: "Кухонная утварь", kitchen_table: "Кухонный стол",
  laboratory_table: "Лабораторный стол", laminar_box: "Ламинарный бокс",
  laser_level: "Лазерный уровень", lathe: "Токарный станок",
  precise_powertools: "Точный электроинструмент", precise_tools: "Точные инструменты",
  rotary_evaporator: "Ротационный испаритель", scalpels_kit: "Набор скальпелей",
  screwdrivers: "Отвёртки", sterilization_system: "Система стерилизации",
  stove: "Плита", tool_trolley: "Тележка с инструментами",
  water_collector: "Сборник воды", welding_equipment: "Сварочное оборудование",
  workbench: "Верстак", wrenches_kit: "Набор ключей",
};
const BENCH_RU = { workbench: "ВЕРСТАК", kitchen_table: "КУХОННЫЙ СТОЛ", laboratory_table: "ЛАБОРАТОРНЫЙ СТОЛ" };
const perkName = (k) => PERK_RU[k] || k.replace(/_/g, " ");
const featureName = (k) => FEATURE_RU[k] || k.replace(/_/g, " ");
const benchName = (k) => BENCH_RU[k] || String(k || "ВЕРСТАК").replace(/_/g, " ").toUpperCase();

const fmt = (n) => (n == null ? "—" : Math.round(n).toLocaleString("ru-RU"));
const fmtSales = (n) => (n == null ? "—" : (+n).toFixed(1));

const $ = (id) => document.getElementById(id);
const results = $("results"), detail = $("detail"),
      home = $("home"), page = $("page"), input = $("searchInput");

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

// ---------- часы в шапке ----------
(function clock() {
  const el = $("clock");
  const p = (n) => String(n).padStart(2, "0");
  const tick = () => {
    const d = new Date();
    el.textContent = `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  };
  tick();
  setInterval(tick, 1000);
})();

// ---------- health → шапка + режим ----------
let API_IS_DEMO = true;
fetch(api("/health")).then((r) => r.json()).then((h) => {
  API_IS_DEMO = !!h.demo;
  $("regionBadge").textContent = `${h.region || "RU"} · ${h.demo ? "ДЕМО" : "PROD"}`;
  $("statItems").textContent = fmt(h.items);
  $("statRecipes").textContent = fmt(h.craft_results);
  $("statPrices").textContent = fmt((h.prices || {}).priced);
}).catch(() => {});

// ---------- авторизация (OAuth 2.0, аккаунт EXBO) ----------
const authBox = $("authBox"), modeToggle = $("modeToggle");
let ME = null;   // ответ /api/me (кэш для тумблера и фильтров)

const availMode = () => localStorage.getItem("sz_avail") === "1";
const availParam = (sep) => (ME && ME.authenticated && availMode() ? `${sep}available=1` : "");

function renderModeToggle() {
  const authed = ME && ME.authenticated;
  // без включённой авторизации фильтр «доступные» посчитать не по чему — прячем
  if (!authed && !(ME && ME.auth_enabled)) { modeToggle.classList.add("hidden"); return; }
  modeToggle.classList.remove("hidden");
  const on = authed && availMode();
  modeToggle.textContent = on ? "КРАФТЫ: ДОСТУПНЫЕ" : "КРАФТЫ: ВСЕ";
  modeToggle.classList.toggle("on", on);
  modeToggle.classList.toggle("locked", !authed);
  modeToggle.title = authed
    ? "Показывать все крафты или только доступные по прокачке убежища"
    : "Фильтр по прокачке убежища — доступен после входа через EXBO";
}
modeToggle.addEventListener("click", () => {
  if (!(ME && ME.authenticated)) { navigate("/profile"); return; }
  localStorage.setItem("sz_avail", availMode() ? "0" : "1");
  renderModeToggle();
  lastQuery = null;          // форсировать перезапрос поиска
  home.dataset.ts = "";      // и главной
  route();
});

async function loadAuth() {
  try {
    ME = await fetch(api("/me")).then((r) => r.json());
    if (ME.authenticated) {
      const name = ME.user.display_login || ME.user.login;
      authBox.innerHTML = `<a class="auth-user" href="/profile" title="Профиль убежища · EXBO ID ${ME.user.exbo_id}">${escapeHtml(name)}</a>
        <button class="auth-out" id="logoutBtn" title="Завершить сессию">ВЫХОД</button>`;
      $("logoutBtn").addEventListener("click", async () => {
        await fetch(`${BASE}/auth/logout`, { method: "POST" }).catch(() => {});
        localStorage.removeItem("sz_avail");
        localStorage.removeItem("sz_onb");
        loadAuth().then(() => { if (location.pathname === "/profile") navigate("/"); });
      });
    } else if (ME.auth_enabled) {
      authBox.innerHTML = `<a class="auth-login" href="${BASE}/auth/login">ВХОД</a>`;
    } else {
      authBox.innerHTML = "";
    }
  } catch (e) { ME = null; authBox.innerHTML = ""; }
  renderModeToggle();
  renderOnboard();
  // стартовый рендер мог уйти без фильтра, пока /me не ответил — перерисовать
  if (ME && ME.authenticated && availMode()) {
    lastQuery = null; home.dataset.ts = "";
    route();
  }
}

// ---------- онбординг: подсказка заполнить профиль после первого входа ----------
const onboard = $("onboard");
function renderOnboard() {
  // подсказка только в крафт-контексте (главная, поиск, карточка), не в других разделах
  const craftCtx = /^\/(item\/|search|$)/.test(location.pathname) || location.pathname === "/";
  const show = ME && ME.authenticated && ME.profile_empty
    && localStorage.getItem("sz_onb") !== "1" && craftCtx;
  if (!show) { onboard.classList.add("hidden"); onboard.innerHTML = ""; return; }
  onboard.classList.remove("hidden");
  onboard.innerHTML = `<span class="mark">[!]</span>
    <span class="txt">ПРОФИЛЬ УБЕЖИЩА НЕ ЗАПОЛНЕН. Отметь прокачанные навыки и станки —
      терминал покажет доступные тебе рецепты и подсветит, чего не хватает в карточках.</span>
    <a class="onb-go" href="/profile">ЗАПОЛНИТЬ</a>
    <button class="onb-x" title="Скрыть подсказку">✕</button>`;
  onboard.querySelector(".onb-x").addEventListener("click", () => {
    localStorage.setItem("sz_onb", "1");
    renderOnboard();
  });
}
(function authInit() {
  const m = new URLSearchParams(location.hash.slice(1));
  if (m.get("auth") === "error") {
    authBox.innerHTML = `<span class="auth-err">ОШИБКА ВХОДА</span>`;
    history.replaceState(null, "", location.pathname + location.search);
    setTimeout(loadAuth, 4000);
  } else loadAuth();
})();

// ---------- поиск ----------
let searchTimer = null, lastQuery = "";
input.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    // держим URL в синхроне (без замусоривания истории), затем ищем
    const q = input.value.trim();
    const path = q ? `/search?q=${encodeURIComponent(q)}` : "/";
    if (location.pathname + location.search !== path)
      history.replaceState(null, "", path);
    doSearch();
  }, 250);
});

async function doSearch() {
  const q = input.value.trim();
  if (q === lastQuery) return;
  lastQuery = q;
  detail.classList.add("hidden");
  if (!q) { results.innerHTML = ""; home.classList.remove("hidden"); loadHome(); return; }
  home.classList.add("hidden");
  results.innerHTML = `<div class="spinner">// ПОИСК ПО БАЗЕ</div>`;
  try {
    const r = await fetch(api(`/search?q=${encodeURIComponent(q)}&limit=48${availParam("&")}`));
    const data = await r.json();
    renderResults(data.results || [], data.available_only);
  } catch (e) {
    results.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
  }
}

function renderResults(items, availOnly) {
  if (!items.length) {
    results.innerHTML = `<div class="empty">${availOnly
      ? `НЕТ ДОСТУПНЫХ ПО ПРОКАЧКЕ РЕЦЕПТОВ. ПРОВЕРЬ <a href="/profile">ПРОФИЛЬ</a> ИЛИ ПЕРЕКЛЮЧИ НА «ВСЕ».`
      : "НИЧЕГО НЕ НАЙДЕНО"}</div>`;
    return;
  }
  results.innerHTML = `<div class="results-head">РЕЗУЛЬТАТЫ: ${items.length}${availOnly ? " · ТОЛЬКО ДОСТУПНЫЕ" : ""}</div>`;
  const grid = document.createElement("div");
  grid.className = "grid";
  for (const it of items) {
    const cell = document.createElement("div");
    cell.className = "cell";
    cell.style.borderLeftColor = rank(it.color).color;
    cell.innerHTML = `<img loading="lazy" src="${asset(it.icon)}" alt="">
                      <div class="nm">${escapeHtml(it.name)}</div>`;
    cell.addEventListener("click", () => { navigate(`/item/${it.id}`); });
    grid.appendChild(cell);
  }
  results.appendChild(grid);
}

// ---------- карточка предмета ----------
async function openItem(id) {
  results.innerHTML = "";
  home.classList.add("hidden");
  detail.classList.remove("hidden");
  detail.innerHTML = `<div class="spinner">// АНАЛИЗ РЕЦЕПТА И ЦЕН</div>`;
  window.scrollTo(0, 0);
  try {
    const r = await fetch(api(`/craft/${id}`));
    renderDetail(await r.json());
  } catch (e) {
    detail.innerHTML = `<div class="empty">[!] ОШИБКА ЗАГРУЗКИ</div>`;
  }
}

function verdictBlock(d) {
  const v = d.verdict || {};
  let cls = "warn", main = "—", sub = "";
  if (v.status === "profitable") {
    cls = "ok";
    main = `ВЫГОДНО ▲+${v.pct}%`;
    sub = `МАРЖА +${fmt(v.diff)} ₽ НА ЕДИНИЦУ ПРИ ТЕКУЩИХ ЦЕНАХ`;
  } else if (v.status === "unprofitable") {
    cls = "bad";
    main = `НЕВЫГОДНО ▼−${Math.abs(v.pct)}%`;
    sub = `МАРЖА −${fmt(Math.abs(v.diff))} ₽ НА ЕДИНИЦУ ПРИ ТЕКУЩИХ ЦЕНАХ`;
  } else if (v.status === "unknown") {
    main = `РАСЧЁТ ЦЕН…`;
    sub = `ЦЕНЫ ЧАСТИ ИНГРЕДИЕНТОВ СЧИТАЮТСЯ В ФОНЕ — ОБНОВИ СТРАНИЦУ ЧЕРЕЗ 1–2 МИНУТЫ`;
  } else if (v.status === "no_market") {
    main = `НЕТ ЛОТОВ НА АУКЕ`;
    sub = `ГОТОВОГО НЕТ В ПРОДАЖЕ — СРАВНИВАТЬ НЕ С ЧЕМ`;
  } else if (v.status === "not_craftable") {
    cls = "bad";
    main = `НЕ КРАФТИТСЯ`;
    sub = `ПРЕДМЕТ МОЖНО ТОЛЬКО НАЙТИ, ВЫБИТЬ ИЛИ КУПИТЬ`;
  }

  let bars = "";
  if (d.craft_cost != null && d.buy_price != null) {
    const maxv = Math.max(d.craft_cost, d.buy_price) || 1;
    bars = `<div class="v-bars">
      <div class="v-bar">
        <div class="row"><span>КРАФТ</span><span class="num">${fmt(d.craft_cost)} ₽</span></div>
        <div class="track"><div class="fill craft" style="width:${Math.round(d.craft_cost / maxv * 100)}%"></div></div>
      </div>
      <div class="v-bar">
        <div class="row"><span>АУК</span><span class="num">${fmt(d.buy_price)} ₽</span></div>
        <div class="track"><div class="fill" style="width:${Math.round(d.buy_price / maxv * 100)}%"></div></div>
      </div>
    </div>`;
  }

  return `<div class="verdict ${cls}">
    <div>
      <div class="v-label">ВЕРДИКТ СИСТЕМЫ</div>
      <div class="v-main">${main}</div>
      ${sub ? `<div class="v-sub">${sub}</div>` : ""}
    </div>
    ${bars}
  </div>`;
}

function tilesBlock(d, chosen) {
  const v = d.verdict || {};
  const diff = v.diff;
  const diffCls = diff == null ? "" : diff >= 0 ? "up" : "down";
  const diffVal = diff == null ? "—" : (diff >= 0 ? "+" : "−") + fmt(Math.abs(diff)) + " ₽";
  return `<div class="tiles">
    <div class="tile"><div class="lbl">СЕБЕСТОИМОСТЬ</div>
      <div class="val">${d.craft_cost != null ? fmt(d.craft_cost) + " ₽" : "—"}</div></div>
    <div class="tile"><div class="lbl">ЦЕНА АУКА</div>
      <div class="val">${d.buy_price != null ? fmt(d.buy_price) + " ₽" : "—"}</div></div>
    <div class="tile"><div class="lbl">МАРЖА / ШТ</div>
      <div class="val ${diffCls}">${diffVal}</div></div>
    <div class="tile"><div class="lbl">ЭНЕРГИЯ ВЕРСТАКА</div>
      <div class="val amber">${chosen && chosen.energy != null ? fmt(chosen.energy) : "—"}</div></div>
  </div>`;
}

// плоский список строк дерева с ASCII-префиксами ├─ / └─
function flattenTree(recipe, ancestors, rows, stats) {
  const ings = recipe.ingredients || [];
  ings.forEach((ing, i) => {
    const last = i === ings.length - 1;
    const prefix = ancestors.map((more) => (more ? "│ " : "  ")).join("") + (last ? "└─" : "├─");
    rows.push({ ing, prefix, depth: ancestors.length });
    stats.depth = Math.max(stats.depth, ancestors.length + 1);
    if (ing.node && ing.node.recipe) flattenTree(ing.node.recipe, ancestors.concat(!last), rows, stats);
  });
}

function srcTag(n) {
  if (n.best_source === "craft") return `<span class="ttag craft">КРАФТ</span>`;
  if (n.best_source === "market") return `<span class="ttag market">АУК</span>`;
  if (n.craftable) return `<span class="ttag">ТОЛЬКО КРАФТ</span>`;
  return `<span class="ttag">НЕТ ЦЕНЫ</span>`;
}

function treeBlock(d, chosen) {
  const rows = [], stats = { depth: 0 };
  flattenTree(chosen, [], rows, stats);

  let body = "";
  for (const r of rows) {
    const n = r.ing.node;
    body += `<div class="trow ${r.depth ? "sub" : ""}">
      <div class="tcomp">
        <span class="tprefix">${r.prefix}</span>
        <img loading="lazy" src="${asset(n.icon)}" alt="">
        <span class="tname ${r.depth ? "" : "top"}" data-id="${n.id}">${escapeHtml(n.name)}</span>
        <span class="x">×${r.ing.amount}</span>
      </div>
      <div class="tunit">${fmt(n.best_cost)}</div>
      <div class="tsrc">${srcTag(n)}</div>
      <div class="tline">${r.ing.line_cost != null ? fmt(r.ing.line_cost) + " ₽" : "—"}</div>
    </div>`;
  }

  const perOne = chosen.result_amount > 1 ? ` · ЗА 1 ШТ ИЗ ${chosen.result_amount}` : "";
  return `<div class="section-head">
      <div class="section-title">▸ ДЕРЕВО КРАФТА · ОПТИМАЛЬНЫЙ ПУТЬ</div>
      <div class="section-note">ГЛУБИНА ${stats.depth} · ВАРИАНТОВ ${d.tree.n_variants || 1}</div>
    </div>
    <div class="ttable"><div class="ttable-inner">
      <div class="thead">
        <div>КОМПОНЕНТ</div><div style="text-align:right">₽/ШТ</div>
        <div style="text-align:center">ИСТОЧНИК</div><div style="text-align:right">СТРОКА</div>
      </div>
      ${body}
      <div class="ttotal">
        <div class="lbl">ИТОГО СЕБЕСТОИМОСТЬ КРАФТА${perOne}</div>
        <div class="nums">
          ${d.buy_price != null ? `<div class="buy">АУК <span>${fmt(d.buy_price)} ₽</span></div>` : ""}
          <div class="craft">${d.craft_cost != null ? fmt(d.craft_cost) + " ₽" : "—"}</div>
        </div>
      </div>
    </div></div>`;
}

function altsBlock(alts) {
  let h = `<div class="section-head">
    <div class="section-title">▸ ДРУГИЕ ВАРИАНТЫ РЕЦЕПТА</div>
    <div class="section-note">ВСЕГО ${alts.length}</div></div>`;
  for (const a of alts) {
    const cost = a.recipe_cost != null ? fmt(a.recipe_cost) + " ₽" : "ЦЕНА НЕИЗВЕСТНА";
    h += `<details class="alt"><summary><b>${cost}</b> · ВЕРСТАК${a.result_amount > 1 ? " · ×" + a.result_amount : ""}</summary>`;
    for (const i of a.ingredients)
      h += `<div class="alt-ing"><span class="ilink" data-id="${i.id}">${escapeHtml(i.name)}</span> <span class="x">×${i.amount}</span>${i.unit_price != null ? ` — ${fmt(i.unit_price)} ₽/ШТ` : ""}</div>`;
    h += `</details>`;
  }
  return h;
}

function reqsSections(chosen, rc) {
  const req = chosen.requirements || {};
  const feats = req.features || [];
  const perks = Object.entries(req.perks || {});
  // rc = req_check с бэка (только для авторизованных с профилем)
  const featOk = rc ? Object.fromEntries((rc.features || []).map((f) => [f.id, f.ok])) : null;
  const perkChk = rc ? Object.fromEntries((rc.perks || []).map((p) => [p.id, p])) : null;

  let tools = "";
  for (const f of feats) {
    const st = featOk ? (featOk[f] ? "have" : "lack") : "";
    const mark = featOk ? (featOk[f] ? "✓" : "✗") : "▣";
    tools += `<div class="tool ${st}"><div class="row">
      <span class="mark">${mark}</span><span class="nm">${escapeHtml(featureName(f))}</span>
      ${st === "lack" ? `<span class="miss">НЕТ</span>` : ""}
    </div></div>`;
  }

  let perkHtml = "";
  for (const [k, lvl] of perks) {
    const pc = perkChk && perkChk[k];
    let pips = "";
    for (let i = 0; i < 10; i++) {
      let cls = i < lvl ? "on" : "";
      if (pc && i < lvl) cls = i < pc.have ? "on ok" : "on bad";  // есть/не хватает
      pips += `<div class="pip ${cls}"></div>`;
    }
    perkHtml += `<div class="perk-row ${pc ? (pc.ok ? "ok" : "bad") : ""}">
        <div class="nm">${escapeHtml(perkName(k))}</div>
        <div class="lvl">УР. ${lvl}${pc ? ` <span class="have ${pc.ok ? "ok" : "bad"}">/ У ТЕБЯ ${pc.have}</span>` : ""}</div>
      </div>
      <div class="pips">${pips}</div>
      <div class="pips-scale"><span>1</span><span>ТРЕБУЕМЫЙ ИЗ 10</span><span>10</span></div>`;
  }

  let h = "";
  if (tools) h += `<div class="reqs-sec"><div class="reqs-lbl">СТАНКИ И ИНСТРУМЕНТЫ</div>${tools}</div>`;
  if (perkHtml) h += `<div class="reqs-sec"><div class="reqs-lbl">НАВЫК КРАФТА</div>${perkHtml}</div>`;
  h += `<div class="reqs-sec">
    <div class="reqs-lbl">РЕСУРСЫ ВЕРСТАКА</div>
    <div class="res-row"><span class="k">ЭНЕРГИЯ</span>
      <span class="v">${chosen.energy != null ? fmt(chosen.energy) + " ЕД." : "—"}</span></div>
  </div>`;
  return h;
}

function usedInSection(usedIn) {
  const rows = usedIn.map((u) => `<div class="use-row" data-id="${u.id}">
    <img loading="lazy" src="${asset(u.icon)}" alt="">
    <span class="nm">${escapeHtml(u.name)}</span>
  </div>`).join("");
  return `<div class="reqs-sec">
    <div class="reqs-lbl">НУЖЕН ДЛЯ КРАФТОВ · ${usedIn.length}</div>
    <div class="use-list">${rows}</div>
  </div>`;
}

function asideBlock(chosen, usedIn, rc) {
  const hasUsed = usedIn && usedIn.length;
  if (!chosen && !hasUsed) return "";
  const note = !chosen ? "КРАФТ"
    : rc ? (rc.ok ? `<span class="ok">✓ ВСЁ ПРОКАЧАНО</span>`
                  : `<span class="bad">✗ НЕ ХВАТАЕТ: ${rc.missing}</span>`)
         : "УБЕЖИЩЕ";
  return `<aside class="reqs">
    <div class="reqs-head">
      <div class="reqs-title">${chosen ? "▸ ТРЕБОВАНИЯ" : "▸ ПРИМЕНЕНИЕ"}</div>
      <div class="reqs-note">${note}</div>
    </div>
    ${chosen ? reqsSections(chosen, rc) : ""}
    ${hasUsed ? usedInSection(usedIn) : ""}
  </aside>`;
}

function renderDetail(d) {
  const it = d.item;
  const rk = rank(it.color);
  const chosen = d.tree && d.tree.recipe;

  let html = `<button class="back">◂ НАЗАД</button>`;

  const crumbs = ["БАЗА"];
  if (chosen && chosen.category) crumbs.push(escapeHtml(chosen.category));
  if (chosen && chosen.subcategory) crumbs.push(escapeHtml(chosen.subcategory));
  html += `<div class="crumbs">${crumbs.join(" ▸ ")} ▸ <span class="id">${escapeHtml(it.id)}</span></div>`;

  html += `<div class="card-cols"><div class="card-main">`;

  html += `<div class="item-head">
    <div class="item-icon" style="border-color:${rk.color}"><img src="${asset(it.icon)}" alt=""></div>
    <div class="head-info">
      <div class="title">${escapeHtml(it.name)}</div>
      <div class="head-chips">
        ${it.name_en ? `<span class="sub">${escapeHtml(it.name_en)}</span>` : ""}
        <span class="chip" style="border-color:${rk.color};color:${rk.color}">${rk.label}</span>
        ${chosen ? `<span class="chip">${benchName(chosen.bench)}${chosen.category ? " · " + escapeHtml(chosen.category).toUpperCase() : ""}</span>` : ""}
      </div>
    </div>
    <div class="head-liq">
      <div class="lbl">ЛИКВИДНОСТЬ</div>
      <div class="val">${fmtSales(d.sales_per_hour)} <span class="unit">ПРОД/Ч</span></div>
    </div>
  </div>`;

  if (d.description)
    html += `<div class="item-desc">${escapeHtml(d.description)}</div>`;

  html += verdictBlock(d);

  if (d.craftable) {
    html += tilesBlock(d, chosen);
    if (chosen) {
      html += treeBlock(d, chosen);
      if (d.tree.alternatives && d.tree.alternatives.length)
        html += altsBlock(d.tree.alternatives);
    } else {
      html += `<div class="empty">РЕЦЕПТ ЕСТЬ, НО ДЕРЕВО НЕ РАСКРЫЛОСЬ (СЛИШКОМ ГЛУБОКО ИЛИ ЦИКЛ).</div>`;
    }
    if (API_IS_DEMO)
      html += `<div class="note-warn"><span class="mark">[!]</span>
        ДЕМО-РЕЖИМ: ЦЕНЫ АУКЦИОНА ТЕСТОВЫЕ. ДЛЯ РЕАЛЬНЫХ КОТИРОВОК НУЖЕН PROD-ТОКЕН API.</div>`;
  }

  html += `</div>`;                      // /card-main
  html += asideBlock(chosen, d.used_in, d.req_check);
  html += `</div>`;                      // /card-cols

  detail.innerHTML = html;
  wireDetail();
}

function wireDetail() {
  const b = detail.querySelector(".back");
  if (b) b.addEventListener("click", () => {
    navigate(lastQuery ? `/search?q=${encodeURIComponent(lastQuery)}` : "/");
  });
  detail.querySelectorAll(".tname[data-id], .ilink[data-id], .use-row[data-id]").forEach((el) =>
    el.addEventListener("click", () => { navigate(`/item/${el.dataset.id}`); }));
}

// ---------- главная: биржа ингредиентов + подборки ----------
async function loadHome() {
  // не дёргаем чаще раза в минуту — на бэке рейтинги тоже кэшируются
  if (home.dataset.ts && Date.now() - +home.dataset.ts < 60000) return;
  if (!home.innerHTML) home.innerHTML = `<div class="spinner">// ЗАГРУЗКА ГЛАВНОЙ</div>`;
  try {
    const [top, watch] = await Promise.all([
      fetch(api(`/top${availParam("?")}`)).then((r) => r.json()),
      fetch(api("/watch")).then((r) => r.json()).catch(() => null),
    ]);
    home.dataset.ts = Date.now();
    renderHome(top, watch);
  } catch (e) {
    home.innerHTML = `<div class="empty">[!] НЕ УДАЛОСЬ ЗАГРУЗИТЬ ГЛАВНУЮ</div>`;
  }
}

// линия средней цены по снапшотам (2 замера/сутки)
function chartSvg(series) {
  const vals = series.map((e) => e.avg).filter((v) => v != null);
  if (!vals.length) return `<div class="watch-nodata">НЕТ ДАННЫХ — ЖДЁМ ПЕРВЫЙ ЗАМЕР</div>`;
  const pts = vals.length === 1 ? [vals[0], vals[0]] : vals;
  const W = 200, H = 48, P = 5;
  const min = Math.min(...pts), max = Math.max(...pts), r = max - min || 1;
  const xy = pts.map((v, i) =>
    `${(i / (pts.length - 1)) * W},${(P + (H - 2 * P) * (1 - (v - min) / r)).toFixed(1)}`);
  const line = xy.join(" ");
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <polyline points="0,${H * 2 / 3} ${W},${H * 2 / 3}" fill="none" stroke="var(--bar-track)" stroke-width="1"></polyline>
    <polyline points="0,${H / 3} ${W},${H / 3}" fill="none" stroke="var(--bar-track)" stroke-width="1"></polyline>
    <polygon points="0,${H} ${line} ${W},${H}" fill="rgba(124,230,142,0.08)"></polygon>
    <polyline points="${line}" fill="none" stroke="var(--green)" stroke-width="1.5"></polyline>
  </svg>`;
}

function watchCard(m) {
  const dp = m.delta_pct;
  const delta = dp == null ? ""
    : `<span class="pct ${dp > 0 ? "up" : dp < 0 ? "down" : "dim"}">${dp > 0 ? "+" : ""}${dp}%</span>`;
  return `<div class="watch-card" data-id="${m.id}">
    <div class="watch-head">
      <img loading="lazy" src="${asset(m.icon)}" alt="">
      <div class="watch-name">${escapeHtml(m.name)}</div>${delta}
    </div>
    <div class="watch-price">${m.avg != null ? fmt(m.avg) + " ₽" : "—"} <span class="unit">СР./ШТ</span></div>
    <div class="watch-chart">${chartSvg(m.series || [])}</div>
    <div class="watch-foot">
      <span>МИН ВЫКУП ${m.min_buyout != null ? fmt(m.min_buyout) + " ₽" : "—"}</span>
      <span>${m.sales_per_hour != null ? fmtSales(m.sales_per_hour) + " ПРОД/Ч" : ""}</span>
    </div>
  </div>`;
}

const fmtSlot = (slot) => {
  // "2026-07-10T01:00" -> "10.07 01:00"
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})$/.exec(slot || "");
  return m ? `${m[3]}.${m[2]} ${m[4]}` : "";
};

function watchBlock(w) {
  if (!w || !w.items || !w.items.length) return "";
  const hours = (w.hours || []).map((h) => String(h).padStart(2, "0") + ":00").join(" · ");
  const upd = w.last_slot ? ` · ЗАМЕР ${fmtSlot(w.last_slot)}` : "";
  return `<section>
    <div class="section-head">
      <div class="section-title">▸ БИРЖА ИНГРЕДИЕНТОВ · СРЕДНЯЯ ЦЕНА ПРОДАЖ</div>
      <div class="section-note">ОБНОВЛЕНИЕ ${hours} МСК${upd}</div>
    </div>
    <div class="watch-grid">${w.items.map(watchCard).join("")}</div>
  </section>`;
}

function sideRow(e, extra) {
  const badge = e.pct == null
    ? `<span class="pct dim">—</span>`
    : `<span class="pct ${e.pct > 0 ? "up" : "down"}">${e.pct > 0 ? "+" : ""}${e.pct}%</span>`;
  const meta = [];
  if (e.craft_cost != null) meta.push(`КРАФТ ${fmt(e.craft_cost)}`);
  if (e.buy_price != null) meta.push(`АУК ${fmt(e.buy_price)}`);
  if (extra === "sales" && e.sales_per_hour != null) meta.push(`${fmtSales(e.sales_per_hour)} ПРОД/Ч`);
  if (extra === "opens" && e.opens) meta.push(`${e.opens} ОТКР`);
  return `<div class="side-row" data-id="${e.id}" style="border-left-color:transparent">
    <img loading="lazy" src="${asset(e.icon)}" alt="">
    <div class="info">
      <div class="nm">${escapeHtml(e.name)}</div>
      <div class="meta">${meta.join(" · ")}</div>
    </div>
    ${badge}</div>`;
}

function renderHome(d, w) {
  const sec = (title, note, list, extra, empty) => `
    <section>
      <div class="side-head">
        <div class="side-title">▸ ${title}</div>
        <div class="side-note">${note}</div>
      </div>
      ${list && list.length
        ? `<div class="side-list">${list.map((e) => sideRow(e, extra)).join("")}</div>`
        : `<div class="empty-sm">${empty}</div>`}
    </section>`;

  // лендинг «что выгодно крафтить» — видимый заголовок под SEO-запрос
  let h = location.pathname === "/vygodno-kraftit"
    ? `<div class="landing-intro">
        <h2>Что выгодно крафтить в STALZONE сегодня</h2>
        <p>Живой рейтинг выгоды: сравниваем себестоимость крафта по дереву рецептов
        с ценой готового предмета на аукционе и показываем, где маржа положительная.
        Данные обновляются автоматически.</p>
      </div>` : "";
  h += watchBlock(w);

  h += `<div class="home-cols">`;
  const availEmpty = d.available_only
    ? "ПО ТВОЕЙ ПРОКАЧКЕ НИЧЕГО НЕ ПРОШЛО — ПРОВЕРЬ ПРОФИЛЬ ИЛИ ПЕРЕКЛЮЧИ НА «ВСЕ»." : null;
  const availNote = d.available_only ? " · ДОСТУПНЫЕ" : "";
  h += sec("ВЫГОДНЫЕ КРАФТЫ", "КРАФТ VS АУК" + availNote, d.profitable, null,
           availEmpty || "ЦЕНЫ СЧИТАЮТСЯ В ФОНЕ — ЗАГЛЯНИ ЧЕРЕЗ ПАРУ МИНУТ.");
  h += sec("ПРОФИТНЫЕ", `ПРОДАЖИ ${d.liquid_threshold || 10}+/Ч${availNote}`, d.liquid, "sales",
           availEmpty || "НЕТ ПРЕДМЕТОВ С ТАКОЙ ЧАСТОТОЙ ПРОДАЖ (ИЛИ ЦЕНЫ ЕЩЁ СЧИТАЮТСЯ).");
  h += sec("ПОПУЛЯРНЫЕ", "ОТКРЫТИЯ КАРТОЧЕК" + availNote, d.popular, "opens",
           availEmpty || "ПОКА НЕТ СТАТИСТИКИ — ОТКРЫВАЙ КАРТОЧКИ ПРЕДМЕТОВ.");
  h += `</div>`;

  h += `<div class="side-foot">ИСТОЧНИКИ: STALZONE-DATABASE (РЕЦЕПТЫ, СУТОЧНОЕ ОБНОВЛЕНИЕ) ·
    AUCTION API (ЦЕНЫ, ФОНОВЫЙ ПРОГРЕВ).${API_IS_DEMO ? `<br><span class="warn">РЕЖИМ ДЕМО — ЦЕНЫ ТЕСТОВЫЕ.</span>` : ""}</div>`;

  home.innerHTML = h;
  home.querySelectorAll(".side-row, .watch-card").forEach((r) =>
    r.addEventListener("click", () => { navigate(`/item/${r.dataset.id}`); }));
}

// ---------- биржа артефактов: топ роста цен по корзинам качество×заточка ----------
const QLT_RU = { 0: "ОБЫЧНЫЙ", 1: "НЕОБЫЧНЫЙ", 2: "ОСОБЫЙ",
                 3: "РЕДКИЙ", 4: "ИСКЛЮЧИТЕЛЬНЫЙ", 5: "ЛЕГЕНДАРНЫЙ" };
const qltLabel = (q) => `Q${q}` + (QLT_RU[q] ? ` · ${QLT_RU[q]}` : "");
const bucketBadge = (qlt, ptn) => `Q${qlt} +${ptn}`;
const PTN_LEVELS = [0, 5, 10, 15];  // уровни заточки в UI (решение: только эти)

let artFilters = { window: "7d", qlt: -1, ptn: -1 };
let artCardSel = null;  // предвыбор корзины при переходе из рейтинга {qlt, ptn}

async function openAuction() {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА БИРЖИ АРТЕФАКТОВ</div>`;
  try {
    const q = `window=${artFilters.window}&qlt=${artFilters.qlt}&ptn=${artFilters.ptn}`;
    const d = await fetch(api(`/artmarket/top?${q}`)).then((r) => r.json());
    renderAuction(d);
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
  }
}

function artRow(e) {
  return `<div class="side-row" data-id="${e.id}" data-qlt="${e.qlt}" data-ptn="${e.ptn}">
    <img loading="lazy" src="${asset(e.icon)}" alt="">
    <div class="info">
      <div class="nm">${escapeHtml(e.name)} <span class="bucket">${bucketBadge(e.qlt, e.ptn)}</span></div>
      <div class="meta">СР. ${fmt(e.avg)} ₽ · БЫЛО ${fmt(e.prev_avg)} ₽ · ${e.n} ПРОД</div>
    </div>
    <span class="pct ${e.pct > 0 ? "up" : "down"}">${e.pct > 0 ? "+" : ""}${e.pct}%</span>
  </div>`;
}

function renderAuction(d) {
  const optQ = [-1, 0, 1, 2, 3, 4, 5].map((v) =>
    `<option value="${v}" ${artFilters.qlt === v ? "selected" : ""}>${v < 0 ? "КАЧЕСТВО: ВСЕ" : qltLabel(v)}</option>`).join("");
  const optP = [-1, ...PTN_LEVELS].map((v) =>
    `<option value="${v}" ${artFilters.ptn === v ? "selected" : ""}>${v < 0 ? "ЗАТОЧКА: ВСЕ" : "+" + v}</option>`).join("");

  let h = `<div class="section-head">
      <div class="section-title">▸ БИРЖА АРТЕФАКТОВ · ДИНАМИКА СРЕДНЕЙ ЦЕНЫ ПРОДАЖ</div>
      <div class="section-note">${d.last_slot ? "ЗАМЕР " + fmtSlot(d.last_slot) : "ЗАМЕРОВ ЕЩЁ НЕ БЫЛО"}</div>
    </div>
    <div class="artbar">
      <button class="awin ${d.window === "7d" ? "on" : ""}" data-w="7d">НЕДЕЛЯ</button>
      <button class="awin ${d.window === "24h" ? "on" : ""}" data-w="24h">СУТКИ</button>
      <select id="aQlt">${optQ}</select>
      <select id="aPtn">${optP}</select>
      <span class="art-note">КОРЗИН В РЕЙТИНГЕ: ${d.buckets_ranked} · ПОРОГ ${d.min_sales} ПРОДАЖ/ОКНО</span>
    </div>`;

  if (!d.up.length && !d.down.length) {
    h += `<div class="stub">
      <div class="stub-code">[ НАКОПЛЕНИЕ ДАННЫХ ]</div>
      <div class="stub-title">▸ ДАННЫЕ КОПЯТСЯ</div>
      <div class="stub-desc">${d.buckets_tracked
        ? `Корзины уже отслеживаются (${d.buckets_tracked}), но для рейтинга нужно два полных
           окна (${d.window === "24h" ? "сутки + неделя до них" : "неделя + неделя до неё"}).
           Первый замер: ${d.first_slot ? fmtSlot(d.first_slot) : "—"}.`
        : `Замеры идут ${(d.hours || []).map((x) => String(x).padStart(2, "0") + ":00").join(" · ")} МСК.
           Первые данные появятся после ближайшего замера.`}
      ${API_IS_DEMO ? "<br><br>ДЕМО-РЕЖИМ: биржа артефактов не работает — демо-API не отдаёт качество/заточку продаж." : ""}</div>
      <div class="stub-status">СТАТУС: СБОР ДАННЫХ</div>
    </div>`;
  } else {
    h += `<div class="art-cols">
      <section>
        <div class="side-head"><div class="side-title">▸ РАСТУТ В ЦЕНЕ</div>
          <div class="side-note">${d.window === "24h" ? "СУТКИ VS НЕДЕЛЯ ДО НИХ" : "НЕДЕЛЯ VS ПРЕДЫДУЩАЯ"}</div></div>
        ${d.up.length ? `<div class="side-list">${d.up.map(artRow).join("")}</div>`
                      : `<div class="empty-sm">НЕТ РАСТУЩИХ КОРЗИН ПОД ФИЛЬТР</div>`}
      </section>
      <section>
        <div class="side-head"><div class="side-title">▸ ПАДАЮТ</div>
          <div class="side-note">ТА ЖЕ БАЗА СРАВНЕНИЯ</div></div>
        ${d.down.length ? `<div class="side-list">${d.down.map(artRow).join("")}</div>`
                        : `<div class="empty-sm">НЕТ ПАДАЮЩИХ КОРЗИН ПОД ФИЛЬТР</div>`}
      </section>
    </div>`;
  }
  h += `<div class="side-foot">СРЕДНЯЯ ЦЕНА ПРОДАЖ ИЗ ИСТОРИИ АУКЦИОНА ПО КОРЗИНАМ
    КАЧЕСТВО (Q0 ОБЫЧНЫЙ … Q5 ЛЕГЕНДАРНЫЙ) × ЗАТОЧКА (+0/+5/+10/+15).
    МОМЕНТАЛЬНЫЕ ЛОТЫ НЕ УЧИТЫВАЮТСЯ — ОНИ ЛЕГКО МАНИПУЛИРУЮТСЯ.</div>`;

  page.innerHTML = h;
  page.querySelectorAll(".awin").forEach((b) => b.addEventListener("click", () => {
    artFilters.window = b.dataset.w;
    openAuction();
  }));
  $("aQlt").addEventListener("change", (e) => { artFilters.qlt = +e.target.value; openAuction(); });
  $("aPtn").addEventListener("change", (e) => { artFilters.ptn = +e.target.value; openAuction(); });
  page.querySelectorAll(".side-row").forEach((r) => r.addEventListener("click", () => {
    artCardSel = { qlt: +r.dataset.qlt, ptn: +r.dataset.ptn };
    navigate(`/artefact/${r.dataset.id}`);
  }));
}

// ---------- карточка артефакта на бирже ----------
async function openArtCard(id) {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА КОРЗИН АРТЕФАКТА</div>`;
  window.scrollTo(0, 0);
  try {
    const d = await fetch(api(`/artmarket/${id}`)).then((r) => r.json());
    renderArtCard(d);
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] ОШИБКА ЗАГРУЗКИ</div>`;
  }
}

function renderArtCard(d) {
  const it = d.item;
  const rk = rank(it.color);
  const bs = d.buckets || [];
  let sel = artCardSel && bs.find((b) => b.qlt === artCardSel.qlt && b.ptn === artCardSel.ptn);
  if (!sel) sel = bs.find((b) => b.avg7d != null) || bs[0];
  artCardSel = null;

  let h = `<button class="back" id="artBack">◂ К БИРЖЕ</button>
    <div class="item-head">
      <div class="item-icon" style="border-color:${rk.color}"><img src="${asset(it.icon)}" alt=""></div>
      <div class="head-info">
        <div class="title">${escapeHtml(it.name)}</div>
        <div class="head-chips">
          <span class="chip" style="border-color:${rk.color};color:${rk.color}">${rk.label}</span>
          <span class="chip">БИРЖА АРТЕФАКТОВ</span>
          ${d.last_slot ? `<span class="chip">ЗАМЕР ${fmtSlot(d.last_slot)}</span>` : ""}
        </div>
      </div>
    </div>`;

  if (!bs.length) {
    h += `<div class="empty">ПО ЭТОМУ АРТЕФАКТУ ЕЩЁ НЕТ ЗАМЕРОВ — ДАННЫЕ КОПЯТСЯ ПО РАСПИСАНИЮ.</div>`;
    page.innerHTML = h;
    $("artBack").addEventListener("click", () => { navigate("/auction"); });
    return;
  }

  h += `<div class="section-head"><div class="section-title">▸ КОРЗИНЫ КАЧЕСТВО × ЗАТОЧКА</div>
    <div class="section-note">СР. ЦЕНА ЗА 7 ДНЕЙ · ПОРОГ ${d.min_sales} ПРОДАЖ</div></div>
    <div class="bucket-row">${bs.map((b) => `
      <button class="bucket-chip ${b === sel ? "on" : ""} ${PTN_LEVELS.includes(b.ptn) ? "" : "offlevel"}"
              data-q="${b.qlt}" data-p="${b.ptn}" title="${qltLabel(b.qlt)}, заточка +${b.ptn}">
        <span class="bb">${bucketBadge(b.qlt, b.ptn)}</span>
        <span class="bp">${b.avg7d != null ? fmt(b.avg7d) + " ₽"
          : b.price ? fmt(b.price.price) + " ₽ · ЛОТЫ" : "мало данных"}</span>
        <span class="bn">${b.n7} ПРОД/7Д</span>
      </button>`).join("")}
    </div>
    <div id="bucketChart"></div>`;

  page.innerHTML = h;
  $("artBack").addEventListener("click", () => { navigate("/auction"); });
  const drawChart = (b) => {
    $("bucketChart").innerHTML = `
      <div class="section-head"><div class="section-title">▸ ДИНАМИКА · ${bucketBadge(b.qlt, b.ptn)}</div>
        <div class="section-note">ТОЧКА = ЗАМЕР (~КАЖДЫЕ 6 Ч)</div></div>
      <div class="watch-card art-chart">
        <div class="watch-price">${b.avg7d != null ? fmt(b.avg7d) + " ₽" : "—"} <span class="unit">СР. 7Д</span></div>
        <div class="watch-chart">${chartSvg(b.series || [])}</div>
        <div class="watch-foot">
          <span>${b.series.length ? "С " + fmtSlot(b.series[0].slot) : ""}</span>
          <span>${b.n7} ПРОДАЖ ЗА 7 ДНЕЙ</span>
        </div>
      </div>`;
  };
  drawChart(sel);
  page.querySelectorAll(".bucket-chip").forEach((c) => c.addEventListener("click", () => {
    page.querySelectorAll(".bucket-chip").forEach((x) => x.classList.remove("on"));
    c.classList.add("on");
    const b = bs.find((x) => x.qlt === +c.dataset.q && x.ptn === +c.dataset.p);
    if (b) drawChart(b);
  }));
}

// ---------- калькулятор сборок: ручной + автоподбор ----------
let BUILD_DICT = null;   // /api/build/dict (кэш на сессию)
let buildTab = "manual";
const buildState = { container: null, slots: [] };  // слот: {id, ptn, m} | null
const autoState = { budget: 500000, stats: [{ key: "", weight: 60 }], result: null };
const artPriceCache = {};  // itemId -> {"qlt:ptn": {avg7d, n7}}
let pickerSlot = -1, pickerQuery = "";

const MDL = () => BUILD_DICT.model;
const tierTop = (q) => 1 + MDL().tier_step * q;
const tierBottom = (q) => (q === 0 ? MDL().m_min : tierTop(q) - MDL().tier_step);
const qltFromM = (m) => (m <= 1 ? 0 : Math.min(5, Math.ceil((m - 1) / MDL().tier_step - 1e-9)));
// опорное значение — конец диапазона с большим модулем (у «меньше — лучше» он отрицательный)
const statBase = (st) => (Math.abs(st.max) >= Math.abs(st.min) ? st.max : st.min);
const statVal = (st, m, ptn) => (st.harmful ? statBase(st) : statBase(st) * m * (1 + MDL().ptn_bonus * ptn));
const fmtStat = (v) => (v > 0 ? "+" : "") + (Math.abs(v) >= 100 ? Math.round(v) : v.toFixed(2));
const contLabel = (c) =>
  `${c.name} · ${c.slots} СЛОТ${c.slots > 1 ? "А" : ""} · ЭФФ ${c.efficiency ?? "—"}% · ЗАЩИТА ${c.protection ?? "—"}`;

async function openBuilds() {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  if (!BUILD_DICT) {
    page.innerHTML = `<div class="spinner">// ЗАГРУЗКА КАЛЬКУЛЯТОРА СБОРОК</div>`;
    try {
      BUILD_DICT = await fetch(api("/build/dict")).then((r) => r.json());
    } catch (e) {
      page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
      return;
    }
    const first = BUILD_DICT.containers[0];
    buildState.container = first ? first.id : null;
    buildState.slots = first ? Array(first.slots).fill(null) : [];
  }
  renderBuilds();
}

function buildContainer() {
  return BUILD_DICT.containers.find((c) => c.id === buildState.container);
}

async function loadArtPrices(id) {
  if (artPriceCache[id]) return;
  artPriceCache[id] = {};
  try {
    const d = await fetch(api(`/artmarket/${id}`)).then((r) => r.json());
    for (const b of d.buckets || [])
      artPriceCache[id][`${b.qlt}:${b.ptn}`] = b.price || null;  // {price, n, src}
  } catch (e) { /* цен нет — покажем «нет цены» */ }
  renderBuilds();
}

// эффективная цена корзины: {price, n, src} или null (источник решает бэк)
function slotPrice(s) {
  return (artPriceCache[s.id] || {})[`${qltFromM(s.m)}:${s.ptn}`] || null;
}

const srcLabel = (src) => (src === "lots" ? `СР. 5 ДЕШЁВЫХ ЛОТОВ` : "СР. ЗА 7 ДНЕЙ");

// суммарные статы: полезные × эффективность контейнера, вредные — константа
function manualTotals(cont) {
  const eff = (cont.efficiency ?? 100) / 100;
  const stats = {}, out = { cost: 0, unpriced: 0, weight: cont.weight || 0, stats };
  for (const s of buildState.slots) {
    if (!s) continue;
    const art = BUILD_DICT.artefacts.find((a) => a.id === s.id);
    out.weight += art.weight || 0;
    for (const [k, st] of Object.entries(art.stats)) {
      const t = stats[k] || (stats[k] = { name: st.name, harmful: st.harmful, total: 0 });
      t.total += st.harmful ? st.max : statVal(st, s.m, s.ptn) * eff;
    }
    const p = slotPrice(s);
    if (p) out.cost += p.price; else out.unpriced++;
  }
  return out;
}

function totalsBlock(t, cont, budget) {
  const rows = Object.values(t.stats)
    .sort((a, b) => a.harmful - b.harmful || a.name.localeCompare(b.name, "ru"))
    .map((s) => `<div class="bt-row ${s.harmful ? "bad" : ""}">
        <span class="k">${escapeHtml(s.name)}</span>
        <span class="v">${fmtStat(s.total)}</span></div>`).join("");
  return `<div class="btotals">
    <div class="reqs-lbl">ИТОГО ПО СБОРКЕ</div>
    ${rows || `<div class="empty-sm">СЛОТЫ ПУСТЫ</div>`}
    <div class="bt-row"><span class="k">ВЕС (С КОНТЕЙНЕРОМ)</span><span class="v">${t.weight.toFixed(2)} КГ</span></div>
    <div class="bt-row"><span class="k">ЗАЩИТА КОНТЕЙНЕРА</span><span class="v">${cont.protection ?? "—"}</span></div>
    <div class="bt-row cost"><span class="k">СТОИМОСТЬ СБОРКИ</span>
      <span class="v">${fmt(t.cost)} ₽${t.unpriced ? ` <span class="warn">+ ${t.unpriced} БЕЗ ЦЕНЫ</span>` : ""}</span></div>
    ${budget != null ? `<div class="bt-row"><span class="k">БЮДЖЕТ</span><span class="v">${fmt(budget)} ₽</span></div>` : ""}
  </div>`;
}

function manualSlotCard(s, idx) {
  if (!s) {
    if (pickerSlot === idx) {
      const q = pickerQuery.toLowerCase();
      const found = BUILD_DICT.artefacts
        .filter((a) => a.name.toLowerCase().includes(q)).slice(0, 8);
      return `<div class="bslot picker">
        <input id="pickerInput" type="text" placeholder="НАЗВАНИЕ АРТЕФАКТА…" value="${escapeHtml(pickerQuery)}">
        <div class="pick-list">${found.map((a) =>
          `<div class="pick-row" data-pick="${a.id}">
             <img loading="lazy" src="${asset(a.icon)}" alt=""><span>${escapeHtml(a.name)}</span>
             <span class="cls">${escapeHtml(a.class)}</span></div>`).join("") || `<div class="empty-sm">НЕ НАЙДЕНО</div>`}
        </div></div>`;
    }
    return `<div class="bslot empty-slot" data-addslot="${idx}">+ АРТЕФАКТ</div>`;
  }
  const art = BUILD_DICT.artefacts.find((a) => a.id === s.id);
  const qlt = qltFromM(s.m);
  const ptnOpts = Array.from({ length: 16 }, (_, i) =>
    `<option value="${i}" ${s.ptn === i ? "selected" : ""}>+${i}</option>`).join("");
  const price = slotPrice(s);
  const statRows = Object.entries(art.stats).map(([k, st]) => {
    if (st.harmful)
      return `<div class="bstat bad"><span class="sn">${escapeHtml(st.name)}</span>
        <span class="sv">${fmtStat(st.min)}…${fmtStat(st.max)}</span></div>`;
    const v = statVal(st, s.m, s.ptn);
    return `<div class="bstat"><span class="sn">${escapeHtml(st.name)}</span>
      <span class="sctl">
        <button class="mbtn" data-slot="${idx}" data-d="-1">−</button>
        <input class="sval" data-slot="${idx}" data-stat="${k}" value="${v.toFixed(2)}">
        <button class="mbtn" data-slot="${idx}" data-d="1">+</button>
      </span></div>`;
  }).join("");
  return `<div class="bslot">
    <div class="bs-head">
      <img loading="lazy" src="${asset(art.icon)}" alt="">
      <div class="bs-nm">${escapeHtml(art.name)}<div class="bs-cls">${escapeHtml(art.class)}</div></div>
      <button class="bs-x" data-rm="${idx}" title="Убрать">✕</button>
    </div>
    <div class="bs-ctl">
      <span class="chip" title="${qltLabel(qlt)} · меняется стрелками у статов">${qltLabel(qlt)}</span>
      <select class="bs-ptn" data-slot="${idx}">${ptnOpts}</select>
    </div>
    ${statRows}
    <div class="bs-price">${price ? `${fmt(price.price)} ₽ · ${srcLabel(price.src)}` : "НЕТ ЦЕНЫ (НЕТ ЛОТОВ И ИСТОРИИ)"}</div>
  </div>`;
}

function renderBuilds() {
  const cont = buildContainer();
  if (!cont) { page.innerHTML = `<div class="empty">НЕТ ДАННЫХ КОНТЕЙНЕРОВ</div>`; return; }
  const contOpts = BUILD_DICT.containers.map((c) =>
    `<option value="${c.id}" ${c.id === buildState.container ? "selected" : ""}>${escapeHtml(contLabel(c))}</option>`).join("");

  let h = `<div class="section-head">
      <div class="section-title">▸ КАЛЬКУЛЯТОР СБОРОК АРТЕФАКТОВ</div>
      <div class="section-note">ЦЕНЫ: 5 ДЕШЁВЫХ ЛОТОВ → СР. 7Д ПОСЛЕ НАКОПЛЕНИЯ БИРЖИ</div>
    </div>
    <div class="btabs">
      <button class="btab ${buildTab === "manual" ? "on" : ""}" data-tab="manual">СОБРАТЬ ВРУЧНУЮ</button>
      <button class="btab ${buildTab === "auto" ? "on" : ""}" data-tab="auto">АВТОПОДБОР ПОД БЮДЖЕТ</button>
    </div>
    <div class="bbar"><select id="bCont">${contOpts}</select></div>`;

  h += buildTab === "manual" ? renderManual(cont) : renderAuto(cont);
  h += `<div class="side-foot">КАЧЕСТВО ЗАДАЁТСЯ ЗНАЧЕНИЕМ СТАТА (СТРЕЛКИ/ВВОД): ВЫХОД ЗА ГРАНИЦЫ ТИРА
    МЕНЯЕТ КАЧЕСТВО АВТОМАТИЧЕСКИ, ДИАПАЗОН — ОТ НИЗА ОБЫЧНОГО ДО ВЕРХА ЛЕГЕНДАРНОГО.
    СЛУЧАЙНЫЕ ДОП-СВОЙСТВА КАЖДЫХ +5 ЗАТОЧКИ И СВЕЖЕСТЬ НЕ МОДЕЛИРУЮТСЯ.</div>`;
  page.innerHTML = h;
  wireBuilds(cont);
}

function renderManual(cont) {
  const t = manualTotals(cont);
  return `<div class="bgrid">${buildState.slots.map((s, i) => manualSlotCard(s, i)).join("")}</div>
    ${totalsBlock(t, cont, null)}`;
}

function renderAuto(cont) {
  const beneficial = BUILD_DICT.stats.filter((s) => !s.harmful);
  const rows = autoState.stats.map((row, i) => {
    const used = autoState.stats.map((r) => r.key);
    const opts = [`<option value="">— СТАТ —</option>`, ...beneficial
      .filter((s) => s.key === row.key || !used.includes(s.key))
      .map((s) => `<option value="${s.key}" ${row.key === s.key ? "selected" : ""}>${escapeHtml(s.name)}</option>`)];
    return `<div class="arow">
      <select class="aStat" data-i="${i}">${opts.join("")}</select>
      <input class="aW" data-i="${i}" type="range" min="0" max="100" value="${row.weight}">
      <span class="aWv">${row.weight}</span>
      ${autoState.stats.length > 1 ? `<button class="bs-x" data-rmstat="${i}">✕</button>` : ""}
    </div>`;
  }).join("");
  let res = "";
  const r = autoState.result;
  if (r && r.error === "no_priced_variants")
    res = `<div class="note-warn"><span class="mark">[!]</span> ${escapeHtml(r.hint || "НЕТ ЦЕНОВЫХ ДАННЫХ")}</div>`;
  else if (r && r.builds && r.builds.length) res = renderAutoResult(r);
  else if (r && r.builds) res = `<div class="empty">НИЧЕГО НЕ ПОДОБРАЛОСЬ ПОД БЮДЖЕТ.</div>`;
  return `<div class="aform">
      <label class="albl">БЮДЖЕТ, ₽ <input id="aBudget" type="number" min="1" value="${autoState.budget}"></label>
      ${rows}
      ${autoState.stats.length < 3 ? `<button id="aAdd" class="awin">+ СТАТ</button>` : ""}
      <button id="aGo" class="prof-save">РАССЧИТАТЬ СБОРКУ</button>
    </div>${res}`;
}

function renderAutoResult(r) {
  const build = (b, title, open) => `<details class="alt abuild" ${open ? "open" : ""}>
    <summary><b>${title}</b> · ${fmt(b.totals.cost)} ₽ · ${b.slots.length} СЛОТ</summary>
    <div class="bgrid">${b.slots.map((s) => `
      <div class="bslot ro">
        <div class="bs-head"><img loading="lazy" src="${asset(s.icon)}" alt="">
          <div class="bs-nm">${escapeHtml(s.name)}</div>
          <span class="bucket">${bucketBadge(s.qlt, s.ptn)}</span></div>
        <div class="bs-price">${fmt(s.price)} ₽ · ${s.src === "lots" ? s.sales + " ЛОТ." : s.sales + " ПРОД/7Д"}</div>
      </div>`).join("")}</div>
    ${totalsBlock({ stats: b.totals.stats, cost: b.totals.cost, unpriced: 0, weight: b.totals.weight },
                  r.container, autoState.budget)}
  </details>`;
  let h = build(r.builds[0], "ОПТИМАЛЬНАЯ СБОРКА", true);
  r.builds.slice(1).forEach((b, i) => { h += build(b, `АЛЬТЕРНАТИВА ${i + 1}`, false); });
  if (r.warnings && r.warnings.length)
    h += `<div class="note-warn"><span class="mark">[!]</span> ${r.warnings.map(escapeHtml).join("<br>")}</div>`;
  return h;
}

function wireBuilds(cont) {
  page.querySelectorAll(".btab").forEach((b) => b.addEventListener("click", () => {
    buildTab = b.dataset.tab;
    renderBuilds();
  }));
  $("bCont").addEventListener("change", (e) => {
    buildState.container = e.target.value;
    const c = buildContainer();
    const old = buildState.slots;
    buildState.slots = Array(c.slots).fill(null).map((_, i) => old[i] || null);
    renderBuilds();
  });

  if (buildTab === "auto") {
    $("aBudget").addEventListener("change", (e) => { autoState.budget = Math.max(1, +e.target.value || 1); });
    page.querySelectorAll(".aStat").forEach((s) => s.addEventListener("change", () => {
      autoState.stats[+s.dataset.i].key = s.value;
      renderBuilds();
    }));
    page.querySelectorAll(".aW").forEach((s) => s.addEventListener("input", () => {
      autoState.stats[+s.dataset.i].weight = +s.value;
      s.nextElementSibling.textContent = s.value;
    }));
    page.querySelectorAll("[data-rmstat]").forEach((b) => b.addEventListener("click", () => {
      autoState.stats.splice(+b.dataset.rmstat, 1);
      renderBuilds();
    }));
    const add = $("aAdd");
    if (add) add.addEventListener("click", () => {
      autoState.stats.push({ key: "", weight: 50 });
      renderBuilds();
    });
    $("aGo").addEventListener("click", async () => {
      const stats = autoState.stats.filter((s) => s.key);
      if (!stats.length) return;
      $("aGo").textContent = "СЧИТАЮ…";
      try {
        autoState.result = await fetch(api("/build/auto"), {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ budget: autoState.budget, container: buildState.container, stats }),
        }).then((r) => r.json());
      } catch (e) { autoState.result = { error: "no_priced_variants", hint: "ОШИБКА СЕТИ" }; }
      renderBuilds();
    });
    return;
  }

  // ручной режим
  page.querySelectorAll("[data-addslot]").forEach((el) => el.addEventListener("click", () => {
    pickerSlot = +el.dataset.addslot;
    pickerQuery = "";
    renderBuilds();
    const inp = $("pickerInput");
    if (inp) inp.focus();
  }));
  const inp = $("pickerInput");
  if (inp) {
    inp.focus();
    inp.setSelectionRange(inp.value.length, inp.value.length);
    inp.addEventListener("input", () => {
      pickerQuery = inp.value;
      renderBuilds();
      const again = $("pickerInput");
      if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
    });
  }
  page.querySelectorAll("[data-pick]").forEach((el) => el.addEventListener("click", () => {
    buildState.slots[pickerSlot] = { id: el.dataset.pick, ptn: 0, m: 1.0 };
    pickerSlot = -1;
    loadArtPrices(el.dataset.pick);  // цены подтянутся и перерисуют
    renderBuilds();
  }));
  page.querySelectorAll("[data-rm]").forEach((el) => el.addEventListener("click", () => {
    buildState.slots[+el.dataset.rm] = null;
    renderBuilds();
  }));
  page.querySelectorAll(".bs-ptn").forEach((el) => el.addEventListener("change", () => {
    buildState.slots[+el.dataset.slot].ptn = +el.value;
    renderBuilds();
  }));
  page.querySelectorAll(".mbtn").forEach((el) => el.addEventListener("click", () => {
    const s = buildState.slots[+el.dataset.slot];
    s.m = Math.min(MDL().m_max, Math.max(MDL().m_min, s.m + 0.01 * +el.dataset.d));
    renderBuilds();
  }));
  page.querySelectorAll(".sval").forEach((el) => el.addEventListener("change", () => {
    const s = buildState.slots[+el.dataset.slot];
    const art = BUILD_DICT.artefacts.find((a) => a.id === s.id);
    const st = art.stats[el.dataset.stat];
    const v = parseFloat(String(el.value).replace(",", "."));
    const base = st ? statBase(st) : 0;
    if (!isNaN(v) && st && !st.harmful && base) {
      const m = v / (base * (1 + MDL().ptn_bonus * s.ptn));
      s.m = Math.min(MDL().m_max, Math.max(MDL().m_min, m));
    }
    renderBuilds();
  }));
}

// ---------- профиль убежища: прокачка перков и станков ----------
async function openProfile() {
  home.classList.add("hidden");
  results.innerHTML = "";
  detail.classList.remove("hidden");
  detail.innerHTML = `<div class="spinner">// ЗАГРУЗКА ПРОФИЛЯ</div>`;
  try {
    const me = await fetch(api("/me")).then((r) => r.json());
    if (!me.authenticated) {
      detail.innerHTML = `<div class="empty">ПРОФИЛЬ ДОСТУПЕН ПОСЛЕ ВХОДА ЧЕРЕЗ EXBO.
        <a class="auth-login" href="${BASE}/auth/login">ВОЙТИ</a></div>`;
      return;
    }
    const [dict, prof] = await Promise.all([
      fetch(api("/hideout")).then((r) => r.json()),
      fetch(api("/profile")).then((r) => r.json()),
    ]);
    renderProfile(dict, prof, me.user);
  } catch (e) {
    detail.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
  }
}

function renderProfile(dict, prof, user) {
  const pm = dict.perk_max || 10;
  const P = { perks: { ...(prof.perks || {}) }, features: new Set(prof.features || []) };
  const feats = [...(dict.features || [])]
    .sort((a, b) => featureName(a).localeCompare(featureName(b), "ru"));

  const perkRow = (p) => {
    const lvl = P.perks[p.id] || 0;
    let pips = "";
    for (let i = 0; i < pm; i++)
      pips += `<div class="pip ppip ${i < lvl ? "on" : ""}" data-lvl="${i + 1}"></div>`;
    return `<div class="prof-perk" data-perk="${p.id}">
      <div class="nm">${escapeHtml(p.name || perkName(p.id))}</div>
      <button class="pbtn" data-d="-1">−</button>
      <div class="pips">${pips}</div>
      <button class="pbtn" data-d="1">+</button>
      <div class="plvl">УР. <span>${lvl}</span></div>
    </div>`;
  };

  detail.innerHTML = `<button class="back">◂ НАЗАД</button>
    <div class="section-head">
      <div class="section-title">▸ ПРОФИЛЬ УБЕЖИЩА · ${escapeHtml(user.display_login || user.login)}</div>
      <div class="section-note">ОТМЕТЬ ПРОКАЧАННОЕ</div>
    </div>
    <div class="prof-hint">Карточки рецептов и тумблер «КРАФТЫ: ДОСТУПНЫЕ» в разделе крафта считают по этому профилю.</div>
    <div class="reqs-lbl prof-lbl">НАВЫКИ КРАФТА · УРОВЕНЬ 0–${pm}</div>
    <div class="prof-perks">${dict.perks.map(perkRow).join("")}</div>
    <div class="reqs-lbl prof-lbl">СТАНКИ И ИНСТРУМЕНТЫ · ${feats.length}</div>
    <div class="prof-feats">${feats.map((f) =>
      `<button class="feat ${P.features.has(f) ? "on" : ""}" data-feat="${f}">
         <span class="fmark">${P.features.has(f) ? "✓" : "+"}</span>${escapeHtml(featureName(f))}</button>`).join("")}
    </div>
    <div class="prof-actions">
      <button class="prof-save" id="profSave">СОХРАНИТЬ ПРОФИЛЬ</button>
      <span class="prof-msg" id="profMsg"></span>
    </div>`;

  const setLvl = (row, lvl) => {
    const id = row.dataset.perk;
    lvl = Math.max(0, Math.min(pm, lvl));
    if (lvl) P.perks[id] = lvl; else delete P.perks[id];
    row.querySelector(".plvl span").textContent = lvl;
    row.querySelectorAll(".ppip").forEach((el, i) => el.classList.toggle("on", i < lvl));
  };
  detail.querySelectorAll(".prof-perk").forEach((row) => {
    row.querySelectorAll(".pbtn").forEach((b) => b.addEventListener("click", () =>
      setLvl(row, (P.perks[row.dataset.perk] || 0) + (+b.dataset.d))));
    row.querySelectorAll(".ppip").forEach((el) => el.addEventListener("click", () => {
      const cur = P.perks[row.dataset.perk] || 0, v = +el.dataset.lvl;
      setLvl(row, v === cur ? 0 : v);   // клик по текущему уровню — сброс в 0
    }));
  });
  detail.querySelectorAll(".feat").forEach((b) => b.addEventListener("click", () => {
    const f = b.dataset.feat;
    const on = !P.features.has(f);
    if (on) P.features.add(f); else P.features.delete(f);
    b.classList.toggle("on", on);
    b.querySelector(".fmark").textContent = on ? "✓" : "+";
  }));
  $("profSave").addEventListener("click", async () => {
    const msg = $("profMsg");
    msg.textContent = "…";
    try {
      const r = await fetch(api("/profile"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ perks: P.perks, features: [...P.features] }),
      });
      msg.textContent = r.ok ? "СОХРАНЕНО ✓" : "[!] ОШИБКА СОХРАНЕНИЯ";
      msg.className = "prof-msg " + (r.ok ? "ok" : "bad");
      home.dataset.ts = "";   // главная пересчитается с новым профилем
      if (r.ok && ME) {       // профиль заполнен — онбординг-подсказка больше не нужна
        ME.profile_empty = !(Object.keys(P.perks).length || P.features.size);
        renderOnboard();
      }
    } catch (e) {
      msg.textContent = "[!] ОШИБКА СЕТИ";
      msg.className = "prof-msg bad";
    }
  });
  const b = detail.querySelector(".back");
  if (b) b.addEventListener("click", () => { navigate("/"); });
}

// ---------- разделы в разработке: заглушки с описанием модуля ----------
const PAGES = {
  map: {
    title: "ИНТЕРАКТИВНАЯ КАРТА",
    desc: "Карта зоны с зумом и слоями: артефакты, ресурсы, тайники, переходы между " +
          "локациями. Точки связаны с базой предметов терминала.",
  },
  guides: {
    title: "ГАЙДЫ",
    desc: "Статьи по крафту, фарму и снаряжению — с живыми ценами и ссылками на " +
          "карточки предметов прямо из текста.",
  },
};

function setNav(sec) {
  document.querySelectorAll("#topnav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.sec === sec));
}

function openPage(key) {
  const p = PAGES[key];
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="stub">
    <div class="stub-code">[ МОДУЛЬ ${key.toUpperCase()} ]</div>
    <div class="stub-title">▸ ${p.title}</div>
    <div class="stub-desc">${p.desc}</div>
    <div class="stub-status">СТАТУС: В РАЗРАБОТКЕ</div>
    <a class="stub-back" href="/">◂ ВЕРНУТЬСЯ К КРАФТУ</a>
  </div>`;
  window.scrollTo(0, 0);
}

// ---------- роутер на реальных путях ----------
// Старые #hash-ссылки (item=/q=/auction/artm=/builds/profile/map/guides) —
// разово переводим в новый путь при загрузке (шаринг в комьюнити не ломается).
function migrateLegacyHash() {
  const h = location.hash.slice(1);
  if (!h || h === "auth=error") return;
  const m = new URLSearchParams(h);
  let path = null;
  if (m.get("item")) path = `/item/${m.get("item")}`;
  else if (m.get("artm")) path = `/artefact/${m.get("artm")}`;
  else if (m.has("auction")) path = "/auction";
  else if (m.has("builds")) path = "/builds";
  else if (m.has("profile")) path = "/profile";
  else if (m.has("map")) path = "/map";
  else if (m.has("guides")) path = "/guides";
  else if (m.get("q")) path = `/search?q=${encodeURIComponent(m.get("q"))}`;
  if (path) history.replaceState(null, "", path);
}

function route() {
  renderOnboard();  // подсказка прячется на профиле, заглушках и в других разделах
  const path = location.pathname;
  const strip = document.querySelector(".search-strip");
  let mm;

  if (path === "/auction") {
    strip.classList.add("hidden"); page.classList.add("hidden");
    setNav("auction"); openAuction(); return;
  }
  if ((mm = path.match(/^\/artefact\/(.+)$/))) {
    strip.classList.add("hidden"); page.classList.add("hidden");
    setNav("auction"); openArtCard(decodeURIComponent(mm[1])); return;
  }
  if (path === "/builds") {
    strip.classList.add("hidden"); page.classList.add("hidden");
    setNav("builds"); openBuilds(); return;
  }
  if (PAGES[path.slice(1)]) {
    strip.classList.add("hidden"); page.classList.add("hidden");
    setNav(path.slice(1)); openPage(path.slice(1)); return;
  }

  // крафт-контекст: главная / лендинг / поиск / карточка / профиль
  strip.classList.remove("hidden");
  page.classList.add("hidden");
  setNav("craft");
  if (path === "/profile") { openProfile(); return; }
  if ((mm = path.match(/^\/item\/(.+)$/))) { openItem(decodeURIComponent(mm[1])); return; }
  if (path === "/search") {
    const q = new URLSearchParams(location.search).get("q") || "";
    input.value = q; lastQuery = ""; doSearch(); return;
  }
  // "/" и "/vygodno-kraftit" (лендинг) — главная
  input.value = ""; lastQuery = "";
  detail.classList.add("hidden");
  results.innerHTML = "";
  home.classList.remove("hidden");
  loadHome();
}

// перехват кликов по внутренним ссылкам → SPA-переход (кроме /api, /auth, _blank)
document.addEventListener("click", (e) => {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const a = e.target.closest("a");
  if (!a) return;
  const href = a.getAttribute("href");
  if (!href || !href.startsWith("/") || a.target === "_blank" || a.hasAttribute("download")) return;
  if (href.startsWith("/api") || href.startsWith("/auth")) return;  // серверные редиректы
  e.preventDefault();
  navigate(href);
});

window.addEventListener("popstate", route);
migrateLegacyHash();
route();
