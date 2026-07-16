// StalZone Craft — фронт «PDA-терминал». Только отрисовка, вся логика на бэке.
const BASE = "";                       // приложение на корне домена
const api = (p) => `${BASE}/api${p}`;
const asset = (p) => (p ? `${BASE}/${p}` : "");

// ---------- Я.Метрика: целевые действия ----------
// Цели-«JavaScript-событие» в счётчике 110585101: signup (регистрация) / login (вход).
const YM_ID = 110585101;
function ymGoal(name) {
  try { if (window.ym) ym(YM_ID, "reachGoal", name); } catch (e) { /* счётчик не загрузился */ }
}

// A/B-тест дизайна: сервер проставил вариант в <html data-ab="A|B"> (только когда
// тест включён). Шлём его параметром визита — в Метрике все отчёты (глубина, время,
// отказы) сегментируются условием «Параметры визита → ab_design = A/B».
// ym-заглушка в <head> ставится синхронно и очередит вызов до загрузки счётчика.
(function reportAbVariant() {
  const ab = document.documentElement.getAttribute("data-ab");
  if (!ab) return;
  if (document.documentElement.hasAttribute("data-ab-preview")) return;  // админский предпросмотр — мимо статистики
  try { if (window.ym) ym(YM_ID, "params", { ab_design: ab }); } catch (e) { /* счётчик не загрузился */ }
})();

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
// вес редкости для сортировки списков «крутое сверху» (Легенда/Мастер выше)
const RANK_WEIGHT = { RANK_LEGEND: 6, RANK_MASTER: 5, RANK_VETERAN: 4,
                      RANK_STALKER: 3, RANK_NEWBIE: 2, QUEST_ITEM: 1, DEFAULT: 0 };
const rankWeight = (c) => RANK_WEIGHT[c] ?? 0;

// русские названия перков/станков убежища (ключи из hideout_recipes.json)
const PERK_RU = {
  ammunition: "Боеприпасы", armorer: "Оружейное дело", brewing: "Варение",
  cooking: "Кулинария", engineering: "Инженерия", materials: "Материалы",
  medicine: "Медицина", pyrotechnics: "Пиротехника",
};
// официальные имена из ru.lang клиента STALZONE (go.hideout_*.name)
const FEATURE_RU = {
  calipers_kit: "Набор штангенциркулей", centrifuge: "Центрифуга",
  chemical_reactor: "Химический реактор", chromatographic_equipment: "Хроматографическое оборудование",
  cnc: "ЧПУ", electronics_kit: "Набор для работы с электроникой",
  fermentation_container: "Тара для брожения", flasks_kit: "Набор колб и мензурок",
  gauze_filter: "Фильтр из марли",
  generator_energy_source_anomal: "Станция аномального преобразования",
  generator_energy_source_battery: "Станция для приема батарей",
  generator_energy_source_gas: "Станция для приема баллонов с газом",
  generator_fuel_filter: "Топливный фильтр",
  generator_inverter: "Инвертор",
  generator_battery_cabinet: "Аккумуляторный шкаф",
  hoods: "Вытяжка", kitchen_items: "Кухонная утварь", kitchen_table: "Кухонный стол",
  laboratory_table: "Лабораторный стол", laminar_box: "Ламинарный бокс",
  laser_level: "Лазерный уровень", lathe: "Токарный станок",
  precise_powertools: "Точные электроинструменты", precise_tools: "Прецизионный инструментарий",
  rotary_evaporator: "Роторный испаритель", scalpels_kit: "Набор скальпелей",
  screwdrivers: "Набор отверток и щипцов", sterilization_system: "Система стерилизации",
  stove: "Кухонная плита", tool_trolley: "Тележка с инструментами",
  water_collector: "Водосборник", welding_equipment: "Сварочное оборудование",
  workbench: "Верстак", wrenches_kit: "Набор гаечных ключей",
};
const BENCH_RU = { workbench: "ВЕРСТАК", kitchen_table: "КУХОННЫЙ СТОЛ",
                   laboratory_table: "ЛАБОРАТОРНЫЙ СТОЛ", generator: "ГЕНЕРАТОР" };
// пристройки генератора выделяются в профиле в свою группу; станции приёма
// (газ/батареи/аномальное) открывают топливо в учёте расходов
const isGenFeature = (f) => f.startsWith("generator_");
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
// учёт топлива генератора в себестоимости крафта (тумблер в карточке предмета)
const fuelMode = () => localStorage.getItem("sz_fuel") === "1";

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
      authBox.innerHTML = `<a class="auth-user" href="/profile" title="Профиль убежища: навыки и станки · EXBO ID ${ME.user.exbo_id}"><span class="gear">⚙</span>${escapeHtml(name)}</a>
        <button class="auth-out" id="logoutBtn" title="Завершить сессию">ВЫХОД</button>`;
      renderAuthGlow();
      $("logoutBtn").addEventListener("click", async () => {
        await fetch(`${BASE}/auth/logout`, { method: "POST" }).catch(() => {});
        localStorage.removeItem("sz_avail");
        localStorage.removeItem("sz_onb");
        loadAuth().then(() => { if (location.pathname === "/profile") navigate("/"); });
      });
    } else if (ME.auth_enabled) {
      authBox.innerHTML = `<button class="auth-login" id="loginBtn">ВХОД</button>`;
      $("loginBtn").addEventListener("click", () => openAuthModal("signin"));
    } else {
      authBox.innerHTML = "";
    }
  } catch (e) { ME = null; authBox.innerHTML = ""; }
  renderModeToggle();
  renderOnboard();
  chatDockRender();   // форма чата зависит от авторизации
  // DEV-вкладка (редактор карты) — только админам (ADMIN_USER_IDS)
  document.querySelectorAll(".nav-adm").forEach((el) =>
    el.classList.toggle("hidden", !(ME && ME.is_admin)));
  // прямой заход на /dev* мог отрисовать «проверка доступа», пока /me не ответил
  if (location.pathname.startsWith("/dev")) route();
  // стартовый рендер мог уйти без фильтра, пока /me не ответил — перерисовать
  else if (ME && ME.authenticated && availMode()) {
    lastQuery = null; home.dataset.ts = "";
    route();
  }
}

// кнопка с ником мягко пульсирует зелёным, пока профиль убежища не заполнен
function renderAuthGlow() {
  const el = authBox.querySelector(".auth-user");
  if (el) el.classList.toggle("unset", !!(ME && ME.profile_empty));
}

// ---------- онбординг: подсказка заполнить профиль после первого входа ----------
const onboard = $("onboard");
function renderOnboard() {
  // подсказка только в крафт-контексте (главная, поиск, карточка), не в других разделах
  const craftCtx = /^\/(item\/|search$|craft$|vygodno-kraftit$)/.test(location.pathname);
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
// ---------- всплывающее уведомление ----------
function authNotice(msg, kind = "ok") {
  let el = $("authNotice");
  if (!el) {
    el = document.createElement("div");
    el.id = "authNotice";
    el.className = "auth-notice";
    document.body.appendChild(el);
  }
  el.className = `auth-notice ${kind}`;
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 6000);
}

// ---------- модал авторизации (вкладки Вход / Регистрация + EXBO) ----------
let authModal = null;

function exboBlock(label) {
  if (!(ME && ME.oauth_enabled)) return "";
  return `<div class="auth-or">ИЛИ</div>
    <a class="auth-exbo" href="${BASE}/auth/login">${label}</a>`;
}

function ensureAuthModal() {
  if (authModal) return authModal;
  authModal = document.createElement("div");
  authModal.id = "authModal";
  authModal.className = "mk-modal auth-modal hidden";
  authModal.setAttribute("role", "dialog");
  authModal.setAttribute("aria-modal", "true");
  authModal.addEventListener("click", (e) => {
    if (e.target === authModal || e.target.closest("[data-close]")) closeAuthModal();
  });
  document.body.appendChild(authModal);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !authModal.classList.contains("hidden")) closeAuthModal();
  });
  return authModal;
}

function authModalHtml(tab) {
  const mailOff = ME && ME.mail_enabled === false;
  return `<div class="mk-modal-box auth-box">
    <button class="mk-modal-x" data-close title="Закрыть (Esc)">✕</button>
    <div class="auth-brand">SCZ//ДОСТУП</div>
    <div class="auth-tabs" data-tabs>
      <button class="auth-tab" data-tab="signin">ВХОД</button>
      <button class="auth-tab" data-tab="register">РЕГИСТРАЦИЯ</button>
    </div>

    <form class="auth-pane" data-pane="signin" autocomplete="on">
      <label>EMAIL ИЛИ НИК
        <input name="ident" autocomplete="username" required></label>
      <label>ПАРОЛЬ
        <input name="password" type="password" autocomplete="current-password" required></label>
      <div class="auth-err" data-err></div>
      <button type="submit" class="auth-submit">ВОЙТИ</button>
      ${mailOff ? "" : `<button type="button" class="auth-link" data-goto="reset">Забыли пароль?</button>`}
      ${exboBlock("ВОЙТИ ЧЕРЕЗ EXBO")}
    </form>

    <form class="auth-pane" data-pane="register" autocomplete="on">
      <label>EMAIL
        <input name="email" type="email" autocomplete="email" required></label>
      <label>НИК
        <input name="login" autocomplete="nickname" required minlength="2" maxlength="24"></label>
      <label>ПАРОЛЬ
        <input name="password" type="password" autocomplete="new-password" required minlength="8"></label>
      <label>ПОВТОР ПАРОЛЯ
        <input name="password2" type="password" autocomplete="new-password" required minlength="8"></label>
      <div class="auth-err" data-err></div>
      <button type="submit" class="auth-submit">СОЗДАТЬ АККАУНТ</button>
      ${exboBlock("РЕГИСТРАЦИЯ ЧЕРЕЗ EXBO")}
    </form>

    <form class="auth-pane" data-pane="reset" autocomplete="on">
      <div class="auth-note">Укажи email аккаунта — пришлём ссылку для сброса пароля.</div>
      <label>EMAIL
        <input name="email" type="email" autocomplete="email" required></label>
      <div class="auth-err" data-err></div>
      <button type="submit" class="auth-submit">ОТПРАВИТЬ ССЫЛКУ</button>
      <button type="button" class="auth-link" data-goto="signin">← Назад ко входу</button>
    </form>

    <form class="auth-pane" data-pane="reset-confirm" autocomplete="on">
      <div class="auth-note">Задай новый пароль для аккаунта.</div>
      <label>НОВЫЙ ПАРОЛЬ
        <input name="password" type="password" autocomplete="new-password" required minlength="8"></label>
      <label>ПОВТОР ПАРОЛЯ
        <input name="password2" type="password" autocomplete="new-password" required minlength="8"></label>
      <div class="auth-err" data-err></div>
      <button type="submit" class="auth-submit">СОХРАНИТЬ И ВОЙТИ</button>
    </form>
  </div>`;
}

let resetToken = "";  // токен из ссылки письма (для вкладки reset-confirm)

function setAuthTab(tab) {
  const box = authModal;
  box.querySelectorAll("[data-tabs] .auth-tab").forEach((b) =>
    b.classList.toggle("on", b.dataset.tab === tab));
  box.querySelectorAll(".auth-pane").forEach((p) =>
    p.classList.toggle("active", p.dataset.pane === tab));
  // вкладки видны только для форм входа/регистрации
  box.querySelector("[data-tabs]").style.display =
    (tab === "signin" || tab === "register") ? "" : "none";
  box.querySelectorAll(".auth-err").forEach((e) => (e.textContent = ""));
  const first = box.querySelector(`.auth-pane[data-pane="${tab}"] input`);
  if (first) setTimeout(() => first.focus(), 30);
}

function openAuthModal(tab = "signin") {
  ensureAuthModal();
  authModal.innerHTML = authModalHtml(tab);
  authModal.querySelectorAll("[data-tabs] .auth-tab").forEach((b) =>
    b.addEventListener("click", () => setAuthTab(b.dataset.tab)));
  authModal.querySelectorAll("[data-goto]").forEach((b) =>
    b.addEventListener("click", () => setAuthTab(b.dataset.goto)));
  authModal.querySelectorAll(".auth-pane").forEach((f) =>
    f.addEventListener("submit", onAuthSubmit));
  authModal.classList.remove("hidden");
  document.body.classList.add("modal-open");
  setAuthTab(tab);
}

function closeAuthModal() {
  if (!authModal) return;
  authModal.classList.add("hidden");
  document.body.classList.remove("modal-open");
  // почистить токен сброса из URL, если был
  if (resetToken) {
    resetToken = "";
    const u = new URL(location.href);
    u.searchParams.delete("reset");
    history.replaceState(null, "", u.pathname + u.search);
  }
}

async function onAuthSubmit(e) {
  e.preventDefault();
  const form = e.currentTarget;
  const pane = form.dataset.pane;
  const errEl = form.querySelector("[data-err]");
  const btn = form.querySelector(".auth-submit");
  const val = (n) => (form.querySelector(`[name="${n}"]`) || {}).value || "";
  errEl.textContent = "";

  // клиентская проверка совпадения паролей
  if ((pane === "register" || pane === "reset-confirm") && val("password") !== val("password2")) {
    errEl.textContent = "Пароли не совпадают";
    return;
  }

  let url, payload, goal = null;
  if (pane === "signin") {
    url = "/auth/signin"; payload = { ident: val("ident"), password: val("password") }; goal = "login";
  } else if (pane === "register") {
    url = "/auth/register";
    payload = { email: val("email"), login: val("login"), password: val("password") };
    goal = "signup";
  } else if (pane === "reset") {
    url = "/auth/reset"; payload = { email: val("email") };
  } else if (pane === "reset-confirm") {
    url = "/auth/reset/confirm"; payload = { token: resetToken, password: val("password") };
  }

  btn.disabled = true;
  const prev = btn.textContent;
  btn.textContent = "…";
  try {
    const r = await fetch(`${BASE}${url}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { errEl.textContent = data.error || "Ошибка. Попробуйте ещё раз."; return; }

    if (pane === "reset") {
      // не раскрываем, есть ли такой email
      setAuthTab("signin");
      authNotice("Если email зарегистрирован — письмо со ссылкой отправлено.");
      return;
    }
    // signin / register / reset-confirm — успех, сессия установлена
    if (goal) ymGoal(goal);
    closeAuthModal();
    await loadAuth();
    if (pane === "register") {
      authNotice(data.mail_sent
        ? "Аккаунт создан. Проверь почту — отправили письмо для подтверждения email."
        : "Аккаунт создан. Добро пожаловать!");
    } else if (pane === "reset-confirm") {
      authNotice("Пароль обновлён. Ты вошёл в аккаунт.");
    } else {
      authNotice("Вход выполнен.");
    }
  } catch (err) {
    errEl.textContent = "Сеть недоступна. Попробуйте ещё раз.";
  } finally {
    btn.disabled = false;
    btn.textContent = prev;
  }
}

// открытие модала из CTA (чат/комменты/профиль) — делегирование по классу
document.addEventListener("click", (e) => {
  const t = e.target.closest(".js-open-auth");
  if (t) { e.preventDefault(); openAuthModal(t.dataset.authTab || "signin"); }
});

(function authInit() {
  const hash = new URLSearchParams(location.hash.slice(1));
  const marker = hash.get("auth");
  const resetQ = new URLSearchParams(location.search).get("reset");

  const afterAuth = () => {
    if (resetQ) {                       // пришли по ссылке сброса пароля из письма
      resetToken = resetQ;
      openAuthModal("reset-confirm");
    }
  };

  if (marker) history.replaceState(null, "", location.pathname + location.search);

  if (marker === "error" || marker === "verify_failed") {
    authNotice(marker === "error" ? "Не удалось войти через EXBO." :
      "Ссылка подтверждения недействительна или устарела.", "err");
    loadAuth().then(afterAuth);
  } else if (marker === "signup" || marker === "login") {
    ymGoal(marker);                     // цель Я.Метрики после EXBO-редиректа
    loadAuth().then(() => {
      afterAuth();
      authNotice(marker === "signup" ? "Аккаунт EXBO создан. Добро пожаловать!" : "Вход выполнен.");
    });
  } else if (marker === "verified") {
    loadAuth().then(() => { afterAuth(); authNotice("Email подтверждён."); });
  } else {
    loadAuth().then(afterAuth);
  }
})();

// ---------- поиск ----------
let searchTimer = null, lastQuery = "";
input.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    // держим URL в синхроне (без замусоривания истории), затем ищем
    const q = input.value.trim();
    const path = q ? `/search?q=${encodeURIComponent(q)}` : "/craft";
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
    const r = await fetch(api(`/craft/${id}${fuelMode() ? "?fuel=1" : ""}`));
    renderDetail(await r.json());
    loadBarterBlocks(id);   // асинхронно: «получается бартером» / «сдаётся в бартер»
  } catch (e) {
    detail.innerHTML = `<div class="empty">[!] ОШИБКА ЗАГРУЗКИ</div>`;
  }
}

function verdictBlock(d) {
  const v = d.verdict || {};
  let cls = "warn", main = "—", sub = "";
  const fee = v.fee_pct != null ? ` − КОМИССИЯ ${v.fee_pct}%` : "";
  const basis = (v.sell_basis === "sales"
    ? "ПО РЕАЛЬНЫМ ПРОДАЖАМ (МЕДИАНА 10 ПОСЛЕДНИХ)"
    : "ПО МИН. ВЫКУПУ (ИСТОРИИ ПРОДАЖ ЕЩЁ НЕТ)") + fee;
  const fuelMark = d.fuel && d.fuel.enabled && d.fuel.source ? " · ТОПЛИВО УЧТЕНО" : "";
  if (v.status === "profitable") {
    cls = "ok";
    main = `ВЫГОДНО ▲+${v.pct}%`;
    sub = `МАРЖА +${fmt(v.diff)} ₽ НА ЕДИНИЦУ · ${basis}${fuelMark}`;
  } else if (v.status === "unprofitable") {
    cls = "bad";
    main = `НЕВЫГОДНО ▼−${Math.abs(v.pct)}%`;
    sub = `МАРЖА −${fmt(Math.abs(v.diff))} ₽ НА ЕДИНИЦУ · ${basis}${fuelMark}`;
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
  if (d.craft_cost != null && (d.buy_price != null || d.sell_price != null)) {
    const net = v.sell_net != null && v.sell_basis === "sales" ? v.sell_net : d.sell_price;
    const rowsArr = [["КРАФТ", d.craft_cost, "craft"]];
    if (net != null) rowsArr.push([`ПРОДАЖА ~ (−${v.fee_pct ?? 5}%)`, net, ""]);
    if (d.buy_price != null) rowsArr.push(["КУПИТЬ ~", d.buy_price, ""]);
    const maxv = Math.max(...rowsArr.map((r) => r[1])) || 1;
    bars = `<div class="v-bars">` + rowsArr.map(([lbl, val, extra]) => `
      <div class="v-bar">
        <div class="row"><span>${lbl}</span><span class="num">${fmt(val)} ₽</span></div>
        <div class="track"><div class="fill ${extra}" style="width:${Math.round(val / maxv * 100)}%"></div></div>
      </div>`).join("") + `</div>`;
    if (d.last_sale != null)
      bars += `<div class="v-lastsale">ПОСЛЕДНЯЯ ПРОДАЖА: ${fmt(d.last_sale)} ₽</div>`;
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
  const f = d.fuel;
  const fuelTile = f && f.enabled ? `
    <div class="tile"><div class="lbl">ТОПЛИВО / ШТ</div>
      <div class="val amber">${f.unit_fuel_cost != null ? fmt(f.unit_fuel_cost) + " ₽" : "—"}</div></div>` : "";
  return `<div class="tiles ${fuelTile ? "five" : ""}">
    <div class="tile"><div class="lbl">СЕБЕСТОИМОСТЬ${fuelTile ? " +⛽" : ""}</div>
      <div class="val">${d.craft_cost != null ? fmt(d.craft_cost) + " ₽" : "—"}</div></div>
    <div class="tile"><div class="lbl">ЦЕНА АУКА</div>
      <div class="val">${d.buy_price != null ? fmt(d.buy_price) + " ₽" : "—"}</div></div>
    <div class="tile"><div class="lbl">МАРЖА / ШТ</div>
      <div class="val ${diffCls}">${diffVal}</div></div>
    <div class="tile"><div class="lbl">ЭНЕРГИЯ ВЕРСТАКА</div>
      <div class="val amber">${chosen && chosen.energy != null ? fmt(chosen.energy) : "—"}</div></div>
    ${fuelTile}
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

// подписи базы расчёта цены топлива (services/fuel.py: unit_price)
const FUEL_BASIS_RU = {
  sales50: "ПО 50 ПОСЛЕДНИМ СДЕЛКАМ", sales10: "ПО 10 ПОСЛЕДНИМ СДЕЛКАМ",
  avg: "ПО СРЕДНЕЙ ЦЕНЕ ПРОДАЖ", market: "ПО ЛОТАМ АУКА",
};

function fuelSection(d) {
  const f = d.fuel;
  const on = !!(f && f.enabled);
  let rows = "";
  if (on && f.source) {
    const s = f.source;
    rows = `
      <div class="res-row"><span class="k">ТОПЛИВО НА КРАФТ</span>
        <span class="v">${f.craft_fuel_cost != null ? fmt(f.craft_fuel_cost) + " ₽" : "—"}</span></div>
      <div class="fuel-src" data-id="${s.id}" title="Открыть карточку топлива">
        <img loading="lazy" src="${asset(s.icon)}" alt="">
        <span class="nm">${escapeHtml(s.name)}</span>
        <span class="x">${fmt(s.price)} ₽ / ${fmt(s.energy)} ЕД</span></div>
      <div class="fuel-note">ЦЕНА ЭНЕРГИИ ${fmt(f.per_1k)} ₽ ЗА 1000 ЕД · ${FUEL_BASIS_RU[s.basis] || ""}<br>
        ${ME && ME.authenticated
          ? "САМЫЙ ВЫГОДНЫЙ ИЗ ДОСТУПНЫХ ТЕБЕ ИСТОЧНИКОВ (УЛУЧШЕНИЯ — В ПРОФИЛЕ)"
          : "САМЫЙ ВЫГОДНЫЙ ИСТОЧНИК ЭНЕРГИИ НА АУКЕ"}</div>`;
  } else if (on) {
    rows = `<div class="fuel-note">ЦЕНЫ ТОПЛИВА ЕЩЁ СЧИТАЮТСЯ В ФОНЕ — ЗАГЛЯНИ ЧЕРЕЗ ПАРУ МИНУТ.</div>`;
  }
  return `<button class="mkc-btn fuel-toggle ${on ? "on" : ""}" id="fuelToggle" data-item="${d.item.id}"
      title="Закладывать ли стоимость топлива генератора в себестоимость крафта">
      ⛽ УЧЁТ ТОПЛИВА: ${on ? "ВКЛ" : "ВЫКЛ"}</button>${rows}`;
}

function reqsSections(chosen, rc, d) {
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
    ${fuelSection(d)}
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

function asideBlock(chosen, usedIn, rc, d) {
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
    ${chosen ? reqsSections(chosen, rc, d) : ""}
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

  html += `<div id="barterBlocks"></div>`;  // заполняется loadBarterBlocks
  html += `</div>`;                      // /card-main
  html += asideBlock(chosen, d.used_in, d.req_check, d);
  html += `</div>`;                      // /card-cols

  detail.innerHTML = html;
  wireDetail();
}

function wireDetail() {
  const b = detail.querySelector(".back");
  if (b) b.addEventListener("click", () => {
    navigate(lastQuery ? `/search?q=${encodeURIComponent(lastQuery)}` : "/craft");
  });
  detail.querySelectorAll(".tname[data-id], .ilink[data-id], .use-row[data-id], .fuel-src[data-id]").forEach((el) =>
    el.addEventListener("click", () => { navigate(`/item/${el.dataset.id}`); }));
  const ft = detail.querySelector("#fuelToggle");
  if (ft) ft.addEventListener("click", () => {
    localStorage.setItem("sz_fuel", fuelMode() ? "0" : "1");
    openItem(ft.dataset.item);   // перечитать карточку с новым режимом
  });
}

// ---------- раздел «Крафт»: биржа ингредиентов + подборки ----------
async function loadHome() {
  // не дёргаем чаще раза в минуту — на бэке рейтинги тоже кэшируются
  if (home.dataset.view === "craft"
      && home.dataset.ts && Date.now() - +home.dataset.ts < 60000) return;
  home.innerHTML = `<div class="spinner">// ЗАГРУЗКА РАЗДЕЛА</div>`;
  try {
    const [top, watch] = await Promise.all([
      fetch(api(`/top${availParam("?")}`)).then((r) => r.json()),
      fetch(api("/watch")).then((r) => r.json()).catch(() => null),
    ]);
    home.dataset.ts = Date.now();
    home.dataset.view = "craft";
    renderHome(top, watch);
  } catch (e) {
    home.innerHTML = `<div class="empty">[!] НЕ УДАЛОСЬ ЗАГРУЗИТЬ РАЗДЕЛ</div>`;
  }
}

// ---------- дашборд-главная: сводка по всем разделам ----------
async function loadDashboard() {
  if (home.dataset.view === "dash"
      && home.dataset.ts && Date.now() - +home.dataset.ts < 60000) return;
  home.innerHTML = `<div class="spinner">// ЗАГРУЗКА ГЛАВНОЙ</div>`;
  try {
    const [top, art, watch, em, sales, fuelTop, patches, daily] = await Promise.all([
      fetch(api(`/top${availParam("?")}`)).then((r) => r.json()).catch(() => null),
      fetch(api("/artmarket/top?window=24h")).then((r) => r.json()).catch(() => null),
      fetch(api("/watch")).then((r) => r.json()).catch(() => null),
      fetch(api("/emission")).then((r) => r.json()).catch(() => null),
      fetch(api("/sales/top?n=12")).then((r) => r.json()).catch(() => null),
      fetch(api("/fuel/top?n=20")).then((r) => r.json()).catch(() => null),
      fetch(api("/patches?limit=5")).then((r) => r.json()).catch(() => null),
      fetch(api("/build/daily")).then((r) => r.json()).catch(() => null),
    ]);
    home.dataset.ts = Date.now();
    home.dataset.view = "dash";
    renderDashboard(top, art, watch, em, sales, fuelTop, patches, daily);
  } catch (e) {
    home.innerHTML = `<div class="empty">[!] НЕ УДАЛОСЬ ЗАГРУЗИТЬ ГЛАВНУЮ</div>`;
  }
}

// ---------- карточка выбросов ----------
let emTick = null;

const fmtAgo = (ms) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h} Ч ${String(m).padStart(2, "0")} МИН` : `${m} МИН ${String(s % 60).padStart(2, "0")} С`;
};
const fmtMsk = (iso) => {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit",
  }).replace(",", " ·") + " МСК";
};

function emissionBody(em) {
  if (!em || (!em.history?.length && !em.previous_start && !em.current_start))
    return `<div class="empty-sm">ЖДЁМ ПЕРВЫЙ ЗАМЕР ВОТЧЕРА ВЫБРОСОВ.</div>`;
  const hist = em.history?.length ? em.history
    : [em.current_start, em.previous_start].filter(Boolean);
  let head;
  if (em.current_start) {
    head = `<div class="em-now">⚠ ВЫБРОС ИДЁТ ПРЯМО СЕЙЧАС</div>
      <div class="em-sub">НАЧАЛСЯ <span class="em-ago" data-ts="${em.current_start}">…</span> НАЗАД</div>`;
  } else {
    head = `<div class="em-since"><span class="em-ago" data-ts="${hist[0]}">…</span></div>
      <div class="em-sub">С ПОСЛЕДНЕГО ВЫБРОСА</div>`;
  }
  const rows = hist.slice(0, 13).map((t) =>
    `<div class="em-row">☢ ${fmtMsk(t)}</div>`).join("");
  return `${head}<div class="em-hist"><div class="dash-grp">ПОСЛЕДНИЕ ВЫБРОСЫ</div>${rows}</div>`;
}

function startEmTick() {
  if (emTick) clearInterval(emTick);
  const upd = () => {
    const els = document.querySelectorAll(".em-ago");
    if (!els.length) { clearInterval(emTick); emTick = null; return; }
    els.forEach((el) => { el.textContent = fmtAgo(Date.now() - new Date(el.dataset.ts)); });
  };
  upd();
  emTick = setInterval(upd, 1000);
}

function dashCraftRow(e, pctBadge) {
  // бейдж — дельта ₽ за цикл (ВЫГОДНЫЕ) или % маржи (ПРОФИТНЫЕ), вторая метрика в тултипе
  const badge = e.diff != null
    ? (pctBadge
        ? `<span class="pct ${e.pct > 0 ? "up" : "down"}" title="${e.diff > 0 ? "+" : ""}${fmt(e.diff)} ₽">${e.pct > 0 ? "+" : ""}${e.pct}%</span>`
        : `<span class="pct ${e.diff > 0 ? "up" : "down"}" title="${e.pct != null ? (e.pct > 0 ? "+" : "") + e.pct + "%" : ""}">${e.diff > 0 ? "+" : ""}${fmt(e.diff)} ₽</span>`)
    : (e.sell_price ?? e.buy_price) != null ? `<span class="dash-p">${fmt(e.sell_price ?? e.buy_price)} ₽</span>` : "";
  return `<div class="dash-row" data-nav="/item/${e.id}">
    <img loading="lazy" src="${asset(e.icon)}" alt="">
    <div class="nm">${escapeHtml(e.name)}</div>
    ${badge}
  </div>`;
}

function dashArtRow(r) {
  return `<div class="dash-row" data-nav="/artefact/${r.id}">
    <img loading="lazy" src="${asset(r.icon)}" alt="">
    <div class="nm" style="color:${qltColor(r.qlt)}">${escapeHtml(r.name)}
      <span class="dash-sub" style="color:${qltColor(r.qlt)}">${bucketBadge(r.qlt, r.ptn)}</span></div>
    <span class="pct ${r.pct > 0 ? "up" : "down"}">${r.pct > 0 ? "+" : ""}${r.pct}%</span>
  </div>`;
}

function salesBody(s) {
  if (!s || !(s.today || []).length)
    return `<div class="empty-sm">ИСТОРИЯ ПРОДАЖ ПРОГРЕВАЕТСЯ — ЗАГЛЯНИ ЧЕРЕЗ ПАРУ МИНУТ.</div>`;
  const row = (r) => `<div class="dash-row" data-nav="/item/${r.id}">
    <img loading="lazy" src="${asset(r.icon)}" alt="">
    <div class="nm">${escapeHtml(r.name)}</div>
    <span class="dash-p">~${fmt(r.per_day)}/СУТ</span></div>`;
  const today = s.today.slice(0, 12).map(row).join("");
  const week = (s.week || []).length
    ? s.week.slice(0, 12).map(row).join("")
    : `<div class="empty-sm">КОПИМ СНАПШОТЫ (ЕСТЬ ${s.snapshots || 0}) — НЕДЕЛЬНЫЙ ТОП СОБЕРЁТСЯ ЗА ПАРУ ДНЕЙ.</div>`;
  return `<div class="sales-tabs">
      <button class="stab on" data-view="today">СЕГОДНЯ</button>
      <button class="stab" data-view="week">НЕДЕЛЯ</button></div>
    <div class="sales-view" data-view="today">${today}</div>
    <div class="sales-view hidden" data-view="week">${week}</div>`;
}

// все источники заправки генератора, выгодные первыми: ₽ за 1000 ед. энергии
const FUEL_GROUP_SUB = { gas: "СТАНЦИЯ ГАЗА", battery: "СТАНЦИЯ БАТАРЕЙ", anomal: "АНОМ. СТАНЦИЯ" };
function fuelBody(fu) {
  const src = (fu && fu.sources) || [];
  if (!src.some((s) => s.per_1k != null))
    return `<div class="empty-sm">ЦЕНЫ ТОПЛИВА СЧИТАЮТСЯ В ФОНЕ — ЗАГЛЯНИ ЧЕРЕЗ ПАРУ МИНУТ.</div>`;
  const rows = src.map((s) => `<div class="dash-row" data-nav="/item/${s.id}">
    <img loading="lazy" src="${asset(s.icon)}" alt="">
    <div class="nm">${escapeHtml(s.name)}${FUEL_GROUP_SUB[s.group]
      ? ` <span class="dash-sub">${FUEL_GROUP_SUB[s.group]}</span>` : ""}</div>
    <span class="dash-p">${s.per_1k != null
      ? `<b>${fmt(s.per_1k)}</b> ₽/1К ЭН` : "ЦЕНА СЧИТАЕТСЯ…"}</span></div>`).join("");
  return rows + `<div class="dash-note">ЦЕНА ТОПЛИВА — ПО 50 ПОСЛЕДНИМ СДЕЛКАМ ·
    БАЗОВЫЙ ГЕНЕРАТОР ЖЖЁТ БЕНЗИН/ДИЗЕЛЬ, ГАЗ/БАТАРЕИ/АНОМАЛЬНОЕ — ПОСЛЕ ПРИСТРОЕК</div>`;
}

// компактный бюджет: 500000 -> «500 ТЫС», 5000000 -> «5 МЛН», 1e9 -> «1 МЛРД»
function fmtBudgetShort(n) {
  if (n == null) return "—";
  if (n >= 1e9) return `${+(n / 1e9).toFixed(2)} МЛРД`;
  if (n >= 1e6) return `${+(n / 1e6).toFixed(2)} МЛН`;
  if (n >= 1e3) return `${+(n / 1e3).toFixed(0)} ТЫС`;
  return String(n);
}

// «сборка дня»: броня + контейнер топ-редкости, подобранные под бюджет арты и
// приведённое ХП. Ролл фиксирован датой на бэке — обновляется раз в сутки.
function dailyBuildBody(d) {
  if (!d || d.error) return `<div class="empty-sm">СБОРКА ДНЯ ВРЕМЕННО НЕДОСТУПНА.</div>`;
  const arm = d.armor || {}, cont = d.container || {};
  const chips = (d.stat_names || []).map((n, i) =>
    `<span class="db-chip${i === 0 ? " on" : ""}">${escapeHtml(n)}</span>`).join("");
  const head = `<div class="db-hero">
      <div class="db-hp"><div class="db-hp-v">${fmt(d.hp ? d.hp.effective_hp : 0)}</div>
        <div class="db-hp-l">ПРИВ. ХП</div></div>
      <div class="db-params">
        <div class="db-budget">БЮДЖЕТ <b>${fmtBudgetShort(d.budget)} ₽</b></div>
        <div class="db-chips">${chips}</div>
      </div>
    </div>`;
  const geo = (icon, color, name, sub) => `<div class="db-geo">
      <img loading="lazy" src="${asset(icon)}" alt="">
      <div class="db-geo-i">
        <span class="nm" style="color:${rank(color).color}">${escapeHtml(name)}</span>
        <span class="db-geo-s">${sub}</span>
      </div></div>`;
  const gear = `<div class="db-gear">
      ${geo(arm.icon, arm.color, `${arm.name || "—"} +${arm.ptn || 0}`,
            `ПУЛЕСТОЙ ${fmt(arm.bullet)}${arm.vitality ? ` · ЖИВУЧ +${arm.vitality}` : ""}`)}
      ${geo(cont.icon, cont.color, cont.name || "—",
            `${cont.slots || "—"} СЛОТ · ЭФФ ${cont.efficiency ?? "—"}% · ЗАЩ ${cont.protection ?? "—"}%`)}
    </div>`;
  if (!d.build) return head + gear + `<div class="dash-note">${escapeHtml(d.hint || "СБОРКА СЧИТАЕТСЯ…")}</div>`;
  const b = d.build;
  const arts = b.slots.map((s) => `<div class="db-art">
      <img loading="lazy" src="${asset(s.icon)}" alt="">
      <span class="nm" style="color:${qltColor(s.qlt)}">${escapeHtml(s.name)}</span>
      <span class="db-badge" style="color:${qltColor(s.qlt)}">${bucketBadge(s.qlt, s.ptn)}</span>
      <span class="db-price">${fmt(s.price)}</span>
    </div>`).join("");
  // итоговые характеристики сборки: сумма статов артов (× эффективность контейнера)
  const statRow = (name, val, bad, extra = "") => `<div class="db-stat${bad ? " bad" : ""}" title="${escapeHtml(name)}">
      <span class="sn">${escapeHtml(name)}</span><span class="sv">${fmtStat(val)}${extra}</span></div>`;
  const totals = Object.values(b.totals.stats || {})
    .sort((x, y) => x.harmful - y.harmful || x.name.localeCompare(y.name, "ru"))
    .map((s) => statRow(s.name, s.total, s.harmful)).join("");
  const contam = (b.totals.contamination || [])
    .map((c) => statRow(c.name, c.net, c.over, c.limit != null ? `<span class="lim"> / ${c.limit}</span>` : ""))
    .join("");
  const totalsHtml = `<div class="db-tt">ПАРАМЕТРЫ СБОРКИ · ДАЮТ АРТЕФАКТЫ</div>
    <div class="db-stats">${totals || `<div class="empty-sm">СТАТОВ НЕТ</div>`}</div>
    ${contam ? `<div class="db-tt sub">ЗАРАЖЕНИЕ (ПОСЛЕ ЗАЩИТЫ КОНТЕЙНЕРА)</div>
       <div class="db-stats">${contam}</div>` : ""}`;
  return head + gear + `<div class="db-arts">${arts}</div>${totalsHtml}
    <div class="db-cost">АРТЕФАКТЫ <b>${fmt(b.totals.cost)} ₽</b> <span class="db-of">/ ${fmtBudgetShort(d.budget)} БЮДЖЕТ</span></div>`;
}

function renderDashboard(top, art, watch, em, sales, fuelTop, patches, daily) {
  const card = (title, note, body, link, linkText) => `<section class="dash-card">
    <div class="side-head">
      <div class="side-title">▸ ${title}</div>
      <div class="side-note">${note}</div>
    </div>
    ${body}
    ${link ? `<a class="dash-more" href="${link}">${linkText || "ОТКРЫТЬ РАЗДЕЛ"} ▸</a>` : ""}
  </section>`;

  // крафты: по 2-3 из каждой подборки
  let crafts = "";
  if (top) {
    const grp = (t, list, pctBadge) => (list && list.length)
      ? `<div class="dash-grp">${t}</div>` + list.slice(0, 3).map((e) => dashCraftRow(e, pctBadge)).join("") : "";
    crafts = grp("ВЫГОДНЫЕ", top.profitable, false) + grp("ПРОФИТНЫЕ", top.liquid, true)
           + grp("ПОПУЛЯРНЫЕ", top.popular, false);
  }
  if (!crafts) crafts = `<div class="empty-sm">ЦЕНЫ СЧИТАЮТСЯ В ФОНЕ — ЗАГЛЯНИ ПОЗЖЕ.</div>`;

  // тренды биржи артефактов
  let trends = "";
  if (art && ((art.up || []).length || (art.down || []).length)) {
    const grp = (t, list) => (list && list.length)
      ? `<div class="dash-grp">${t}</div>` + list.slice(0, 6).map(dashArtRow).join("") : "";
    trends = grp("РАСТУТ", art.up) + grp("ПАДАЮТ", art.down);
  } else trends = `<div class="empty-sm">БИРЖА НАКАПЛИВАЕТ ЗАМЕРЫ — СКОРО ПОЯВЯТСЯ ТРЕНДЫ.</div>`;

  // мини-графики биржи ингредиентов — все наблюдаемые, с полной сводкой
  let charts = "";
  if (watch && watch.items && watch.items.length) {
    charts = `<div class="dash-charts">` + watch.items.map((m) => {
      const meta = [
        `МИН ${m.min_buyout != null ? fmt(m.min_buyout) + " ₽" : "—"}`,
        m.sales_per_hour != null ? `${fmtSales(m.sales_per_hour)} ПРОД/Ч` : "",
      ].filter(Boolean).join(" · ");
      return `
      <div class="dash-chart" data-nav="/item/${m.id}">
        <div class="dc-head"><img loading="lazy" src="${asset(m.icon)}" alt="">
          <span class="nm">${escapeHtml(m.name)}</span>
          ${m.delta_pct != null ? `<span class="pct ${m.delta_pct > 0 ? "up" : m.delta_pct < 0 ? "down" : "dim"}">${m.delta_pct > 0 ? "+" : ""}${m.delta_pct}%</span>` : ""}</div>
        ${chartSvg(m.series || [])}
        <div class="dc-price">${m.avg != null ? fmt(m.avg) + " ₽" : "—"} <span class="dc-unit">СР./ШТ</span></div>
        <div class="dc-meta">${meta}</div>
      </div>`;
    }).join("") + `</div>`;
    const hours = (watch.hours || []).map((h) => String(h).padStart(2, "0") + ":00").join(" · ");
    charts += `<div class="dash-note">ЗАМЕРЫ ${hours} МСК${watch.last_slot
      ? ` · ПОСЛЕДНИЙ ${fmtSlot(watch.last_slot)}` : ""} · ДЕЛЬТА — К ПРОШЛОМУ ЗАМЕРУ</div>`;
  } else charts = `<div class="empty-sm">ЖДЁМ ПЕРВЫЕ ЗАМЕРЫ БИРЖИ.</div>`;

  // последние патчи игры
  let patchBody = "";
  if (patches && patches.items && patches.items.length) {
    patchBody = patches.items.map((p) => `
      <div class="dash-patch" data-nav="/patches/${p.id}">
        <div class="dp-t">${escapeHtml(p.title)}</div>
        <div class="dp-d">${fmtPatchDate(p.created_at)}</div>
        <div class="dp-a">${escapeHtml(p.anons || "")}</div>
      </div>`).join("");
  } else patchBody = `<div class="empty-sm">СИНХРОНИЗАЦИЯ С ФОРУМОМ EXBO…</div>`;

  home.innerHTML = `<div class="dash">
    <div class="dash-hero">
      <div class="dash-hero-t">ТЕРМИНАЛ STALZONE HELPER</div>
      <div class="dash-hero-s">Крафт, аукцион, сборки артефактов и карта Зоны — живые данные аукциона RU.</div>
    </div>
    <div class="dash-grid">
      ${card("КРАФТЫ ДНЯ", "ВЫГОДА В ₽ · ЛИКВИДНОСТЬ · СПРОС", crafts, "/craft", "В РАЗДЕЛ КРАФТА")}
      ${card("САМОЕ ПРОДАВАЕМОЕ", "ТОП-12 ПО ТЕМПУ ПРОДАЖ", salesBody(sales), "/market", "НА АУКЦИОН")}
      ${card("ТРЕНДЫ БИРЖИ АРТЕФАКТОВ", "ЦЕНА ЗА СУТКИ", trends, "/auction", "НА БИРЖУ")}
      ${card("ГРАФИКИ ИНГРЕДИЕНТОВ", "ВСЕ НАБЛЮДАЕМЫЕ · СР. ЦЕНА ПРОДАЖ", charts, "/craft", "В РАЗДЕЛ КРАФТА")}
      ${card("ЗАПРАВКА ГЕНЕРАТОРА", "ВСЕ ИСТОЧНИКИ · ₽ ЗА 1000 ЕД", fuelBody(fuelTop), "/profile", "ПРИСТРОЙКИ — В ПРОФИЛЕ")}
      ${card("ВЫБРОС", "ВРЕМЯ МСК · ЗАМЕР РАЗ В МИНУТУ", emissionBody(em))}
      ${card("СБОРКА ДНЯ", "БРОНЯ + КОНТЕЙНЕР + АРТЕФАКТЫ · РАЗ В СУТКИ", dailyBuildBody(daily), "/builds", "К КАЛЬКУЛЯТОРУ")}
      ${card("ПОСЛЕДНИЙ ПАТЧ", "ОБНОВЛЕНИЯ ИГРЫ", patchBody, "/patches", "ВСЕ ПАТЧИ")}
    </div>
  </div>`;
  home.querySelectorAll("[data-nav]").forEach((el) =>
    el.addEventListener("click", () => { navigate(el.dataset.nav); }));
  home.querySelectorAll(".stab").forEach((b) => b.addEventListener("click", () => {
    home.querySelectorAll(".stab").forEach((x) => x.classList.toggle("on", x === b));
    home.querySelectorAll(".sales-view").forEach((v) =>
      v.classList.toggle("hidden", v.dataset.view !== b.dataset.view));
  }));
  startEmTick();
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

function sideRow(e, extra, pctBadge) {
  // бейдж — либо дельта ₽ (ВЫГОДНЫЕ), либо % маржи (ПРОФИТНЫЕ); вторую метрику в мету
  const badge = e.diff == null
    ? `<span class="pct dim">—</span>`
    : pctBadge
      ? `<span class="pct ${e.pct > 0 ? "up" : "down"}" title="${e.diff > 0 ? "+" : ""}${fmt(e.diff)} ₽ ЗА ЦИКЛ">${e.pct > 0 ? "+" : ""}${e.pct}%</span>`
      : `<span class="pct ${e.diff > 0 ? "up" : "down"}">${e.diff > 0 ? "+" : ""}${fmt(e.diff)} ₽</span>`;
  const meta = [];
  if (e.craft_cost != null) meta.push(`КРАФТ ${fmt(e.craft_cost)}`);
  if (e.sell_price != null) meta.push(`ПРОДАЖА ~${fmt(e.sell_price)}`);
  else if (e.buy_price != null) meta.push(`АУК ${fmt(e.buy_price)}`);
  if (pctBadge) { if (e.diff != null) meta.push(`${e.diff > 0 ? "+" : ""}${fmt(e.diff)} ₽`); }
  else if (e.pct != null) meta.push(`${e.pct > 0 ? "+" : ""}${e.pct}%`);
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
  const sec = (title, note, list, extra, empty, pctBadge) => `
    <section>
      <div class="side-head">
        <div class="side-title">▸ ${title}</div>
        <div class="side-note">${note}</div>
      </div>
      ${list && list.length
        ? `<div class="side-list">${list.map((e) => sideRow(e, extra, pctBadge)).join("")}</div>`
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
  h += sec("ВЫГОДНЫЕ КРАФТЫ", `ДЕЛЬТА ₽ ЗА ЦИКЛ · ПРОДАЖИ ${d.liquid_threshold || 10}+/Ч${availNote}`,
           d.profitable, "sales",
           availEmpty || "НЕТ ЛИКВИДНЫХ КРАФТОВ (ИЛИ ЦЕНЫ ЕЩЁ СЧИТАЮТСЯ) — ЗАГЛЯНИ ПОЗЖЕ.");
  h += sec("ПРОФИТНЫЕ", `МАРЖА % · ПРОДАЖИ ${d.liquid_threshold || 10}+/Ч${availNote}`, d.liquid, "sales",
           availEmpty || "НЕТ ПРЕДМЕТОВ С ТАКОЙ ЧАСТОТОЙ ПРОДАЖ (ИЛИ ЦЕНЫ ЕЩЁ СЧИТАЮТСЯ).", true);
  h += sec("ПОПУЛЯРНЫЕ", "ОТКРЫТИЯ КАРТОЧЕК" + availNote, d.popular, "opens",
           availEmpty || "ПОКА НЕТ СТАТИСТИКИ — ОТКРЫВАЙ КАРТОЧКИ ПРЕДМЕТОВ.");
  h += `</div>`;

  h += `<div class="side-foot">ИСТОЧНИКИ: STALZONE-DATABASE (РЕЦЕПТЫ, СУТОЧНОЕ ОБНОВЛЕНИЕ) ·
    AUCTION API (ЦЕНЫ, ФОНОВЫЙ ПРОГРЕВ).${API_IS_DEMO ? `<br><span class="warn">РЕЖИМ ДЕМО — ЦЕНЫ ТЕСТОВЫЕ.</span>` : ""}</div>`;

  home.innerHTML = h;
  home.querySelectorAll(".side-row, .watch-card").forEach((r) =>
    r.addEventListener("click", () => { navigate(`/item/${r.dataset.id}`); }));
}

// ---------- чаты: виджет справа снизу (общий + баги/предложения) ----------
const CHAT_ROOMS = [["general", "ОБЩИЙ"], ["bugs", "БАГИ/ИДЕИ"]];
let chatRoom = localStorage.getItem("sz_chat_room") || "general";
let chatOpen = localStorage.getItem("sz_chat_open") === "1";
let chatLastId = 0, chatPollTimer = null, chatBusy = false;

function chatDockRender() {
  const dock = $("chatDock");
  if (!dock) return;
  if (chatPollTimer) { clearInterval(chatPollTimer); chatPollTimer = null; }
  if (!chatOpen) {
    dock.className = "chat-dock collapsed";
    dock.innerHTML = `<button class="chat-fab" id="chatFab">▲ ЧАТ // СВЯЗЬ</button>`;
    $("chatFab").addEventListener("click", () => {
      chatOpen = true; localStorage.setItem("sz_chat_open", "1"); chatDockRender();
    });
    return;
  }
  dock.className = "chat-dock open";
  const tabs = CHAT_ROOMS.map(([id, label]) =>
    `<button class="chat-tab ${id === chatRoom ? "on" : ""}" data-room="${id}">${label}</button>`).join("");
  const canPost = ME && ME.authenticated;
  dock.innerHTML = `
    <div class="chat-head">${tabs}<button class="chat-min" id="chatMin" title="Свернуть">▼</button></div>
    <div class="chat-msgs" id="chatMsgs"><div class="spinner">// ЗАГРУЗКА</div></div>
    <div class="chat-form">${canPost
      ? `<input id="chatInput" maxlength="500" autocomplete="off" placeholder="СООБЩЕНИЕ…"><button id="chatSend">▸</button>`
      : `<a class="chat-login js-open-auth" href="${BASE}/auth/login">ВОЙТИ, ЧТОБЫ ПИСАТЬ</a>`}</div>`;
  dock.querySelectorAll(".chat-tab").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.room === chatRoom) return;
    chatRoom = b.dataset.room; localStorage.setItem("sz_chat_room", chatRoom);
    chatLastId = 0; chatDockRender();
  }));
  $("chatMin").addEventListener("click", () => {
    chatOpen = false; localStorage.setItem("sz_chat_open", "0"); chatDockRender();
  });
  if (canPost) {
    const send = async () => {
      const inp = $("chatInput");
      const text = inp.value.trim();
      if (!text) return;
      inp.value = "";
      try {
        const r = await fetch(api(`/chat/${chatRoom}`), {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        if (r.status === 429) inp.placeholder = "НЕ ТАК БЫСТРО…";
        chatRefresh();
      } catch (e) { /* тихо */ }
    };
    $("chatSend").addEventListener("click", send);
    $("chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  }
  chatLastId = 0;
  chatRefresh(true);
  chatPollTimer = setInterval(() => chatRefresh(), 5000);
}

function chatMsgHtml(m) {
  const t = new Date(m.ts * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return `<div class="chat-msg"><span class="t">${t}</span> <span class="u">${escapeHtml(m.login)}</span> ${escapeHtml(m.text)}</div>`;
}

async function chatRefresh(reset = false) {
  if (chatBusy) return;
  chatBusy = true;
  try {
    const d = await fetch(api(`/chat/${chatRoom}?after=${reset ? 0 : chatLastId}`)).then((r) => r.json());
    const box = $("chatMsgs");
    if (!box) return;
    if (reset) box.innerHTML = "";
    if (d.messages && d.messages.length) {
      const ph = box.querySelector(".chat-empty, .spinner");
      if (ph) box.innerHTML = "";
      const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
      box.insertAdjacentHTML("beforeend", d.messages.map(chatMsgHtml).join(""));
      chatLastId = d.last_id;
      if (reset || atBottom) box.scrollTop = box.scrollHeight;
    } else if (!box.children.length) {
      box.innerHTML = `<div class="chat-empty">ПОКА ПУСТО — НАПИШИ ПЕРВЫМ.</div>`;
    }
  } catch (e) { /* тихо */ } finally { chatBusy = false; }
}

// ---------- полный аукцион: живые лоты и история продаж любого предмета ----------
const marketState = { itemId: null };
let mkTimer = null;

async function openMarket() {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА АУКЦИОНА</div>`;
  window.scrollTo(0, 0);
  let ov = null;
  try {
    ov = await fetch(api("/market/overview")).then((r) => r.json());
  } catch (e) { /* покажем без подборок */ }
  if (location.pathname !== "/market") return;
  marketState.itemId = null;   // карточка теперь в модале — при входе закрыта
  renderMarket(ov);
}

function mkRow(r, val) {
  return `<div class="side-row mk-row" data-id="${r.id}" style="border-left-color:transparent">
    <img loading="lazy" src="${asset(r.icon)}" alt="">
    <div class="info"><div class="nm" style="color:${rank(r.color).color}">${escapeHtml(r.name)}</div>
      <div class="meta">${val}</div></div></div>`;
}

function renderMarket(ov) {
  const col = (title, note, rows) => `<section>
    <div class="side-head"><div class="side-title">▸ ${title}</div><div class="side-note">${note}</div></div>
    ${rows && rows.length ? `<div class="side-list">${rows.join("")}</div>`
                          : `<div class="empty-sm">ЦЕНЫ ЕЩЁ СЧИТАЮТСЯ В ФОНЕ.</div>`}
  </section>`;
  const liquid = (ov && ov.liquid || []).map((r) =>
    mkRow(r, `${fmtSales(r.sales_per_hour)} ПРОД/Ч${r.min_buyout ? " · ОТ " + fmt(r.min_buyout) + " ₽" : ""}`));
  const expensive = (ov && ov.expensive || []).map((r) =>
    mkRow(r, `ОТ ${fmt(r.min_buyout)} ₽${r.sales_per_hour ? " · " + fmtSales(r.sales_per_hour) + " ПРОД/Ч" : ""}`));
  page.innerHTML = `<div class="mkmod">
    <div class="section-head">
      <div class="section-title">▸ АУКЦИОН · ЖИВЫЕ ЛОТЫ И ПРОДАЖИ</div>
      <div class="section-note">ЛОТЫ ОБНОВЛЯЮТСЯ ПРИ ОТКРЫТИИ ПРЕДМЕТА</div>
    </div>
    <div class="search-box mk-search">
      <div class="search-prompt">&gt;_</div>
      <input id="mkInput" type="search" autocomplete="off" placeholder="НАЙТИ ПРЕДМЕТ НА АУКЦИОНЕ…">
    </div>
    <div id="mkResults"></div>
    <div id="mkModal" class="mk-modal hidden" aria-modal="true" role="dialog">
      <div class="mk-modal-box">
        <button class="mk-modal-x" id="mkModalX" title="Закрыть (Esc)">✕</button>
        <div id="mkDetail"></div>
      </div>
    </div>
    <div class="home-cols mk-cols">
      ${col("САМЫЕ ПРОДАВАЕМЫЕ", "ПРОДАЖ В ЧАС", liquid)}
      ${col("САМЫЕ ДОРОГИЕ", "МИН. ВЫКУП", expensive)}
    </div>
  </div>`;
  const inp = $("mkInput");
  inp.addEventListener("input", () => {
    clearTimeout(mkTimer);
    mkTimer = setTimeout(async () => {
      const q = inp.value.trim();
      const box = $("mkResults");
      if (!q) { box.innerHTML = ""; return; }
      try {
        const r = await fetch(api(`/search?q=${encodeURIComponent(q)}&limit=12`)).then((x) => x.json());
        box.innerHTML = (r.results || []).map((it) =>
          mkRow(it, "")).join("") || `<div class="empty-sm">НИЧЕГО НЕ НАЙДЕНО.</div>`;
        wireMkRows(box);
      } catch (e) { /* тихо */ }
    }, 250);
  });
  wireMkRows(page);
  $("mkModalX").addEventListener("click", mkModalClose);
  $("mkModal").addEventListener("click", (e) => {
    if (e.target.id === "mkModal") mkModalClose();   // клик по подложке
  });
}

function mkModalClose() {
  const m = $("mkModal");
  if (m) m.classList.add("hidden");
  marketState.itemId = null;
  syncModalScroll();
}

// ---------- общий модал разделов (бартер, обменки, квесты) ----------
let gModalCleanup = null;   // хук закрытия (квесты убивают Leaflet-миникарту)

function gModalOpen(html) {
  if (gModalCleanup) { const f = gModalCleanup; gModalCleanup = null; f(); }
  $("gModalBody").innerHTML = html;
  const m = $("gModal");
  m.classList.remove("hidden");
  m.querySelector(".mk-modal-box").scrollTop = 0;
  document.body.classList.add("modal-open");
}

function gModalClose() {
  if (gModalCleanup) { const f = gModalCleanup; gModalCleanup = null; f(); }
  $("gModal").classList.add("hidden");
  syncModalScroll();
}

function syncModalScroll() {
  const anyOpen = ["gModal", "mkModal"].some((id) => {
    const m = $(id);
    return m && !m.classList.contains("hidden");
  });
  document.body.classList.toggle("modal-open", anyOpen);
}

(function wireGModal() {
  const m = $("gModal");
  $("gModalX").addEventListener("click", gModalClose);
  m.addEventListener("click", (e) => { if (e.target === m) gModalClose(); });
})();

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { mkModalClose(); gModalClose(); }
});

function wireMkRows(root) {
  root.querySelectorAll(".mk-row").forEach((r) => r.addEventListener("click", () => {
    marketState.itemId = r.dataset.id;
    const res = $("mkResults");
    if (res) res.innerHTML = "";
    const inp = $("mkInput");
    if (inp) inp.value = "";
    loadMarketItem(r.dataset.id);
  }));
}

const fmtLotTime = (iso) => {
  const d = new Date(iso);
  return isNaN(d) ? "—" : d.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit" });
};

async function loadMarketItem(id) {
  const box = $("mkDetail");
  if (!box) return;
  const modal = $("mkModal");   // карточка с графиком и ценами — в модале
  if (modal) {
    modal.classList.remove("hidden");
    modal.querySelector(".mk-modal-box").scrollTop = 0;
    document.body.classList.add("modal-open");
  }
  box.innerHTML = `<div class="spinner">// ЗАПРАШИВАЮ ЛОТЫ</div>`;
  let d;
  try {
    d = await fetch(api(`/market/item/${id}`)).then((r) => r.json());
  } catch (e) {
    box.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
    return;
  }
  if (marketState.itemId !== id || !$("mkDetail")) return;
  const it = d.item || {};
  const lots = (d.lots || []).slice(0, 20).map((l) => `<tr>
      <td class="r">${l.unit != null ? fmt(l.unit) : "—"}</td>
      <td class="r">${l.amount}</td>
      <td class="r">${l.buyout != null ? fmt(l.buyout) : "—"}</td>
      <td>${l.end ? fmtLotTime(l.end) : "—"}</td>
    </tr>`).join("");
  const sales = (d.sales || []).slice(0, 20).map((s) => `<tr>
      <td>${s.time ? fmtLotTime(s.time) : "—"}</td>
      <td class="r">${s.unit != null ? fmt(s.unit) : "—"}</td>
      <td class="r">${s.amount}</td>
      <td class="r">${s.price != null ? fmt(s.price) : "—"}</td>
    </tr>`).join("");
  box.innerHTML = `<div class="mk-item">
    <div class="mk-head">
      <img src="${asset(it.icon)}" alt="">
      <div class="mk-title" style="color:${rank(it.color).color}">${escapeHtml(it.name || id)}</div>
      <a class="mk-card" href="/item/${id}">КАРТОЧКА ПРЕДМЕТА ▸</a>
    </div>
    ${d.error ? `<div class="note-warn"><span class="mark">[!]</span> АУКЦИОН НЕ ОТВЕТИЛ (${escapeHtml(String(d.error))}) — ПОКАЗЫВАЮ ЧТО ЕСТЬ.</div>` : ""}
    <div class="mk-chart-wrap">
      <div class="dash-grp mkc-head"><span>ГРАФИК ПРОДАЖ · ЦЕНА/ШТ И ОБЪЁМ</span>
        <span class="mkc-ranges" id="mkcRanges"></span></div>
      <div class="mk-chart" id="mkChartBox"></div>
      <div class="mkc-note" id="mkChartNote"></div>
    </div>
    <div class="mk-tables">
      <div class="mk-tbl">
        <div class="dash-grp">АКТИВНЫЕ ЛОТЫ${d.lots_total != null ? ` · ВСЕГО ${fmt(d.lots_total)}` : ""} (20 ДЕШЁВЫХ)</div>
        ${lots ? `<table><thead><tr><th class="r">ЦЕНА/ШТ</th><th class="r">КОЛ-ВО</th><th class="r">ВЫКУП</th><th>ДО (МСК)</th></tr></thead><tbody>${lots}</tbody></table>`
               : `<div class="empty-sm">АКТИВНЫХ ЛОТОВ НЕТ.</div>`}
      </div>
      <div class="mk-tbl">
        <div class="dash-grp">ПОСЛЕДНИЕ ПРОДАЖИ</div>
        ${sales ? `<table><thead><tr><th>ВРЕМЯ (МСК)</th><th class="r">ЦЕНА/ШТ</th><th class="r">КОЛ-ВО</th><th class="r">СУММА</th></tr></thead><tbody>${sales}</tbody></table>`
                : `<div class="empty-sm">ПРОДАЖ НЕ НАЙДЕНО.</div>`}
      </div>
    </div>
  </div>`;
  initSalesChart(id);
}

// ---------- график продаж предмета: масштабируемый, данные копятся до года ----------
const mkChart = { itemId: null, preset: 7, custom: null, data: null };
const MKC_PRESETS = [[1, "24Ч"], [7, "7Д"], [30, "30Д"], [90, "90Д"], [365, "ГОД"]];
// слоты серии — МСК: 'YYYY-MM-DDTHH:00' (часы) или 'YYYY-MM-DD' (дни)
const mkcSlotMs = (t) => Date.parse(t.length === 10 ? `${t}T00:00:00+03:00` : `${t}:00+03:00`);
const mkcSlotStr = (ms) => {
  const s = new Date(ms).toLocaleString("sv-SE", { timeZone: "Europe/Moscow" });
  return s.slice(0, 13).replace(" ", "T") + ":00";
};
const mkcFmtP = (v) =>
  v >= 1e6 ? (v / 1e6 >= 10 ? Math.round(v / 1e6) : (v / 1e6).toFixed(1)) + "М"
  : v >= 1000 ? (v / 1000 >= 10 ? Math.round(v / 1000) : (v / 1000).toFixed(1)) + "К"
  : String(Math.round(v));
const mkcFmtT = (ms, spanMs, gran) => {
  const o = { timeZone: "Europe/Moscow" };
  const d = new Date(ms);
  if (spanMs <= 36 * 3.6e6) return d.toLocaleString("ru-RU", { ...o, hour: "2-digit", minute: "2-digit" });
  if (gran === "h" || spanMs <= 15 * 86400e3)
    return d.toLocaleString("ru-RU", { ...o, day: "2-digit", month: "2-digit" })
      + (spanMs <= 4 * 86400e3 ? " " + d.toLocaleString("ru-RU", { ...o, hour: "2-digit", minute: "2-digit" }) : "");
  return d.toLocaleString("ru-RU", { ...o, day: "2-digit", month: "2-digit" });
};

function initSalesChart(itemId) {
  mkChart.itemId = itemId;
  mkChart.custom = null;
  mkChart.data = null;
  loadSalesChart();
}

async function loadSalesChart() {
  const box = $("mkChartBox");
  if (!box) return;
  const q = mkChart.custom
    ? `since=${mkChart.custom[0]}&until=${mkChart.custom[1]}`
    : `days=${mkChart.preset}`;
  box.classList.add("dim");
  let d = null;
  try {
    d = await fetch(api(`/market/item/${mkChart.itemId}/sales?${q}`)).then((r) => r.json());
  } catch (e) { /* нарисуем ошибку */ }
  if (!$("mkChartBox")) return;   // карточку уже закрыли
  mkChart.data = d;
  drawSalesChart();
}

function drawSalesChart() {
  const box = $("mkChartBox"), note = $("mkChartNote"), ranges = $("mkcRanges");
  if (!box) return;
  box.classList.remove("dim");
  ranges.innerHTML = MKC_PRESETS.map(([days, lbl]) =>
    `<button class="mkc-btn ${!mkChart.custom && mkChart.preset === days ? "on" : ""}" data-days="${days}">${lbl}</button>`)
    .join("") + (mkChart.custom ? `<button class="mkc-btn on" data-reset="1">⤺ СБРОС</button>` : "");
  ranges.querySelectorAll(".mkc-btn").forEach((b) => b.addEventListener("click", () => {
    if (!b.dataset.reset) mkChart.preset = +b.dataset.days;
    mkChart.custom = null;
    loadSalesChart();
  }));

  const d = mkChart.data;
  if (!d || d.error) {
    box.innerHTML = `<div class="empty-sm">[!] СЕРИЯ ПРОДАЖ НЕ ЗАГРУЗИЛАСЬ.</div>`;
    note.textContent = "";
    return;
  }
  note.textContent = (d.first ? `ДАННЫЕ КОПЯТСЯ С ${mkcFmtT(mkcSlotMs(d.first), 99 * 86400e3)} · ` : "")
    + `ХРАНИМ ГОД (ЧАСЫ — ${d.hourly_days} ДН, СТАРШЕ — ПО ДНЯМ) · МАСШТАБ: ВЫДЕЛИ УЧАСТОК МЫШЬЮ, СБРОС — ДВОЙНОЙ КЛИК`;
  const S = d.series || [];
  const bucketMs = d.granularity === "d" ? 86400e3 : 3600e3;
  const t0 = mkcSlotMs(d.since), t1 = mkcSlotMs(d.until) + bucketMs;
  if (!S.length) {
    box.innerHTML = `<div class="empty-sm">${d.first
      ? "В ЭТОМ ОКНЕ ПРОДАЖ НЕ ЗАПИСАНО."
      : "ПРОДАЖИ НАЧАЛИ КОПИТЬСЯ С ЭТОГО ОТКРЫТИЯ КАРТОЧКИ — ГРАФИК НАПОЛНИТСЯ СО ВРЕМЕНЕМ."}</div>`;
    return;
  }
  const pts = S.map((r) => ({ ...r, t: mkcSlotMs(r.t) }));
  const W = Math.max(box.clientWidth || 800, 480), H = 250;
  const padL = 8, padR = 56, padT = 10, padB = 20, volH = 46, gap = 8;
  const plotW = W - padL - padR, priceH = H - padT - padB - volH - gap;
  const volTop = padT + priceH + gap, volBot = volTop + volH;
  const x = (t) => padL + ((t - t0) / (t1 - t0)) * plotW;
  let lo = Math.min(...pts.map((p) => p.min)), hi = Math.max(...pts.map((p) => p.max));
  if (hi <= lo) { hi = lo + Math.max(1, lo * 0.05); lo = Math.max(0, lo - Math.max(1, lo * 0.05)); }
  const padY = (hi - lo) * 0.07;
  lo = Math.max(0, lo - padY); hi += padY;
  const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * priceH;
  const vmax = Math.max(...pts.map((p) => p.n), 1);
  const barW = Math.max(1, (plotW * bucketMs) / (t1 - t0) - 1);

  let g = "";
  for (let i = 0; i <= 3; i++) {   // сетка цены + подписи справа
    const v = lo + ((hi - lo) * i) / 3, yy = y(v);
    g += `<line x1="${padL}" y1="${yy}" x2="${W - padR}" y2="${yy}" stroke="var(--bar-track)" stroke-width="1"/>
      <text x="${W - padR + 5}" y="${yy + 3.5}" class="mkc-lbl">${mkcFmtP(v)}</text>`;
  }
  for (let i = 1; i <= 5; i++) {   // тики времени
    const t = t0 + ((t1 - t0) * i) / 6, xx = x(t);
    g += `<line x1="${xx}" y1="${padT}" x2="${xx}" y2="${volBot}" stroke="var(--bar-track)" stroke-width="1" opacity="0.5"/>
      <text x="${xx}" y="${H - 6}" text-anchor="middle" class="mkc-lbl">${mkcFmtT(t, t1 - t0, d.granularity)}</text>`;
  }
  const cx = (p) => x(p.t + bucketMs / 2);
  const band = pts.map((p) => `${cx(p).toFixed(1)},${y(p.max).toFixed(1)}`).join(" ")
    + " " + [...pts].reverse().map((p) => `${cx(p).toFixed(1)},${y(p.min).toFixed(1)}`).join(" ");
  const line = pts.map((p) => `${cx(p).toFixed(1)},${y(p.avg).toFixed(1)}`).join(" ");
  const bars = pts.map((p) => {
    const h = Math.max(1, (p.n / vmax) * volH);
    return `<rect x="${(cx(p) - barW / 2).toFixed(1)}" y="${(volBot - h).toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" class="mkc-bar"/>`;
  }).join("");
  const dots = pts.length <= 60
    ? pts.map((p) => `<circle cx="${cx(p).toFixed(1)}" cy="${y(p.avg).toFixed(1)}" r="2" fill="var(--green)"/>`).join("") : "";
  g += `<text x="${W - padR + 5}" y="${volTop + 9}" class="mkc-lbl">${mkcFmtP(vmax)}</text>
    <text x="${W - padR + 5}" y="${volBot}" class="mkc-lbl">ШТ</text>`;

  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" class="mkc-svg">
      ${g}
      <polygon points="${band}" fill="var(--green)" opacity="0.10"/>
      <polyline points="${line}" fill="none" stroke="var(--green)" stroke-width="1.6"/>
      ${dots}${bars}
      <line class="mkc-cross" y1="${padT}" y2="${volBot}" stroke="var(--amber)" stroke-width="1" opacity="0"/>
      <rect class="mkc-sel" y="${padT}" height="${volBot - padT}" width="0" fill="var(--amber)" opacity="0.15"/>
      <rect x="0" y="0" width="${W}" height="${H}" fill="transparent" class="mkc-overlay"/>
    </svg><div class="mkc-tip hidden"></div>`;

  const svg = box.querySelector("svg"), tip = box.querySelector(".mkc-tip");
  const cross = svg.querySelector(".mkc-cross"), sel = svg.querySelector(".mkc-sel");
  const svgX = (ev) => {
    const r = svg.getBoundingClientRect();
    return ((ev.clientX - r.left) / r.width) * W;
  };
  let drag0 = null;
  svg.addEventListener("pointerdown", (ev) => {
    drag0 = svgX(ev);
    svg.setPointerCapture(ev.pointerId);
  });
  svg.addEventListener("pointermove", (ev) => {
    const px = svgX(ev);
    if (drag0 != null) {
      sel.setAttribute("x", Math.min(drag0, px));
      sel.setAttribute("width", Math.abs(px - drag0));
    }
    let best = null, bd = 1e18;   // ближайшая точка — перекрестие + тултип
    for (const p of pts) {
      const dd = Math.abs(cx(p) - px);
      if (dd < bd) { bd = dd; best = p; }
    }
    if (!best) return;
    cross.setAttribute("x1", cx(best));
    cross.setAttribute("x2", cx(best));
    cross.setAttribute("opacity", "0.8");
    tip.innerHTML = `<b>${mkcFmtT(best.t, 0, d.granularity)}${d.granularity === "h" ? " МСК" : ""}</b><br>
      СР ${fmt(best.avg)} ₽<br>МИН ${fmt(best.min)} · МАКС ${fmt(best.max)}<br>ПРОДАНО ${fmt(best.n)} ШТ`;
    tip.classList.remove("hidden");
    // позиция — во viewport-координатах: у правого/нижнего края экрана
    // тултип переворачивается на другую сторону курсора, не уходя за экран
    const wr = box.getBoundingClientRect();
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let vx = ev.clientX + 14;
    if (vx + tw > window.innerWidth - 8) vx = ev.clientX - tw - 14;
    let vy = ev.clientY + 14;
    if (vy + th > window.innerHeight - 8) vy = ev.clientY - th - 12;
    tip.style.left = Math.max(4 - wr.left, vx - wr.left) + "px";
    tip.style.top = (vy - wr.top) + "px";
  });
  svg.addEventListener("pointerup", (ev) => {
    if (drag0 == null) return;
    const a = Math.min(drag0, svgX(ev)), b = Math.max(drag0, svgX(ev));
    drag0 = null;
    sel.setAttribute("width", 0);
    if (b - a < 10) return;   // клик, не выделение
    const ta = t0 + ((a - padL) / plotW) * (t1 - t0);
    const tb = t0 + ((b - padL) / plotW) * (t1 - t0);
    if (tb - ta < 2 * 3600e3) return;   // мельче 2 часов не масштабируем
    mkChart.custom = [mkcSlotStr(Math.max(ta, t0)), mkcSlotStr(Math.min(tb, t1))];
    loadSalesChart();
  });
  svg.addEventListener("pointerleave", () => {
    tip.classList.add("hidden");
    cross.setAttribute("opacity", "0");
  });
  svg.addEventListener("dblclick", () => {
    if (mkChart.custom) { mkChart.custom = null; loadSalesChart(); }
  });
}

// ---------- бартер: выгодные обмены у торговцев поселений ----------
const CAT_RU = {
  weapon: "ОРУЖИЕ", attachment: "ОБВЕСЫ", armor: "БРОНЯ", containers: "КОНТЕЙНЕРЫ",
  backpacks: "РЮКЗАКИ", bullet: "БОЕПРИПАСЫ", misc: "РАЗНОЕ", other: "ПРОЧЕЕ",
  device: "УСТРОЙСТВА", artefact: "АРТЕФАКТЫ", medicine: "МЕДИЦИНА", food: "ЕДА",
  drink: "НАПИТКИ", grenade: "ГРАНАТЫ",
};
const catName = (c) => CAT_RU[c] || String(c || "").toUpperCase();
const CUR_RU = { money: "₽", sleeves: "ГИЛЬЗ" };

let btState = { settlement: "", cat: "", maxLevel: 0, pure: false, q: "", rank: "", shown: 60 };
let btTimer = null;
let btLastRows = [];   // отфильтрованный набор последнего ответа — для «выбрать всё»

// корзина мультивыбора: id -> qty, переживает перезагрузку (localStorage)
let btSel = new Map();
try {
  btSel = new Map(Object.entries(JSON.parse(localStorage.getItem("bt_basket") || "{}"))
    .map(([id, q]) => [id, Math.max(1, Math.min(99, +q || 1))]));
} catch (e) { /* битый JSON — начинаем с пустой */ }
const btSelSave = () => {
  try { localStorage.setItem("bt_basket", JSON.stringify(Object.fromEntries(btSel))); } catch (e) {}
};

async function openBarter() {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА БАРТЕРОВ</div>`;
  window.scrollTo(0, 0);
  await refreshBarter(true);
}

async function refreshBarter(full = false) {
  const p = new URLSearchParams();
  if (btState.settlement) p.set("settlement", btState.settlement);
  if (btState.cat) p.set("cat", btState.cat);
  if (btState.maxLevel) p.set("max_level", btState.maxLevel);
  if (btState.pure) p.set("pure", "1");
  if (btState.q) p.set("q", btState.q);
  if (btState.rank) p.set("rank", btState.rank);
  let d;
  try {
    d = await fetch(api(`/barter/top?${p}`)).then((r) => r.json());
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
    return;
  }
  if (location.pathname !== "/barter") return;
  btLastRows = d.rows;
  // корзина следует фильтрам: не попавшее под текущий фильтр вылетает из выбора
  const visible = new Set(d.rows.map((r) => r.id));
  let pruned = false;
  for (const id of [...btSel.keys()])
    if (!visible.has(id)) { btSel.delete(id); pruned = true; }
  if (pruned) btSelSave();
  if (full) renderBarter(d);
  $("btBody").innerHTML = btRows(d.rows);
  $("btCount").textContent = `${d.total} ОБМЕНОВ · КОМИССИЯ АУКА ${d.fee_pct}% УЧТЕНА`;
  wireBtRows(openBarterModal);
  wireBtSel();
  btSelBar();
  btMore(d.rows);
}

function btRows(rows) {
  return rows.slice(0, btState.shown).map((r) => {
    const cost = r.cost != null ? `${fmt(r.cost)} ₽`
      : (r.cost_partial ? `${fmt(r.cost_partial)} ₽ + ФАРМ` : "ФАРМ");
    const cur = r.currency !== "money" && r.money
      ? `<span class="bt-cur">${fmt(r.money)} ${CUR_RU[r.currency] || r.currency.toUpperCase()}</span>` : "";
    const missing = r.missing.length
      ? `<span class="bt-miss" title="${escapeHtml(r.missing.join(", "))}">+${r.missing.length} ФАРМ</span>` : "";
    const places = r.n_places > 1
      ? ` <span class="bt-more-place" title="Доступно ещё в ${r.n_places - 1} — детали в обмене">+ ещё ${r.n_places - 1}</span>` : "";
    return `<tr class="brt-row" data-id="${r.id}">
      <td class="bt-selc"><input type="checkbox" class="bt-selbox" data-id="${r.id}" ${btSel.has(r.id) ? "checked" : ""}></td>
      <td><div class="bt-item"><img loading="lazy" src="${asset(r.icon)}" alt="">
        <span class="nm" style="color:${rank(r.color).color}">${escapeHtml(r.name)}</span>${missing}${cur}</div></td>
      <td class="bt-place">${escapeHtml(r.settlement_name)}${r.level ? ` <span class="lv">УР.${r.level}</span>` : ""}${places}</td>
      <td class="r">${cost}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="4" class="empty-sm">НИЧЕГО НЕ НАЙДЕНО ПО ФИЛЬТРАМ.</td></tr>`;
}

function btMore(rows) {
  const more = $("btMore");
  if (!more) return;
  more.classList.toggle("hidden", rows.length <= btState.shown);
  more.onclick = () => { btState.shown += 120; refreshBarter(); };
}

function renderBarter(d) {
  const opts = (list, cur, all) => `<option value="">${all}</option>` +
    list.map((s) => `<option value="${s.v}" ${cur === s.v ? "selected" : ""}>${escapeHtml(s.t)}</option>`).join("");
  const setl = (d.settlements || []).map((s) => ({ v: s.key, t: s.name }));
  const lvls = [1, 2, 3, 4, 5, 6, 7].map((v) => ({ v: String(v), t: `БАЗА ДО УР.${v}` }));
  const ranks = ["RANK_NEWBIE", "RANK_STALKER", "RANK_VETERAN", "RANK_MASTER", "RANK_LEGEND"]
    .map((v) => ({ v, t: `РАНГ: ${RANKS[v].label}` }));
  // разделы по категориям результата — табами, как вкладки внутри раздела
  const cats = ["", ...(d.categories || [])];
  const catTabs = cats.map((c) => `<button class="bt-cat ${btState.cat === c ? "on" : ""}"
      data-cat="${c}">${c ? catName(c) : "ВСЕ"}</button>`).join("");
  page.innerHTML = `<div class="btmod">
    <div class="section-head">
      <div class="section-title">▸ БАРТЕР · ОБМЕНЫ У ТОРГОВЦЕВ</div>
      <div class="section-note" id="btCount">${d.total} ОБМЕНОВ · КОМИССИЯ АУКА ${d.fee_pct}% УЧТЕНА</div>
    </div>
    <div class="bt-cats">${catTabs}</div>
    <div class="bt-filters">
      <select id="btSettle">${opts(setl, btState.settlement, "ВСЕ ПОСЕЛЕНИЯ")}</select>
      <select id="btLevel">${opts(lvls, btState.maxLevel ? String(btState.maxLevel) : "", "ЛЮБОЙ УРОВЕНЬ")}</select>
      <select id="btRank">${opts(ranks, btState.rank, "ЛЮБОЙ РАНГ")}</select>
      <label class="bt-pure"><input type="checkbox" id="btPure" ${btState.pure ? "checked" : ""}> БЕЗ ФАРМА</label>
      <button id="btSelAll" class="bt-selall">ВЫБРАТЬ ВСЁ (${d.total})</button>
      <div class="search-box bt-search"><div class="search-prompt">&gt;_</div>
        <input id="btQ" type="search" autocomplete="off" placeholder="ФИЛЬТР ПО НАЗВАНИЮ…" value="${escapeHtml(btState.q)}"></div>
    </div>
    <div class="bt-note">СТОИМОСТЬ = ДЕНЬГИ ТОРГОВЦУ + ЗАКУПКА ВХОДОВ НА АУКЕ (ТРЕЙД-ИН РАСКРЫВАЕТСЯ РЕКУРСИВНО).
      «ФАРМ» — ВХОДЫ, КОТОРЫХ НЕТ НА АУКЕ (КВЕСТОВЫЕ/ЖЕТОНЫ). КЛИК ПО СТРОКЕ — ДЕТАЛИ ОБМЕНА.
      ГАЛОЧКА — В КОРЗИНУ: СУММАРНАЯ СТОИМОСТЬ НЕСКОЛЬКИХ ОБМЕНОВ СРАЗУ.</div>
    <div class="bt-wrap"><table class="bt-table">
      <thead><tr><th class="bt-selc" style="width:34px"></th><th style="width:46%">ПРЕДМЕТ</th>
        <th style="width:30%">ГДЕ</th><th class="r" style="width:20%">СТОИМОСТЬ</th></tr></thead>
      <tbody id="btBody"></tbody>
    </table></div>
    <button id="btMore" class="bt-more hidden">ПОКАЗАТЬ ЕЩЁ</button>
    <div id="btSelBar" class="bt-selbar hidden">
      <span>В КОРЗИНЕ: <b id="btSelN">0</b></span>
      <button id="btSelCalc" class="bt-selcalc">ПОСЧИТАТЬ ИТОГО ▸</button>
      <button id="btSelClear" class="bt-selclear">ОЧИСТИТЬ</button>
    </div>
  </div>`;
  page.querySelectorAll(".bt-cat").forEach((b) => b.addEventListener("click", () => {
    btState.cat = b.dataset.cat; btState.shown = 60;
    page.querySelectorAll(".bt-cat").forEach((x) => x.classList.toggle("on", x === b));
    refreshBarter();
  }));
  $("btSettle").addEventListener("change", (e) => { btState.settlement = e.target.value; btState.shown = 60; refreshBarter(); });
  $("btLevel").addEventListener("change", (e) => { btState.maxLevel = +e.target.value || 0; btState.shown = 60; refreshBarter(); });
  $("btRank").addEventListener("change", (e) => { btState.rank = e.target.value; btState.shown = 60; refreshBarter(); });
  $("btPure").addEventListener("change", (e) => { btState.pure = e.target.checked; btState.shown = 60; refreshBarter(); });
  $("btQ").addEventListener("input", (e) => {
    clearTimeout(btTimer);
    btTimer = setTimeout(() => { btState.q = e.target.value.trim(); btState.shown = 60; refreshBarter(); }, 250);
  });
  // «выбрать всё» — тоггл по отфильтрованному набору: есть выбранное → снять,
  // иначе выбрать всё (не только показанную страницу)
  $("btSelAll").addEventListener("click", () => {
    if (btLastRows.some((r) => btSel.has(r.id)))
      btLastRows.forEach((r) => btSel.delete(r.id));
    else
      btLastRows.slice(0, 300).forEach((r) => btSel.set(r.id, 1));
    btSelSave();
    btSelSync();
  });
  $("btSelClear").addEventListener("click", () => {
    btSel.clear();
    btSelSave();
    btSelSync();
  });
  $("btSelCalc").addEventListener("click", openBasketModal);
  btSelBar();
}

// ---------- корзина: галочки в списке + плавающая панель итога ----------
function wireBtSel() {
  page.querySelectorAll(".bt-selbox").forEach((cb) => {
    cb.addEventListener("click", (e) => e.stopPropagation());  // не открывать модал строки
    cb.addEventListener("change", () => {
      if (cb.checked) btSel.set(cb.dataset.id, btSel.get(cb.dataset.id) || 1);
      else btSel.delete(cb.dataset.id);
      btSelSave();
      btSelBar();
    });
  });
}

function btSelSync() {
  // галочки видимых строк + панель — под текущее состояние корзины
  page.querySelectorAll(".bt-selbox").forEach((cb) => { cb.checked = btSel.has(cb.dataset.id); });
  btSelBar();
}

function btSelBar() {
  const bar = $("btSelBar");
  if (!bar) return;
  bar.classList.toggle("hidden", !btSel.size);
  const n = $("btSelN");
  if (n) n.textContent = btSel.size;
  const all = $("btSelAll");
  if (all) all.textContent = btLastRows.some((r) => btSel.has(r.id))
    ? "СНЯТЬ ВЫБОР" : `ВЫБРАТЬ ВСЁ (${btLastRows.length})`;
}

function wireBtRows(open) {
  // клик по строке раздела открывает модал СВОЕГО раздела (не карточку крафта)
  page.querySelectorAll(".brt-row[data-id]").forEach((r) =>
    r.addEventListener("click", () => { open(r.dataset.id); }));
}

// ---------- модал корзины: итог по выбранным бартерам ----------
async function openBasketModal() {
  if (!btSel.size) return;
  gModalOpen(`<div class="spinner">// СЧИТАЕМ КОРЗИНУ</div>`);
  let d;
  try {
    d = await fetch(api("/barter/basket"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: [...btSel].map(([id, qty]) => ({ id, qty })) }),
    }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
  } catch (e) {
    $("gModalBody").innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
    return;
  }
  const nBarter = d.items.filter((it) => !it.no_barter).reduce((s, it) => s + it.qty, 0);
  const itemRows = d.items.map((it) => {
    const cost = it.no_barter ? `<span class="bt-farm">НЕТ БАРТЕРА</span>`
      : it.cost != null ? `${fmt(it.cost)} ₽`
      : (it.cost_partial ? `${fmt(it.cost_partial)} ₽ + ФАРМ` : `<span class="bt-farm">ФАРМ</span>`);
    const cur = !it.no_barter && it.currency !== "money" && it.money
      ? `<span class="bt-cur">${fmt(it.money * it.qty)} ${CUR_RU[it.currency] || it.currency.toUpperCase()}</span>` : "";
    const missing = (it.missing || []).length
      ? `<span class="bt-miss" title="${escapeHtml(it.missing.join(", "))}">+${it.missing.length} ФАРМ</span>` : "";
    const place = it.no_barter ? "—"
      : `${escapeHtml(it.settlement_name)}${it.level ? ` <span class="lv">УР.${it.level}</span>` : ""}`;
    return `<tr>
      <td><div class="bt-item"><img loading="lazy" src="${asset(it.icon)}" alt="">
        <span class="nm ilink" data-id="${it.id}" style="color:${rank(it.color).color}">${escapeHtml(it.name)}</span>${missing}${cur}</div></td>
      <td class="r"><span class="bk-qty">
        <button class="bk-dec" data-id="${it.id}" title="Меньше">−</button><b>${it.qty}</b>
        <button class="bk-inc" data-id="${it.id}" title="Больше">+</button>
        <button class="bk-del" data-id="${it.id}" title="Убрать из корзины">✕</button></span></td>
      <td class="bt-place">${place}</td>
      <td class="r">${cost}</td></tr>`;
  }).join("");
  const resRows = (d.resources || []).map((r) => {
    // не с аука напрямую — закупаются родители и разбираются (цена уже это учитывает)
    const dz = r.disasm ? `<div class="bk-note">= ${fmt(r.disasm.blocks)}× ${escapeHtml(r.disasm.parent_name)} С АУКА (В КАЖДОМ ${r.disasm.count} ШТ)</div>` : "";
    const ob = r.obmen
      ? `${fmt(r.obmen.coins_total)} МОНЕТ${r.obmen.over_limit ? `<div class="bk-note">ЛИМИТ ${fmt(r.obmen.limit)} ПОКУПОК</div>` : ""}`
      : `<span class="bk-dim">—</span>`;
    const price = r.farm && !r.cost ? '<span class="bt-farm">ФАРМ</span>' : `${fmt(r.cost)} ₽${dz}`;
    return `<tr class="brt-row" data-id="${r.id}">
      <td><div class="bt-item"><img loading="lazy" src="${asset(r.icon)}" alt="">
        <span class="nm" style="color:${rank(r.color).color}">${escapeHtml(r.name)}</span></div></td>
      <td class="r">${fmt(r.amount)}</td>
      <td class="r">${ob}</td>
      <td class="r">${price}</td></tr>`;
  }).join("");
  const moneyRows = (d.money || []).map((m) => `<tr>
      <td><div class="bt-item"><span class="nm">ДЕНЬГИ ТОРГОВЦАМ · ${escapeHtml((m.name || m.currency).toUpperCase())}</span></div></td>
      <td class="r"></td><td class="r"></td>
      <td class="r">${fmt(m.amount)} ${m.currency === "money" ? "₽" : (CUR_RU[m.currency] || "")}</td></tr>`).join("");
  const foreign = (d.money || []).filter((m) => m.currency !== "money");
  $("gModalBody").innerHTML = `
    <div class="gm-head">
      <div class="gm-title">КОРЗИНА БАРТЕРОВ · ${nBarter} ${nBarter === 1 ? "ОБМЕН" : nBarter < 5 ? "ОБМЕНА" : "ОБМЕНОВ"}</div>
    </div>
    <div class="reqs-lbl">ЗАКУПКА РЕСУРСОВ · ВСЕГО ПО КОРЗИНЕ</div>
    <div class="bt-wrap"><table class="bt-table bk-res-tbl">
      <thead><tr><th style="width:42%">РЕСУРС</th><th class="r" style="width:14%">КОЛ-ВО</th>
        <th class="r" style="width:20%">В ОБМЕНКАХ</th><th class="r" style="width:24%">ЦЕНА (АУК)</th></tr></thead>
      <tbody>${resRows || ""}${moneyRows}${!resRows && !moneyRows ? `<tr><td colspan="4" class="empty-sm">НЕЧЕГО ЗАКУПАТЬ.</td></tr>` : ""}</tbody>
    </table></div>
    <div class="chain-total">ИТОГО (РЕСУРСЫ + ДЕНЬГИ): <b>${fmt(d.total)} ₽</b>${foreign.map((m) => ` + <b>${fmt(m.amount)} ${CUR_RU[m.currency] || m.currency.toUpperCase()}</b>`).join("")}${d.has_farm ? ` <span class="bt-farm">+ ФАРМ-ВХОДЫ (НЕТ НА АУКЕ)</span>` : ""}</div>
    <div class="reqs-lbl">ЧТО ПОЛУЧАЕШЬ · ${d.items.length} · ЛУЧШИЙ ОФФЕР НА ПРЕДМЕТ, КЛИК ПО НАЗВАНИЮ — ДОСЬЕ ОБМЕНА</div>
    <div class="bt-wrap"><table class="bt-table bk-tbl">
      <thead><tr><th style="width:42%">ПРЕДМЕТ</th><th class="r" style="width:18%">КОЛ-ВО</th>
        <th style="width:22%">ГДЕ</th><th class="r" style="width:18%">СТОИМОСТЬ</th></tr></thead>
      <tbody>${itemRows}</tbody>
    </table></div>`;
  const upd = (id, delta) => {
    const q = (btSel.get(id) || 1) + delta;
    if (q < 1) return;
    btSel.set(id, Math.min(99, q));
    btSelSave();
    openBasketModal();  // перечёт с сервера
  };
  $("gModalBody").querySelectorAll(".bk-inc").forEach((b) => b.addEventListener("click", () => upd(b.dataset.id, 1)));
  $("gModalBody").querySelectorAll(".bk-dec").forEach((b) => b.addEventListener("click", () => upd(b.dataset.id, -1)));
  $("gModalBody").querySelectorAll(".bk-del").forEach((b) => b.addEventListener("click", () => {
    btSel.delete(b.dataset.id);
    btSelSave();
    btSelSync();
    if (btSel.size) openBasketModal(); else gModalClose();
  }));
  $("gModalBody").querySelectorAll(".ilink[data-id], .brt-row[data-id]").forEach((el) =>
    el.addEventListener("click", () => { openBarterModal(el.dataset.id); }));
}

// ---------- модал бартера: все способы обмена предмета ----------
async function openBarterModal(id) {
  gModalOpen(`<div class="spinner">// БАРТЕР-ДОСЬЕ</div>`);
  let d;
  try {
    d = await fetch(api(`/barter/item/${id}`)).then((r) => r.json());
  } catch (e) {
    $("gModalBody").innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
    return;
  }
  const it = d.item;
  const best = d.ways[0] && d.ways[0].offers[0];
  const stats = [];
  if (d.buy_price != null) stats.push(`КУПИТЬ НА АУКЕ: <b>${fmt(d.buy_price)} ₽</b>`);
  if (d.sell_net != null)
    stats.push(`ПРОДАЖА~ (НЕТТО): <b>${fmt(d.sell_net)} ₽</b>${d.sell_basis === "buyout" ? " <span class='unit'>ПО ВЫКУПУ</span>" : ""}`);
  if (best && best.cost != null) {
    stats.push(`ЛУЧШИЙ БАРТЕР: <b>${fmt(best.cost)} ₽</b>`);
    if (d.buy_price != null)
      stats.push(best.cost < d.buy_price
        ? `<span class="pct up">БАРТЕР ВЫГОДНЕЕ АУКА НА ${fmt(d.buy_price - best.cost)} ₽</span>`
        : `<span class="pct down">АУК ДЕШЕВЛЕ НА ${fmt(best.cost - d.buy_price)} ₽</span>`);
  }
  const ways = d.ways.map((w) => `<div class="bt-way">
    <div class="bt-way-head">${escapeHtml(w.settlement_name)}${w.level ? ` <span class="lv">УР.${w.level}</span>` : ""}</div>
    ${w.offers.map((o) => btOfferHtml(o)).join("")}</div>`).join("");
  const used = (d.used_in || []).length ? `<div class="reqs-sec">
      <div class="reqs-lbl">СДАЁТСЯ В БАРТЕР ДЛЯ · ${d.used_in.length}</div>
      <div class="use-list">${d.used_in.map((u) => `<div class="use-row" data-id="${u.id}">
        <img loading="lazy" src="${asset(u.icon)}" alt=""><span class="nm">${escapeHtml(u.name)}</span></div>`).join("")}</div>
    </div>` : "";
  // полная лестница тиров + калькулятор ресурсов между звеньями
  btChain = { nodes: d.chain || [], idx: d.chain_idx || 0,
              from: 0, to: d.chain_idx || 0 };
  $("gModalBody").innerHTML = `
    <div class="gm-head">
      <img src="${asset(it.icon)}" alt="">
      <div class="gm-title" style="color:${rank(it.color).color}">${escapeHtml(it.name)}</div>
      <a class="mk-card" href="/item/${it.id}">ПОЛНАЯ КАРТОЧКА ▸</a>
    </div>
    ${stats.length ? `<div class="gm-stats">${stats.join(" · ")}</div>` : ""}
    ${chainBlock(it.id)}
    ${ways ? `<div class="reqs-lbl">ГДЕ МЕНЯЕТСЯ · ${d.ways.length} · НУЖНЫЕ РЕСУРСЫ И ЦЕНЫ</div>${ways}`
           : `<div class="empty-sm">ПРЯМЫХ БАРТЕРОВ НА ЭТОТ ПРЕДМЕТ НЕТ.</div>`}
    ${used}`;
  wireChain();
  // клики внутри — остаёмся в бартер-контексте
  $("gModalBody").querySelectorAll(".ilink[data-id], .use-row[data-id]").forEach((el) =>
    el.addEventListener("click", () => { openBarterModal(el.dataset.id); }));
}

// ---------- лестница тиров + калькулятор ресурсов между звеньями ----------
let btChain = { nodes: [], idx: 0, from: 0, to: 0 };

function chainBlock(currentId) {
  const n = btChain.nodes;
  if (n.length < 2) return "";  // одиночный предмет — лестницы нет
  const chips = n.map((node, i) =>
    `${i ? '<span class="chain-arr">→</span>' : ""}<span class="chain-chip${node.id === currentId ? " this" : ""}" data-id="${node.id}" style="color:${rank(node.color).color}">
      <img loading="lazy" src="${asset(node.icon)}" alt="">${escapeHtml(node.name)}</span>`).join("");
  const opts = (sel) => n.map((node, i) =>
    `<option value="${i}" ${i === sel ? "selected" : ""}>${i + 1}. ${escapeHtml(node.name)}</option>`).join("");
  return `<div class="gm-chain">
    <div class="reqs-lbl">ЦЕПОЧКА ОБМЕНОВ · ${n.length} ${n.length < 5 ? "ТИРА" : "ТИРОВ"} (СДАЁШЬ ЛЕВЫЙ → ПОЛУЧАЕШЬ ПРАВЫЙ)</div>
    <div class="gm-chain-row">${chips}</div>
    <div class="chain-calc">
      <div class="chain-calc-ctl">СКОЛЬКО РЕСУРСОВ ОТ
        <select id="chFrom">${opts(btChain.from)}</select> ДО
        <select id="chTo">${opts(btChain.to)}</select></div>
      <div id="chainCalcOut"></div>
    </div></div>`;
}

function wireChain() {
  const f = $("chFrom"), t = $("chTo");
  if (!f || !t) return;
  const upd = () => { btChain.from = +f.value; btChain.to = +t.value; chainCompute(); };
  f.addEventListener("change", upd);
  t.addEventListener("change", upd);
  $("gModalBody").querySelectorAll(".chain-chip[data-id]").forEach((el) =>
    el.addEventListener("click", () => { openBarterModal(el.dataset.id); }));
  chainCompute();
}

function chainCompute() {
  const out = $("chainCalcOut");
  if (!out) return;
  const n = btChain.nodes, from = btChain.from, to = btChain.to;
  if (from >= to) {
    out.innerHTML = `<div class="empty-sm">ВЫБЕРИ ЗВЕНО «ОТ» ЛЕВЕЕ, ЧЕМ «ДО» — СЧИТАЕМ ПУТЬ СНИЗУ ВВЕРХ.</div>`;
    return;
  }
  const agg = {}; let money = 0, cost = 0, hasFarm = false;
  for (let i = from + 1; i <= to; i++) {
    const st = n[i].step;
    if (!st) continue;
    money += st.money || 0;
    for (const r of st.resources) {
      const a = agg[r.id] || (agg[r.id] = { ...r, amount: 0, cost: 0, farm: false });
      a.amount += r.amount;
      if (r.line_cost != null) { a.cost += r.line_cost; cost += r.line_cost; }
      if (r.source === "farm" || r.line_cost == null) { a.farm = true; hasFarm = true; }
    }
  }
  const rows = Object.values(agg).sort((a, b) => (b.cost || 0) - (a.cost || 0)).map((r) =>
    `<tr class="brt-row" data-id="${r.id}"><td><div class="bt-item">
       <img loading="lazy" src="${asset(r.icon)}" alt=""><span class="nm" style="color:${rank(r.color).color}">${escapeHtml(r.name)}</span></div></td>
     <td class="r">${fmt(r.amount)}</td>
     <td class="r">${r.farm && !r.cost ? '<span class="bt-farm">ФАРМ</span>' : fmt(r.cost) + " ₽"}</td></tr>`).join("");
  out.innerHTML = `
    <div class="chain-sum">ОТ <b>${escapeHtml(n[from].name)}</b> ДО <b>${escapeHtml(n[to].name)}</b>:
      нужен <b>1× ${escapeHtml(n[from].name)}</b> (стартовый) + ресурсы ниже${money ? ` + доплата <b>${fmt(money)} ₽</b>` : ""}</div>
    <div class="bt-wrap"><table class="bt-table chain-tbl">
      <thead><tr><th style="width:60%">РЕСУРС · ВСЕГО ПО ПУТИ</th><th class="r" style="width:20%">КОЛ-ВО</th><th class="r" style="width:20%">ЦЕНА</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="3" class="empty-sm">ТОЛЬКО ТРЕЙД-ИН, ДОП. РЕСУРСОВ НЕТ.</td></tr>`}</tbody>
    </table></div>
    <div class="chain-total">ИТОГО ЗАКУПКА РЕСУРСОВ${money ? " + ДОПЛАТА" : ""}: <b>${fmt(cost + money)} ₽</b>${hasFarm ? ` <span class="bt-farm">+ ФАРМ-ВХОДЫ (НЕТ НА АУКЕ)</span>` : ""}</div>`;
  out.querySelectorAll(".brt-row[data-id]").forEach((el) =>
    el.addEventListener("click", () => { openBarterModal(el.dataset.id); }));
}

// ---------- модал обменки: позиция Перекупщика ----------
function openObmenModal(id) {
  const r = (obmenData && obmenData.positions || []).find((p) => p.id === id);
  if (!r) return;
  const chan = [];
  chan.push(`<div class="bt-ing"><span>ЦЕНА У ПЕРЕКУПЩИКА</span>
    <span class="bt-ing-price"><b>${fmt(r.coins)}</b> МОНЕТ${r.amount > 1 ? ` ЗА ${r.amount} ШТ` : ""}</span></div>`);
  if (r.limit) chan.push(`<div class="bt-ing"><span>ЛИМИТ ПОКУПОК</span><span class="bt-ing-price">${fmt(r.limit)}</span></div>`);
  chan.push(`<div class="bt-ing"><span>СБЫТ НА АУКЕ (−${obmenData.fee_pct}%)</span>
    <span class="bt-ing-price">${r.value_auction != null
      ? `${fmt(r.value_auction)} ₽ <span class="unit">${r.sell_basis === "sales" ? "ПО СДЕЛКАМ" : "ПО ВЫКУПУ"}</span>`
      : "ЦЕНА ГРЕЕТСЯ…"}</span></div>`);
  chan.push(`<div class="bt-ing"><span>СБЫТ СКУПЩИКУ (МГНОВЕННО)</span>
    <span class="bt-ing-price">${r.value_vendor != null ? fmt(r.value_vendor) + " ₽" : "—"}</span></div>`);
  const rateLine = r.rate != null
    ? `<div class="bt-ing bt-total"><span>КУРС (ЛУЧШИЙ КАНАЛ — ${r.basis === "vendor" ? "СКУПЩИК" : "АУКЦИОН"})</span>
        <span class="bt-ing-price"><span class="pct ${r.rate >= 1 ? "up" : "down"}">${r.rate.toLocaleString("ru-RU")} ₽/МОНЕТА</span></span></div>` : "";
  gModalOpen(`
    <div class="gm-head">
      <img src="${asset(r.icon)}" alt="">
      <div class="gm-title" style="color:${rank(r.color).color}">${escapeHtml(r.name)}</div>
      <a class="mk-card" href="/item/${r.id}">ПОЛНАЯ КАРТОЧКА ▸</a>
    </div>
    <div class="bt-offer gm-offer">${chan.join("")}${rateLine}</div>
    <div id="gmBarterUse"></div>`);
  // связка с бартером: где этот ресурс сдаётся (подгружаем тихо)
  fetch(api(`/barter/item/${id}`)).then((x) => x.json()).then((d) => {
    const box = $("gmBarterUse");
    if (!box || !(d.used_in || []).length) return;
    box.innerHTML = `<div class="reqs-sec">
      <div class="reqs-lbl">НУЖЕН ДЛЯ БАРТЕРОВ · ${d.used_in.length}</div>
      <div class="use-list">${d.used_in.map((u) => `<div class="use-row" data-id="${u.id}">
        <img loading="lazy" src="${asset(u.icon)}" alt=""><span class="nm">${escapeHtml(u.name)}</span></div>`).join("")}</div></div>`;
    box.querySelectorAll(".use-row[data-id]").forEach((el) =>
      el.addEventListener("click", () => { openBarterModal(el.dataset.id); }));
  }).catch(() => {});
}

// ---------- бартер в карточке предмета ----------
function btOfferHtml(o, level) {
  const inputs = o.inputs.map((i) => {
    const via = i.via ? ` <span class="bt-via">← бартер: ${escapeHtml(i.via.settlement_name)}${i.via.level ? ` ур.${i.via.level}` : ""} за ${fmt(i.via.cost)} ₽</span>` : "";
    const disasm = i.disasm ? ` <span class="bt-via">← разбор: ${i.disasm.count}× из «${escapeHtml(i.disasm.parent_name)}» (${fmt(i.disasm.parent_unit)} ₽ на ауке)</span>` : "";
    const price = i.source === "farm" ? `<span class="bt-farm">ФАРМ</span>`
      : `${fmt(i.line_cost)} ₽${i.amount > 1 ? ` <span class="unit">(${fmt(i.unit_price)}/ШТ)</span>` : ""}`;
    return `<div class="bt-ing"><span class="ilink" data-id="${i.id}">
      <img loading="lazy" src="${asset(i.icon)}" alt="">${i.amount}× ${escapeHtml(i.name)}</span>
      <span class="bt-ing-price">${price}${via}${disasm}</span></div>`;
  }).join("");
  const money = o.money ? `<div class="bt-ing"><span>ДОПЛАТА ТОРГОВЦУ</span>
    <span class="bt-ing-price">${fmt(o.money)} ${CUR_RU[o.currency] || o.currency.toUpperCase()}</span></div>` : "";
  const total = o.cost != null ? `${fmt(o.cost)} ₽`
    : (o.cost_partial ? `${fmt(o.cost_partial)} ₽ + ФАРМ` : "ФАРМ");
  return `<div class="bt-offer">${inputs}${money}
    <div class="bt-ing bt-total"><span>ИТОГО</span><span class="bt-ing-price">${total}</span></div></div>`;
}

async function loadBarterBlocks(id) {
  let d;
  try {
    d = await fetch(api(`/barter/item/${id}`)).then((r) => r.json());
  } catch (e) { return; }
  const box = $("barterBlocks");
  if (!box || !d) return;
  let html = "";
  if (d.ways && d.ways.length) {
    const ways = d.ways.map((w) => {
      const offers = w.offers.map((o) => btOfferHtml(o, w.level)).join("");
      return `<div class="bt-way">
        <div class="bt-way-head">${escapeHtml(w.settlement_name)}${w.level ? ` <span class="lv">УР.${w.level}</span>` : ""}</div>
        ${offers}</div>`;
    }).join("");
    const best = d.ways[0] && d.ways[0].offers[0];
    const vs = best && best.cost != null && d.buy_price != null
      ? (best.cost < d.buy_price
         ? ` · БАРТЕР ДЕШЕВЛЕ АУКА НА ${fmt(d.buy_price - best.cost)} ₽`
         : ` · НА АУКЕ ДЕШЕВЛЕ НА ${fmt(best.cost - d.buy_price)} ₽`) : "";
    html += `<div class="reqs-sec bt-block">
      <div class="reqs-lbl">ПОЛУЧАЕТСЯ БАРТЕРОМ · ${d.ways.length} ${d.ways.length === 1 ? "ПОСЕЛЕНИЕ" : "ПОСЕЛЕНИЙ"}${vs}</div>
      ${ways}</div>`;
  }
  if (d.used_in && d.used_in.length) {
    const rows = d.used_in.map((u) => `<div class="use-row" data-id="${u.id}">
      <img loading="lazy" src="${asset(u.icon)}" alt=""><span class="nm">${escapeHtml(u.name)}</span></div>`).join("");
    html += `<div class="reqs-sec bt-block">
      <div class="reqs-lbl">СДАЁТСЯ В БАРТЕР ДЛЯ · ${d.used_in.length}</div>
      <div class="use-list">${rows}</div></div>`;
  }
  if (!html) { box.remove(); return; }
  box.innerHTML = html;
  box.querySelectorAll(".ilink[data-id], .use-row[data-id]").forEach((el) =>
    el.addEventListener("click", () => { navigate(`/item/${el.dataset.id}`); }));
}

// ---------- патчноуты игры ----------
let patchOffset = 0;

const fmtPatchDate = (iso) => {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString("ru-RU",
    { day: "2-digit", month: "long", year: "numeric" });
};

async function openPatches() {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА ПАТЧНОУТОВ</div>`;
  window.scrollTo(0, 0);
  patchOffset = 0;
  let d;
  try {
    d = await fetch(api("/patches?limit=20")).then((r) => r.json());
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
    return;
  }
  if (location.pathname !== "/patches") return;
  page.innerHTML = `<div class="btmod">
    <div class="section-head">
      <div class="section-title">▸ ПАТЧИ · ОБНОВЛЕНИЯ ИГРЫ</div>
      <div class="section-note">${d.total ? `${d.total} ПАТЧНОУТОВ · ИСТОЧНИК — ФОРУМ EXBO` : "СИНХРОНИЗАЦИЯ С ФОРУМОМ EXBO…"}</div>
    </div>
    <div id="patchList" class="patch-list"></div>
    <button id="patchMore" class="bt-more hidden">ПОКАЗАТЬ ЕЩЁ</button>
  </div>`;
  if (!d.total) {
    $("patchList").innerHTML = `<div class="empty-sm">ПАТЧНОУТЫ ЕЩЁ СКАЧИВАЮТСЯ С ФОРУМА — ЗАГЛЯНИ ЧЕРЕЗ ПАРУ МИНУТ.</div>`;
    return;
  }
  appendPatches(d);
  $("patchMore").addEventListener("click", async () => {
    const more = await fetch(api(`/patches?limit=20&offset=${patchOffset}`))
      .then((r) => r.json()).catch(() => null);
    if (more) appendPatches(more);
  });
}

function appendPatches(d) {
  const box = $("patchList");
  if (!box) return;
  box.insertAdjacentHTML("beforeend", d.items.map((p) => `
    <a class="patch-row" href="/patches/${p.id}">
      <div class="patch-row-t">${escapeHtml(p.title)}</div>
      <div class="patch-row-d">${fmtPatchDate(p.created_at)}</div>
      <div class="patch-row-a">${escapeHtml(p.anons || "")}</div>
    </a>`).join(""));
  patchOffset += d.items.length;
  $("patchMore").classList.toggle("hidden", patchOffset >= d.total);
}

async function openPatch(pid) {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА ПАТЧА</div>`;
  window.scrollTo(0, 0);
  let p;
  try {
    const r = await fetch(api(`/patches/${pid}`));
    if (!r.ok) throw new Error();
    p = await r.json();
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] ПАТЧ НЕ НАЙДЕН</div>`;
    return;
  }
  if (location.pathname !== `/patches/${pid}`) return;
  page.innerHTML = `<div class="btmod">
    <button class="back" id="patchBack">◂ ВСЕ ПАТЧИ</button>
    <article class="patch-article">
      <h1>${escapeHtml(p.title)}</h1>
      <div class="patch-meta">${fmtPatchDate(p.created_at)} ·
        <a href="${escapeHtml(p.source_url)}" target="_blank" rel="noopener">ОРИГИНАЛ НА ФОРУМЕ EXBO ↗</a></div>
      <div class="patch-body">${p.html}</div>
    </article>
    <div id="comments"></div>
  </div>`;
  $("patchBack").addEventListener("click", () => { navigate("/patches"); });
  renderComments(`patch:${pid}`);
}

// ---------- гайды (авторские статьи; тело в стиле патчей) ----------
const guideTags = (tags) => (tags && tags.length)
  ? `<div class="guide-tags">${tags.map((t) => `<span class="guide-tag">${escapeHtml(t)}</span>`).join("")}</div>`
  : "";

async function openGuides() {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА ГАЙДОВ</div>`;
  window.scrollTo(0, 0);
  let d;
  try {
    d = await fetch(api("/guides")).then((r) => r.json());
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
    return;
  }
  if (location.pathname !== "/guides") return;
  const cards = (d.items || []).map((g) => `
    <a class="guide-card" href="/guides/${g.slug}">
      ${g.cover ? `<img class="guide-cover" loading="lazy" src="${escapeHtml(g.cover)}" alt="">` : ""}
      <div class="guide-card-b">
        <div class="guide-card-t">${escapeHtml(g.title)}</div>
        <div class="guide-card-d">${fmtPatchDate(g.created_at)}</div>
        <div class="guide-card-a">${escapeHtml(g.description || "")}</div>
        ${guideTags(g.tags)}
      </div>
    </a>`).join("");
  page.innerHTML = `<div class="btmod">
    <div class="section-head">
      <div class="section-title">▸ ГАЙДЫ · РАЗБОРЫ ПО ИГРЕ</div>
      <div class="section-note">ЗАДАНИЯ · КРАФТ · ЭКОНОМИКА · СНАРЯЖЕНИЕ · СОБЫТИЯ</div>
    </div>
    <div class="guide-list">${cards || `<div class="empty-sm">ГАЙДОВ ПОКА НЕТ — СКОРО ПОЯВЯТСЯ.</div>`}</div>
  </div>`;
}

async function openGuide(slug) {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА ГАЙДА</div>`;
  window.scrollTo(0, 0);
  let g;
  try {
    const r = await fetch(api(`/guides/${encodeURIComponent(slug)}`));
    if (!r.ok) throw new Error();
    g = await r.json();
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] ГАЙД НЕ НАЙДЕН</div>`;
    return;
  }
  if (location.pathname !== `/guides/${slug}`) return;
  page.innerHTML = `<div class="btmod">
    <button class="back" id="guideBack">◂ ВСЕ ГАЙДЫ</button>
    <article class="patch-article guide-article">
      ${guideTags(g.tags)}
      <h1>${escapeHtml(g.title)}</h1>
      <div class="patch-meta">${fmtPatchDate(g.created_at)} · ГАЙД · STALZONE (STALCRAFT)</div>
      <div class="patch-body">${g.html}</div>
    </article>
    <div id="comments"></div>
  </div>`;
  $("guideBack").addEventListener("click", () => { navigate("/guides"); });
  renderComments(`guide:${slug}`);
}

// ---------- комментарии под статьями ----------
async function renderComments(pageKey) {
  const host = $("comments");
  if (!host) return;
  let d;
  try {
    d = await fetch(api(`/comments?page=${encodeURIComponent(pageKey)}`)).then((r) => r.json());
  } catch (e) { return; }
  const authed = ME && ME.authenticated;
  const myLogin = authed ? (ME.user.display_login || ME.user.login) : null;
  const rows = (d.comments || []).map((c) => `
    <div class="cmt" data-id="${c.id}">
      <div class="cmt-head"><span class="cmt-login">${escapeHtml(c.login)}</span>
        <span class="cmt-ts">${new Date(c.ts * 1000).toLocaleString("ru-RU",
          { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</span>
        ${authed && c.login === myLogin ? `<button class="cmt-del" data-id="${c.id}" title="Удалить">✕</button>` : ""}
      </div>
      <div class="cmt-text">${escapeHtml(c.text)}</div>
    </div>`).join("");
  const form = authed
    ? `<div class="cmt-form">
        <textarea id="cmtText" rows="3" maxlength="2000" placeholder="НАПИСАТЬ КОММЕНТАРИЙ…"></textarea>
        <button id="cmtSend" class="bt-more" style="margin:6px 0 0">ОТПРАВИТЬ</button>
        <div id="cmtErr" class="cmt-err"></div></div>`
    : (ME && ME.auth_enabled
       ? `<div class="cmt-cta">ЧТОБЫ КОММЕНТИРОВАТЬ — <a class="js-open-auth" href="${BASE}/auth/login">ВОЙДИ ИЛИ ЗАРЕГИСТРИРУЙСЯ</a>.</div>`
       : "");
  host.innerHTML = `<div class="cmt-box">
    <div class="reqs-lbl">КОММЕНТАРИИ · ${(d.comments || []).length}</div>
    ${rows || `<div class="empty-sm">ПОКА ПУСТО — БУДЬ ПЕРВЫМ.</div>`}
    ${form}</div>`;
  const send = $("cmtSend");
  if (send) send.addEventListener("click", async () => {
    const text = $("cmtText").value.trim();
    if (!text) return;
    send.disabled = true;
    try {
      const r = await fetch(api("/comments"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page: pageKey, text }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        $("cmtErr").textContent = err.detail || "ОШИБКА ОТПРАВКИ";
        return;
      }
      renderComments(pageKey);
    } finally { send.disabled = false; }
  });
  host.querySelectorAll(".cmt-del").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Удалить комментарий?")) return;
    await fetch(api(`/comments/${b.dataset.id}`), { method: "DELETE" }).catch(() => {});
    renderComments(pageKey);
  }));
}

// ---------- квесты: блок-схемы линеек (сталкеры/бандиты/группировки) ----------
// Данные — /api/quests (мета) + /api/quests/{id} (прохождение). Раскладка
// автоматическая: уровень = длина цепочки родителей, стрелки — SVG-безье.
let questData = null;                                  // кэш ответа /api/quests
let questFaction = localStorage.getItem("sz_quest_f") || "stalkers";
let qmMapCleanup = null;                               // Leaflet-миникарта модала
let qmEpoch = 0;                                       // гонки: модал переоткрыли/закрыли

const questFactionOf = (id) =>
  (questData && questData.factions.find((f) => f.id === id))
  || { id, name: id, color: "#7ce68e" };

async function openQuests(selId) {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА КВЕСТОВ</div>`;
  window.scrollTo(0, 0);
  let d;
  try {
    d = await fetch(api("/quests")).then((r) => r.json());
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
    return;
  }
  if (!location.pathname.startsWith("/quests")) return;
  questData = d;
  if (selId != null) {          // диплинк /quests/{id} — открыть нужную линейку
    const q = d.items.find((x) => x.id === selId);
    if (q) questFaction = q.faction;
  }
  if (!d.factions.some((f) => f.id === questFaction)) questFaction = d.factions[0].id;
  renderQuests();
  if (selId != null) openQuestModal(selId);
}

function renderQuests() {
  const d = questData;
  const tabs = d.factions.map((f) => {
    const n = d.items.filter((q) => q.faction === f.id).length;
    return `<button class="qst-tab${f.id === questFaction ? " on" : ""}" data-f="${f.id}"
      style="--fc:${f.color}">${escapeHtml(f.name.toUpperCase())}${n ? ` <span>${n}</span>` : ""}</button>`;
  }).join("");
  page.innerHTML = `<div class="btmod">
    <div class="section-head">
      <div class="section-title">▸ КВЕСТЫ · СХЕМЫ ЛИНЕЕК</div>
      <div class="section-note">КЛИК ПО КВЕСТУ — ПРОХОЖДЕНИЕ, НАГРАДА И ТОЧКИ НА КАРТЕ</div>
    </div>
    <div class="qst-tabs">${tabs}</div>
    <div class="qst-wrap" id="qstWrap"></div>
    <div class="map-legend">Стрелка — «открывается после». Блоки с
      <b style="color:var(--amber)">янтарной</b> рамкой — основная линейка, серые — побочные.
      📍 — у квеста есть точки на карте.${d.is_admin ? " Пунктирные — черновики (видны только админам)." : ""}</div>
  </div>`;
  page.querySelectorAll(".qst-tab").forEach((b) => b.addEventListener("click", () => {
    questFaction = b.dataset.f;
    localStorage.setItem("sz_quest_f", questFaction);
    renderQuests();
  }));
  renderQuestChart(d.items.filter((q) => q.faction === questFaction));
}

function renderQuestChart(items) {
  const wrap = $("qstWrap");
  if (!items.length) {
    wrap.innerHTML = `<div class="empty-sm" style="padding:24px 10px">ЛИНЕЙКА ЕЩЁ ЗАПОЛНЯЕТСЯ — КВЕСТЫ ПОЯВЯТСЯ ПОЗЖЕ.</div>`;
    return;
  }
  const byId = new Map(items.map((q) => [q.id, q]));
  // уровень (колонка) = самая длинная цепочка родителей внутри линейки
  const level = new Map();
  const lvl = (q, stack) => {
    if (level.has(q.id)) return level.get(q.id);
    if (stack.has(q.id)) return 0;                    // защита от цикла в данных
    stack.add(q.id);
    const ps = (q.parents || []).filter((p) => byId.has(p));
    const l = ps.length ? Math.max(...ps.map((p) => lvl(byId.get(p), stack))) + 1 : 0;
    stack.delete(q.id);
    level.set(q.id, l);
    return l;
  };
  items.forEach((q) => lvl(q, new Set()));
  // строка внутри колонки: sort админа, потом ближе к родителям, основные выше
  const cols = [];
  items.forEach((q) => (cols[level.get(q.id)] ||= []).push(q));
  const row = new Map();
  cols.forEach((col) => {
    const pr = (q) => {
      const ps = (q.parents || []).filter((p) => row.has(p));
      return ps.length ? ps.reduce((s, p) => s + row.get(p), 0) / ps.length : 1e9;
    };
    col.sort((a, b) => (a.sort - b.sort) || (pr(a) - pr(b))
      || (a.kind === "main" ? 0 : 1) - (b.kind === "main" ? 0 : 1) || (a.id - b.id));
    col.forEach((q, i) => row.set(q.id, i));
  });

  const W = 190, H = 72, GX = 90, GY = 20, PAD = 10;
  const pos = (q) => ({ x: PAD + level.get(q.id) * (W + GX),
                        y: PAD + row.get(q.id) * (H + GY) });
  const cw = PAD * 2 + cols.length * (W + GX) - GX;
  const ch = PAD * 2 + Math.max(...cols.map((c) => c.length)) * (H + GY) - GY;

  let edges = "";
  items.forEach((q) => (q.parents || []).forEach((pid) => {
    if (!byId.has(pid)) return;
    const a = pos(byId.get(pid)), b = pos(q);
    const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
    const mx = (x1 + x2) / 2;
    edges += `<path d="M${x1} ${y1} C${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}"
      class="qst-edge${q.kind === "side" ? " is-side" : ""}"/>
      <circle cx="${x2}" cy="${y2}" r="2.5" class="qst-dot${q.kind === "side" ? " is-side" : ""}"/>`;
  }));

  const nodes = items.map((q) => {
    const p = pos(q);
    // родители из другой линейки — маленькая метка ⇠ с подсказкой
    const ext = (q.parents || [])
      .filter((pid) => !byId.has(pid))
      .map((pid) => questData.items.find((x) => x.id === pid)).filter(Boolean);
    const extHtml = ext.length
      ? `<div class="qst-ext" title="После: ${escapeHtml(ext.map((x) =>
          `${x.title} (${questFactionOf(x.faction).name})`).join(", "))}">⇠</div>` : "";
    return `<div class="qst-node is-${q.kind}${q.published ? "" : " draft"}" data-id="${q.id}"
      style="left:${p.x}px;top:${p.y}px;width:${W}px;height:${H}px"
      title="${escapeHtml(q.summary || q.title)}">
      <div class="qst-kind">${q.kind === "main" ? "ОСНОВНОЙ" : "ПОБОЧНЫЙ"}${q.published ? "" : " · ЧЕРНОВИК"}</div>
      <div class="qst-name">${escapeHtml(q.title)}</div>
      ${q.has_map ? `<div class="qst-map-i">📍</div>` : ""}${extHtml}
    </div>`;
  }).join("");

  wrap.innerHTML = `<div class="qst-canvas" style="width:${cw}px;height:${ch}px">
    <svg width="${cw}" height="${ch}" viewBox="0 0 ${cw} ${ch}">${edges}</svg>${nodes}</div>`;
  wrap.querySelectorAll(".qst-node").forEach((n) =>
    n.addEventListener("click", () => openQuestModal(+n.dataset.id)));
}

// ---------- модал квеста: прохождение, награда, миникарта с точками ----------
async function openQuestModal(qid) {
  let q;
  try {
    const r = await fetch(api(`/quests/${qid}`));
    if (!r.ok) throw new Error();
    q = await r.json();
  } catch (e) { return; }
  if (!questData || !location.pathname.startsWith("/quests")) return;
  const f = questFactionOf(q.faction);
  const parents = (q.parents || [])
    .map((pid) => questData.items.find((x) => x.id === pid)).filter(Boolean);
  const hasMap = q.map_layer && (q.map_points || []).length;
  gModalOpen(`<div class="qm">
    <div class="qm-badges">
      <span class="qm-badge" style="--fc:${f.color}">${escapeHtml(f.name.toUpperCase())}</span>
      <span class="qm-badge is-${q.kind}">${q.kind === "main" ? "ОСНОВНОЙ КВЕСТ" : "ПОБОЧНЫЙ КВЕСТ"}</span>
      ${q.published ? "" : `<span class="qm-badge draft">ЧЕРНОВИК</span>`}
    </div>
    <h2 class="qm-title">${escapeHtml(q.title)}</h2>
    ${parents.length ? `<div class="qm-after">ОТКРЫВАЕТСЯ ПОСЛЕ: ${parents.map((p) =>
      `<a class="qm-plink" data-id="${p.id}" href="/quests/${p.id}">${escapeHtml(p.title)}</a>`).join(" · ")}</div>` : ""}
    ${q.reward ? `<div class="qm-reward"><span>НАГРАДА</span>${escapeHtml(q.reward)}</div>` : ""}
    <div class="patch-body qm-body">${q.html || `<p style="color:var(--dim)">Прохождение ещё пишется — загляни позже.</p>`}</div>
    ${hasMap ? `<div class="qm-map-h">ТОЧКИ КВЕСТА НА КАРТЕ · наведи на номер</div>
      <div class="qm-map" id="qmMap"></div>` : ""}
    ${questData.is_admin ? `<div class="qm-admin"><a href="/dev/quests?edit=${q.id}">✎ РЕДАКТИРОВАТЬ КВЕСТ</a></div>` : ""}
  </div>`);
  if (location.pathname.startsWith("/quests"))
    history.replaceState(null, "", `/quests/${q.id}`);   // диплинк для шаринга
  const ep = ++qmEpoch;
  gModalCleanup = () => {
    qmEpoch++;
    if (qmMapCleanup) { qmMapCleanup(); qmMapCleanup = null; }
    document.documentElement.classList.remove("on-map");
    if (location.pathname.startsWith("/quests/"))
      history.replaceState(null, "", "/quests");
  };
  $("gModalBody").querySelectorAll(".qm-plink").forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();      // не отдаём SPA-роутеру — просто меняем модал
      openQuestModal(+a.dataset.id);
    }));
  if (hasMap) initQuestModalMap(q, ep);
  ymGoal("quest_open");
}

// Миникарта квеста в модале: тайлы нужного слоя + нумерованные точки.
async function initQuestModalMap(q, ep) {
  try {
    if (!mapMeta) {
      [mapMeta] = await Promise.all([
        fetch(api("/map/meta")).then((r) => r.json()), ensureLeaflet()]);
      MAP_CATS = mapMeta.categories || [];
    } else {
      await ensureLeaflet();
    }
  } catch (e) { return; }
  if (ep !== qmEpoch || !$("qmMap")) return;   // модал уже закрыли/переоткрыли
  const lm = mapMeta[q.map_layer];
  if (!lm) return;
  // десктопный zoom:1.2 сдвигает координаты Leaflet — на время модала снимаем
  document.documentElement.classList.add("on-map");
  const map = L.map("qmMap", {
    crs: L.CRS.Simple, zoomSnap: 0.25, wheelPxPerZoomLevel: 90,
    attributionControl: false, maxBoundsViscosity: 1.0,
  });
  const px = (x, y) => map.unproject([x, y], lm.max_zoom);
  L.tileLayer(asset(lm.tile_url), {
    tileSize: lm.tile_size,
    minNativeZoom: lm.min_zoom, maxNativeZoom: lm.max_zoom,
    bounds: L.latLngBounds(px(0, 0), px(lm.w, lm.h)), noWrap: true,
  }).addTo(map);
  map.setMaxBounds(L.latLngBounds(px(0, 0), px(lm.w, lm.h)));
  map.setMaxZoom(lm.max_zoom);
  (q.map_points || []).forEach((p, i) => {
    const m = L.marker(px(p[0], p[1]), {
      icon: L.divIcon({ className: "", html: `<div class="qm-pt">${i + 1}</div>`,
                        iconSize: [24, 24], iconAnchor: [12, 12] }),
      riseOnHover: true,
    }).addTo(map);
    if (p[2]) m.bindTooltip(`<b>${i + 1}.</b> ${escapeHtml(String(p[2]))}`,
      { direction: "top", className: "mo-tooltip", opacity: 1 });
  });
  const b = L.latLngBounds((q.map_points || []).map((p) => px(p[0], p[1])));
  map.fitBounds(b.pad(0.5), { maxZoom: lm.max_zoom - 1 });
  qmMapCleanup = () => { map.remove(); };
  setTimeout(() => { if (ep === qmEpoch) map.invalidateSize(); }, 60);
}

// ---------- обменки: монеты Перекупщика ----------
let obmenCoins = +(localStorage.getItem("sz_coins") || 0) || "";
let obmenData = null;   // снапшот /api/exchange — данные для модалов позиций

async function openObmen() {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА ОБМЕНОК</div>`;
  window.scrollTo(0, 0);
  let d;
  try {
    d = await fetch(api("/exchange")).then((r) => r.json());
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
    return;
  }
  if (location.pathname !== "/obmen") return;
  obmenData = d;
  renderObmen(d);
}

function obmenRow(r, extra = "") {
  const aucBasis = r.sell_basis === "sales" ? "по сделкам аука, минус комиссия"
                 : r.sell_basis === "buyout" ? "по мин. выкупу, минус комиссия" : "";
  const chip = r.basis ? `<span class="obm-basis ${r.basis}">${r.basis === "vendor" ? "СКУПЩИК" : "АУК"}</span>` : "";
  return `<tr class="brt-row" data-id="${r.id}">
    <td><div class="bt-item"><img loading="lazy" src="${asset(r.icon)}" alt="">
      <span class="nm" style="color:${rank(r.color).color}">${r.amount > 1 ? r.amount + "× " : ""}${escapeHtml(r.name)}</span>
      ${r.note ? `<span class="bt-cur">${escapeHtml(r.note)}</span>` : ""}</div></td>
    <td class="r">${fmt(r.coins)}</td>
    <td class="r" title="${aucBasis}">${r.value_auction != null ? fmt(r.value_auction) + " ₽" : "—"}</td>
    <td class="r" title="мгновенная продажа NPC, без комиссии">${r.value_vendor != null ? fmt(r.value_vendor) + " ₽" : "—"}</td>
    <td class="r">${r.rate != null ? `<span class="pct ${r.rate >= 1 ? "up" : "down"}">${r.rate.toLocaleString("ru-RU")}</span> ${chip}` : "—"}</td>
    ${extra}
  </tr>`;
}

const OBM_HEAD = `<tr><th style="width:38%">ПРЕДМЕТ</th><th class="r" style="width:13%">МОНЕТ</th>
  <th class="r" style="width:16%">АУК~</th><th class="r" style="width:16%">СКУПЩИК</th>
  <th class="r" style="width:17%">₽/МОНЕТА</th></tr>`;
const OBM_PLAN_HEAD = `<tr><th style="width:30%">ПРЕДМЕТ</th><th class="r" style="width:10%">МОНЕТ</th>
  <th class="r" style="width:12%">АУК~</th><th class="r" style="width:12%">СКУПЩИК</th>
  <th class="r" style="width:12%">₽/МОН</th><th class="r" style="width:10%">ПОКУПОК</th>
  <th class="r" style="width:14%">ИТОГО</th></tr>`;

function renderObmen(d) {
  if (d.empty) {
    page.innerHTML = `<div class="btmod">
      <div class="section-head">
        <div class="section-title">▸ ОБМЕНКИ · МОНЕТЫ ПЕРЕКУПЩИКА</div>
        <div class="section-note">ДАННЫЕ ГОТОВЯТСЯ</div>
      </div>
      <div class="obm-about">
        <p><strong>Обменные монеты</strong> — валюта из ивентов, акций и ежедневных наград.
        Потратить их можно только у <strong>Перекупщика</strong> (Бар — Альбатрос, северные
        базы фракций) на бартерные ресурсы и снаряжение.</p>
        <p>Здесь появится курс «рублей за монету» по каждой позиции на живых ценах аукциона:
        что взять за монеты и продать выгоднее всего, и оптимальная корзина под твой запас
        монет. Ассортимент снимается из игры вручную — данные скоро подъедут.</p>
        <p>А пока загляни в <a href="/barter">калькулятор бартера</a> — там 1400+ обменов
        у торговцев поселений с расчётом выгоды.</p>
      </div>
    </div>`;
    return;
  }
  const rows = d.positions.map((r) => obmenRow(r)).join("");
  const topVen = (d.top_vendor || []).length
    ? `<div class="bt-note">ТОП ДЛЯ МГНОВЕННОЙ СДАЧИ СКУПЩИКУ: ${d.top_vendor.map((t) =>
        `<span class="obm-link" data-id="${t.id}">${escapeHtml(t.name)}</span> (${t.rate.toLocaleString("ru-RU")} ₽/МОН)`).join(" · ")}</div>` : "";
  page.innerHTML = `<div class="btmod">
    <div class="section-head">
      <div class="section-title">▸ ОБМЕНКИ · МОНЕТЫ ПЕРЕКУПЩИКА</div>
      <div class="section-note">КУРС = ЛУЧШИЙ СБЫТ: АУК (−${d.fee_pct}%) ИЛИ СКУПЩИК${
        d.updated_at ? ` · АССОРТИМЕНТ ОТ ${new Date(d.updated_at).toLocaleDateString("ru-RU")}` : ""}</div>
    </div>
    <div class="bt-filters">
      <div class="search-box bt-search obm-coins"><div class="search-prompt">◈</div>
        <input id="obmCoins" type="text" inputmode="numeric" autocomplete="off"
               placeholder="СКОЛЬКО У ТЕБЯ МОНЕТ…" value="${obmenCoins ? fmt(obmenCoins) : ""}"></div>
      <button id="obmPlan" class="bt-more" style="margin:0">СОБРАТЬ КОРЗИНУ</button>
    </div>
    ${topVen}
    <div id="obmPlanBox"></div>
    <div class="bt-wrap"><table class="bt-table">
      <thead>${OBM_HEAD}</thead>
      <tbody>${rows}</tbody>
    </table></div>
    <div class="bt-note" style="margin-top:8px">АУК~ — ОЖИДАЕМАЯ ВЫРУЧКА НА АУКЦИОНЕ ПОСЛЕ КОМИССИИ (ПО РЕАЛЬНЫМ СДЕЛКАМ);
      СКУПЩИК — ГАРАНТИРОВАННАЯ МГНОВЕННАЯ ПРОДАЖА NPC. КЛИК ПО СТРОКЕ — ДЕТАЛИ ПОЗИЦИИ.</div>
  </div>`;
  const inp = $("obmCoins");
  wireBudget && wireBudget(inp, (v) => { obmenCoins = v; localStorage.setItem("sz_coins", String(v || 0)); });
  $("obmPlan").addEventListener("click", loadObmenPlan);
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") loadObmenPlan(); });
  page.querySelectorAll(".obm-link[data-id]").forEach((el) =>
    el.addEventListener("click", () => { openObmenModal(el.dataset.id); }));
  wireBtRows(openObmenModal);
}

async function loadObmenPlan() {
  const coins = +String($("obmCoins").value).replace(/\D/g, "") || 0;
  if (!coins) return;
  obmenCoins = coins;
  localStorage.setItem("sz_coins", String(coins));
  const box = $("obmPlanBox");
  box.innerHTML = `<div class="spinner">// СЧИТАЮ КОРЗИНУ</div>`;
  let d;
  try {
    d = await fetch(api(`/exchange/plan?coins=${coins}`)).then((r) => r.json());
  } catch (e) { box.innerHTML = ""; return; }
  const rows = (d.basket || []).map((r) => obmenRow(r,
    `<td class="r">${r.buys}×</td><td class="r">${fmt(r.total_value)} ₽</td>`)).join("");
  box.innerHTML = d.basket && d.basket.length ? `<div class="obm-plan">
    <div class="reqs-lbl">КОРЗИНА НА ${fmt(d.coins)} МОНЕТ → ~${fmt(d.value)} ₽${d.left ? ` · ОСТАНЕТСЯ ${fmt(d.left)}` : ""}</div>
    <div class="bt-wrap"><table class="bt-table">
      <thead>${OBM_PLAN_HEAD}</thead>
      <tbody>${rows}</tbody>
    </table></div></div>`
    : `<div class="empty-sm">НЕ ИЗ ЧЕГО СОБРАТЬ КОРЗИНУ (НЕТ ПОЗИЦИЙ С ИЗВЕСТНОЙ ЦЕНОЙ).</div>`;
  wireBtRows(openObmenModal);
}

// ---------- биржа артефактов: топ роста цен по корзинам качество×заточка ----------
const QLT_RU = { 0: "ОБЫЧНЫЙ", 1: "НЕОБЫЧНЫЙ", 2: "ОСОБЫЙ",
                 3: "РЕДКИЙ", 4: "ИСКЛЮЧИТЕЛЬНЫЙ", 5: "ЛЕГЕНДАРНЫЙ" };
// человеческие имена качества вместо «Q3» (решение юзера), цвет — qltColor
const qltLabel = (q) => QLT_RU[q] || `Q${q}`;
const bucketBadge = (qlt, ptn) => `${QLT_RU[qlt] || "Q" + qlt} +${ptn}`;
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
      <div class="nm" style="color:${qltColor(e.qlt)}">${escapeHtml(e.name)}
        <span class="bucket" style="border-color:${qltColor(e.qlt)};color:${qltColor(e.qlt)}">${bucketBadge(e.qlt, e.ptn)}</span></div>
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
        <span class="bb" style="color:${qltColor(b.qlt)}">${bucketBadge(b.qlt, b.ptn)}</span>
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

// ---------- калькулятор сборок: ручной + автоподбор + приведённое ХП ----------
let BUILD_DICT = null;   // /api/build/dict (кэш на сессию)
let buildTab = "manual";
const buildState = { container: null, slots: [] };  // слот: {id, ptn, m} | null
const autoState = { budget: 500000, stats: [{ key: "", weight: 60 }], result: null };
const hpState = { budget: 500000, armor: null, armorPtn: 15, result: null };
const artPriceCache = {};  // itemId -> {"qlt:ptn": {avg7d, n7}}
let pickerSlot = -1, pickerQuery = "";

const MDL = () => BUILD_DICT.model;
const tierTop = (q) => 1 + MDL().tier_step * q;
const qltFromM = (m) => (m <= 1 ? 0 : Math.min(5, Math.ceil((m - 1) / MDL().tier_step - 1e-9)));
// цвет редкости артефакта (по качеству Q0…Q5): обычный→легендарный
const QLT_COLORS = ["#b9c9b9", "#5fd67a", "#5fa8ff", "#d46bff", "#ff6b5e", "#ffb84d"];
const qltColor = (q) => QLT_COLORS[q] || QLT_COLORS[0];
// опорное значение — конец диапазона с большим модулем (у «меньше — лучше» он отрицательный)
const statBase = (st) => (Math.abs(st.max) >= Math.abs(st.min) ? st.max : st.min);
// заточка нелинейна: ×1 при +0 … ×1.74 при +15 (коэффициенты с бэка)
const sharp = (ptn) => 1 + MDL().sharp_a * ptn + MDL().sharp_b * ptn * ptn;
const tierFrac = (m) => {
  const q = qltFromM(m), lo = q === 0 ? MDL().m_min : tierTop(q) - MDL().tier_step, hi = tierTop(q);
  return hi > lo ? Math.max(0, Math.min(1, (m - lo) / (hi - lo))) : 1;
};
const statVal = (st, m, ptn) => {
  if (st.harmful) {  // эмиссия: заточкой не растёт, внутри тира интерполяция мал.модуль→бол.
    const lo = Math.abs(st.min) <= Math.abs(st.max) ? st.min : st.max;
    const hi = Math.abs(st.max) >= Math.abs(st.min) ? st.max : st.min;
    return lo + (hi - lo) * tierFrac(m);
  }
  return statBase(st) * m * sharp(ptn);
};
const fmtStat = (v) => (v > 0 ? "+" : "") + (Math.abs(v) >= 100 ? Math.round(v) : v.toFixed(2));
// имя контейнера красится в цвет его качества (редкости)
const contLabel = (c) =>
  `<span style="color:${rank(c.color).color}">${escapeHtml(c.name)}</span>` +
  ` · ${c.slots} СЛОТ${c.slots > 1 ? "А" : ""} · ЭФФ ${c.efficiency ?? "—"}% · ЗАЩИТА ${c.protection ?? "—"}%`;
const FROST_KEY = "stalker.artefact_properties.factor.frost_accumulation";  // «холод» — защита не гасит

// заражение сборки: эмиссия (красный) гасится защитой (кроме мороза), защита
// (зелёный, минус) усиливается эффективностью — как на бэке
function clientContam(slots, cont) {
  const prot = (cont.protection ?? 0) / 100, eff = (cont.efficiency ?? 100) / 100;
  const out = [];
  for (const c of BUILD_DICT.contamination) {
    let emit = 0, protect = 0, present = false;
    for (const s of slots) {
      if (!s) continue;
      const art = BUILD_DICT.artefacts.find((a) => a.id === s.id);
      const st = art && art.stats[c.key];
      if (!st) continue;
      present = true;
      const val = statVal(st, s.m, s.ptn);
      if (st.harmful) emit += val; else protect += val * eff;
    }
    if (!present) continue;
    const net = emit * (c.key === FROST_KEY ? 1 : (1 - prot)) + protect;
    out.push({ name: c.name, net: +net.toFixed(3), limit: c.limit,
               over: c.limit != null && net > c.limit + 1e-9 });
  }
  return out;
}

// строки статов одного арта (для результатов авто/ХП): цвет по harmful
function slotStatRows(stats) {
  return Object.values(stats).sort((a, b) => a.harmful - b.harmful)
    .map((s) => `<div class="bstat ${s.harmful ? "bad" : ""}">
      <span class="sn">${escapeHtml(s.name)}</span>
      <span class="sv">${fmtStat(s.val)}</span></div>`).join("");
}

function milestoneNote(ms) {
  if (!ms || !ms.length) return "";
  return `<div class="bs-ms">+${ms.join(" · +")}: ещё ${ms.length}× случайный бонус за заточку</div>`;
}

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

// суммарные статы: положительные × эффективность контейнера; заражения — отдельно
function manualTotals(cont) {
  const eff = (cont.efficiency ?? 100) / 100;
  const stats = {}, out = { cost: 0, unpriced: 0, weight: cont.weight || 0, stats };
  for (const s of buildState.slots) {
    if (!s) continue;
    const art = BUILD_DICT.artefacts.find((a) => a.id === s.id);
    out.weight += art.weight || 0;
    for (const [k, st] of Object.entries(art.stats)) {
      if (BUILD_DICT.contamination.some((c) => c.key === k)) continue;  // заражения — в блоке
      const t = stats[k] || (stats[k] = { name: st.name, harmful: st.harmful, total: 0 });
      t.total += st.harmful ? statVal(st, s.m, s.ptn) : statVal(st, s.m, s.ptn) * eff;
    }
    const p = slotPrice(s);
    if (p) out.cost += p.price; else out.unpriced++;
  }
  out.contamination = clientContam(buildState.slots, cont);
  return out;
}

function contamBlock(contam) {
  if (!contam || !contam.length) return "";
  const rows = contam.map((c) => `<div class="bt-row ${c.over ? "bad" : ""}">
      <span class="k">${escapeHtml(c.name)}${c.over ? " ⚠" : ""}</span>
      <span class="v">${fmtStat(c.net)}${c.limit != null ? ` <span class="lim">/ ${c.limit}</span>` : ""}</span>
    </div>`).join("");
  return `<div class="reqs-lbl" style="margin-top:10px">ЗАРАЖЕНИЕ (после защиты контейнера)</div>${rows}`;
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
    ${contamBlock(t.contamination)}
    <div class="bt-row"><span class="k">ВЕС (С КОНТЕЙНЕРОМ)</span><span class="v">${t.weight.toFixed(2)} КГ</span></div>
    <div class="bt-row"><span class="k">ЗАЩИТА КОНТЕЙНЕРА</span><span class="v">${cont.protection ?? "—"}%</span></div>
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
        .filter((a) => a.name.toLowerCase().includes(q))
        .sort((a, b) => rankWeight(b.color) - rankWeight(a.color))  // крутое сверху
        .slice(0, 8);
      return `<div class="bslot picker">
        <input id="pickerInput" type="text" placeholder="НАЗВАНИЕ АРТЕФАКТА…" value="${escapeHtml(pickerQuery)}">
        <div class="pick-list">${found.map((a) =>
          `<div class="pick-row" data-pick="${a.id}">
             <img loading="lazy" src="${asset(a.icon)}" alt=""><span style="color:${rank(a.color).color}">${escapeHtml(a.name)}</span>
             <span class="cls">${escapeHtml(a.class)}</span></div>`).join("") || `<div class="empty-sm">НЕ НАЙДЕНО</div>`}
        </div></div>`;
    }
    return `<div class="bslot empty-slot" data-addslot="${idx}">+ АРТЕФАКТ</div>`;
  }
  const art = BUILD_DICT.artefacts.find((a) => a.id === s.id);
  const qlt = qltFromM(s.m);
  const qOpts = [0, 1, 2, 3, 4, 5].map((q) =>
    `<option value="${q}" ${q === qlt ? "selected" : ""}>${qltLabel(q)}</option>`).join("");
  const ptnOpts = Array.from({ length: 16 }, (_, i) =>
    `<option value="${i}" ${s.ptn === i ? "selected" : ""}>+${i}</option>`).join("");
  const price = slotPrice(s);
  const statRows = Object.entries(art.stats).map(([k, st]) =>
    `<div class="bstat ${st.harmful ? "bad" : ""}">
      <span class="sn">${escapeHtml(st.name)}</span>
      <span class="sv">${fmtStat(statVal(st, s.m, s.ptn))}</span></div>`).join("");
  return `<div class="bslot">
    <div class="bs-head">
      <img loading="lazy" src="${asset(art.icon)}" alt="">
      <div class="bs-nm" style="color:${qltColor(qlt)}">${escapeHtml(art.name)}
        <div class="bs-cls">${escapeHtml(art.class)}</div></div>
      <button class="bs-x" data-rm="${idx}" title="Убрать">✕</button>
    </div>
    <div class="bs-ctl">
      <select class="bs-qlt" data-slot="${idx}" style="color:${qltColor(qlt)}">${qOpts}</select>
      <select class="bs-ptn" data-slot="${idx}">${ptnOpts}</select>
      <label class="bs-pct" title="Множитель качества, %: выход за тир меняет редкость (85–175%)">
        <input class="mval" data-slot="${idx}" value="${Math.round(s.m * 100)}"><span>%</span>
      </label>
    </div>
    ${statRows}
    <div class="bs-price">${price ? `${fmt(price.price)} ₽ · ${srcLabel(price.src)}` : "НЕТ ЦЕНЫ (НЕТ ЛОТОВ И ИСТОРИИ)"}</div>
  </div>`;
}

function renderBuilds() {
  const cont = buildContainer();
  if (!cont) { page.innerHTML = `<div class="empty">НЕТ ДАННЫХ КОНТЕЙНЕРОВ</div>`; return; }

  let h = `<div class="section-head">
      <div class="section-title">▸ КАЛЬКУЛЯТОР СБОРОК АРТЕФАКТОВ</div>
      <div class="section-note">ЦЕНЫ: 5 ДЕШЁВЫХ ЛОТОВ → СР. 7Д ПОСЛЕ НАКОПЛЕНИЯ БИРЖИ</div>
    </div>
    <div class="btabs">
      <button class="btab ${buildTab === "manual" ? "on" : ""}" data-tab="manual">СОБРАТЬ ВРУЧНУЮ</button>
      <button class="btab ${buildTab === "auto" ? "on" : ""}" data-tab="auto">АВТОПОДБОР ПОД БЮДЖЕТ</button>
      <button class="btab ${buildTab === "hp" ? "on" : ""}" data-tab="hp">ПРИВЕДЁННОЕ ХП</button>
    </div>
    <div class="bbar"><div class="isel" id="bContSel"></div></div>`;

  h += buildTab === "manual" ? renderManual(cont)
     : buildTab === "auto" ? renderAuto(cont) : renderHP(cont);
  const footer = buildTab === "manual"
    ? `КАЧЕСТВО — РЕДКОСТЬ ИЛИ ПОЛЕ % (85–175%): ВЫХОД ЗА ТИР МЕНЯЕТ РЕДКОСТЬ. ЦВЕТ ИМЕНИ — РЕДКОСТЬ.
       ЭФФЕКТИВНОСТЬ КОНТЕЙНЕРА УСИЛИВАЕТ ПОЛОЖИТЕЛЬНЫЕ СТАТЫ; ВНУТР. ЗАЩИТА ГАСИТ ЗАРАЖЕНИЯ (КРОМЕ ХОЛОДА).
       ЛИМИТЫ ИГРОКА: РАД/ТЕМП/БИО/ХОЛОД — 1.0, ПСИ — 3.0; МИНУС — ЗАПАС ЗАЩИТЫ, НЕ ВРЕДЕН.`
    : `ПОЛОЖИТЕЛЬНЫЕ СТАТЫ АРТОВ × ЭФФЕКТИВНОСТЬ КОНТЕЙНЕРА; ЗАРАЖЕНИЯ ГАСЯТСЯ ВНУТР. ЗАЩИТОЙ (КРОМЕ ХОЛОДА).
       ЛИМИТЫ РАД/ТЕМП/БИО/ХОЛОД — 1.0, ПСИ — 3.0 — ЖЁСТКИЕ: СБОРКИ СВЕРХ ЛИМИТА НЕ ВЫДАЮТСЯ,
       ПРИ НУЖДЕ ДОБАВЛЯЮТСЯ КОНТРАРТЫ. СЛУЧАЙНЫЕ ДОП-СВОЙСТВА ЗАТОЧКИ НЕ МОДЕЛИРУЮТСЯ.`;
  h += `<div class="side-foot">${footer}</div>`;
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
  if (r && r.error)
    res = `<div class="note-warn"><span class="mark">[!]</span> ${escapeHtml(r.hint || "НЕТ ЦЕНОВЫХ ДАННЫХ")}</div>`;
  else if (r && r.builds && r.builds.length) res = renderAutoResult(r, autoState.budget);
  else if (r && r.builds) res = `<div class="empty">НИЧЕГО НЕ ПОДОБРАЛОСЬ ПОД БЮДЖЕТ.</div>`;
  return `<div class="aform">
      <label class="albl">БЮДЖЕТ, ₽ <input id="aBudget" type="text" inputmode="numeric" value="${fmt(autoState.budget)}"></label>
      ${rows}
      ${autoState.stats.length < 3 ? `<button id="aAdd" class="awin">+ СТАТ</button>` : ""}
      <button id="aGo" class="prof-save">РАССЧИТАТЬ СБОРКУ</button>
    </div>${res}`;
}

// карточка подобранного арта: цвет редкости, полные статы, майлстоуны, цена
function resultSlotCard(s) {
  return `<div class="bslot ro">
    <div class="bs-head"><img loading="lazy" src="${asset(s.icon)}" alt="">
      <div class="bs-nm" style="color:${qltColor(s.qlt)}">${escapeHtml(s.name)}</div>
      <span class="bucket" style="border-color:${qltColor(s.qlt)};color:${qltColor(s.qlt)}">${bucketBadge(s.qlt, s.ptn)}</span></div>
    ${slotStatRows(s.stats)}
    ${milestoneNote(s.milestones)}
    <div class="bs-price">${fmt(s.price)} ₽ · ${s.src === "lots" ? s.sales + " ЛОТ." : s.sales + " ПРОД/7Д"}</div>
  </div>`;
}

function renderAutoResult(r, budget) {
  const build = (b, title, open) => `<details class="alt abuild" ${open ? "open" : ""}>
    <summary><b>${title}</b> · ${fmt(b.totals.cost)} ₽ · ${b.slots.length} СЛОТ</summary>
    <div class="bgrid">${b.slots.map(resultSlotCard).join("")}</div>
    ${totalsBlock({ stats: b.totals.stats, cost: b.totals.cost, unpriced: 0,
                    weight: b.totals.weight, contamination: b.totals.contamination },
                  r.container, budget)}
  </details>`;
  let h = build(r.builds[0], "ОПТИМАЛЬНАЯ СБОРКА", true);
  r.builds.slice(1).forEach((b, i) => { h += build(b, `АЛЬТЕРНАТИВА ${i + 1}`, false); });
  if (r.warnings && r.warnings.length)
    h += `<div class="note-warn"><span class="mark">[!]</span> ${r.warnings.map(escapeHtml).join("<br>")}</div>`;
  return h;
}

// ---------- вкладка «Приведённое ХП» ----------
function renderHP(cont) {
  const armor = BUILD_DICT.armor || [];
  if (!hpState.armor && armor.length) hpState.armor = armor[0].id;
  const ptnOpts = [0, 5, 10, 11, 15].map((p) =>
    `<option value="${p}" ${p === hpState.armorPtn ? "selected" : ""}>+${p}</option>`).join("");
  let res = "";
  const r = hpState.result;
  if (r && r.error) res = `<div class="note-warn"><span class="mark">[!]</span> ${escapeHtml(r.hint || "НЕТ ДАННЫХ")}</div>`;
  else if (r && r.builds && r.builds.length) res = renderHPResult(r);
  return `<div class="hp-intro">Подбор артефактов на максимум <b>приведённого ХП от пуль</b>:
      <span class="mono">(100 + пулестойкость) × живучесть</span>. Броня и контейнер — фикс, бюджет — на артефакты.</div>
    <div class="aform">
      <label class="albl">БЮДЖЕТ, ₽ <input id="hBudget" type="text" inputmode="numeric" value="${fmt(hpState.budget)}"></label>
      <div class="arow"><span class="albl" style="min-width:70px">БРОНЯ</span>
        <div class="isel" id="hArmorSel" style="flex:1"></div>
        <select id="hPtn">${ptnOpts}</select></div>
      <button id="hGo" class="prof-save">РАССЧИТАТЬ СБОРКУ</button>
    </div>${res}`;
}

function renderHPResult(r) {
  const b = r.builds[0], hp = b.hp;
  const arm = hp.armor;
  let h = `<div class="hp-hero">
      <div class="hp-num"><div class="hp-val">${fmt(hp.effective_hp)}</div>
        <div class="hp-lbl">ПРИВЕДЁННОЕ ХП ОТ ПУЛЬ</div></div>
      <div class="hp-formula">(100 + <b>${fmt(hp.total_bullet)}</b> пулестой) × <b>${(100 + hp.total_vitality).toFixed(2)}%</b> живучести</div>
    </div>
    <div class="hp-break">
      <div class="bt-row"><span class="k">БРОНЯ <span style="color:${rank(arm.color).color}">${escapeHtml(arm.name)} +${arm.ptn}</span></span>
        <span class="v">ПУЛЕСТОЙ ${fmt(arm.bullet)}${arm.vitality ? ` · ЖИВУЧ +${arm.vitality}` : ""}</span></div>
      <div class="bt-row"><span class="k">АРТЕФАКТЫ</span>
        <span class="v">ПУЛЕСТОЙ ${fmtStat(hp.artefact_bullet)} · ЖИВУЧ ${fmtStat(hp.artefact_vitality)}%</span></div>
    </div>
    <div class="bgrid">${b.slots.map(resultSlotCard).join("")}</div>
    ${totalsBlock({ stats: b.totals.stats, cost: b.totals.cost, unpriced: 0,
                    weight: b.totals.weight, contamination: b.totals.contamination },
                  r.container, hpState.budget)}`;
  if (r.warnings && r.warnings.length)
    h += `<div class="note-warn"><span class="mark">[!]</span> ${r.warnings.map(escapeHtml).join("<br>")}</div>`;
  return h;
}

// кастомный выпадающий список с иконками (нативный <select> их не умеет):
// сортировка по редкости (сверху крутое) + живой поиск по названию.
function iconSelect(host, items, curId, onPick) {
  items = items.map((it, i) => ({ ...it, _i: i }))
    .sort((a, b) => (rankWeight(b.color) - rankWeight(a.color)) || (a._i - b._i));
  const cur = items.find((it) => it.id === curId) || items[0];
  if (!cur) { host.innerHTML = ""; return; }
  const lbl = (it) => it.labelHtml || escapeHtml(it.label);  // labelHtml — уже экранирован вызывающим
  const searchOf = (it) => (it.search != null ? it.search
    : String(it.labelHtml || it.label || "").replace(/<[^>]*>/g, "")).toLowerCase();
  host.innerHTML = `<button type="button" class="isel-btn">
      <img src="${asset(cur.icon)}" alt="">
      <span class="isel-lbl">${lbl(cur)}</span><span class="isel-arr">▾</span></button>
    <div class="isel-list hidden">
      <div class="isel-search"><input type="text" class="isel-q" placeholder="Поиск…" autocomplete="off"></div>
      <div class="isel-opts">${items.map((it) => `
        <div class="isel-opt${it.id === cur.id ? " on" : ""}" data-id="${it.id}" data-s="${escapeHtml(searchOf(it))}">
          <img loading="lazy" src="${asset(it.icon)}" alt=""><span>${lbl(it)}</span>
        </div>`).join("")}</div>
    </div>`;
  const list = host.querySelector(".isel-list");
  const q = host.querySelector(".isel-q");
  const opts = host.querySelector(".isel-opts");
  const filter = () => {
    const needle = q.value.trim().toLowerCase();
    opts.querySelectorAll(".isel-opt").forEach((o) =>
      o.classList.toggle("hidden", !!needle && !o.dataset.s.includes(needle)));
  };
  host.querySelector(".isel-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = list.classList.contains("hidden");
    closeIconSelects(list);
    list.classList.toggle("hidden");
    if (willOpen) {
      q.value = ""; filter();
      q.focus();
      const on = opts.querySelector(".on");
      if (on) on.scrollIntoView({ block: "center" });
    }
  });
  // клики/ввод внутри списка не должны закрывать его глобальным обработчиком
  list.addEventListener("click", (e) => e.stopPropagation());
  q.addEventListener("input", filter);
  opts.querySelectorAll(".isel-opt").forEach((o) => o.addEventListener("click", () => {
    list.classList.add("hidden");
    if (o.dataset.id !== cur.id) onPick(o.dataset.id);
  }));
}
function closeIconSelects(except) {
  document.querySelectorAll(".isel-list").forEach((l) => {
    if (l !== except) l.classList.add("hidden");
  });
}
document.addEventListener("click", () => closeIconSelects());

// поле суммы: живые разделители разрядов («1 500 000»)
function wireBudget(el, setter) {
  el.addEventListener("input", () => {
    const digits = el.value.replace(/\D/g, "").replace(/^0+(?=\d)/, "").slice(0, 12);
    el.value = digits.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    setter(Math.max(1, +digits || 1));
  });
}

function wireBuilds(cont) {
  page.querySelectorAll(".btab").forEach((b) => b.addEventListener("click", () => {
    buildTab = b.dataset.tab;
    renderBuilds();
  }));
  iconSelect($("bContSel"),
    BUILD_DICT.containers.map((c) => ({ id: c.id, icon: c.icon, color: c.color,
                                        search: c.name, labelHtml: contLabel(c) })),
    buildState.container, (id) => {
      buildState.container = id;
      const c = buildContainer();
      const old = buildState.slots;
      buildState.slots = Array(c.slots).fill(null).map((_, i) => old[i] || null);
      renderBuilds();
    });

  if (buildTab === "auto") {
    wireBudget($("aBudget"), (v) => { autoState.budget = v; });
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

  if (buildTab === "hp") {
    wireBudget($("hBudget"), (v) => { hpState.budget = v; });
    iconSelect($("hArmorSel"),
      (BUILD_DICT.armor || []).map((a) => ({
        id: a.id, icon: a.icon, color: a.color, search: a.name,
        labelHtml: `<span style="color:${rank(a.color).color}">${escapeHtml(a.name)}</span>` +
                   ` · ПУЛЕСТОЙ ${Math.round(a.bullet0)}`,
      })),
      hpState.armor, (id) => { hpState.armor = id; renderBuilds(); });   // перерисовка обновляет иконку
    $("hPtn").addEventListener("change", (e) => { hpState.armorPtn = +e.target.value; });
    $("hGo").addEventListener("click", async () => {
      if (!hpState.armor) return;
      $("hGo").textContent = "СЧИТАЮ…";
      try {
        hpState.result = await fetch(api("/build/hp"), {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ budget: hpState.budget, container: buildState.container,
                                 armor: hpState.armor, armor_ptn: hpState.armorPtn }),
        }).then((r) => r.json());
      } catch (e) { hpState.result = { error: "net", hint: "ОШИБКА СЕТИ" }; }
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
  // редкость: выбор тира → множитель на верх этого тира
  page.querySelectorAll(".bs-qlt").forEach((el) => el.addEventListener("change", () => {
    buildState.slots[+el.dataset.slot].m = tierTop(+el.value);
    renderBuilds();
  }));
  // единое %-поле: множитель качества; выход за тир меняет редкость автоматически
  page.querySelectorAll(".mval").forEach((el) => el.addEventListener("change", () => {
    const s = buildState.slots[+el.dataset.slot];
    const v = parseFloat(String(el.value).replace(",", "."));
    if (!isNaN(v)) s.m = Math.min(MDL().m_max, Math.max(MDL().m_min, v / 100));
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
      detail.innerHTML = `<div class="empty">ПРОФИЛЬ ДОСТУПЕН ПОСЛЕ ВХОДА.
        <a class="auth-login js-open-auth" href="${BASE}/auth/login">ВОЙТИ</a></div>`;
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

  // навык — как в игре: имя, уровень и широкая сегментная шкала (без опыта)
  const perkRow = (p) => {
    const lvl = P.perks[p.id] || 0;
    let pips = "";
    for (let i = 0; i < pm; i++)
      pips += `<div class="pip ppip ${i < lvl ? "on" : ""}" data-lvl="${i + 1}"></div>`;
    return `<div class="prof-perk" data-perk="${p.id}">
      <div class="phead">
        <div class="nm">${escapeHtml(p.name || perkName(p.id))}</div>
        <div class="plvl">УРОВЕНЬ <span>${lvl}</span> / ${pm}</div>
      </div>
      <div class="pbar">
        <button class="pbtn" data-d="-1">−</button>
        <div class="pips">${pips}</div>
        <button class="pbtn" data-d="1">+</button>
      </div>
    </div>`;
  };

  // станки — в столбик, сгруппированы по столу, к которому относятся;
  // улучшения генератора — отдельной группой (учёт топлива в крафте)
  const FB = dict.feature_bench || {};
  const byBench = {};
  feats.forEach((f) => {
    const b = isGenFeature(f) ? "generator" : (FB[f] || "workbench");
    (byBench[b] = byBench[b] || []).push(f);
  });
  const benchOrder = ["workbench", "laboratory_table", "kitchen_table", "generator"]
    .concat(Object.keys(byBench).filter((b) =>
      !["workbench", "laboratory_table", "kitchen_table", "generator"].includes(b)));
  const featBtn = (f) => {
    const ic = (dict.feature_icons || {})[f];
    return `<button class="feat ${P.features.has(f) ? "on" : ""}" data-feat="${f}">
       <span class="fmark">${P.features.has(f) ? "✓" : "+"}</span>
       ${ic ? `<img class="feat-ic" loading="lazy" src="${asset(ic)}" alt="">` : ""}
       ${escapeHtml(featureName(f))}</button>`;
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
    <div class="prof-feats">${benchOrder
      .filter((b) => (byBench[b] || []).length)
      .map((b) => `<div class="feat-grp">
        <div class="feat-grp-ttl">${benchName(b)} · ${byBench[b].length}</div>
        ${b === "generator" ? `<div class="feat-grp-note">Станции приёма (газ, батареи,
          аномальное) открывают источники энергии — их учитывает «УЧЁТ ТОПЛИВА» в карточках
          крафта. Фильтр, инвертор и шкаф поднимают лимит/скорость генератора и на цену
          энергии не влияют.</div>` : ""}
        <div class="feat-col">${byBench[b].map(featBtn).join("")}</div>
      </div>`).join("")}
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
      if (r.ok && ME) {       // профиль заполнен — онбординг-подсказка и пульсация ника больше не нужны
        ME.profile_empty = !(Object.keys(P.perks).length || P.features.size);
        renderOnboard();
        renderAuthGlow();
      }
    } catch (e) {
      msg.textContent = "[!] ОШИБКА СЕТИ";
      msg.className = "prof-msg bad";
    }
  });
  const b = detail.querySelector(".back");
  if (b) b.addEventListener("click", () => { navigate("/craft"); });
}

// ---------- интерактивная карта мира (Leaflet, тайлы из КПК STALZONE) ----------
let mapCleanup = null;
let leafletReady = null;

// Leaflet вендорится локально и грузится только при первом открытии карты.
function ensureLeaflet() {
  if (leafletReady) return leafletReady;
  leafletReady = new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = asset("vendor/leaflet/leaflet.css");
    document.head.appendChild(css);
    const js = document.createElement("script");
    js.src = asset("vendor/leaflet/leaflet.js");
    js.onload = () => resolve();
    js.onerror = reject;
    document.head.appendChild(js);
  });
  return leafletReady;
}

let mapMeta = null;                                   // кэш /api/map/meta

async function openMap(territoryId) {
  if (mapCleanup) { mapCleanup(); mapCleanup = null; }
  mapEpoch++;
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="mapmod"><div class="spinner">// ЗАГРУЗКА КАРТЫ</div></div>`;
  window.scrollTo(0, 0);
  const want = territoryId ? `/map/${territoryId}` : "/map";
  try {
    if (!mapMeta) {
      [mapMeta] = await Promise.all([
        fetch(api("/map/meta")).then((r) => r.json()),
        ensureLeaflet(),
      ]);
    } else {
      await ensureLeaflet();
    }
  } catch (e) {
    if (location.pathname === want)
      page.innerHTML = `<div class="mapmod"><div class="empty">[!] КАРТА НЕДОСТУПНА</div></div>`;
    return;
  }
  MAP_CATS = mapMeta.categories || [];
  if (location.pathname !== want) return;             // пользователь ушёл, пока грузилось
  const terr = territoryId
    && (mapMeta.territories || []).find((t) => t.id === territoryId && t.bbox);
  if (territoryId && !terr) { navigate("/map", { replace: true }); return; }
  if (terr) renderTerritory(terr);
  else renderWorldMap();
}

// Общая инициализация Leaflet-вида (CRS.Simple, границы строго по изображению).
function makeTileMap(layerMeta, viewBoundsPx, elId = "mapView") {
  const map = L.map(elId, {
    crs: L.CRS.Simple,
    zoomSnap: 0.25,
    wheelPxPerZoomLevel: 90,
    attributionControl: false,
    maxBoundsViscosity: 1.0,
  });
  const px = (x, y) => map.unproject([x, y], layerMeta.max_zoom);
  const [bx0, by0, bx1, by1] = viewBoundsPx;
  const bounds = L.latLngBounds(px(bx0, by0), px(bx1, by1));
  L.tileLayer(asset(layerMeta.tile_url), {
    tileSize: layerMeta.tile_size,
    minNativeZoom: layerMeta.min_zoom, maxNativeZoom: layerMeta.max_zoom,
    bounds: L.latLngBounds(px(0, 0), px(layerMeta.w, layerMeta.h)),
    noWrap: true,
  }).addTo(map);
  map.setMaxBounds(bounds);
  // не даём отдалиться дальше, чем вписанный вид
  const fitZoom = map.getBoundsZoom(bounds, false);
  map.setMinZoom(Math.min(fitZoom, layerMeta.max_zoom));
  map.setMaxZoom(layerMeta.max_zoom);
  map.fitBounds(bounds);
  mapCleanup = () => { map.remove(); };
  // обратная проекция: latlng → нативные px слоя (для расстановки/сохранения меток)
  const toPx = (latlng) => {
    const p = map.project(latlng, layerMeta.max_zoom);
    return [Math.round(p.x * 100) / 100, Math.round(p.y * 100) / 100];
  };
  return { map, px, toPx, bounds, layerMeta };
}

// ---------- объекты карты (метки/области/линии): общий рендер вьюера и редактора ----------
let MAP_CATS = [];                                   // категории меток из /map/meta
let mapEpoch = 0;                                    // защита от гонок при навигации

const catById = (id) =>
  MAP_CATS.find((c) => c.id === id) ||
  MAP_CATS.find((c) => c.id === "poi") ||
  { id: "poi", name: "Точка", emoji: "📍", color: "#dff5df" };

function markerDivIcon(o, selected) {
  const c = catById(o.category);
  const col = o.color || c.color;
  return L.divIcon({
    className: "",
    html: `<div class="mo-marker${selected ? " sel" : ""}${o.published ? "" : " draft"}"
              style="--mo:${col}"><span>${c.emoji}</span></div>`,
    iconSize: [26, 26], iconAnchor: [13, 13],
  });
}

function objTooltipHtml(o) {
  const c = o.kind === "marker" ? catById(o.category) : null;
  const title = escapeHtml(o.name || (c ? c.name : "Без названия"));
  const badge = c ? `<div class="mo-tip-cat">${c.emoji} ${escapeHtml(c.name)}</div>` : "";
  const desc = o.description
    ? `<div class="mo-tip-desc">${escapeHtml(o.description)}</div>` : "";
  return `<div class="mo-tip"><div class="mo-tip-h">${title}</div>${badge}${desc}</div>`;
}

// Нарисовать один объект на карте (ctx: {map, px, editable, selected}). Возвращает слой.
function renderMapObject(o, ctx) {
  const { map, px } = ctx;
  let layer;
  if (o.kind === "marker") {
    layer = L.marker(px(o.geometry[0], o.geometry[1]), {
      icon: markerDivIcon(o, ctx.selected),
      draggable: !!ctx.editable, riseOnHover: true,
    });
  } else {
    const pts = o.geometry.map((p) => px(p[0], p[1]));
    const col = o.color || (o.kind === "area" ? "#7ce68e" : "#9ecbff");
    const base = { color: col, weight: ctx.selected ? 4 : 2,
                   opacity: o.published ? 0.95 : 0.5,
                   dashArray: o.published ? null : "5,5" };
    layer = o.kind === "area"
      ? L.polygon(pts, { ...base, fillColor: col, fillOpacity: o.published ? 0.18 : 0.08 })
      : L.polyline(pts, base);
  }
  layer.bindTooltip(objTooltipHtml(o),
    { sticky: true, direction: "top", className: "mo-tooltip", opacity: 1 });
  layer.addTo(map);
  return layer;
}

// Публичный вьюер: подгрузить опубликованные объекты слоя и отрисовать с тултипами.
function loadViewerObjects(layer, map, px) {
  const ep = mapEpoch;
  fetch(api(`/map/objects?layer=${layer}`)).then((r) => r.json()).then((d) => {
    if (ep !== mapEpoch || !map._container) return;   // ушли с карты, пока грузилось
    (d.objects || []).forEach((o) => renderMapObject(o, { map, px }));
  }).catch(() => {});
}

// Скрываемая плашка «карта ещё в разработке» над публичной картой (не в редакторе).
// Закрытие запоминается в localStorage — больше не мозолит глаза.
const MAP_WIP_KEY = "sz_map_wip";
function mapWipBanner() {
  if (localStorage.getItem(MAP_WIP_KEY) === "1") return "";
  return `<div class="map-wip" id="mapWip">
    <span class="map-wip-i">[!]</span>
    <span class="map-wip-t">Интерактивная карта ещё в разработке — метки и области
      появляются постепенно.</span>
    <button class="map-wip-x" id="mapWipX" title="Скрыть">✕</button>
  </div>`;
}
function wireMapWip() {
  const x = $("mapWipX");
  if (x) x.addEventListener("click", () => {
    localStorage.setItem(MAP_WIP_KEY, "1");
    const b = $("mapWip"); if (b) b.remove();
  });
}

function renderWorldMap() {
  const g = mapMeta.global;
  page.innerHTML = `<div class="mapmod">
    ${mapWipBanner()}
    <div class="section-head">
      <div class="section-title">▸ КАРТА МИРА · ГЛОБАЛЬНЫЙ ВИД</div>
      <div class="section-note">КЛИК ПО ТЕРРИТОРИИ — ПОДРОБНАЯ КАРТА</div>
    </div>
    <div class="map-view" id="mapView"></div>
    <div class="map-legend">Карта из КПК STALZONE. Территории с меткой открываются в
      детальном виде; ✕ — сейчас закрыто в игре.</div>
  </div>`;
  wireMapWip();
  const { map, px } = makeTileMap(g, [0, 0, g.w, g.h]);
  (mapMeta.territories || []).forEach((t) => {
    const openable = !!t.bbox;
    const cls = "map-terr" + (t.closed ? " closed" : "") + (openable ? " openable" : "");
    const icon = L.divIcon({
      className: "",
      html: `<div class="${cls}">${t.closed ? "✕ " : ""}${escapeHtml(t.name)}</div>`,
      iconSize: null,
    });
    const m = L.marker(px(t.label[0], t.label[1]), { icon }).addTo(map);
    if (openable) m.on("click", () => { navigate(`/map/${t.id}`); });
  });
  loadViewerObjects("global", map, px);
}

function renderTerritory(terr) {
  const d = mapMeta.detail;
  page.innerHTML = `<div class="mapmod">
    ${mapWipBanner()}
    <div class="section-head">
      <div class="section-title">▸ КАРТА · ${escapeHtml(terr.name.toUpperCase())}${terr.closed ? " · ЗАКРЫТО" : ""}</div>
      <div class="section-note"><a href="/map" class="map-back">◂ К ГЛОБАЛЬНОЙ КАРТЕ</a></div>
    </div>
    <div class="map-view" id="mapView"></div>
    <div class="map-legend">Детальная карта из КПК STALZONE (облака — как в игре).
      Дальше — точки локаций и артефактов с привязкой к базе предметов.</div>
  </div>`;
  wireMapWip();
  const { map, px } = makeTileMap(d, terr.bbox);
  loadViewerObjects("detail", map, px);
}

// ======================================================================
//  DEV · РЕДАКТОР КАРТЫ (только админ) — расстановка меток, областей, линий
// ======================================================================
const KIND_LABEL = { marker: "МЕТКА", area: "ОБЛАСТЬ", line: "ЛИНИЯ" };

const ed = {                 // состояние редактора (живёт, пока открыт /dev/map)
  layer: "detail", mode: "view", cat: "poi",
  map: null, px: null, toPx: null, layerMeta: null,
  objects: [], layers: {}, selected: null,
  draftPts: [], draftLine: null, draftDots: [], handles: [],
  el: {},
};

async function apiJson(path, method, body) {
  const r = await fetch(api(path), {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error((await r.text().catch(() => "")) || String(r.status));
  return r.status === 204 ? null : r.json();
}

async function openDevMap() {
  if (mapCleanup) { mapCleanup(); mapCleanup = null; }
  mapEpoch++;
  home.classList.add("hidden"); detail.classList.add("hidden"); results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="mapmod"><div class="spinner">// ПРОВЕРКА ДОСТУПА</div></div>`;
  window.scrollTo(0, 0);
  if (!ME) return;                     // /me ещё не ответил — loadAuth перезапустит route()
  if (!ME.is_admin) {
    page.innerHTML = `<div class="stub"><div class="stub-code">[ 403 ]</div>
      <div class="stub-title">▸ ДОСТУП ТОЛЬКО ДЛЯ АДМИНОВ</div>
      <a class="stub-back" href="/">◂ НА ГЛАВНУЮ</a></div>`;
    return;
  }
  try {
    if (!mapMeta) {
      [mapMeta] = await Promise.all([
        fetch(api("/map/meta")).then((r) => r.json()), ensureLeaflet()]);
    } else { await ensureLeaflet(); }
  } catch (e) {
    if (location.pathname === "/dev/map")
      page.innerHTML = `<div class="mapmod"><div class="empty">[!] КАРТА НЕДОСТУПНА</div></div>`;
    return;
  }
  if (location.pathname !== "/dev/map") return;
  MAP_CATS = mapMeta.categories || [];
  renderDevMap();
}

function renderDevMap() {
  Object.assign(ed, { mode: "view", selected: null, objects: [], layers: {},
    draftPts: [], draftLine: null, draftDots: [], handles: [] });
  page.innerHTML = `<div class="mapmod maped">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · РЕДАКТОР КАРТЫ</div>
      <div class="section-note">Метки, области и линии для интерактивной карты Зоны</div>
    </div>
    ${devSubnav("map")}
    <div class="maped-bar" id="mapedBar"></div>
    <div class="maped-wrap">
      <div class="map-view" id="mapView"></div>
      <div class="maped-hint" id="mapedHint"></div>
      <div class="maped-panel hidden" id="mapedPanel"></div>
    </div>
    <div class="map-legend" id="mapedStatus"></div>
  </div>`;
  ed.el = { bar: $("mapedBar"), hint: $("mapedHint"),
            panel: $("mapedPanel"), status: $("mapedStatus") };
  ed.el.bar.addEventListener("click", onBarClick);
  ed.el.bar.addEventListener("change", onBarChange);
  ed.el.hint.addEventListener("click", onHintClick);
  initEditorMap();
  renderBar();
  updateHint();
  loadEditorObjects();
}

// ---------- DEV · A/B-тест: форс-предпросмотр варианта для админа ----------
function openDevAb() {
  if (mapCleanup) { mapCleanup(); mapCleanup = null; }
  home.classList.add("hidden"); detail.classList.add("hidden"); results.innerHTML = "";
  page.classList.remove("hidden");
  window.scrollTo(0, 0);
  if (!ME) { page.innerHTML = `<div class="mapmod"><div class="spinner">// ПРОВЕРКА ДОСТУПА</div></div>`; return; }
  if (!ME.is_admin) {
    page.innerHTML = `<div class="stub"><div class="stub-code">[ 403 ]</div>
      <div class="stub-title">▸ ДОСТУП ТОЛЬКО ДЛЯ АДМИНОВ</div>
      <a class="stub-back" href="/">◂ НА ГЛАВНУЮ</a></div>`;
    return;
  }
  renderDevAb();
}

function renderDevAb() {
  const cur = document.documentElement.getAttribute("data-ab");
  const preview = document.documentElement.hasAttribute("data-ab-preview");
  const state = !cur ? "НЕ НАЗНАЧЕН — тест выключен, показывается A"
    : (preview ? `${cur} · ПРИНУДИТЕЛЬНО (предпросмотр)` : `${cur} · обычное назначение сплитом`);
  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · A/B-ТЕСТ ДИЗАЙНА</div>
      <div class="section-note">Форс-предпросмотр варианта для себя. На статистику Метрики не влияет
        и обычных посетителей не касается — их сплит идёт как раньше.</div>
    </div>
    ${devSubnav("ab")}
    <div class="devab">
      <div class="devab-cur">ТЕКУЩИЙ ВАРИАНТ: <b>${escapeHtml(state)}</b></div>
      <div class="devab-btns">
        <button class="devab-btn ${cur === "A" && preview ? "on" : ""}" data-v="A">ПОКАЗАТЬ A · ТЕКУЩИЙ ДИЗАЙН</button>
        <button class="devab-btn ${cur === "B" && preview ? "on" : ""}" data-v="B">ПОКАЗАТЬ B · ТОРГОВЫЙ ТЕРМИНАЛ</button>
        <button class="devab-btn" data-v="off">СБРОС · КАК ОБЫЧНОМУ ЮЗЕРУ</button>
      </div>
      <div class="devab-note">Переключение ставит служебную cookie (только у тебя) и открывает главную с выбранным вариантом.</div>
    </div>
  </div>`;
  page.querySelectorAll(".devab-btn").forEach((b) => b.addEventListener("click", async () => {
    page.querySelectorAll(".devab-btn").forEach((x) => { x.disabled = true; });
    try {
      const r = await fetch(api("/dev/ab"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ variant: b.dataset.v }),
      });
      if (!r.ok) throw new Error(r.status);
      location.href = "/";                 // полная перезагрузка → сервер применит вариант
    } catch (e) {
      page.querySelectorAll(".devab-btn").forEach((x) => { x.disabled = false; });
      const n = page.querySelector(".devab-note");
      if (n) n.textContent = "НЕ УДАЛОСЬ ПЕРЕКЛЮЧИТЬ (нужны права админа). " + e;
    }
  }));
}

// ---------- панель форматирования HTML-полей (гайды, квесты) ----------
// Выделяешь текст в textarea → жмёшь кнопку → тег оборачивает выделенное.
// Без выделения вставляется заготовка с выделенным плейсхолдером — сразу печатай.
const FMT_ACTIONS = [
  { t: "h2", label: "H2 ЗАГОЛОВОК", hint: "Крупный заголовок раздела", block: true, ph: "Заголовок" },
  { t: "h3", label: "H3 ПОДЗАГОЛОВОК", hint: "Подзаголовок внутри раздела", block: true, ph: "Подзаголовок" },
  { t: "p", label: "¶ АБЗАЦ", hint: "Абзац текста", block: true, ph: "Текст абзаца" },
  { t: "b", label: "Ж ЖИРНЫЙ", hint: "Жирный текст (Ctrl+B)", ph: "жирный" },
  { t: "i", label: "К КУРСИВ", hint: "Курсив (Ctrl+I)", ph: "курсив" },
  { t: "s", label: "ЗАЧЁРКНУТЫЙ", hint: "Зачёркнутый текст", ph: "зачёркнутый" },
  { t: "ul", label: "• СПИСОК", hint: "Маркированный список: каждая строка выделения станет пунктом" },
  { t: "ol", label: "1. НУМЕРАЦИЯ", hint: "Нумерованный список: каждая строка выделения станет пунктом" },
  { t: "blockquote", label: "❝ ЦИТАТА", hint: "Врезка-цитата / совет (рамка слева)", block: true, ph: "Текст врезки" },
  { t: "a", label: "🔗 ССЫЛКА", hint: "Ссылка — спросит адрес, выделенный текст станет текстом ссылки" },
  { t: "img", label: "🖼 КАРТИНКА", hint: "Картинка по URL — спросит адрес (или загрузи файл кнопкой ниже)" },
  { t: "hr", label: "— РАЗДЕЛИТЕЛЬ", hint: "Горизонтальная линия между блоками" },
];

// host — контейнер кнопок, ta — textarea, onChange — колбэк (обновить предпросмотр)
function fmtToolbar(host, ta, onChange) {
  const apply = (a) => {
    const s = ta.selectionStart, e = ta.selectionEnd;
    const sel = ta.value.slice(s, e);
    let ins, cs = -1, ce = -1;                 // cs/ce — что выделить после вставки
    if (a.t === "hr") {
      ins = "\n<hr>\n";
    } else if (a.t === "img") {
      const url = prompt("Адрес картинки (URL):", "");
      if (url == null || !url.trim()) return;
      ins = `\n<img src="${url.trim()}" alt="">\n`;
    } else if (a.t === "a") {
      const url = prompt("Адрес ссылки (URL):", "https://");
      if (url == null || !url.trim()) return;
      const body = sel || "текст ссылки";
      const pre = `<a href="${url.trim()}">`;
      ins = `${pre}${body}</a>`;
      if (!sel) { cs = pre.length; ce = cs + body.length; }
    } else if (a.t === "ul" || a.t === "ol") {
      const lines = (sel || "пункт списка").split("\n")
        .map((l) => l.trim()).filter(Boolean);
      ins = `\n<${a.t}>\n${lines.map((l) => `  <li>${l}</li>`).join("\n")}\n</${a.t}>\n`;
    } else {
      const body = sel || a.ph;
      const pre = a.block ? `\n<${a.t}>` : `<${a.t}>`;
      ins = `${pre}${body}</${a.t}>${a.block ? "\n" : ""}`;
      if (!sel) { cs = pre.length; ce = cs + body.length; }
    }
    ta.setRangeText(ins, s, e, "end");
    if (cs >= 0) { ta.selectionStart = s + cs; ta.selectionEnd = s + ce; }
    ta.focus();
    if (onChange) onChange();
  };
  host.classList.add("fmt-bar");
  host.innerHTML = FMT_ACTIONS.map((a, i) =>
    `<button type="button" class="fmt-btn" data-i="${i}" title="${escapeHtml(a.hint)}">${a.label}</button>`).join("")
    + `<span class="fmt-tip">выдели текст → кнопка обернёт его в тег</span>`;
  host.addEventListener("click", (ev) => {
    const b = ev.target.closest(".fmt-btn");
    if (b) apply(FMT_ACTIONS[+b.dataset.i]);
  });
  ta.addEventListener("keydown", (ev) => {
    if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;
    const k = ev.key.toLowerCase();
    if (k === "b" || k === "i") {
      ev.preventDefault();
      apply(FMT_ACTIONS.find((a) => a.t === k));
    }
  });
}

// ---------- ДЕВ · редактор гайдов (только админ) ----------
const devSubnav = (on) => `<div class="dev-subnav">
  <a href="/dev/map"${on === "map" ? ' class="on"' : ""}>КАРТА</a>
  <a href="/dev/ab"${on === "ab" ? ' class="on"' : ""}>A/B-ТЕСТ</a>
  <a href="/dev/guides"${on === "guides" ? ' class="on"' : ""}>ГАЙДЫ</a>
  <a href="/dev/quests"${on === "quests" ? ' class="on"' : ""}>КВЕСТЫ</a>
</div>`;

const todayISO = () => new Date().toISOString().slice(0, 10);

function devGate() {
  if (mapCleanup) { mapCleanup(); mapCleanup = null; }
  home.classList.add("hidden"); detail.classList.add("hidden"); results.innerHTML = "";
  page.classList.remove("hidden");
  window.scrollTo(0, 0);
  if (!ME) { page.innerHTML = `<div class="mapmod"><div class="spinner">// ПРОВЕРКА ДОСТУПА</div></div>`; return false; }
  if (!ME.is_admin) {
    page.innerHTML = `<div class="stub"><div class="stub-code">[ 403 ]</div>
      <div class="stub-title">▸ ДОСТУП ТОЛЬКО ДЛЯ АДМИНОВ</div>
      <a class="stub-back" href="/">◂ НА ГЛАВНУЮ</a></div>`;
    return false;
  }
  return true;
}

async function openDevGuides() {
  if (!devGate()) return;
  await renderDevGuidesList();
}

async function renderDevGuidesList() {
  page.innerHTML = `<div class="mapmod"><div class="spinner">// ЗАГРУЗКА ГАЙДОВ</div></div>`;
  let d;
  try { d = await fetch(api("/admin/guides")).then((r) => r.json()); }
  catch (e) { page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`; return; }
  if (location.pathname !== "/dev/guides") return;
  const rows = (d.items || []).map((g) => `
    <div class="gadm-row">
      <div class="gadm-row-i">
        <div class="gadm-row-t">${escapeHtml(g.title)}${g.published ? "" : ` <span class="gadm-draft">ЧЕРНОВИК</span>`}</div>
        <div class="gadm-row-s">/guides/${escapeHtml(g.slug)} · ${escapeHtml(g.created_at || "")}</div>
      </div>
      <div class="gadm-row-a">
        <a class="gadm-btn" href="/guides/${escapeHtml(g.slug)}" target="_blank" rel="noopener" title="Открыть">↗</a>
        <button class="gadm-btn" data-edit="${escapeHtml(g.slug)}">РЕД.</button>
        <button class="gadm-btn gadm-del" data-del="${escapeHtml(g.slug)}" title="Удалить">✕</button>
      </div>
    </div>`).join("");
  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · ГАЙДЫ</div>
      <div class="section-note">Создание и правка гайдов. Публикация — сразу на /guides, в sitemap и выдачу.</div>
    </div>
    ${devSubnav("guides")}
    <button class="gadm-new" id="gadmNew">＋ НОВЫЙ ГАЙД</button>
    <div class="gadm-list">${rows || `<div class="empty-sm">ГАЙДОВ ПОКА НЕТ.</div>`}</div>
  </div>`;
  $("gadmNew").addEventListener("click", () => renderDevGuideForm(null));
  page.querySelectorAll("[data-edit]").forEach((b) =>
    b.addEventListener("click", () => renderDevGuideForm(b.dataset.edit)));
  page.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm(`Удалить гайд «${b.dataset.del}»? Страница уйдёт с сайта.`)) return;
      await fetch(api(`/admin/guides/${b.dataset.del}`), { method: "DELETE" }).catch(() => {});
      renderDevGuidesList();
    }));
}

async function renderDevGuideForm(slug) {
  let g = { slug: "", title: "", description: "", tags: [], cover: "", html: "",
            created_at: todayISO(), published: true };
  const isNew = !slug;
  if (slug) {
    try { g = await fetch(api(`/admin/guides/${slug}`)).then((r) => r.json()); }
    catch (e) { alert("не удалось загрузить гайд"); return; }
  }
  if (location.pathname !== "/dev/guides") return;
  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · ГАЙДЫ · ${isNew ? "НОВЫЙ" : "РЕДАКТИРОВАНИЕ"}</div>
    </div>
    ${devSubnav("guides")}
    <div class="gform">
      <label class="gform-l">АДРЕС СТРАНИЦЫ · SLUG (латиница, цифры, дефис)
        <input id="gfSlug" value="${escapeHtml(g.slug)}" ${isNew ? "" : "readonly"}
          placeholder="konvert-s-baksami" autocomplete="off"></label>
      <div class="gform-url">URL: <b>/guides/<span id="gfUrl">${escapeHtml(g.slug || "…")}</span></b></div>
      <label class="gform-l">ЗАГОЛОВОК
        <input id="gfTitle" value="${escapeHtml(g.title)}" placeholder="Конверт с баксами: как разменять доллары у торговца"></label>
      <label class="gform-l">КРАТКОЕ ОПИСАНИЕ · для списка и поисковиков (до 400 симв.)
        <textarea id="gfDesc" rows="2">${escapeHtml(g.description)}</textarea></label>
      <label class="gform-l">ТЕГИ · через запятую
        <input id="gfTags" value="${escapeHtml((g.tags || []).join(", "))}" placeholder="Задания, Экономика"></label>
      <div class="gform-row">
        <label class="gform-l">ДАТА <input id="gfDate" type="date" value="${escapeHtml(g.created_at || "")}"></label>
        <label class="gform-chk"><input id="gfPub" type="checkbox" ${g.published ? "checked" : ""}> ОПУБЛИКОВАН</label>
      </div>
      <label class="gform-l">ОБЛОЖКА · URL картинки
        <input id="gfCover" value="${escapeHtml(g.cover)}" placeholder="/guide-uploads/… или /guide-img/…"></label>
      <div class="gform-cover"><img id="gfCoverImg" alt="" src="${escapeHtml(g.cover || "")}" ${g.cover ? "" : 'style="display:none"'}></div>
      <div class="gform-upload">
        <input type="file" id="gfImg" accept="image/png,image/jpeg,image/webp,image/gif">
        <button type="button" class="gadm-btn" id="gfUpload">ЗАГРУЗИТЬ КАРТИНКУ</button>
        <span id="gfUpMsg" class="gform-msg"></span>
      </div>
      <div class="gform-l">ТЕЛО ГАЙДА · HTML — выдели текст и жми кнопки форматирования
        <div id="gfBar"></div>
        <textarea id="gfHtml" rows="18" class="gform-html" spellcheck="false">${escapeHtml(g.html)}</textarea></div>
      <div class="gform-actions">
        <button type="button" class="gadm-save" id="gfSave">СОХРАНИТЬ</button>
        <button type="button" class="gadm-btn" id="gfPrevBtn">ОБНОВИТЬ ПРЕДПРОСМОТР ⟳</button>
        <button type="button" class="gadm-btn" id="gfCancel">◂ К СПИСКУ</button>
        <span id="gfMsg" class="gform-msg"></span>
      </div>
      <div class="gform-prev-h">ПРЕДПРОСМОТР</div>
      <article class="patch-article guide-article"><div class="patch-body gform-prev" id="gfPrev"></div></article>
    </div>
  </div>`;

  const gv = (id) => $(id).value;
  const setCover = (url) => {
    $("gfCover").value = url;
    const im = $("gfCoverImg"); im.src = url; im.style.display = url ? "" : "none";
  };
  if (isNew) $("gfSlug").addEventListener("input", () => {
    $("gfUrl").textContent = $("gfSlug").value.trim().toLowerCase() || "…";
  });
  $("gfCover").addEventListener("input", () => {
    const im = $("gfCoverImg"), v = $("gfCover").value.trim();
    im.src = v; im.style.display = v ? "" : "none";
  });
  const renderPrev = () => { $("gfPrev").innerHTML = gv("gfHtml"); };
  fmtToolbar($("gfBar"), $("gfHtml"), renderPrev);
  $("gfPrevBtn").addEventListener("click", renderPrev);
  renderPrev();
  $("gfCancel").addEventListener("click", () => renderDevGuidesList());

  $("gfUpload").addEventListener("click", () => {
    const f = $("gfImg").files[0], msg = $("gfUpMsg");
    if (!f) { msg.textContent = "выбери файл"; return; }
    const rd = new FileReader();
    rd.onload = async () => {
      msg.textContent = "загрузка…";
      try {
        const r = await fetch(api("/admin/guides/image"), {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data: rd.result, filename: f.name }),
        });
        const j = await r.json();
        if (!r.ok) { msg.textContent = j.detail || "ошибка загрузки"; return; }
        const ta = $("gfHtml");
        ta.value = `${ta.value}\n<img src="${j.url}" alt="">\n`;
        if (!$("gfCover").value.trim()) setCover(j.url);
        msg.innerHTML = `готово, вставлено в тело: <b>${escapeHtml(j.url)}</b>`;
        renderPrev();
      } catch (e) { msg.textContent = "ошибка сети"; }
    };
    rd.readAsDataURL(f);
  });

  $("gfSave").addEventListener("click", async () => {
    const slugV = gv("gfSlug").trim().toLowerCase(), msg = $("gfMsg");
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slugV)) { msg.textContent = "адрес: латиница, цифры, дефис"; return; }
    if (!gv("gfTitle").trim()) { msg.textContent = "нужен заголовок"; return; }
    const body = {
      slug: slugV, title: gv("gfTitle").trim(), description: gv("gfDesc").trim(),
      tags: gv("gfTags").split(",").map((t) => t.trim()).filter(Boolean),
      cover: gv("gfCover").trim(), html: gv("gfHtml"),
      created_at: gv("gfDate"), published: $("gfPub").checked, is_new: isNew,
    };
    $("gfSave").disabled = true; msg.textContent = "сохранение…";
    try {
      const r = await fetch(api("/admin/guides"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) { msg.textContent = j.detail || "ошибка сохранения"; $("gfSave").disabled = false; return; }
      renderDevGuidesList();
    } catch (e) { msg.textContent = "ошибка сети"; $("gfSave").disabled = false; }
  });
}

// ---------- ДЕВ · редактор квестов (только админ) ----------
async function openDevQuests() {
  if (!devGate()) return;
  const editId = new URLSearchParams(location.search).get("edit");
  if (editId && /^\d+$/.test(editId)) { await renderDevQuestForm(+editId); return; }
  await renderDevQuestsList();
}

// уйти из формы: убить Leaflet формы и вернуть десктопный масштаб
function qfCleanup() {
  if (mapCleanup) { mapCleanup(); mapCleanup = null; }
  document.documentElement.classList.remove("on-map");
}

async function renderDevQuestsList() {
  qfCleanup();
  if (location.search) history.replaceState(null, "", "/dev/quests");
  page.innerHTML = `<div class="mapmod"><div class="spinner">// ЗАГРУЗКА КВЕСТОВ</div></div>`;
  let d;
  try { d = await fetch(api("/quests")).then((r) => r.json()); }
  catch (e) { page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`; return; }
  if (location.pathname !== "/dev/quests") return;
  questData = d;
  const titleOf = (pid) => {
    const p = d.items.find((x) => x.id === pid);
    return p ? p.title : `#${pid}`;
  };
  const groups = d.factions.map((f) => {
    const rows = d.items.filter((q) => q.faction === f.id).map((q) => `
      <div class="gadm-row">
        <div class="gadm-row-i">
          <div class="gadm-row-t">${q.kind === "main" ? `<span style="color:var(--amber)">★</span> ` : ""}${escapeHtml(q.title)}${q.published ? "" : ` <span class="gadm-draft">ЧЕРНОВИК</span>`}</div>
          <div class="gadm-row-s">#${q.id} · ${q.parents.length
            ? `после: ${escapeHtml(q.parents.map(titleOf).join(", "))}`
            : "старт линейки"}${q.has_map ? " · 📍 карта" : ""}</div>
        </div>
        <div class="gadm-row-a">
          <a class="gadm-btn" href="/quests/${q.id}" target="_blank" rel="noopener" title="Открыть на сайте">↗</a>
          <button class="gadm-btn" data-edit="${q.id}">РЕД.</button>
          <button class="gadm-btn gadm-del" data-del="${q.id}" data-t="${escapeHtml(q.title)}" title="Удалить">✕</button>
        </div>
      </div>`).join("");
    return `<div class="qadm-f" style="--fc:${f.color}">${escapeHtml(f.name.toUpperCase())}
        <span>${d.items.filter((q) => q.faction === f.id).length}</span></div>
      ${rows || `<div class="empty-sm" style="margin:4px 0 10px">пусто</div>`}`;
  }).join("");
  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · КВЕСТЫ</div>
      <div class="section-note">Блок-схема строится сама по связям «после». Публикация — сразу на /quests.</div>
    </div>
    ${devSubnav("quests")}
    <button class="gadm-new" id="qadmNew">＋ НОВЫЙ КВЕСТ</button>
    <div class="gadm-list">${groups}</div>
  </div>`;
  $("qadmNew").addEventListener("click", () => renderDevQuestForm(null));
  page.querySelectorAll("[data-edit]").forEach((b) =>
    b.addEventListener("click", () => renderDevQuestForm(+b.dataset.edit)));
  page.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm(`Удалить квест «${b.dataset.t}»? Связи на него у других квестов очистятся.`)) return;
      await fetch(api(`/admin/quests/${b.dataset.del}`), { method: "DELETE" }).catch(() => {});
      renderDevQuestsList();
    }));
}

async function renderDevQuestForm(qid) {
  qfCleanup();
  page.innerHTML = `<div class="mapmod"><div class="spinner">// ЗАГРУЗКА</div></div>`;
  let all, q = { id: null, title: "", faction: "stalkers", kind: "main", summary: "",
                 reward: "", html: "", parents: [], map_layer: "", map_points: [],
                 sort: 0, published: false };
  try {
    all = await fetch(api("/quests")).then((r) => r.json());
    if (qid != null) {
      const r = await fetch(api(`/quests/${qid}`));
      if (!r.ok) throw new Error();
      q = await r.json();
    }
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] КВЕСТ НЕ ЗАГРУЗИЛСЯ</div>`;
    return;
  }
  if (location.pathname !== "/dev/quests") return;
  questData = all;
  const isNew = qid == null;

  const factionOpts = all.factions.map((f) =>
    `<option value="${f.id}"${q.faction === f.id ? " selected" : ""}>${escapeHtml(f.name)}</option>`).join("");
  const parentsBox = all.factions.map((f) => {
    const opts = all.items.filter((x) => x.faction === f.id && x.id !== qid).map((x) => `
      <label class="qadm-p"><input type="checkbox" data-pid="${x.id}"
          ${q.parents.includes(x.id) ? " checked" : ""}>
        ${x.kind === "main" ? "★ " : ""}${escapeHtml(x.title)}${x.published ? "" : " (черновик)"}</label>`).join("");
    return opts ? `<div class="qadm-pf" style="--fc:${f.color}">${escapeHtml(f.name.toUpperCase())}</div>${opts}` : "";
  }).join("");
  const terrOpts = `<option value="">ВСЯ КАРТА</option>` + ((mapMeta && mapMeta.territories) || [])
    .filter((t) => t.bbox)
    .map((t) => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join("");

  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · КВЕСТЫ · ${isNew ? "НОВЫЙ" : `РЕДАКТИРОВАНИЕ #${qid}`}</div>
    </div>
    ${devSubnav("quests")}
    <div class="gform">
      <label class="gform-l">НАЗВАНИЕ КВЕСТА
        <input id="qfTitle" value="${escapeHtml(q.title)}" placeholder="Например: Первый выход в Зону"></label>
      <div class="gform-row">
        <label class="gform-l">ЛИНЕЙКА <select id="qfFaction">${factionOpts}</select></label>
        <label class="gform-l">ТИП <select id="qfKind">
          <option value="main"${q.kind === "main" ? " selected" : ""}>Основной</option>
          <option value="side"${q.kind === "side" ? " selected" : ""}>Побочный</option>
        </select></label>
        <label class="gform-l" title="Ветки на одном уровне сортируются по этому числу (меньше — выше)">
          ПОРЯДОК <input id="qfSort" type="number" value="${q.sort || 0}" style="width:80px"></label>
        <label class="gform-chk"><input id="qfPub" type="checkbox"${q.published ? " checked" : ""}> ОПУБЛИКОВАН</label>
      </div>
      <div class="gform-l">ОТКРЫВАЕТСЯ ПОСЛЕ · отметь квесты-предшественники (стрелки на схеме)
        <div class="qadm-parents" id="qfParents">${parentsBox || `<div class="empty-sm">других квестов пока нет — этот будет стартовым</div>`}</div>
      </div>
      <label class="gform-l">КРАТКО · подсказка при наведении на блок схемы (до 400 симв.)
        <textarea id="qfSummary" rows="2">${escapeHtml(q.summary)}</textarea></label>
      <label class="gform-l">НАГРАДА · текст (деньги, предметы, репутация)
        <input id="qfReward" value="${escapeHtml(q.reward)}" placeholder="15 000 ₽ · Аптечка армейская ×2 · +репутация у барменов"></label>
      <div class="gform-l">ПРОХОЖДЕНИЕ · HTML — выдели текст и жми кнопки форматирования
        <div id="qfBar"></div>
        <textarea id="qfHtml" rows="14" class="gform-html" spellcheck="false">${escapeHtml(q.html)}</textarea>
      </div>
      <div class="gform-upload">
        <input type="file" id="qfImg" accept="image/png,image/jpeg,image/webp,image/gif">
        <button type="button" class="gadm-btn" id="qfUpload">ЗАГРУЗИТЬ КАРТИНКУ В ТЕКСТ</button>
        <span id="qfUpMsg" class="gform-msg"></span>
      </div>
      <div class="gform-row">
        <label class="gform-l">ТОЧКИ НА КАРТЕ · слой
          <select id="qfLayer">
            <option value=""${q.map_layer ? "" : " selected"}>БЕЗ КАРТЫ</option>
            <option value="global"${q.map_layer === "global" ? " selected" : ""}>ГЛОБАЛЬНАЯ</option>
            <option value="detail"${q.map_layer === "detail" ? " selected" : ""}>ДЕТАЛЬНАЯ</option>
          </select></label>
        <label class="gform-l hidden" id="qfGotoWrap">ПЕРЕЙТИ К ТЕРРИТОРИИ
          <select id="qfGoto">${terrOpts}</select></label>
      </div>
      <div id="qfMapBlock" class="hidden">
        <div class="qadm-maphint">Клик по карте — добавить точку. Маркеры можно перетаскивать.
          Подписи и удаление — в списке под картой; в модале квеста точки нумеруются так же.</div>
        <div class="map-view qadm-map" id="qfMap"></div>
        <div class="qadm-pts" id="qfPts"></div>
      </div>
      <div class="gform-actions">
        <button type="button" class="gadm-save" id="qfSave">СОХРАНИТЬ</button>
        <button type="button" class="gadm-btn" id="qfPrevBtn">ОБНОВИТЬ ПРЕДПРОСМОТР ⟳</button>
        <button type="button" class="gadm-btn" id="qfCancel">◂ К СПИСКУ</button>
        <span id="qfMsg" class="gform-msg"></span>
      </div>
      <div class="gform-prev-h">ПРЕДПРОСМОТР ПРОХОЖДЕНИЯ</div>
      <article class="patch-article guide-article"><div class="patch-body gform-prev" id="qfPrev"></div></article>
    </div>
  </div>`;

  // --- прохождение: панель форматирования + предпросмотр + картинки ---
  const renderPrev = () => { $("qfPrev").innerHTML = $("qfHtml").value; };
  fmtToolbar($("qfBar"), $("qfHtml"), renderPrev);
  $("qfPrevBtn").addEventListener("click", renderPrev);
  renderPrev();
  $("qfCancel").addEventListener("click", () => renderDevQuestsList());
  $("qfUpload").addEventListener("click", () => {
    const f = $("qfImg").files[0], msg = $("qfUpMsg");
    if (!f) { msg.textContent = "выбери файл"; return; }
    const rd = new FileReader();
    rd.onload = async () => {
      msg.textContent = "загрузка…";
      try {
        const r = await fetch(api("/admin/guides/image"), {   // общий загрузчик картинок
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data: rd.result, filename: f.name }),
        });
        const j = await r.json();
        if (!r.ok) { msg.textContent = j.detail || "ошибка загрузки"; return; }
        const ta = $("qfHtml");
        ta.value = `${ta.value}\n<img src="${j.url}" alt="">\n`;
        msg.innerHTML = `готово, вставлено в текст: <b>${escapeHtml(j.url)}</b>`;
        renderPrev();
      } catch (e) { msg.textContent = "ошибка сети"; }
    };
    rd.readAsDataURL(f);
  });

  // --- точки на карте: встроенный Leaflet-редактор ---
  const pts = (q.map_points || []).map((p) => [p[0], p[1], p[2] || ""]);
  let qem = null;                                // {map, px, toPx} текущего слоя
  let qemLayer = "";                             // слой, под который создана карта
  let qemMarkers = [];

  const ptIcon = (i) => L.divIcon({ className: "",
    html: `<div class="qm-pt">${i + 1}</div>`, iconSize: [24, 24], iconAnchor: [12, 12] });

  const renderPtList = () => {
    const box = $("qfPts");
    if (!box) return;
    box.innerHTML = pts.map((p, i) => `
      <div class="qadm-pt-row">
        <span class="qadm-pt-n">${i + 1}</span>
        <input data-pi="${i}" value="${escapeHtml(p[2])}" placeholder="подпись точки — например: забрать записку из тайника">
        <button type="button" class="gadm-btn gadm-del" data-px="${i}" title="Удалить точку">✕</button>
      </div>`).join("") || `<div class="empty-sm">точек нет — кликни по карте</div>`;
    box.querySelectorAll("input[data-pi]").forEach((inp) =>
      inp.addEventListener("input", () => { pts[+inp.dataset.pi][2] = inp.value.slice(0, 120); }));
    box.querySelectorAll("[data-px]").forEach((b) =>
      b.addEventListener("click", () => { pts.splice(+b.dataset.px, 1); redrawPts(); }));
  };

  const redrawPts = () => {
    if (!qem) { renderPtList(); return; }
    qemMarkers.forEach((m) => qem.map.removeLayer(m));
    qemMarkers = pts.map((p, i) => {
      const m = L.marker(qem.px(p[0], p[1]), { draggable: true, icon: ptIcon(i) })
        .addTo(qem.map);
      m.on("dragend", () => {
        const c = qem.toPx(m.getLatLng());
        p[0] = c[0]; p[1] = c[1];
      });
      return m;
    });
    renderPtList();
  };

  async function initQuestEditorMap(layer) {
    try {
      if (!mapMeta) {
        [mapMeta] = await Promise.all([
          fetch(api("/map/meta")).then((r) => r.json()), ensureLeaflet()]);
        MAP_CATS = mapMeta.categories || [];
      } else {
        await ensureLeaflet();
      }
    } catch (e) { return; }
    if (location.pathname !== "/dev/quests" || $("qfLayer").value !== layer) return;
    if (qem && qemLayer === layer) return;
    // территории могли не попасть в форму, если mapMeta грузился только что
    const goto = $("qfGoto");
    if (goto && goto.options.length <= 1) {
      goto.innerHTML = `<option value="">ВСЯ КАРТА</option>` + (mapMeta.territories || [])
        .filter((t) => t.bbox)
        .map((t) => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join("");
    }
    if (mapCleanup) { mapCleanup(); mapCleanup = null; }   // карта предыдущего слоя
    qemMarkers = [];
    // территории есть только на детальной пирамиде
    $("qfGotoWrap").classList.toggle("hidden", layer !== "detail");
    document.documentElement.classList.add("on-map");      // зум 1.2 ломает клики Leaflet
    const lm = mapMeta[layer];
    qem = makeTileMap(lm, [0, 0, lm.w, lm.h], "qfMap");
    qemLayer = layer;
    qem.map.on("click", (e) => {
      const c = qem.toPx(e.latlng);
      pts.push([c[0], c[1], ""]);
      redrawPts();
    });
    if (pts.length) {
      const b = L.latLngBounds(pts.map((p) => qem.px(p[0], p[1])));
      qem.map.fitBounds(b.pad(0.5), { maxZoom: lm.max_zoom - 1 });
    }
    redrawPts();
    setTimeout(() => { if (qem) qem.map.invalidateSize(); }, 60);
  }

  const syncMapBlock = () => {
    const layer = $("qfLayer").value;
    $("qfMapBlock").classList.toggle("hidden", !layer);
    if (!layer) {
      if (mapCleanup) { mapCleanup(); mapCleanup = null; }
      document.documentElement.classList.remove("on-map");
      qem = null; qemLayer = ""; qemMarkers = [];
      return;
    }
    initQuestEditorMap(layer);
  };
  $("qfLayer").addEventListener("change", () => {
    const layer = $("qfLayer").value;
    if (pts.length && layer !== qemLayer) {
      if (!confirm("Сменить слой? Координаты точек привязаны к слою — текущие точки будут удалены.")) {
        $("qfLayer").value = qemLayer || "";
        return;
      }
      pts.length = 0;
    }
    syncMapBlock();
  });
  $("qfGoto").addEventListener("change", () => {
    const t = ((mapMeta && mapMeta.territories) || []).find((x) => x.id === $("qfGoto").value);
    if (qem) {
      const [x0, y0, x1, y1] = t && t.bbox ? t.bbox : [0, 0, qem.layerMeta.w, qem.layerMeta.h];
      qem.map.fitBounds(L.latLngBounds(qem.px(x0, y0), qem.px(x1, y1)));
    }
  });
  syncMapBlock();

  // --- сохранение ---
  $("qfSave").addEventListener("click", async () => {
    const msg = $("qfMsg");
    if (!$("qfTitle").value.trim()) { msg.textContent = "нужно название"; return; }
    const parents = [...page.querySelectorAll("#qfParents input:checked")]
      .map((c) => +c.dataset.pid);
    const layer = $("qfLayer").value;
    const body = {
      id: qid, title: $("qfTitle").value.trim(),
      faction: $("qfFaction").value, kind: $("qfKind").value,
      summary: $("qfSummary").value.trim(), reward: $("qfReward").value.trim(),
      html: $("qfHtml").value, parents,
      map_layer: layer, map_points: layer ? pts : [],
      sort: +$("qfSort").value || 0, published: $("qfPub").checked,
    };
    $("qfSave").disabled = true;
    msg.textContent = "сохранение…";
    try {
      const r = await fetch(api("/admin/quests"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) {
        msg.textContent = j.detail || "ошибка сохранения";
        $("qfSave").disabled = false;
        return;
      }
      renderDevQuestsList();
    } catch (e) {
      msg.textContent = "ошибка сети";
      $("qfSave").disabled = false;
    }
  });
}

function initEditorMap() {
  const lm = mapMeta[ed.layer];
  const { map, px, toPx } = makeTileMap(lm, [0, 0, lm.w, lm.h]);
  ed.map = map; ed.px = px; ed.toPx = toPx; ed.layerMeta = lm;
  map.doubleClickZoom.disable();       // dblclick замыкает область/линию
  map.on("click", onMapClick);
  map.on("dblclick", () => {
    if (ed.mode === "area" || ed.mode === "line") finishDraft();
  });
}

// ---------- панель инструментов ----------
function renderBar() {
  const tool = (m, label) =>
    `<button class="mp-tool ${ed.mode === m ? "on" : ""}" data-mode="${m}">${label}</button>`;
  const cats = MAP_CATS.map((c) =>
    `<button class="mp-cat ${ed.cat === c.id ? "on" : ""}" data-cat="${c.id}"
       title="${escapeHtml(c.name)}" style="--mo:${c.color}"><span>${c.emoji}</span></button>`).join("");
  const terrOpts = (mapMeta.territories || []).filter((t) => t.bbox)
    .map((t) => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join("");
  ed.el.bar.innerHTML = `
    <div class="mp-group">
      ${tool("view", "▮ КУРСОР")}${tool("marker", "● МЕТКА")}
      ${tool("area", "▱ ОБЛАСТЬ")}${tool("line", "╱ ЛИНИЯ")}
    </div>
    <div class="mp-group mp-cats ${ed.mode === "marker" ? "" : "off"}">${cats}</div>
    <div class="mp-group">
      <span class="mp-lbl">СЛОЙ</span>
      <button class="mp-layer ${ed.layer === "detail" ? "on" : ""}" data-layer="detail">ДЕТАЛЬНАЯ</button>
      <button class="mp-layer ${ed.layer === "global" ? "on" : ""}" data-layer="global">ГЛОБАЛЬНАЯ</button>
    </div>
    ${ed.layer === "detail" ? `<div class="mp-group">
      <span class="mp-lbl">К ТЕРРИТОРИИ</span>
      <select class="mp-terr" data-role="terr"><option value="">— выбрать —</option>${terrOpts}</select>
    </div>` : ""}`;
}

function onBarClick(e) {
  const t = e.target.closest("[data-mode],[data-cat],[data-layer]");
  if (!t) return;
  if (t.dataset.mode) setMode(t.dataset.mode);
  else if (t.dataset.cat) { ed.cat = t.dataset.cat; setMode("marker"); }
  else if (t.dataset.layer) switchLayer(t.dataset.layer);
}

function onBarChange(e) {
  const sel = e.target.closest('[data-role="terr"]');
  if (!sel || !sel.value) return;
  const t = (mapMeta.territories || []).find((x) => x.id === sel.value);
  if (t && t.bbox) {
    ed.map.fitBounds(L.latLngBounds(
      ed.px(t.bbox[0], t.bbox[1]), ed.px(t.bbox[2], t.bbox[3])));
  }
  sel.value = "";
}

function setMode(m) {
  if ((ed.mode === "area" || ed.mode === "line") && m !== ed.mode) clearDraft();
  ed.mode = m;
  if (m !== "view") selectObject(null);
  renderBar();
  updateHint();
  document.documentElement.classList.toggle("map-drawing", m !== "view");
}

function switchLayer(l) {
  if (l === ed.layer) return;
  clearDraft();
  if (mapCleanup) { mapCleanup(); mapCleanup = null; }
  ed.layer = l; ed.mode = "view"; ed.selected = null;
  ed.objects = []; ed.layers = {}; ed.handles = [];
  ed.el.panel.classList.add("hidden");
  initEditorMap();
  renderBar();
  updateHint();
  loadEditorObjects();
}

// ---------- подсказка / рисование области-линии ----------
function updateHint() {
  const drawing = (ed.mode === "area" || ed.mode === "line") && ed.draftPts.length;
  const need = ed.mode === "area" ? 3 : 2;
  let txt;
  if (ed.mode === "marker") {
    txt = `Клик по карте — поставить метку «${catById(ed.cat).name}».`;
  } else if (ed.mode === "area" || ed.mode === "line") {
    txt = `Клик — вершина. Двойной клик или «ГОТОВО» — завершить (нужно ≥${need}). Точек: ${ed.draftPts.length}.`;
  } else {
    txt = "Клик по объекту — редактировать. Тяни метку или вершины — переместить.";
  }
  ed.el.hint.innerHTML = `<span class="mh-txt">${txt}</span>` + (drawing
    ? `<button class="mh-btn ok" data-act="finish">ГОТОВО</button>
       <button class="mh-btn" data-act="cancel">ОТМЕНА</button>` : "");
}

function onHintClick(e) {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  if (b.dataset.act === "finish") finishDraft();
  else if (b.dataset.act === "cancel") { clearDraft(); updateHint(); }
}

function refreshDraft() {
  const latlngs = ed.draftPts.map((p) => ed.px(p[0], p[1]));
  if (ed.draftLine) ed.map.removeLayer(ed.draftLine);
  ed.draftLine = (ed.mode === "area" ? L.polygon : L.polyline)(latlngs,
    { color: "#ffb84d", weight: 2, dashArray: "5,5", interactive: false,
      fillOpacity: ed.mode === "area" ? 0.08 : 0 }).addTo(ed.map);
  ed.draftDots.forEach((d) => ed.map.removeLayer(d));
  ed.draftDots = latlngs.map((ll) =>
    L.marker(ll, { icon: vertexIcon(), keyboard: false, interactive: false }).addTo(ed.map));
  updateHint();
}

function clearDraft() {
  if (ed.draftLine) { ed.map.removeLayer(ed.draftLine); ed.draftLine = null; }
  ed.draftDots.forEach((d) => ed.map.removeLayer(d));
  ed.draftDots = [];
  ed.draftPts = [];
}

async function finishDraft() {
  const need = ed.mode === "area" ? 3 : 2;
  if (ed.draftPts.length < need) { flashHint(`нужно ≥${need} точек`); return; }
  const kind = ed.mode, pts = ed.draftPts.slice();
  clearDraft();
  await createObject({ kind, layer: ed.layer, geometry: pts,
    color: kind === "area" ? "#7ce68e" : "#9ecbff",
    name: "", description: "", published: false });
  setMode("view");
}

function flashHint(msg) {
  ed.el.hint.querySelector(".mh-txt").textContent = "⚠ " + msg;
}

// ---------- клики по карте ----------
function onMapClick(e) {
  if (ed.mode === "marker") {
    createObject({ kind: "marker", layer: ed.layer, category: ed.cat,
      geometry: ed.toPx(e.latlng), name: "", description: "", published: false });
  } else if (ed.mode === "area" || ed.mode === "line") {
    ed.draftPts.push(ed.toPx(e.latlng));
    refreshDraft();
  } else {
    selectObject(null);              // клик по пустому месту — снять выделение
  }
}

// ---------- CRUD объектов ----------
async function loadEditorObjects() {
  clearAllLayers();
  try {
    const d = await fetch(api(`/map/objects?layer=${ed.layer}`)).then((r) => r.json());
    ed.objects = d.objects || [];
  } catch (e) { ed.objects = []; }
  ed.objects.forEach(addObjectLayer);
  updateStatus();
}

function clearAllLayers() {
  Object.values(ed.layers).forEach((l) => ed.map.removeLayer(l));
  ed.layers = {};
  clearHandles();
}

async function createObject(payload) {
  try {
    const o = await apiJson("/map/objects", "POST", payload);
    ed.objects.push(o);
    addObjectLayer(o);
    selectObject(o.id);
    updateStatus();
  } catch (e) { alert("Не удалось создать объект: " + e.message); }
}

// (Пере)создать слой объекта на карте с актуальным выделением и хэндлерами.
function addObjectLayer(o) {
  if (ed.layers[o.id]) ed.map.removeLayer(ed.layers[o.id]);
  const layer = renderMapObject(o, {
    map: ed.map, px: ed.px, editable: true, selected: ed.selected === o.id });
  ed.layers[o.id] = layer;
  layer.on("click", (e) => { L.DomEvent.stop(e); if (ed.mode === "view") selectObject(o.id); });
  if (o.kind === "marker") {
    layer.on("dragend", async () => {
      o.geometry = ed.toPx(layer.getLatLng());
      await saveFields(o, { geometry: o.geometry });
    });
  }
  return layer;
}

function reRenderObject(o) {
  addObjectLayer(o);
  if (ed.selected === o.id) showHandles(o);
}

async function saveFields(o, fields) {
  try {
    const upd = await apiJson(`/map/objects/${o.id}`, "PUT", fields);
    Object.assign(o, upd);
    return true;
  } catch (e) { alert("Не удалось сохранить: " + e.message); return false; }
}

// ---------- выделение и панель редактирования ----------
ed.byId = (id) => ed.objects.find((o) => o.id === id);

function selectObject(id) {
  if (ed.selected === id && id != null) return;
  const prev = ed.selected;
  ed.selected = id;
  clearHandles();
  if (prev != null && ed.byId(prev)) addObjectLayer(ed.byId(prev));   // снять подсветку
  const o = id != null ? ed.byId(id) : null;
  if (!o) { ed.el.panel.classList.add("hidden"); return; }
  addObjectLayer(o);                                                  // подсветить
  showHandles(o);
  renderPanel(o);
}

function renderPanel(o) {
  const isMarker = o.kind === "marker";
  const catSel = isMarker ? `<label class="mp-f"><span>Категория</span>
    <select id="pfCat">${MAP_CATS.map((c) =>
      `<option value="${c.id}" ${o.category === c.id ? "selected" : ""}>${c.emoji} ${escapeHtml(c.name)}</option>`).join("")}</select></label>` : "";
  const colorF = !isMarker ? `<label class="mp-f"><span>Цвет</span>
    <input type="color" id="pfColor" value="${o.color || (o.kind === "area" ? "#7ce68e" : "#9ecbff")}"></label>` : "";
  ed.el.panel.innerHTML = `
    <div class="mp-p-head"><span>${KIND_LABEL[o.kind]} #${o.id}</span>
      <button class="mp-x" id="pfClose" title="Закрыть">✕</button></div>
    <label class="mp-f"><span>Название</span>
      <input id="pfName" maxlength="120" value="${escapeHtml(o.name || "")}"
        placeholder="${isMarker ? escapeHtml(catById(o.category).name) : ""}"></label>
    ${catSel}${colorF}
    <label class="mp-f"><span>Описание</span>
      <textarea id="pfDesc" rows="4" maxlength="2000" placeholder="Показывается во всплывашке">${escapeHtml(o.description || "")}</textarea></label>
    <label class="mp-chk"><input type="checkbox" id="pfPub" ${o.published ? "checked" : ""}>
      <span>Опубликовано — видно всем на /map</span></label>
    <div class="mp-p-actions">
      <button class="mp-save" id="pfSave">СОХРАНИТЬ</button>
      <button class="mp-del" id="pfDel">УДАЛИТЬ</button>
    </div>
    <div class="mp-p-msg" id="pfMsg"></div>`;
  ed.el.panel.classList.remove("hidden");
  $("pfClose").addEventListener("click", () => selectObject(null));
  $("pfSave").addEventListener("click", () => savePanel(o));
  $("pfDel").addEventListener("click", () => deleteObject(o));
  // живой предпросмотр категории/цвета
  if (isMarker) $("pfCat").addEventListener("change", (e) => {
    o.category = e.target.value; reRenderObject(o);
  });
  else $("pfColor").addEventListener("input", (e) => {
    o.color = e.target.value; reRenderObject(o);
  });
}

async function savePanel(o) {
  const fields = {
    name: $("pfName").value.trim(),
    description: $("pfDesc").value.trim(),
    published: $("pfPub").checked,
  };
  if (o.kind === "marker") fields.category = $("pfCat").value;
  else fields.color = $("pfColor").value;
  const ok = await saveFields(o, fields);
  if (ok) {
    reRenderObject(o);
    updateStatus();
    const msg = $("pfMsg");
    if (msg) { msg.textContent = "✓ сохранено"; msg.className = "mp-p-msg ok";
      setTimeout(() => { if ($("pfMsg") === msg) msg.textContent = ""; }, 1800); }
  }
}

async function deleteObject(o) {
  if (!confirm(`Удалить ${KIND_LABEL[o.kind].toLowerCase()} «${o.name || o.id}»?`)) return;
  try {
    await apiJson(`/map/objects/${o.id}`, "DELETE");
    if (ed.layers[o.id]) ed.map.removeLayer(ed.layers[o.id]);
    delete ed.layers[o.id];
    ed.objects = ed.objects.filter((x) => x.id !== o.id);
    selectObject(null);
    updateStatus();
  } catch (e) { alert("Не удалось удалить: " + e.message); }
}

// ---------- хэндлы вершин области/линии ----------
function vertexIcon() {
  return L.divIcon({ className: "", html: `<div class="mo-vtx"></div>`,
    iconSize: [12, 12], iconAnchor: [6, 6] });
}

function showHandles(o) {
  clearHandles();
  if (o.kind === "marker") return;
  o.geometry.forEach((p, i) => {
    const h = L.marker(ed.px(p[0], p[1]),
      { icon: vertexIcon(), draggable: true, keyboard: false, zIndexOffset: 1000 });
    h.on("drag", () => {
      o.geometry[i] = ed.toPx(h.getLatLng());
      const layer = ed.layers[o.id];
      if (layer && layer.setLatLngs) layer.setLatLngs(o.geometry.map((q) => ed.px(q[0], q[1])));
    });
    h.on("dragend", () => saveFields(o, { geometry: o.geometry }));
    h.addTo(ed.map);
    ed.handles.push(h);
  });
}

function clearHandles() {
  ed.handles.forEach((h) => ed.map.removeLayer(h));
  ed.handles = [];
}

function updateStatus() {
  const total = ed.objects.length;
  const drafts = ed.objects.filter((o) => !o.published).length;
  const n = (k) => ed.objects.filter((o) => o.kind === k).length;
  ed.el.status.innerHTML = `Слой: <b>${ed.layer === "detail" ? "детальная" : "глобальная"}</b> ·
    объектов: <b>${total}</b> (метки ${n("marker")}, области ${n("area")}, линии ${n("line")}) ·
    черновиков: <b>${drafts}</b>. Черновики видны только тебе (пунктир/полупрозрачные),
    опубликованные — всем на <a href="/map">/map</a>.`;
}

// ---------- разделы в разработке: заглушки с описанием модуля ----------
const PAGES = {};

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
    <a class="stub-back" href="/">◂ НА ГЛАВНУЮ</a>
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
  gModalClose();    // навигация закрывает модалы разделов
  const path = location.pathname;
  const strip = document.querySelector(".search-strip");
  let mm;

  // десктопный масштаб 120% ломает координаты Leaflet — на карте отключаем
  const onMap = path.startsWith("/map") || path === "/dev/map";
  document.documentElement.classList.toggle("on-map", onMap);
  document.documentElement.classList.remove("map-drawing");

  if (mapCleanup && !onMap) { mapCleanup(); mapCleanup = null; }
  if (path === "/dev") { navigate("/dev/map", { replace: true }); return; }
  if (path === "/dev/map") {
    strip.classList.add("hidden");
    setNav("dev"); openDevMap(); return;
  }
  if (path === "/dev/ab") {
    strip.classList.add("hidden");
    setNav("dev"); openDevAb(); return;
  }
  if (path === "/dev/guides") {
    strip.classList.add("hidden");
    setNav("dev"); openDevGuides(); return;
  }
  if (path === "/dev/quests") {
    strip.classList.add("hidden");
    setNav("dev"); openDevQuests(); return;
  }
  if ((mm = path.match(/^\/map(?:\/([a-z0-9_-]+))?$/))) {
    strip.classList.add("hidden");
    setNav("map"); openMap(mm[1] || null); return;
  }

  if (path === "/market") {
    strip.classList.add("hidden");
    setNav("market"); openMarket(); return;
  }
  if (path === "/barter") {
    strip.classList.add("hidden"); detail.classList.add("hidden");
    setNav("barter"); openBarter(); return;
  }
  if (path === "/obmen") {
    strip.classList.add("hidden"); detail.classList.add("hidden");
    setNav("obmen"); openObmen(); return;
  }
  if (path === "/patches") {
    strip.classList.add("hidden"); detail.classList.add("hidden");
    setNav("patches"); openPatches(); return;
  }
  if ((mm = path.match(/^\/patches\/(\d+)$/))) {
    strip.classList.add("hidden"); detail.classList.add("hidden");
    setNav("patches"); openPatch(mm[1]); return;
  }
  if ((mm = path.match(/^\/quests(?:\/(\d+))?$/))) {
    strip.classList.add("hidden"); detail.classList.add("hidden");
    setNav("quests"); openQuests(mm[1] ? +mm[1] : null); return;
  }
  if (path === "/guides") {
    strip.classList.add("hidden"); detail.classList.add("hidden");
    setNav("guides"); openGuides(); return;
  }
  if ((mm = path.match(/^\/guides\/([a-z0-9-]+)$/))) {
    strip.classList.add("hidden"); detail.classList.add("hidden");
    setNav("guides"); openGuide(mm[1]); return;
  }
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

  // "/" — дашборд-главная
  if (path === "/") {
    strip.classList.add("hidden"); page.classList.add("hidden");
    setNav("home");
    detail.classList.add("hidden"); results.innerHTML = "";
    home.classList.remove("hidden");
    loadDashboard(); return;
  }

  // крафт-контекст: раздел / лендинг / поиск / карточка / профиль
  strip.classList.remove("hidden");
  page.classList.add("hidden");
  setNav("craft");
  if (path === "/profile") { openProfile(); return; }
  if ((mm = path.match(/^\/item\/(.+)$/))) { openItem(decodeURIComponent(mm[1])); return; }
  if (path === "/search") {
    const q = new URLSearchParams(location.search).get("q") || "";
    input.value = q; lastQuery = ""; doSearch(); return;
  }
  // "/craft" и "/vygodno-kraftit" (лендинг) — раздел крафта
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
