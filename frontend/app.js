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

// SPA-переходы Метрика сама не видит: navigate() меняет URL через pushState, а
// счётчик считает хит только на загрузке документа. Без этого «глубина просмотра»
// показывала число серверных загрузок, а не поведение — переходы между разделами
// внутри страницы просто не попадали в отчёты.
// Дедуп по pathname: route() зовут и без смены адреса (тумблер режима, сброс
// фильтров), а поиск правит только query — хит на каждую букву не нужен.
let ymLastPath = location.pathname;   // первый хит уже отправил init в <head>
function ymHit() {
  if (location.pathname === ymLastPath) return;
  const referer = location.origin + ymLastPath;
  ymLastPath = location.pathname;
  try {
    if (window.ym) ym(YM_ID, "hit", location.pathname + location.search, { referer });
  } catch (e) { /* счётчик не загрузился */ }
}

// Поиск по сайту Метрика тоже не видела: набор в строке правит URL через
// replaceState и зовёт doSearch() напрямую, мимо route()/ymHit(). Автоцель
// «поиск по сайту» ищет параметр в адресе ХИТА, а хита не было — отсюда 3
// срабатывания на ~5000 визитов (аудит счёл поиск мёртвым, а он просто не
// измерялся). Ждём паузы в наборе, чтобы не слать хит на каждую букву.
let ymSearchTimer = null, ymLastSearch = "";
function ymSearchHit(q) {
  clearTimeout(ymSearchTimer);
  if (!q || q === ymLastSearch) return;
  ymSearchTimer = setTimeout(() => {
    ymLastSearch = q;
    const referer = location.origin + ymLastPath;
    ymLastPath = "/search";      // следующий переход уйдёт с реферером поиска
    const url = `/search?q=${encodeURIComponent(q)}`;
    try { if (window.ym) ym(YM_ID, "hit", url, { referer }); } catch (e) { /* счётчик не загрузился */ }
  }, 1200);
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
      authBox.innerHTML = `<a class="auth-user" href="/profile" title="Профиль убежища: навыки и станки · EXBO ID ${ME.user.exbo_id}"><span class="gear">⚙</span><span class="auth-name">${escapeHtml(name)}</span></a>
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
  chatAuthChanged();  // форма чата зависит от авторизации (лента уже загружена)
  // DEV-вкладка (редактор карты) — только админам (ADMIN_USER_IDS)
  document.querySelectorAll(".nav-adm").forEach((el) =>
    el.classList.toggle("hidden", !(ME && ME.is_admin)));
  // прямой заход на /dev* и /home2 мог отрисовать «проверка доступа», пока /me не ответил
  if (location.pathname.startsWith("/dev") || location.pathname === "/home2") route();
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
      <label class="auth-consent">
        <input name="consent" type="checkbox" required>
        <span>Я принимаю <a href="/terms" target="_blank" rel="noopener">Пользовательское
        соглашение</a> и даю согласие на обработку персональных данных в соответствии
        с <a href="/privacy" target="_blank" rel="noopener">Политикой конфиденциальности</a>.
        Мне есть 18 лет.</span></label>
      <div class="auth-err" data-err></div>
      <button type="submit" class="auth-submit">СОЗДАТЬ АККАУНТ</button>
      ${exboBlock("РЕГИСТРАЦИЯ ЧЕРЕЗ EXBO")}
      <div class="auth-legal-note">Продолжая через EXBO, вы принимаете
        <a href="/terms" target="_blank" rel="noopener">Соглашение</a> и
        <a href="/privacy" target="_blank" rel="noopener">Политику конфиденциальности</a>.</div>
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
  // Верх воронки. Без него измерять было нечем: автоцель Метрики «отправил
  // контактные данные» не ловит сабмит через fetch с preventDefault (в июле
  // она показала 8 отправок при 13 успешных регистрациях), а цель signup
  // шлётся только на успехе — доля бросивших форму нигде не видна.
  ymGoal("auth_open");
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

  // Дошёл до отправки — считаем попытку независимо от исхода. Пара
  // auth_try/auth_fail показывает, где именно теряются люди: до попытки
  // (бросили форму) или на ней (не проходят проверки).
  if (pane === "register") ymGoal("auth_try");

  // клиентская проверка совпадения паролей
  if ((pane === "register" || pane === "reset-confirm") && val("password") !== val("password2")) {
    errEl.textContent = "Пароли не совпадают";
    if (pane === "register") ymGoal("auth_fail");
    return;
  }

  let url, payload, goal = null;
  if (pane === "signin") {
    url = "/auth/signin"; payload = { ident: val("ident"), password: val("password") }; goal = "login";
  } else if (pane === "register") {
    const consent = (form.querySelector('[name="consent"]') || {}).checked;
    if (!consent) {
      errEl.textContent = "Нужно принять соглашение и согласие на обработку данных";
      ymGoal("auth_fail");
      return;
    }
    url = "/auth/register";
    payload = { email: val("email"), login: val("login"),
                password: val("password"), consent: true };
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
    if (!r.ok) {
      errEl.textContent = data.error || "Ошибка. Попробуйте ещё раз.";
      if (pane === "register") ymGoal("auth_fail");   // отказ бэка: занятый email/ник, слабый пароль
      return;
    }

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
    ymSearchHit(q);
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
  // энергия всего дерева: операция корня + дробные операции крафтимых компонентов
  const treeE = chosen ? Math.round(calcTreeEnergy(chosen)) : null;
  const eSub = treeE != null && chosen.energy != null && treeE !== Math.round(chosen.energy)
    ? `<div class="tile-sub" title="С учётом крафта компонентов дерева (на 1 крафт-операцию)">ВСЁ ДЕРЕВО ~${fmt(treeE)}</div>` : "";
  // Маржа считается от ЦЕНЫ ПРОДАЖИ (медиана реальных сделок минус комиссия), а
  // не от цены аука — цена аука это «сколько отдать за готовое», а не «сколько
  // выручить». У большинства предметов они близки, и строка читается. Но там,
  // где продажа сильно выше выкупа, выходит «ВЫГОДНО +34%» при себестоимости
  // ВЫШЕ аука (Контрольная плата: себест 19 834, аук 7 580) — и это выглядит
  // как перепутанные местами плитки. Ровно так его и прочитали в чате багов
  // (Derkin, 11.08). Числа верные, не хватало того, из чего считается маржа:
  // подписываем её базу и помечаем случай «купить готовое дешевле, чем крафтить».
  const mSub = v.sell_net != null
    ? `<div class="tile-sub" title="Маржа = чистая продажа (${fmt(v.sell_net)} ₽ после комиссии ${
        v.fee_pct ?? 5}%) минус себестоимость">С ПРОДАЖИ ~${fmt(v.sell_net)}</div>` : "";
  const bSub = d.buy_price != null && d.craft_cost != null && d.buy_price < d.craft_cost
    ? `<div class="tile-sub warn" title="Готовое на ауке дешевле, чем собрать его из компонентов. Крафт всё равно может быть выгоден НА ПРОДАЖУ — маржа считается от цены продажи, а не от этой цены.">ДЕШЕВЛЕ КРАФТА</div>` : "";
  return `<div class="tiles ${fuelTile ? "five" : ""}">
    <div class="tile"><div class="lbl">СЕБЕСТОИМОСТЬ${fuelTile ? " +⛽" : ""}</div>
      <div class="val">${d.craft_cost != null ? fmt(d.craft_cost) + " ₽" : "—"}</div></div>
    <div class="tile"><div class="lbl">ЦЕНА АУКА</div>
      <div class="val">${d.buy_price != null ? fmt(d.buy_price) + " ₽" : "—"}</div>${bSub}</div>
    <div class="tile"><div class="lbl">МАРЖА / ШТ</div>
      <div class="val ${diffCls}">${diffVal}</div>${mSub}</div>
    <div class="tile"><div class="lbl">ЭНЕРГИЯ ВЕРСТАКА</div>
      <div class="val amber">${chosen && chosen.energy != null ? fmt(chosen.energy) : "—"}</div>${eSub}</div>
    ${fuelTile}
  </div>`;
}

// ---- пересчёт дерева на клиенте (замены «крафт → аук», без похода на бэк) ----
// TREE_BUY — id компонентов, переключённых на закупку. Живёт только в текущей
// карточке: renderDetail() всегда начинает с чистого листа (стандартное дерево).
let DETAIL_D = null;
let TREE_BUY = new Set();

function calcEffUnit(n) {
  // цена получения 1 шт с учётом замен (зеркало craft.py: min(аук, крафт))
  if (n.recipe && !TREE_BUY.has(n.id)) {
    const cu = calcRecipeUnit(n.recipe);
    if (cu != null) return cu;
  }
  if (TREE_BUY.has(n.id) && n.market_price != null) return n.market_price;
  return n.best_cost;
}

function calcRecipeUnit(rec) {
  let total = 0;
  for (const ing of rec.ingredients || []) {
    const u = calcEffUnit(ing.node);
    if (u == null) return null;
    total += u * ing.amount;
  }
  const mult = rec.bonus ? rec.bonus.mult : 1;   // матожидание бонусного крафта
  return Math.round((total + (rec.fuel_cost || 0)) / ((rec.result_amount || 1) * mult));
}

function calcTreeEnergy(rec) {
  // энергия на 1 крафт-операцию с учётом крафта компонентов (дробные операции)
  let e = rec.energy || 0;
  for (const ing of rec.ingredients || []) {
    const n = ing.node;
    if (n && n.recipe && !TREE_BUY.has(n.id)) {
      const mult = n.recipe.bonus ? n.recipe.bonus.mult : 1;
      e += calcTreeEnergy(n.recipe) * (ing.amount / ((n.recipe.result_amount || 1) * mult));
    }
  }
  return e;
}

function calcAdjusted(d) {
  // d с пересчитанными себестоимостью и вердиктом; без замен — ответ бэка как есть
  if (!TREE_BUY.size || !d.tree || !d.tree.recipe) return d;
  const craft = calcRecipeUnit(d.tree.recipe);
  if (craft == null) return d;
  const v = { ...d.verdict, craft_cost: craft };
  if (v.sell_net != null && (v.status === "profitable" || v.status === "unprofitable")) {
    const diff = v.sell_net - craft;
    const pct = craft > 0 ? Math.round((diff / craft) * 100) : 0;
    Object.assign(v, {
      status: diff > 0 ? "profitable" : "unprofitable",
      text: `${diff > 0 ? "ВЫГОДНО" : "НЕВЫГОДНО"} ${pct >= 0 ? "+" + pct : pct}%`,
      diff, pct,
    });
  }
  return { ...d, craft_cost: craft, verdict: v };
}

// плоский список строк дерева с ASCII-префиксами ├─ / └─ (замены не раскрываем)
function flattenTree(recipe, ancestors, rows, stats) {
  const ings = recipe.ingredients || [];
  ings.forEach((ing, i) => {
    const last = i === ings.length - 1;
    const prefix = ancestors.map((more) => (more ? "│ " : "  ")).join("") + (last ? "└─" : "├─");
    rows.push({ ing, prefix, depth: ancestors.length });
    stats.depth = Math.max(stats.depth, ancestors.length + 1);
    if (ing.node && ing.node.recipe && !TREE_BUY.has(ing.node.id))
      flattenTree(ing.node.recipe, ancestors.concat(!last), rows, stats);
  });
}

function srcTag(n) {
  if (TREE_BUY.has(n.id)) return `<span class="ttag market">АУК</span>`;
  if (n.best_source === "craft") return `<span class="ttag craft">КРАФТ</span>`;
  if (n.best_source === "market") return `<span class="ttag market">АУК</span>`;
  if (n.craftable) return `<span class="ttag">ТОЛЬКО КРАФТ</span>`;
  return `<span class="ttag">НЕТ ЦЕНЫ</span>`;
}

function treeBlock(d, chosen) {
  const rows = [], stats = { depth: 0 };
  flattenTree(chosen, [], rows, stats);
  const live = TREE_BUY.size > 0;   // есть замены — все числа считаем на клиенте

  let body = "";
  for (const r of rows) {
    const n = r.ing.node;
    const swapped = TREE_BUY.has(n.id);
    const unit = live ? calcEffUnit(n) : n.best_cost;
    const line = unit != null ? Math.round(unit * r.ing.amount) : null;
    // подпись выгоды: у крафтимых — на сколько дешевле аука; у заменённых — цена крафта
    let hint = "";
    if (n.recipe && !swapped) {
      const cu = live ? calcRecipeUnit(n.recipe) : n.best_cost;
      if (n.market_price != null && cu != null) {
        const pct = Math.round((1 - cu / n.market_price) * 100);
        hint = pct > 0
          ? `<span class="tsave" title="Крафт ${fmt(cu)} ₽ против ${fmt(n.market_price)} ₽ на ауке">ДЕШЕВЛЕ АУКА НА ${pct}%</span>`
          : `<span class="tsave dim">≈ ЦЕНА АУКА</span>`;
      } else if (n.market_price == null) {
        hint = `<span class="tsave dim">НА АУКЕ НЕТ</span>`;
      }
      if (n.recipe.bonus)
        hint += `<span class="tbonus" title="Бонусный крафт +${n.recipe.bonus.pct}% (навык выше требуемого на ${n.recipe.bonus.levels}) — учтён в цене">↑${n.recipe.bonus.pct}%</span>`;
    } else if (swapped && n.craft_cost != null) {
      hint = `<span class="tsave dim">КРАФТ: ${fmt(live ? calcRecipeUnit(n.recipe) ?? n.craft_cost : n.craft_cost)} ₽/ШТ</span>`;
    }
    if (n.craft_locked)
      hint += `<span class="tsave lock" title="Рецепт есть, но прокачки не хватает — считаем закупку${n.locked_cost != null ? `. Крафт стоил бы ~${fmt(n.locked_cost)} ₽/шт` : ""}">🔒 НЕТ ПРОКАЧКИ</span>`;
    const swapBtn = n.recipe && n.market_price != null
      ? `<button class="tswap ${swapped ? "on" : ""}" data-tid="${n.id}"
           title="${swapped ? "Вернуть крафт компонента" : "Покупать на ауке вместо крафта"}">⇄</button>`
      : "";
    body += `<div class="trow ${r.depth ? "sub" : ""} ${swapped ? "swapped" : ""}">
      <div class="tcomp">
        <span class="tprefix">${r.prefix}</span>
        <img loading="lazy" src="${asset(n.icon)}" alt="">
        <span class="tname ${r.depth ? "" : "top"}" data-id="${n.id}">${escapeHtml(n.name)}</span>
        <span class="x">×${r.ing.amount}</span>
        ${hint}
      </div>
      <div class="tunit">${fmt(unit)}</div>
      <div class="tsrc">${srcTag(n)}${swapBtn}</div>
      <div class="tline">${line != null ? fmt(line) + " ₽" : "—"}</div>
    </div>`;
  }

  let perOne = chosen.result_amount > 1 ? ` · ЗА 1 ШТ ИЗ ${chosen.result_amount}` : "";
  if (chosen.bonus) perOne += ` · БОНУСНЫЙ КРАФТ +${chosen.bonus.pct}% УЧТЁН`;
  return `<div class="section-head">
      <div class="section-title">▸ ДЕРЕВО КРАФТА${TREE_BUY.size ? " · С ЗАМЕНАМИ" : " · ОПТИМАЛЬНЫЙ ПУТЬ"}</div>
      <div class="tree-tools">
        <button id="treeReset" class="tree-reset" ${TREE_BUY.size ? "" : "hidden"}
          title="Вернуть стандартное дерево, рассчитанное калькулятором">⟲ СБРОС ЗАМЕН (${TREE_BUY.size})</button>
        <div class="section-note">ГЛУБИНА ${stats.depth} · ВАРИАНТОВ ${d.tree.n_variants || 1}</div>
      </div>
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
    h += `<details class="alt"><summary><b>${cost}</b> · ВЕРСТАК${a.result_amount > 1 ? " · ×" + a.result_amount : ""}${a.req_ok === false ? ` · <span class="alt-lock" title="На этот вариант не хватает прокачки">✗ ПРОКАЧКА</span>` : ""}</summary>`;
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
  const bn = chosen.bonus;
  if (bn) perkHtml += `<div class="bonus-note"
      title="Каждый уровень навыка выше требуемого рецептом даёт +75% бонусного крафта. Каждые полные 100% — гарантированная дополнительная партия результата, остаток — шанс ещё одной. Матожидание уже учтено в себестоимости.">
      ⚡ БОНУСНЫЙ КРАФТ +${bn.pct}%${bn.guaranteed ? ` · ГАРАНТ. +${bn.guaranteed}` : ""}${bn.chance_pct ? ` · ШАНС ${bn.chance_pct}% ЕЩЁ +1` : ""}</div>`;

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

function treeReqsHtml(d) {
  // сводка по ВСЕМУ дереву: максимум уровня каждого навыка + все станки
  // крафтимых компонентов (заменённые на аук — не считаются)
  const root = d.tree && d.tree.recipe;
  if (!root) return "";
  const perks = {}, feats = new Set();
  const walk = (rec) => {
    const rq = rec.requirements || {};
    for (const [k, lvl] of Object.entries(rq.perks || {}))
      perks[k] = Math.max(perks[k] || 0, lvl);
    (rq.features || []).forEach((f) => feats.add(f));
    for (const ing of rec.ingredients || []) {
      const n = ing.node;
      if (n && n.recipe && !TREE_BUY.has(n.id)) walk(n.recipe);
    }
  };
  walk(root);
  const prof = d.hideout_profile;
  const row = (nm, need, have, ok) => `<div class="treq ${ok == null ? "" : ok ? "ok" : "bad"}">
      <span class="nm">${nm}</span>
      <span class="lv">${need}${have != null ? ` <span class="hv">/ ${have}</span>` : ""} ${ok == null ? "" : ok ? "✓" : "✗"}</span>
    </div>`;
  const perkRows = Object.entries(perks).map(([k, lvl]) => {
    const have = prof ? (prof.perks[k] || 0) : null;
    return row(escapeHtml(perkName(k)), `УР. ${lvl}`, have, have == null ? null : have >= lvl);
  }).join("");
  const featRows = [...feats].sort().map((f) => {
    const ok = prof ? (prof.features || []).includes(f) : null;
    return row(escapeHtml(featureName(f)), "", null, ok);
  }).join("");
  if (!perkRows && !featRows) return "";
  return `<div class="reqs-lbl" title="Навыки и станки для крафта всех компонентов дерева (компоненты, переключённые на закупку, не считаются)">ВСЁ ДЕРЕВО · НАВЫКИ И СТАНКИ</div>
    ${perkRows}${featRows}`;
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
    ${chosen ? `<div class="reqs-sec" id="treeReqs">${treeReqsHtml(d)}</div>` : ""}
    ${hasUsed ? usedInSection(usedIn) : ""}
  </aside>`;
}

function craftCalcHtml(d0) {
  // вердикт + плитки + дерево: всё, что пересчитывается при заменах крафт/аук
  const d = calcAdjusted(d0);
  const chosen = d.tree && d.tree.recipe;
  let html = verdictBlock(d);
  if (d.craftable) {
    html += tilesBlock(d, chosen);
    if (chosen && chosen.req_ok === false)
      html += `<div class="note-warn"><span class="mark">[!]</span>
        НА ЭТОТ КРАФТ НЕ ХВАТАЕТ ПРОКАЧКИ — СМ. ТРЕБОВАНИЯ. ЦИФРЫ СПРАВЕДЛИВЫ ПОСЛЕ ПРОКАЧКИ.</div>`;
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
  return html;
}

function recalcCraft() {
  // риалтайм-пересчёт карточки после замены/сброса (без запроса на бэк)
  const c = document.getElementById("craftCalc");
  if (!c || !DETAIL_D) return;
  c.innerHTML = craftCalcHtml(DETAIL_D);
  const tr = document.getElementById("treeReqs");
  if (tr) tr.innerHTML = treeReqsHtml(DETAIL_D);
  wireCalc();
}

function wireCalc() {
  const c = document.getElementById("craftCalc");
  if (!c) return;
  c.querySelectorAll(".tname[data-id], .ilink[data-id]").forEach((el) =>
    el.addEventListener("click", () => { navigate(`/item/${el.dataset.id}`); }));
  c.querySelectorAll(".tswap[data-tid]").forEach((b) =>
    b.addEventListener("click", () => {
      const id = b.dataset.tid;
      if (TREE_BUY.has(id)) TREE_BUY.delete(id); else TREE_BUY.add(id);
      recalcCraft();
    }));
  const rst = c.querySelector("#treeReset");
  if (rst) rst.addEventListener("click", () => { TREE_BUY.clear(); recalcCraft(); });
}

function renderDetail(d) {
  const it = d.item;
  const rk = rank(it.color);
  const chosen = d.tree && d.tree.recipe;
  DETAIL_D = d;
  TREE_BUY = new Set();   // замены не храним: новая карточка = стандартное дерево

  let html = `<button class="back">◂ НАЗАД</button>`;

  // хлебные крошки: предмет живёт в разделе «База предметов»
  const crumbs = [`<a href="/items">БАЗА ПРЕДМЕТОВ</a>`];
  const catName = IDB_CAT_RU[d.category];
  if (catName) crumbs.push(escapeHtml(catName));
  else if (chosen && chosen.category) crumbs.push(escapeHtml(chosen.category));
  if (chosen && chosen.subcategory) crumbs.push(escapeHtml(chosen.subcategory));
  html += `<div class="crumbs">${crumbs.join(" ▸ ")} ▸ <span class="id">${escapeHtml(it.id)}</span></div>`;

  html += `<div class="card-cols"><div class="card-main">`;

  // игровая карточка (оружие/броня/контейнеры/арты) — вид как в игре; для прочих
  // предметов (ресурсы/крафт-компоненты) остаётся прежняя крафт-шапка
  const hasChars = (d.characteristics || []).length > 0;
  if (hasChars) {
    html += gameCardHtml(d);
  } else {
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
  }

  if (d.description)
    html += `<div class="item-desc">${escapeHtml(d.description)}</div>`;

  html += itemActionsHtml(d);            // строка действий: аук / крафт / сборка / бартер

  html += `<div id="craftCalc">${craftCalcHtml(d)}</div>`;

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
    // возврат туда, откуда пришли (поиск / каталог / операции); иначе — в базу
    if (history.length > 1) history.back();
    else navigate("/items");
  });
  // ссылки внутри #craftCalc вешает wireCalc — он же перевешивает их при пересчёте
  detail.querySelectorAll(".use-row[data-id], .fuel-src[data-id]").forEach((el) =>
    el.addEventListener("click", () => { navigate(`/item/${el.dataset.id}`); }));
  // строка действий карточки: аук (модал), крафт/бартер (прокрутка к блоку)
  detail.querySelectorAll(".item-act[data-act]").forEach((b) => b.addEventListener("click", () => {
    const act = b.dataset.act;
    if (act === "auction") { openMarketModal(DETAIL_D.item.id); return; }
    if (act === "compare") {
      const it = DETAIL_D.item;
      if (!cmpToggle(it)) authNotice(`В СРАВНЕНИИ УЖЕ ${CMP_MAX} ПРЕДМЕТА — УБЕРИТЕ ЛИШНЕЕ`, "err");
      return;
    }
    const anchor = act === "craft" ? "craftCalc" : act === "barter" ? "barterBlocks" : null;
    const el = anchor && document.getElementById(anchor);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  syncCmpButtons();
  wireCalc();
  const ft = detail.querySelector("#fuelToggle");
  if (ft) ft.addEventListener("click", () => {
    localStorage.setItem("sz_fuel", fuelMode() ? "0" : "1");
    openItem(ft.dataset.item);   // перечитать карточку с новым режимом
  });
}

// строка действий карточки предмета: аукцион всегда; крафт/сборка/бартер — по контексту
function itemActionsHtml(d) {
  const cat = d.category || "";
  const acts = [`<button class="item-act" data-act="auction">▸ НА АУКЕ</button>`];
  if (d.craftable) acts.push(`<button class="item-act" data-act="craft">▸ КРАФТ</button>`);
  // сравнивать есть что только у предметов с игровыми характеристиками
  if ((d.characteristics || []).length)
    acts.push(`<button class="item-act cmp-act" data-act="compare"
      data-cmp-id="${escapeHtml(d.item.id)}" data-cmp-label="1">⇄ К СРАВНЕНИЮ</button>`);
  if (["armor", "artefact", "containers", "backpacks"].includes(cat))
    acts.push(`<a class="item-act" href="/builds">▸ В СБОРКИ</a>`);
  // кнопка «бартер» добавляется динамически в loadBarterBlocks, если предмет барется
  return `<div class="item-acts" id="itemActs">${acts.join("")}</div>`;
}

// статус предмета из базы → русская подпись (как в игре)
const ITEM_STATUS_RU = {
  PERSONAL: "Персональный предмет",
  PERSONAL_ON_USE: "Персональный предмет",
  QUEST: "Квестовый предмет",
};

// игровая карточка предмета (оружие/броня/контейнеры/арты): шапка (иконка + имя +
// статус) → инфо-блок (ранг/класс/вес/прочность) → «Итоговые характеристики» →
// боевые статы. Ранг — цветом редкости, минусы — красным, значения с единицами.
function gameCardHtml(d) {
  const it = d.item, rk = rank(it.color);
  const chars = d.characteristics || [];
  const info = chars.filter((c) => c.group === "info");
  const stats = chars.filter((c) => c.group === "stat");
  const row = (c) => {
    const v = `${escapeHtml(c.value)}${c.unit ? ` <span class="gc-u">${escapeHtml(c.unit)}</span>` : ""}`;
    const style = c.rank ? ` style="color:${rk.color}"` : "";
    return `<div class="gc-row${c.harmful ? " bad" : ""}">
      <span class="gc-n">${escapeHtml(c.name)}</span>
      <span class="gc-v"${style}>${v}</span></div>`;
  };
  const status = ITEM_STATUS_RU[it.status];
  return `<div class="game-card" style="--rar:${rk.color}">
    <div class="gc-head">
      <div class="gc-art"><img src="${asset(it.icon)}" alt=""></div>
      <div class="gc-title">
        <div class="gc-name" style="color:${rk.color}">${escapeHtml(it.name)}</div>
        ${it.name_en ? `<div class="gc-en">${escapeHtml(it.name_en)}</div>` : ""}
        ${status ? `<div class="gc-status">🔒 ${escapeHtml(status)}</div>` : ""}
      </div>
    </div>
    ${info.length ? `<div class="gc-info">${info.map(row).join("")}</div>` : ""}
    ${stats.length ? `<div class="gc-div"><span>ИТОГОВЫЕ ХАРАКТЕРИСТИКИ</span></div>
      <div class="gc-stats">${stats.map(row).join("")}</div>` : ""}
  </div>`;
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
  const totalsHtml = `<div class="db-tt">ПАРАМЕТРЫ СБОРКИ · АРТЕФАКТЫ + КОНТЕЙНЕР</div>
    <div class="db-stats">${totals || `<div class="empty-sm">СТАТОВ НЕТ</div>`}</div>
    ${contam ? `<div class="db-tt sub">ЗАРАЖЕНИЕ (ПОСЛЕ ЗАЩИТЫ КОНТЕЙНЕРА)</div>
       <div class="db-stats">${contam}</div>` : ""}`;
  return head + gear + `<div class="db-arts">${arts}</div>${totalsHtml}
    <div class="db-cost">АРТЕФАКТЫ <b>${fmt(b.totals.cost)} ₽</b> <span class="db-of">/ ${fmtBudgetShort(d.budget)} БЮДЖЕТ</span></div>`;
}

// модуль промокодов на главной: код (клик копирует) + срок; реферальный — сверху.
// Срок идёт строкой ПОД кодом: в узкой рейке ПУЛЬТА он стоял справа и отжимал
// кнопку до многоточия — код «FRN…» скопировать нельзя, а иногда его съедало целиком.
function promoDashBody(p) {
  const items = (p && p.items) || [];
  if (!items.length)
    return `<div class="empty-sm">АКТУАЛЬНЫХ ПРОМОКОДОВ СЕЙЧАС НЕТ.</div>`;
  const short = (d) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})$/.exec(d || "");
    if (!m) return "БЕССРОЧНЫЙ";
    return `ДО ${m[3]}.${m[2]}${m[4] === "23:59" ? "" : ` · ${m[4]} МСК`}`;
  };
  const row = (x) => `<div class="dash-promo${x.is_ref ? " ref" : ""}">
      ${promoCodeBtn(x)}
      <div class="dash-promo-m">
        ${x.is_ref ? `<span class="dash-promo-ref">★ РЕФЕРАЛЬНЫЙ</span><span class="dash-promo-sep">·</span>` : ""}
        <span class="dash-promo-exp">${short(x.expires_at)}</span>
      </div>
    </div>`;
  // сетка auto-fit, а не колонка: один и тот же модуль стоит и в узкой рейке
  // (одна колонка), и широким в центре главной (три) — без второй вёрстки
  return `<div class="dash-promos">${items.slice(0, 6).map(row).join("")}</div>`;
}

// ---------- главная: терминальный «ПУЛЬТ» ----------
// Боевая «/» рисуется макетом ПУЛЬТ (приборная строка, индикаторы слева,
// главный экран по центру, новости справа). Второй макет ПЛАТА остался
// песочницей на /home2 под админом — там же переключатель и предпросмотр
// будущих правок, чтобы не трогать боевую страницу.
const HOME2_KEY = "sz_home2";
const HOME2_LAYOUTS = { hud: "ПУЛЬТ", board: "ПЛАТА" };
const home2Layout = () => {
  // ?lay=board — чтобы кинуть ссылку сразу на нужный макет; выбор запоминается
  const q = new URLSearchParams(location.search).get("lay");
  if (HOME2_LAYOUTS[q]) { localStorage.setItem(HOME2_KEY, q); return q; }
  const v = localStorage.getItem(HOME2_KEY);
  return HOME2_LAYOUTS[v] ? v : "hud";
};
let home2Data = null, home2Ts = 0;

// данные общие у боевой главной и у песочницы: минута кэша, чтобы переход
// «/» ↔ «/home2» и смена макета не дёргали десяток эндпоинтов заново
async function loadHome2Data() {
  if (home2Data && Date.now() - home2Ts < 60000) return home2Data;
  const j = (u) => fetch(api(u)).then((r) => r.json()).catch(() => null);
  const [top, art, watch, em, sales, fuelTop, patches, daily, promos, ops, feed] =
    await Promise.all([
      j(`/top${availParam("?")}`), j("/artmarket/top?window=24h"), j("/watch"),
      j("/emission"), j("/sales/top?n=12"), j("/fuel/top?n=20"),
      j("/patches?limit=5"), j("/build/daily"), j("/promos"),
      j("/operations/overview"), j("/news/feed?limit=14"),
    ]);
  home2Data = { top, art, watch, em, sales, fuelTop, patches, daily, promos, ops, feed };
  home2Ts = Date.now();
  return home2Data;
}

// общая привязка обработчиков: нужна и боевой главной, и песочнице, и
// результатам поиска внутри модулей
function h2Bind(root) {
  h2BindNav(root);
  root.querySelectorAll(".h2-find").forEach(h2BindFind);
  bindPromoCopy(root);
  root.querySelectorAll(".stab").forEach((b) => b.addEventListener("click", () => {
    root.querySelectorAll(".stab").forEach((x) => x.classList.toggle("on", x === b));
    root.querySelectorAll(".sales-view").forEach((v) =>
      v.classList.toggle("hidden", v.dataset.view !== b.dataset.view));
  }));
  startEmTick();
}

// боевая «/»: всегда ПУЛЬТ, без админской полосы и переключателя макетов
async function openHomeMain() {
  if (mapCleanup) { mapCleanup(); mapCleanup = null; }
  detail.classList.add("hidden"); page.classList.add("hidden"); results.innerHTML = "";
  home.classList.remove("hidden");
  if (home.dataset.view === "main"
      && home.dataset.ts && Date.now() - +home.dataset.ts < 60000) return;
  home.innerHTML = `<div class="spinner">// ЗАГРУЗКА ГЛАВНОЙ</div>`;
  const d = await loadHome2Data();
  if (location.pathname !== "/") return;     // успели уйти со страницы
  home.dataset.ts = Date.now();
  home.dataset.view = "main";
  home.innerHTML = home2Hud(d);
  h2Bind(home);
}

// ---------- ДЕВ · песочница макетов (/home2, только админ) ----------
async function openHome2() {
  if (mapCleanup) { mapCleanup(); mapCleanup = null; }
  detail.classList.add("hidden"); page.classList.add("hidden"); results.innerHTML = "";
  home.classList.remove("hidden");
  window.scrollTo(0, 0);
  if (!ME) { home.innerHTML = `<div class="spinner">// ПРОВЕРКА ДОСТУПА</div>`; return; }
  if (!ME.is_admin) {
    home.dataset.view = "";
    home.innerHTML = `<div class="stub"><div class="stub-code">[ 403 ]</div>
      <div class="stub-title">▸ ПЕСОЧНИЦА МАКЕТОВ — ТОЛЬКО ДЛЯ АДМИНОВ</div>
      <a class="stub-back" href="/">◂ НА ГЛАВНУЮ</a></div>`;
    return;
  }
  if (home.dataset.view === "home2" && home2Data
      && home.dataset.ts && Date.now() - +home.dataset.ts < 60000) {
    renderHome2(); return;
  }
  home.innerHTML = `<div class="spinner">// СБОРКА МАКЕТА</div>`;
  await loadHome2Data();
  if (location.pathname !== "/home2") return;
  home.dataset.ts = Date.now();
  home.dataset.view = "home2";
  renderHome2();
}

// ---- общие куски обоих макетов ----

// модуль: разметка одна на оба макета, вид задаёт CSS — у ПУЛЬТА угловые скобы,
// у ПЛАТЫ восьмиугольная рамка со срезами. h2-frame нужен отдельным слоем: у
// ПЛАТЫ он обрезан clip-path, а дорожка к шине (h2-trace) торчит наружу и
// обрезкой была бы срезана — поэтому она снаружи рамки.
const h2Mod = (mark, title, note, body, link, linkText, cls = "") =>
  `<section class="h2-mod${cls ? " " + cls : ""}">
    <div class="h2-frame">
      <header class="h2-mh">
        ${mark ? `<span class="h2-mark">${mark}</span>` : ""}
        <span class="h2-mt">${title}</span>
        ${note ? `<span class="h2-mn">${note}</span>` : ""}
      </header>
      <div class="h2-mb">${body}</div>
      ${link ? `<a class="h2-more" href="${link}">${linkText || "ОТКРЫТЬ"} ▸</a>` : ""}
    </div>
    <i class="h2-trace" aria-hidden="true"></i>
  </section>`;

// прибор: одно крупное число + подпись; клик уводит в раздел
const h2Gauge = (label, value, unit, sub, nav) =>
  `<div class="h2-gauge"${nav ? ` data-nav="${nav}"` : ""}>
    <div class="h2-g-l">${label}</div>
    <div class="h2-g-v">${value}${unit ? `<span class="h2-g-u">${unit}</span>` : ""}</div>
    ${sub ? `<div class="h2-g-s">${sub}</div>` : ""}
  </div>`;

// «время с последнего выброса» живым счётчиком — span.em-ago оживляет startEmTick()
function h2EmValue(em) {
  const hist = (em && (em.history || []).length) ? em.history
    : [em && em.current_start, em && em.previous_start].filter(Boolean);
  if (em && em.current_start)
    return { v: `<span class="em-ago" data-ts="${em.current_start}">…</span>`,
             sub: "⚠ ВЫБРОС ИДЁТ СЕЙЧАС", alarm: true };
  if (!hist.length) return { v: "—", sub: "ЖДЁМ ПЕРВЫЙ ЗАМЕР", alarm: false };
  return { v: `<span class="em-ago" data-ts="${hist[0]}">…</span>`,
           sub: `ПОСЛЕДНИЙ ${fmtMsk(hist[0])}`, alarm: false };
}

function h2BestFuel(fu) {
  const src = ((fu && fu.sources) || []).filter((s) => s.per_1k != null);
  return src.sort((a, b) => a.per_1k - b.per_1k)[0] || null;
}

// строка приборов: одинаковая в обоих макетах, наверху страницы
function h2Bar(d) {
  const em = h2EmValue(d.em);
  const fuel = h2BestFuel(d.fuelTop);
  const lead = ((d.art && d.art.up) || [])[0];
  const hp = d.daily && d.daily.hp ? d.daily.hp.effective_hp : null;
  const promoN = ((d.promos && d.promos.items) || []).length;
  // крафт — самый посещаемый раздел, а в приборах его не было; берём верх списка
  // «выгодных»: это ₽ за один цикл верстака, самая понятная цифра из /top
  const craft = ((d.top && d.top.profitable) || []).find((e) => e.diff != null);
  const cells = [
    h2Gauge("ВЫБРОС", em.v, "", em.sub, null),
    h2Gauge("ЛУЧШИЙ КРАФТ", craft ? `+${fmt(craft.diff)}` : "—", craft ? " ₽" : "",
            craft ? escapeHtml(craft.name) : "ЦЕНЫ СЧИТАЮТСЯ…", "/craft"),
    h2Gauge("ТОПЛИВО ОТ", fuel ? fmt(fuel.per_1k) : "—", " ₽/1К",
            fuel ? escapeHtml(fuel.name) : "СЧИТАЕТСЯ…", "/profile"),
    h2Gauge("СБОРКА ДНЯ", hp != null ? fmt(hp) : "—", " ХП",
            d.daily && d.daily.budget ? `БЮДЖЕТ ${fmtBudgetShort(d.daily.budget)} ₽` : "—",
            "/builds"),
    h2Gauge("ЛИДЕР РОСТА", lead ? `+${lead.pct}` : "—", lead ? "%" : "",
            lead ? escapeHtml(lead.name) : "БИРЖА КОПИТ ЗАМЕРЫ", "/auction"),
    h2Gauge("ПРОМОКОДОВ", promoN || "—", "", promoN ? "АКТИВНЫ СЕЙЧАС" : "СЕЙЧАС НЕТ", "/promo"),
  ].join("");
  return `<div class="h2-bar${em.alarm ? " alarm" : ""}">${cells}
    <div class="h2-bar-live"><span class="h2-dot"></span>LIVE · АУКЦИОН RU</div></div>`;
}

// колонка новостей сайта: ручные посты + автособытия (гайды/промокоды/патчи)
function h2NewsBody(feed) {
  const items = (feed && feed.items) || [];
  if (!items.length)
    return `<div class="empty-sm">ЛЕНТА ПУСТА — ПЕРВУЮ НОВОСТЬ МОЖНО НАПИСАТЬ В ДЕВ · НОВОСТИ.</div>`;
  return items.map((n) => {
    const d = String(n.created_at || "").slice(5).split("-").reverse().join(".");
    return `<article class="h2-news k-${n.kind}${n.pinned ? " pin" : ""}"${
      n.url ? ` data-nav="${escapeHtml(n.url)}"` : ""}>
      <div class="h2-news-h">
        <span class="h2-news-d">${d || "—"}</span>
        ${n.tag ? `<span class="h2-news-t">${escapeHtml(n.tag)}</span>` : ""}
        ${n.pinned ? `<span class="h2-news-pin" title="Закреплено">★</span>` : ""}
      </div>
      <div class="h2-news-ti">${escapeHtml(n.title)}</div>
      ${n.body ? `<div class="h2-news-b">${escapeHtml(n.body)}</div>` : ""}
    </article>`;
  }).join("");
}

// Поиск внутри модуля: строка ввода, под ней либо результаты, либо обычная
// подборка. Оборачивает готовое тело — разметка одна на оба макета, обработчик
// вешается в renderHome2 по data-find.
const h2Findable = (kind, ph, body) => `<div class="h2-find" data-find="${kind}">
    <span class="h2-find-p">&gt;_</span>
    <input type="search" class="h2-find-i" inputmode="search" autocomplete="off"
           placeholder="${ph}" aria-label="${ph}">
    <button type="button" class="h2-find-x hidden" title="Сбросить (Esc)">✕</button>
  </div>
  <div class="h2-find-res hidden"></div>
  <div class="h2-find-base">${body}</div>`;

// строка результата в «самом продаваемом»: темп продаж, а без истории — цена
function h2MarketRow(r) {
  const val = r.per_day != null ? `~${fmt(r.per_day)}/СУТ`
    : r.min_buyout != null ? `${fmt(r.min_buyout)} ₽`
    : `<span class="h2-find-dim">НЕТ СДЕЛОК</span>`;
  return `<div class="dash-row" data-nav="/item/${r.id}">
    <img loading="lazy" src="${asset(r.icon)}" alt="">
    <div class="nm">${escapeHtml(r.name)}</div>
    <span class="dash-p">${val}</span></div>`;
}

// data-nav вешаем через флаг: результаты поиска доклеиваются после общей
// привязки, без флага повторный проход навесил бы второй обработчик
function h2BindNav(root) {
  root.querySelectorAll("[data-nav]").forEach((el) => {
    if (el.dataset.navBound) return;
    el.dataset.navBound = "1";
    el.addEventListener("click", () => { navigate(el.dataset.nav); });
  });
}

function h2BindFind(box) {
  const kind = box.dataset.find;
  const input = box.querySelector(".h2-find-i");
  const clear = box.querySelector(".h2-find-x");
  const res = box.parentNode.querySelector(".h2-find-res");
  const base = box.parentNode.querySelector(".h2-find-base");
  let timer = null, ctl = null;
  const show = (on) => {
    res.classList.toggle("hidden", !on);
    base.classList.toggle("hidden", on);
    clear.classList.toggle("hidden", !on);
  };
  const reset = () => { input.value = ""; res.innerHTML = ""; show(false); };
  const run = async () => {
    const q = input.value.trim();
    if (!q) { reset(); return; }
    show(true);
    res.innerHTML = `<div class="h2-find-msg">// ИЩУ…</div>`;
    if (ctl) ctl.abort();          // ответ на прошлую букву уже не нужен
    ctl = new AbortController();
    try {
      const d = await fetch(
        api(`/home/search?kind=${kind}&q=${encodeURIComponent(q)}&limit=8`),
        { signal: ctl.signal }).then((r) => r.json());
      if (input.value.trim() !== q) return;      // пока ждали, запрос сменился
      const items = d.items || [];
      res.innerHTML = items.length
        ? items.map(kind === "craft" ? (r) => dashCraftRow(r, false) : h2MarketRow).join("")
          + `<a class="h2-find-all" href="/search?q=${encodeURIComponent(q)}">ИСКАТЬ «${
              escapeHtml(q)}» ПО ВСЕЙ БАЗЕ ▸</a>`
        : `<div class="h2-find-msg">НИЧЕГО НЕ НАЙДЕНО${
            kind === "craft" ? " СРЕДИ КРАФТЯЩЕГОСЯ" : ""}</div>`;
      h2BindNav(res);
    } catch (e) {
      if (e.name !== "AbortError")
        res.innerHTML = `<div class="h2-find-msg">[!] ОШИБКА СЕТИ</div>`;
    }
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 250); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { reset(); input.blur(); }
    if (e.key === "Enter") { clearTimeout(timer); run(); }
  });
  clear.addEventListener("click", () => { reset(); input.focus(); });
}

function h2Crafts(top) {
  if (!top) return `<div class="empty-sm">ЦЕНЫ СЧИТАЮТСЯ В ФОНЕ — ЗАГЛЯНИ ПОЗЖЕ.</div>`;
  const grp = (t, list, pctBadge) => (list && list.length)
    ? `<div class="dash-grp">${t}</div>`
      + list.slice(0, 5).map((e) => dashCraftRow(e, pctBadge)).join("") : "";
  return grp("ВЫГОДНЫЕ", top.profitable, false) + grp("ПРОФИТНЫЕ", top.liquid, true)
    || `<div class="empty-sm">ЦЕНЫ СЧИТАЮТСЯ В ФОНЕ — ЗАГЛЯНИ ПОЗЖЕ.</div>`;
}

function h2Trends(art) {
  if (!art || !((art.up || []).length || (art.down || []).length))
    return `<div class="empty-sm">БИРЖА НАКАПЛИВАЕТ ЗАМЕРЫ — СКОРО ПОЯВЯТСЯ ТРЕНДЫ.</div>`;
  const grp = (t, list) => (list && list.length)
    ? `<div class="dash-grp">${t}</div>` + list.slice(0, 5).map(dashArtRow).join("") : "";
  return grp("РАСТУТ", art.up) + grp("ПАДАЮТ", art.down);
}

function h2Charts(watch) {
  if (!watch || !(watch.items || []).length)
    return `<div class="empty-sm">ЖДЁМ ПЕРВЫЕ ЗАМЕРЫ БИРЖИ.</div>`;
  const cards = watch.items.map((m) => `
    <div class="dash-chart" data-nav="/item/${m.id}">
      <div class="dc-head"><img loading="lazy" src="${asset(m.icon)}" alt="">
        <span class="nm">${escapeHtml(m.name)}</span>
        ${m.delta_pct != null ? `<span class="pct ${m.delta_pct > 0 ? "up" : m.delta_pct < 0 ? "down" : "dim"}">${m.delta_pct > 0 ? "+" : ""}${m.delta_pct}%</span>` : ""}</div>
      ${chartSvg(m.series || [])}
      <div class="dc-price">${m.avg != null ? fmt(m.avg) + " ₽" : "—"} <span class="dc-unit">СР./ШТ</span></div>
    </div>`).join("");
  return `<div class="dash-charts h2-charts">${cards}</div>`;
}

function h2Patches(patches) {
  const items = (patches && patches.items) || [];
  if (!items.length) return `<div class="empty-sm">СИНХРОНИЗАЦИЯ С ФОРУМОМ EXBO…</div>`;
  return items.slice(0, 3).map((p) => `
    <div class="dash-patch" data-nav="/patches/${p.id}">
      <div class="dp-t">${escapeHtml(p.title)}</div>
      <div class="dp-d">${fmtPatchDate(p.created_at)}</div>
      <div class="dp-a">${escapeHtml(p.anons || "")}</div>
    </div>`).join("");
}

// ---- макет 1: ПУЛЬТ (приборы слева, главный экран в центре, новости справа) ----
function home2Hud(d) {
  return `<div class="h2 h2-hud">
    ${h2Bar(d)}
    <div class="h2-hud-grid">
      <aside class="h2-rail">
        ${h2Mod("", "ЗАПРАВКА ГЕНЕРАТОРА", "₽ ЗА 1000 ЕД", fuelBody(d.fuelTop),
                "/profile", "ПРИСТРОЙКИ")}
        ${h2Mod("", "ВЫБРОС", "ЗАМЕР РАЗ В МИНУТУ", emissionBody(d.em))}
        ${h2Mod("", "МЕТА ОПЕРАЦИЙ", opsDashNote(d.ops), opsDashBody(d.ops),
                "/operations", "К СТАТИСТИКЕ")}
      </aside>
      <main class="h2-view">
        <!-- Промокоды — самой первой строкой центра, выше главного экрана.
             История места: на старом дашборде это была одна из десяти равных
             плиток и цель promo_ref_click срабатывала в 1.05% визитов; в ПУЛЬТЕ
             модуль уехал в левую рейку и дал 0.24%, после подъёма первым в
             рейке (81f0a6f) за 08.08 — ноль. За два дня 1/764 против 20/1908,
             p=0.015. Рейка безнадёжна by design: с 1200px и уже она в сетке
             уходит ПОД весь центр («view news» / «rail news»).
             Место над hero — решение владельца: промокоды должны быть видны
             сразу, без скролла и без конкуренции с чем-либо. Цена решения —
             крафт и аук съезжают вниз на высоту полосы, а это верх воронки
             (/craft +93% в день переезда). Высоту поэтому держим сеткой
             .dash-promos: на широком экране коды встают в один ряд (замерено
             на проде — 1920 да, 1366 в две строки, там центр из-за
             body{zoom:1.2} вдвое уже, чем кажется по скриншоту). Смотреть
             /craft и /market в следующем срезе — если просядут, это плата за
             место.
             NB: комментарий внутри шаблонной строки — бэктики здесь ставить
             нельзя, они рвут литерал. -->
        ${h2Mod("", "ПРОМОКОДЫ", "КЛИК — КОПИРУЕТ", promoDashBody(d.promos),
                "/promo", "ВСЕ КОДЫ", "wide promo-strip")}
        <!-- порядок центра — по Метрике за 25.07–06.08: /market 674 человека,
             /craft 1393 просмотра, /auction 1091, гайд про конверт 493. Значит
             первым экраном идут «что выгодно скрафтить» и «что разбирают на
             ауке»; сборка дня — приятная, но пассивная сводка, ей место ниже. -->
        <div class="h2-split hero">
          ${h2Mod("", "КРАФТЫ ДНЯ", "ВЫГОДА · ЛИКВИДНОСТЬ",
                  h2Findable("craft", "НАЙТИ ПРЕДМЕТ ДЛЯ КРАФТА…", h2Crafts(d.top)),
                  "/craft", "В КРАФТ", "hero-craft")}
          ${h2Mod("", "САМОЕ ПРОДАВАЕМОЕ", "ТЕМП ПРОДАЖ",
                  h2Findable("market", "НАЙТИ ПРЕДМЕТ НА АУКЕ…", salesBody(d.sales)),
                  "/market", "НА АУКЦИОН", "hero-sales")}
        </div>
        ${h2Mod("", "ГРАФИКИ ИНГРЕДИЕНТОВ", "СР. ЦЕНА ПРОДАЖ", h2Charts(d.watch),
                "/craft", "В КРАФТ", "wide")}
        ${h2Mod("", "СБОРКА ДНЯ", "БРОНЯ + КОНТЕЙНЕР + АРТЕФАКТЫ",
                dailyBuildBody(d.daily), "/builds", "К КАЛЬКУЛЯТОРУ", "wide")}
      </main>
      <aside class="h2-news-col">
        ${h2Mod("", "НОВОСТИ САЙТА", "ЧТО ПОМЕНЯЛОСЬ", h2NewsBody(d.feed), "", "", "news")}
        ${h2Mod("", "ТРЕНДЫ БИРЖИ", "ЦЕНА ЗА СУТКИ", h2Trends(d.art), "/auction", "НА БИРЖУ")}
        ${h2Mod("", "ПАТЧИ ИГРЫ", "ФОРУМ EXBO", h2Patches(d.patches), "/patches", "ВСЕ ПАТЧИ")}
      </aside>
    </div>
  </div>`;
}

// ---- макет 2: ПЛАТА (центральная шина новостей, модули-компоненты по бокам) ----
function home2Board(d) {
  // порядок подобран по высоте модулей: крылья должны заканчиваться примерно
  // на одной высоте, иначе симметрия платы разваливается пустотой в одном из них
  const left = [
    h2Mod("R1", "КРАФТЫ ДНЯ", "ВЫГОДА · ЛИКВИДНОСТЬ",
          h2Findable("craft", "НАЙТИ ПРЕДМЕТ ДЛЯ КРАФТА…", h2Crafts(d.top)),
          "/craft", "В КРАФТ"),
    h2Mod("R2", "ВЫБРОС", "ЗАМЕР РАЗ В МИНУТУ", emissionBody(d.em)),
    h2Mod("R3", "ЗАПРАВКА ГЕНЕРАТОРА", "₽ ЗА 1000 ЕД", fuelBody(d.fuelTop),
          "/profile", "ПРИСТРОЙКИ"),
    h2Mod("R4", "САМОЕ ПРОДАВАЕМОЕ", "ТЕМП ПРОДАЖ",
          h2Findable("market", "НАЙТИ ПРЕДМЕТ НА АУКЕ…", salesBody(d.sales)),
          "/market", "НА АУКЦИОН"),
  ].join("");
  const right = [
    h2Mod("C1", "ТРЕНДЫ БИРЖИ", "ЦЕНА ЗА СУТКИ", h2Trends(d.art), "/auction", "НА БИРЖУ"),
    h2Mod("C2", "СБОРКА ДНЯ", "РАЗ В СУТКИ", dailyBuildBody(d.daily), "/builds", "К КАЛЬКУЛЯТОРУ"),
    h2Mod("C3", "ГРАФИКИ ИНГРЕДИЕНТОВ", "СР. ЦЕНА", h2Charts(d.watch), "/craft", "В КРАФТ"),
    h2Mod("C4", "МЕТА ОПЕРАЦИЙ", opsDashNote(d.ops), opsDashBody(d.ops),
          "/operations", "К СТАТИСТИКЕ"),
  ].join("");
  return `<div class="h2 h2-board">
    ${h2Bar(d)}
    <div class="h2-board-grid">
      <div class="h2-wing left">${left}</div>
      <div class="h2-bus">
        <div class="h2-bus-line" aria-hidden="true"></div>
        ${h2Mod("U0", "НОВОСТИ САЙТА", "ЧТО ПОМЕНЯЛОСЬ", h2NewsBody(d.feed), "", "", "news")}
        ${h2Mod("U1", "ПРОМОКОДЫ", "КЛИК — КОПИРУЕТ", promoDashBody(d.promos), "/promo", "ВСЕ КОДЫ")}
        ${h2Mod("U2", "ПАТЧИ ИГРЫ", "ФОРУМ EXBO", h2Patches(d.patches), "/patches", "ВСЕ ПАТЧИ")}
      </div>
      <div class="h2-wing right">${right}</div>
    </div>
  </div>`;
}

function renderHome2() {
  const lay = home2Layout();
  const d = home2Data || {};
  const btns = Object.entries(HOME2_LAYOUTS).map(([k, name]) =>
    `<button class="h2-adm-btn${k === lay ? " on" : ""}" data-lay="${k}">${name}</button>`).join("");
  home.innerHTML = `<div class="h2-adm">
      <span class="h2-adm-l">▸ ПЕСОЧНИЦА МАКЕТОВ · ВИДНА ТОЛЬКО АДМИНУ</span>
      <div class="h2-adm-b">${btns}</div>
      <a class="h2-adm-a" href="/dev/news">✎ РЕДАКТОР НОВОСТЕЙ</a>
      <a class="h2-adm-a" href="/">◂ БОЕВАЯ ГЛАВНАЯ</a>
    </div>` + (lay === "board" ? home2Board(d) : home2Hud(d));
  home.querySelectorAll(".h2-adm-btn").forEach((b) => b.addEventListener("click", () => {
    localStorage.setItem(HOME2_KEY, b.dataset.lay);
    renderHome2();
    window.scrollTo(0, 0);
  }));
  h2Bind(home);
}

// линия средней цены по снапшотам (2 замера/сутки); класс spark — наведение
// показывает значение в точке (общий тултип, обработчик ниже)
const SPARK = { W: 200, H: 48, P: 5 };
function chartSvg(series) {
  const pts = (series || []).filter((e) => e && e.avg != null);
  if (!pts.length) return `<div class="watch-nodata">НЕТ ДАННЫХ — ЖДЁМ ПЕРВЫЙ ЗАМЕР</div>`;
  if (pts.length === 1) pts.push(pts[0]);
  const vals = pts.map((e) => e.avg);
  const { W, H, P } = SPARK;
  const min = Math.min(...vals), max = Math.max(...vals), r = max - min || 1;
  const xy = vals.map((v, i) =>
    `${(i / (vals.length - 1)) * W},${(P + (H - 2 * P) * (1 - (v - min) / r)).toFixed(1)}`);
  const line = xy.join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"
      data-vals="${vals.join(",")}" data-slots="${pts.map((e) => e.slot || "").join(",")}">
    <polyline points="0,${H * 2 / 3} ${W},${H * 2 / 3}" fill="none" stroke="var(--bar-track)" stroke-width="1"></polyline>
    <polyline points="0,${H / 3} ${W},${H / 3}" fill="none" stroke="var(--bar-track)" stroke-width="1"></polyline>
    <polygon points="0,${H} ${line} ${W},${H}" fill="rgba(124,230,142,0.08)"></polygon>
    <polyline points="${line}" fill="none" stroke="var(--green)" stroke-width="1.5"></polyline>
    <line class="spark-x" x1="0" x2="0" y1="0" y2="${H}" stroke="var(--amber)" stroke-width="1"
      vector-effect="non-scaling-stroke" opacity="0"></line>
    <circle class="spark-pt" cx="0" cy="0" r="2.5" fill="var(--amber)" opacity="0"></circle>
  </svg>`;
}

// общий тултип спарклайнов: один элемент на страницу, следует за курсором
let sparkTipEl = null, sparkHover = null;
function sparkHide() {
  if (sparkHover) {
    sparkHover.querySelector(".spark-x").setAttribute("opacity", "0");
    sparkHover.querySelector(".spark-pt").setAttribute("opacity", "0");
    sparkHover = null;
  }
  if (sparkTipEl) sparkTipEl.classList.add("hidden");
}
document.addEventListener("pointermove", (e) => {
  const t = e.target;
  const svg = t && t.closest ? t.closest("svg.spark") : null;
  if (!svg) { sparkHide(); return; }
  if (sparkHover && sparkHover !== svg) sparkHide();
  const vals = (svg.dataset.vals || "").split(",").map(Number);
  if (vals.length < 2) return;
  const slots = (svg.dataset.slots || "").split(",");
  const rc = svg.getBoundingClientRect();
  const i = Math.round(Math.max(0, Math.min(1, (e.clientX - rc.left) / rc.width)) * (vals.length - 1));
  const { W, H, P } = SPARK;
  const min = Math.min(...vals), max = Math.max(...vals), r = max - min || 1;
  const x = (i / (vals.length - 1)) * W;
  sparkHover = svg;
  const cross = svg.querySelector(".spark-x"), dot = svg.querySelector(".spark-pt");
  cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("opacity", "0.7");
  dot.setAttribute("cx", x);
  dot.setAttribute("cy", (P + (H - 2 * P) * (1 - (vals[i] - min) / r)).toFixed(1));
  dot.setAttribute("opacity", "1");
  if (!sparkTipEl) {
    sparkTipEl = document.createElement("div");
    sparkTipEl.className = "spark-tip hidden";
    document.body.appendChild(sparkTipEl);
  }
  sparkTipEl.innerHTML = `<b>${fmt(vals[i])} ₽</b>${slots[i] ? `<span class="t">${fmtSlot(slots[i])}</span>` : ""}`;
  sparkTipEl.classList.remove("hidden");
  // position: fixed внутри зумленного body — координаты и размеры делим/умножаем на --zoom
  const zf = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--zoom")) || 1;
  const tw = sparkTipEl.offsetWidth * zf, th = sparkTipEl.offsetHeight * zf;
  let vx = e.clientX + 12, vy = e.clientY - th - 12;
  if (vx + tw > window.innerWidth - 8) vx = e.clientX - tw - 12;
  if (vy < 8) vy = e.clientY + 16;
  sparkTipEl.style.left = (vx / zf).toFixed(1) + "px";
  sparkTipEl.style.top = (vy / zf).toFixed(1) + "px";
});

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
let chatLastId = 0, chatPollTimer = null, chatReq = null, chatAuthKnown = false;
const CHAT_TIMEOUT = 10000;   // сеть молчит дольше — рвём запрос, иначе виджет заморожен

// Форма зависит от авторизации, а /me отвечает позже, чем рисуется док, — поэтому
// разметка формы и её обработчики живут отдельно от рендера всего виджета.
function chatFormHtml() {
  if (!chatAuthKnown) return "";     // /me ещё не ответил — не мигаем чужой формой
  return ME && ME.authenticated
    ? `<input id="chatInput" maxlength="500" autocomplete="off" placeholder="СООБЩЕНИЕ…"><button id="chatSend">▸</button>`
    : `<a class="chat-login js-open-auth" href="${BASE}/auth/login">ВОЙТИ, ЧТОБЫ ПИСАТЬ</a>`;
}

function chatFormBind() {
  const inp = $("chatInput");
  if (!inp) return;                  // гость или авторизация ещё не подъехала
  const send = async () => {
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
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
}

// /me ответил: док уже нарисован — меняем только форму, ленту не перезагружаем.
function chatAuthChanged() {
  chatAuthKnown = true;
  const form = document.querySelector(".chat-form");
  if (chatOpen && form) { form.innerHTML = chatFormHtml(); chatFormBind(); }
  else chatDockRender();
}

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
  dock.innerHTML = `
    <div class="chat-head">${tabs}<button class="chat-min" id="chatMin" title="Свернуть">▼</button></div>
    <div class="chat-msgs" id="chatMsgs"><div class="spinner">// ЗАГРУЗКА</div></div>
    <div class="chat-form">${chatFormHtml()}</div>`;
  dock.querySelectorAll(".chat-tab").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.room === chatRoom) return;
    chatRoom = b.dataset.room; localStorage.setItem("sz_chat_room", chatRoom);
    chatLastId = 0; chatDockRender();
  }));
  $("chatMin").addEventListener("click", () => {
    chatOpen = false; localStorage.setItem("sz_chat_open", "0"); chatDockRender();
  });
  chatFormBind();
  chatLastId = 0;
  chatRefresh(true);
  chatPollTimer = setInterval(() => chatRefresh(), 5000);
}

function chatDayLabel(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const midnight = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((midnight(now) - midnight(d)) / 86400000);
  if (days === 0) return "СЕГОДНЯ";
  if (days === 1) return "ВЧЕРА";
  const opts = { day: "numeric", month: "long" };
  if (d.getFullYear() !== now.getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString("ru-RU", opts).replace(/\s*г\.$/i, "").toUpperCase();
}

function chatMsgHtml(m) {
  const dt = new Date(m.ts * 1000);
  const t = dt.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  const full = dt.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
  return `<div class="chat-msg"><span class="t" title="${full}">${t}</span> <span class="u">${escapeHtml(m.login)}</span> ${escapeHtml(m.text)}</div>`;
}

// Лента — это последние 500 сообщений комнаты, то есть месяцы истории, а одно
// время без даты на вопрос «когда это писали» не отвечает (просьба Sanshiai,
// 10.08). Ставим разделители дней, как в мессенджерах: дату на каждой строке
// док шириной с колонку не переживёт. chatLastDay — день последнего
// отрисованного сообщения; сообщения приходят порциями по таймеру и клеятся
// в конец, поэтому состояние живёт между вызовами и сбрасывается вместе с лентой.
let chatLastDay = "";

function chatFeedHtml(msgs) {
  let h = "";
  for (const m of msgs) {
    const key = new Date(m.ts * 1000).toDateString();
    if (key !== chatLastDay) {
      h += `<div class="chat-day"><span>${chatDayLabel(m.ts)}</span></div>`;
      chatLastDay = key;
    }
    h += chatMsgHtml(m);
  }
  return h;
}

// reset — первая загрузка комнаты (спиннер на экране), иначе догрузка по таймеру.
// Висящий запрос НЕ должен глушить reset: иначе спиннер стоит до следующего тика,
// а на свёрнутой вкладке браузер душит setInterval до минуты и больше.
async function chatRefresh(reset = false) {
  if (chatReq && !reset) return;                       // обычный опрос ждёт своей очереди
  if (chatReq) chatReq.abort();                        // reset важнее висящего опроса
  const ctl = new AbortController();
  chatReq = ctl;
  let timedOut = false;
  const killer = setTimeout(() => { timedOut = true; ctl.abort(); }, CHAT_TIMEOUT);
  const room = chatRoom, after = reset ? 0 : chatLastId;
  let d = null;
  try {
    const r = await fetch(api(`/chat/${room}?after=${after}`), { signal: ctl.signal });
    d = await r.json();
  } catch (e) { /* обрыв, таймаут или не-JSON — покажем ниже, что связи нет */ }
  clearTimeout(killer);
  if (chatReq === ctl) chatReq = null;
  // отменил более свежий запрос или сменилась комната — молча уходим;
  // свой таймаут (timedOut) — наоборот, показываем, что связи нет
  if ((ctl.signal.aborted && !timedOut) || room !== chatRoom) return;
  const box = $("chatMsgs");
  if (!box) return;
  const hasMsgs = () => !!box.querySelector(".chat-msg");
  if (!d || !Array.isArray(d.messages)) {              // не дошло — спиннер не оставляем
    if (!hasMsgs()) box.innerHTML = `<div class="chat-empty">[!] НЕТ СВЯЗИ — ПОВТОР ЧЕРЕЗ 5 С</div>`;
    return;
  }
  if (reset) { box.innerHTML = ""; chatLastDay = ""; }
  if (d.messages.length) {
    box.querySelectorAll(".chat-empty, .spinner").forEach((el) => el.remove());
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.insertAdjacentHTML("beforeend", chatFeedHtml(d.messages));
    chatLastId = d.last_id;
    if (reset || atBottom) box.scrollTop = box.scrollHeight;
  } else if (!hasMsgs()) {
    box.innerHTML = `<div class="chat-empty">ПОКА ПУСТО — НАПИШИ ПЕРВЫМ.</div>`;
  }
}

// Свёрнутую вкладку браузер тормозит (таймер раз в минуту и реже) — вернулись,
// догружаем сразу, чтобы не смотреть ни на спиннер, ни на устаревшую ленту.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && chatOpen && $("chatMsgs")) chatRefresh();
});

// Виджет рисуем сразу, не дожидаясь /me: сообщения читают все, форму дошлёт
// chatAuthChanged() из loadAuth().
chatDockRender();

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

// Суточный оборот бывает в сотни миллионов — полное число не влезает в строку
// списка, поэтому крупные суммы сокращаем до млн/тыс.
function fmtMoneyShort(n) {
  if (!n) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(".", ",").replace(",0", "") + " МЛН";
  if (n >= 1e4) return Math.round(n / 1e3).toLocaleString("ru-RU") + " ТЫС";
  return fmt(n);
}

function mkRow(r, val, price) {
  // price — крупно справа: посетитель по запросу «аукцион цены» должен увидеть
  // цены сразу в списке, а не в мелкой строке-мете после клика
  const pct = price ? `<div class="pct mk-price">${price}</div>` : "";
  return `<div class="side-row mk-row" data-id="${r.id}" style="border-left-color:transparent">
    <img loading="lazy" src="${asset(r.icon)}" alt="">
    <div class="info"><div class="nm" style="color:${rank(r.color).color}">${escapeHtml(r.name)}</div>
      <div class="meta">${val}</div></div>${pct}</div>`;
}

function renderMarket(ov) {
  const col = (title, note, rows) => `<section>
    <div class="side-head"><div class="side-title">▸ ${title}</div><div class="side-note">${note}</div></div>
    ${rows && rows.length ? `<div class="side-list">${rows.join("")}</div>`
                          : `<div class="empty-sm">ЦЕНЫ ЕЩЁ СЧИТАЮТСЯ В ФОНЕ.</div>`}
  </section>`;
  const liquid = (ov && ov.liquid || []).map((r) =>
    mkRow(r, `${fmtSales(r.sales_per_hour)} ПРОД/Ч`,
          r.min_buyout ? `${fmt(r.min_buyout)} ₽` : ""));
  const expensive = (ov && ov.expensive || []).map((r) =>
    mkRow(r, r.avg ? `СДЕЛКИ ~${fmtMoneyShort(r.avg)} ₽` : "СДЕЛОК ЕЩЁ НЕ БЫЛО",
          `${fmtMoneyShort(r.min_buyout)} ₽`));
  const turnover = (ov && ov.turnover || []).map((r) =>
    mkRow(r, `${fmtSales(r.sales_per_hour)} ПРОД/Ч × ${fmt(r.avg)} ₽`,
          `${fmtMoneyShort(r.turnover)} ₽`));
  page.innerHTML = `<div class="mkmod">
    <div class="section-head">
      <div class="section-title">▸ АУКЦИОН · ЦЕНЫ И ПРОДАЖИ</div>
      <div class="section-note">${ov && ov.tracked ? `${fmt(ov.tracked)} ПРЕДМЕТОВ ПОД НАБЛЮДЕНИЕМ` : ""}</div>
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
      ${col("ОБОРОТ ЗА СУТКИ", "ГДЕ КРУТЯТСЯ ДЕНЬГИ", turnover)}
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
  if (m) {
    m.classList.add("hidden");
    if (m.dataset.detached) m.remove();   // модал, созданный вне /market
  }
  marketState.itemId = null;
  syncModalScroll();
}

// Модал карточки аука лежит в разметке /market. На других разделах (ДЕВ-сканер)
// создаём такой же на body — карточка открывается поверх текущей страницы,
// уходит при закрытии и при навигации (route → mkModalClose).
function openMarketModal(id) {
  if (!$("mkModal")) {
    const m = document.createElement("div");
    m.id = "mkModal";
    m.className = "mk-modal hidden";
    m.dataset.detached = "1";
    m.setAttribute("aria-modal", "true");
    m.setAttribute("role", "dialog");
    m.innerHTML = `<div class="mk-modal-box">
        <button class="mk-modal-x" title="Закрыть (Esc)">✕</button>
        <div id="mkDetail"></div>
      </div>`;
    document.body.appendChild(m);
    m.querySelector(".mk-modal-x").addEventListener("click", mkModalClose);
    m.addEventListener("click", (e) => { if (e.target === m) mkModalClose(); });
  }
  marketState.itemId = id;
  loadMarketItem(id);
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
  mkItemData = d;
  mkBucket = { qlt: null, ptn: null };   // новая карточка — фильтр сброшен
  box.innerHTML = `<div class="mk-item">
    <div class="mk-head">
      <img src="${asset(it.icon)}" alt="">
      <div class="mk-title" style="color:${rank(it.color).color}">${escapeHtml(it.name || id)}</div>
      <a class="mk-card" href="/item/${id}">КАРТОЧКА ПРЕДМЕТА ▸</a>
    </div>
    ${d.error ? `<div class="note-warn"><span class="mark">[!]</span> АУКЦИОН НЕ ОТВЕТИЛ (${escapeHtml(String(d.error))}) — ПОКАЗЫВАЮ ЧТО ЕСТЬ.</div>` : ""}
    <div id="mkBuckets"></div>
    <div class="mk-chart-wrap">
      <div class="dash-grp mkc-head"><span>ГРАФИК ПРОДАЖ · ЦЕНА/ШТ И ОБЪЁМ${d.has_buckets ? " · ВСЕ КОРЗИНЫ" : ""}</span>
        <span class="mkc-ranges" id="mkcRanges"></span></div>
      <div class="mk-chart" id="mkChartBox"></div>
      <div class="mkc-note" id="mkChartNote"></div>
    </div>
    <div class="mk-tables" id="mkTables"></div>
  </div>`;
  renderMkBuckets();
  renderMkTables();
  initSalesChart(id);
}

// ---------- карточка аука: корзины качество × заточка ----------
// У артефактов и снаряжения цена зависит от качества и заточки в разы, поэтому
// лоты и продажи считаются отдельно по корзинам. Заточка группируется как в игре:
// +0–4 / +5–9 / +10–14 / +15 (см. market.ptn_bucket на бэке).
let mkItemData = null;
let mkBucket = { qlt: null, ptn: null };   // null — «все»

// корзины заточки и имена качества — общие с биржей артефактов
// (ptnBucket / ptnRange / qltLabel определены ниже по файлу, к вызову готовы)
const mkBucketMatch = (x) =>
  (mkBucket.qlt == null || (x.qlt || 0) === mkBucket.qlt)
  && (mkBucket.ptn == null || ptnBucket(x.ptn) === mkBucket.ptn);

function renderMkBuckets() {
  const box = $("mkBuckets");
  if (!box || !mkItemData) return;
  if (!mkItemData.has_buckets) { box.innerHTML = ""; return; }
  const all = [...(mkItemData.lots || []), ...(mkItemData.sales || [])];
  const qlts = [...new Set(all.map((x) => x.qlt || 0))].sort((a, b) => a - b);
  const ptns = [...new Set(all.map((x) => ptnBucket(x.ptn)))].sort((a, b) => a - b);
  const chip = (kind, val, label, on) =>
    `<button class="mkb-chip${on ? " on" : ""}" data-k="${kind}" data-v="${val == null ? "" : val}">${label}</button>`;
  const qRow = qlts.length > 1 ? `<div class="mkb-row"><span class="mkb-l">КАЧЕСТВО</span>
    ${chip("qlt", null, "ВСЕ", mkBucket.qlt == null)}
    ${qlts.map((q) => chip("qlt", q, qltLabel(q), mkBucket.qlt === q)).join("")}</div>` : "";
  const pRow = ptns.length > 1 || (ptns.length === 1 && ptns[0] !== 0)
    ? `<div class="mkb-row"><span class="mkb-l">ЗАТОЧКА</span>
      ${chip("ptn", null, "ВСЕ", mkBucket.ptn == null)}
      ${PTN_LEVELS.filter((v) => ptns.includes(v))
        .map((v) => chip("ptn", v, ptnRange(v), mkBucket.ptn === v)).join("")}</div>` : "";
  box.innerHTML = qRow || pRow ? `<div class="mk-buckets">${qRow}${pRow}</div>` : "";
  box.querySelectorAll(".mkb-chip").forEach((b) => b.addEventListener("click", () => {
    mkBucket[b.dataset.k] = b.dataset.v === "" ? null : +b.dataset.v;
    renderMkBuckets();
    renderMkTables();
  }));
}

function renderMkTables() {
  const box = $("mkTables");
  if (!box || !mkItemData) return;
  const d = mkItemData;
  const bk = d.has_buckets;
  const fLots = (d.lots || []).filter(mkBucketMatch);
  const fSales = (d.sales || []).filter(mkBucketMatch);
  // сводка по выбранной корзине: за сколько реально купить и почём уходит
  const sold = fSales.reduce((s, x) => s + (x.amount || 1), 0);
  const soldSum = fSales.reduce((s, x) => s + (x.price || 0), 0);
  const avgUnit = sold ? Math.round(soldSum / sold) : null;
  const minUnit = fLots.length ? fLots[0].unit : null;
  const bcell = (l, v, cls) => `<span class="mks-i">${l} <b class="${cls || ""}">${v}</b></span>`;
  const summary = `<div class="mk-sum">
    ${bcell("МИН. ВЫКУП", minUnit != null ? fmt(minUnit) + " ₽/ШТ" : "—")}
    ${bcell("СРЕДНЯЯ ПРОДАЖА", avgUnit != null ? fmt(avgUnit) + " ₽/ШТ" : "—")}
    ${bcell("ПРОДАНО", sold ? fmt(sold) + " ШТ" : "—")}
    ${bk ? `<span class="mks-i mks-note">${mkBucket.qlt == null && mkBucket.ptn == null
      ? "ПО ВСЕМ КОРЗИНАМ — ВЫБЕРИ КАЧЕСТВО/ЗАТОЧКУ ДЛЯ ТОЧНОЙ ЦЕНЫ"
      : `КОРЗИНА: ${mkBucket.qlt == null ? "ЛЮБОЕ КАЧЕСТВО" : qltLabel(mkBucket.qlt)}${
        mkBucket.ptn == null ? "" : " · ЗАТОЧКА " + ptnRange(mkBucket.ptn)}`}</span>` : ""}
  </div>`;
  const bcols = bk ? `<th class="r">КЧ</th><th class="r">ЗТЧ</th>` : "";
  const bvals = (x) => bk ? `<td class="r">${x.qlt || 0}</td><td class="r">${x.ptn ? "+" + x.ptn : "—"}</td>` : "";
  const lots = fLots.slice(0, 20).map((l) => `<tr>
      <td class="r">${fmt(l.unit)}</td>
      <td class="r">${l.amount}</td>${bvals(l)}
      <td class="r">${fmt(l.buyout)}</td>
      <td>${l.end ? fmtLotTime(l.end) : "—"}</td>
    </tr>`).join("");
  const sales = fSales.slice(0, 20).map((s) => `<tr>
      <td>${s.time ? fmtLotTime(s.time) : "—"}</td>
      <td class="r">${s.unit != null ? fmt(s.unit) : "—"}</td>
      <td class="r">${s.amount}</td>${bvals(s)}
      <td class="r">${s.price != null ? fmt(s.price) : "—"}</td>
    </tr>`).join("");
  box.innerHTML = `${summary}
    <div class="mk-tbl">
      <div class="dash-grp">АКТИВНЫЕ ЛОТЫ · С ВЫКУПОМ ${fmt(fLots.length)}${
        d.lots_total != null ? ` ИЗ ${fmt(d.lots_total)}` : ""} (20 ДЕШЁВЫХ)</div>
      ${lots ? `<table><thead><tr><th class="r">ЦЕНА/ШТ</th><th class="r">КОЛ-ВО</th>${bcols}<th class="r">ВЫКУП</th><th>ДО (МСК)</th></tr></thead><tbody>${lots}</tbody></table>`
             : `<div class="empty-sm">ЛОТОВ С ВЫКУПОМ НЕТ${bk ? " В ЭТОЙ КОРЗИНЕ" : ""}.</div>`}
    </div>
    <div class="mk-tbl">
      <div class="dash-grp">ПОСЛЕДНИЕ ПРОДАЖИ${fSales.length ? ` · ${fmt(fSales.length)}` : ""}</div>
      ${sales ? `<table><thead><tr><th>ВРЕМЯ (МСК)</th><th class="r">ЦЕНА/ШТ</th><th class="r">КОЛ-ВО</th>${bcols}<th class="r">СУММА</th></tr></thead><tbody>${sales}</tbody></table>`
              : `<div class="empty-sm">ПРОДАЖ НЕ НАЙДЕНО${bk ? " В ЭТОЙ КОРЗИНЕ" : ""}.</div>`}
    </div>`;
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
    // Позиция тултипа — в ЛОКАЛЬНЫХ координатах бокса (он position:absolute внутри).
    // getBoundingClientRect/clientX отдают вьюпортные пиксели, а left/top читаются
    // как неотмасштабированные, поэтому делим на zoom (см. --zoom, body zoom 1.2).
    // По горизонтали держимся внутри графика: модал скроллится (overflow-y:auto),
    // и вылезший вправо тултип обрезался бы его краем — у края уходим влево от курсора.
    const zf = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--zoom")) || 1;
    const wr = box.getBoundingClientRect();
    const bw = wr.width / zf, tw = tip.offsetWidth, th = tip.offsetHeight;
    const lx = (ev.clientX - wr.left) / zf, ly = (ev.clientY - wr.top) / zf;
    let x = lx + 14;
    if (x + tw > bw - 4) x = lx - tw - 14;      // у правого края — влево от курсора
    let y = ly + 14;
    if (ev.clientY + (th + 22) * zf > window.innerHeight) y = ly - th - 12;
    tip.style.left = Math.max(4, Math.min(x, bw - tw - 4)).toFixed(1) + "px";
    tip.style.top = y.toFixed(1) + "px";
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
    // выгоду показываем только там, где цене продажи можно верить (trust=ok):
    // у неликвида «последняя сделка» бывает двухлетней давности, а стартовый
    // хлам на ауке «стоит» сотни тысяч — это перевод валюты, а не выгода
    const roi = r.trust === "ok"
      ? `<div class="bt-roi ${r.pct >= 0 ? "up" : "down"}" title="ПРОДАЖА ~${fmt(r.sell_net)} ₽ ЗА ВЫЧЕТОМ КОМИССИИ, ПОСЛЕДНЯЯ СДЕЛКА ${r.sale_age_days < 1 ? "СЕГОДНЯ" : Math.round(r.sale_age_days) + " ДН. НАЗАД"}">${r.pct > 0 ? "+" : ""}${fmt(r.pct)}%</div>`
      : "";
    return `<tr class="brt-row" data-id="${r.id}">
      <td class="bt-selc c-sel"><input type="checkbox" class="bt-selbox" data-id="${r.id}" ${btSel.has(r.id) ? "checked" : ""}></td>
      <td class="c-itm"><div class="bt-item"><img loading="lazy" src="${asset(r.icon)}" alt="">
        <span class="nm" style="color:${rank(r.color).color}">${escapeHtml(r.name)}</span>${missing}${cur}</div></td>
      <td class="bt-place c-place" data-l="ГДЕ">${escapeHtml(r.settlement_name)}${r.level ? ` <span class="lv">УР.${r.level}</span>` : ""}${places}</td>
      <td class="r c-key">${cost}${roi}</td>
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
      «ФАРМ» — ВХОДЫ, КОТОРЫХ НЕТ В ПРОДАЖЕ: КВЕСТОВЫЕ, А ТАКЖЕ ЖЕТОНЫ И ТАЛОНЫ (ИХ ЗАРАБАТЫВАЮТ, А НЕ ПОКУПАЮТ).
      ЗЕЛЁНЫМ ПОД СТОИМОСТЬЮ — ВЫГОДА ПЕРЕПРОДАЖИ, И ТОЛЬКО У ПРЕДМЕТОВ, КОТОРЫЕ РЕАЛЬНО ПРОДАВАЛИСЬ
      В ПОСЛЕДНИЕ ДВЕ НЕДЕЛИ: ПО НЕЛИКВИДУ «ЦЕНА» НА АУКЕ БЫВАЕТ ДВУХЛЕТНЕЙ ДАВНОСТИ.
      КЛИК ПО СТРОКЕ — ДЕТАЛИ ОБМЕНА. ГАЛОЧКА — В КОРЗИНУ: СУММАРНАЯ СТОИМОСТЬ НЕСКОЛЬКИХ ОБМЕНОВ СРАЗУ.</div>
    <div class="bt-wrap"><table class="bt-table bt-cards">
      <thead><tr><th class="bt-selc" style="width:34px"></th><th style="width:46%">ПРЕДМЕТ</th>
        <th style="width:30%">ГДЕ</th><th class="r" style="width:20%">СТОИМОСТЬ · ВЫГОДА</th></tr></thead>
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
  if (d.sell_net != null) {
    // возраст последней сделки: без него «цена продажи» неликвида вводит в
    // заблуждение — предмет мог продаваться последний раз год назад
    const age = d.sale_age_days == null ? " <span class='unit'>СДЕЛОК НЕ ВИДНО</span>"
      : d.sell_fresh ? ""
      : ` <span class='unit warn'>ПОСЛЕДНЯЯ СДЕЛКА ${Math.round(d.sale_age_days)} ДН. НАЗАД</span>`;
    stats.push(`ПРОДАЖА~ (НЕТТО): <b>${fmt(d.sell_net)} ₽</b>${d.sell_basis === "buyout" ? " <span class='unit'>ПО ВЫКУПУ</span>" : ""}${age}`);
  }
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
  if (r.value_market != null && r.disasm) {
    // предмет личный: продать нельзя, поэтому показываем цену замещения и её вывод
    chan.push(`<div class="bt-ing"><span>РЫНОЧНАЯ ЦЕНА (ЧЕРЕЗ РАЗБОР)</span>
      <span class="bt-ing-price">${fmt(r.value_market)} ₽
        <span class="bt-via">← ${r.disasm.count}× из «${escapeHtml(r.disasm.parent_name)}»
        (${fmt(r.disasm.parent_unit)} ₽ на ауке)</span></span></div>`);
  } else if (r.value_auction != null) {
    chan.push(`<div class="bt-ing"><span>СБЫТ НА АУКЕ (−${obmenData.fee_pct}%)</span>
      <span class="bt-ing-price">${fmt(r.value_auction)} ₽
        <span class="unit">${r.sell_basis === "sales" ? "ПО СДЕЛКАМ" : "ПО ВЫКУПУ"}</span></span></div>`);
  } else {
    chan.push(`<div class="bt-ing"><span>РЫНОЧНАЯ ЦЕНА</span>
      <span class="bt-ing-price">ЦЕНА ГРЕЕТСЯ…</span></div>`);
  }
  chan.push(`<div class="bt-ing"><span>СБЫТ СКУПЩИКУ (МГНОВЕННО)</span>
    <span class="bt-ing-price">${r.value_vendor != null ? fmt(r.value_vendor) + " ₽" : "—"}</span></div>`);
  const rateLine = r.rate != null
    ? `<div class="bt-ing bt-total"><span>КУРС (ЛУЧШИЙ КАНАЛ — ${
        r.basis === "vendor" ? "СКУПЩИК" : r.basis === "market" ? "РАЗБОР" : "АУКЦИОН"})</span>
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
  // предмет барется → добавить кнопку «бартер» в строку действий (прокрутка к блоку)
  const acts = $("itemActs");
  if (acts && !acts.querySelector("[data-act='barter']")) {
    acts.insertAdjacentHTML("beforeend", `<button class="item-act" data-act="barter">▸ БАРТЕР</button>`);
    acts.querySelector("[data-act='barter']").addEventListener("click", () =>
      box.scrollIntoView({ behavior: "smooth", block: "start" }));
  }
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

// серверный SEO-блок (тело патча/гайда/квеста) прячем — JS рисует интерактивную
// версию в #page; краулеры без JS видят серверный текст
function hideSeoBlock() {
  const s = document.getElementById("seoProse");
  if (s) s.hidden = true;
}

async function openPatch(pid) {
  hideSeoBlock();
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
  adInsert(page);
  renderComments(`patch:${pid}`);
}

// ---------- реклама РСЯ ----------
// Блок включает сервер: <html data-ads="R-A-XXXXXXX-N"> из config.RSYA_BLOCK_ID.
// Пусто — скрипт Яндекса не грузится вообще (это состояние по умолчанию).
//
// Ставим ОДИН блок «в тексте» и только в статьях (гайд, патчнот). На
// калькуляторах рекламы нет намеренно: это ядро продукта, а отказы и глубину там
// чинили весь июль-август.
//
// SPA-грабли: РСЯ считает показ по вызову render(). При клиентской навигации
// страница не перезагружается, поэтому на каждую статью нужен свой контейнер и
// свой pageNumber — иначе показ засчитается один раз за визит, а по Метрике
// глубина у нас 4.0, то есть потеряли бы три четверти показов.
const AD_BLOCK = document.documentElement.dataset.ads || "";          // в тексте статьи
const AD_BOTTOM = document.documentElement.dataset.adsBottom || "";   // под контентом
let adCtx = null;      // промис загрузки context.js — грузим один раз за визит
let adPage = 0;        // «номер страницы» для РСЯ, растёт на каждый показ
const adLive = new Map();  // blockId -> id последнего контейнера (для destroy)

function adLoadCtx() {
  if (adCtx) return adCtx;
  window.yaContextCb = window.yaContextCb || [];
  adCtx = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://yandex.ru/ads/system/context.js";
    s.async = true;                 // грузим лениво: критический путь не трогаем
    s.onload = resolve;
    s.onerror = reject;             // блокировщик — просто живём без рекламы
    document.head.appendChild(s);
  });
  return adCtx;
}

// Общий показ: host уже в DOM, drop() убирает место, если рекламы не будет.
// Стратегия «максимальный доход» в РСЯ поднимает CPM ценой заполняемости — часть
// показов остаётся без подходящего объявления. Пустая рамка с подписью «РЕКЛАМА»
// читается как сломанная вёрстка, поэтому незаполненную врезку убираем совсем.
// Блокировщик приводит сюда же: context.js просто не загрузится.
function adMount(host, blockId, drop) {
  if (!blockId) return;
  const slotId = `adSlot${++adPage}`;
  const num = adPage;
  host.innerHTML = `<div class="ad-label">РЕКЛАМА</div><div id="${slotId}"></div>`;
  // Проверку «рекламы не приехало» считаем от момента, когда место доехало до
  // экрана, а не от монтирования. РСЯ умеет откладывать отрисовку до показа, и
  // тогда высота остаётся нулевой сколько угодно долго — а на телефоне нижняя
  // врезка лежит экранов на десять ниже, так что слепой таймер сносил бы её
  // всегда, ещё до того как человек до неё долистает.
  const check = () => setTimeout(() => {
    const el = document.getElementById(slotId);
    if (el && !el.offsetHeight) drop();      // рекламы не приехало
  }, 4000);
  if (typeof IntersectionObserver === "function") {
    const io = new IntersectionObserver((es) => {
      if (!es.some((e) => e.isIntersecting)) return;
      io.disconnect();
      check();
    }, { rootMargin: "300px" });
    io.observe(host);
  } else check();

  adLoadCtx().then(() => {
    window.yaContextCb.push(() => {
      try {
        const prev = adLive.get(blockId);
        if (prev) window.Ya.Context.AdvManager.destroy({ blockId, renderTo: prev });
        // контейнер мог уехать, пока грузился скрипт (быстрый переход)
        if (!document.getElementById(slotId)) return;
        window.Ya.Context.AdvManager.render({
          blockId, renderTo: slotId, pageNumber: num,
          onError: drop,     // нет подходящей рекламы — врезки как не было
        });
        adLive.set(blockId, slotId);
      } catch (e) { drop(); }
    });
  }).catch(drop);
}

// Врезка после третьего блока текста: выше — сразу реклама в лицо, ниже — её не
// увидят. Короткие статьи пропускаем совсем, в них врезка выглядит как половина
// страницы (правило «без баннеров на пол-экрана» — решение владельца).
function adInsert(root) {
  if (!AD_BLOCK) return;
  const body = root.querySelector(".patch-body");
  if (!body) return;
  const kids = [...body.children];
  if (kids.length < 8) return;
  const box = document.createElement("div");
  box.className = "ad-slot";
  kids[3].after(box);
  adMount(box, AD_BLOCK, () => box.remove());
}

// Нижняя врезка — под контентом раздела, когда человек уже получил ответ.
// Правило владельца: реклама везде, но не поперёк контента. Значит в наборе
// должны быть ВСЕ страницы с ответом, и список сверен с роутером целиком.
//
// Разделы, которых тут нет, остаются без рекламы намеренно: /search (самый
// вовлечённый вход сайта, глубина 18.5 — не трогаем), /map (врезка не влезает
// под полноэкранный холст), /profile, /home2 и /dev/* (админские), юридические
// страницы.
const AD_BOTTOM_PATHS = new Set([
  "/", "/market", "/auction", "/barter", "/obmen", "/builds", "/compare",
  "/operations", "/items", "/guides", "/patches", "/quests", "/promo",
  "/craft", "/vygodno-kraftit",
]);
// Карточки: /item/… и /artefact/… — один и тот же тип страницы (детальная
// карточка с ценами), поэтому и правило у них одно.
const adBottomOk = (p) => AD_BOTTOM_PATHS.has(p)
  || /^\/(guides|patches|quests|item|artefact)\/[^/]+$/.test(p);

let adBottomTimer = null, adBottomAt = 0;
const adHost = document.getElementById("adBottom");   // ссылку держим сами: внутри
const adMain = document.querySelector("main.main");   // секции узел бывает отцеплен

// Замер на телефоне (390×844): врезка внизу главной начиналась на 5638-м
// пикселе — 6.7 экрана вниз, на /market 5.2. Столько не листает почти никто,
// поэтому на узких экранах место переезжает под первый блок контента, который
// занял экран: ответ человек уже получил, а реклама попадается на глаза.
// Внутрь карточки (section/article) не лезем — встаём после неё.
function adPlaceMobile(host) {
  if (innerWidth > 900 || !adMain) return;      // на десктопе врезка остаётся внизу
  const sec = [detail, page, home, results].find(
    (s) => s && !s.classList.contains("hidden") && s.offsetHeight > 40);
  if (!sec) return;
  const vh = innerHeight;
  const limit = adMain.getBoundingClientRect().top + scrollY + vh * 0.8;
  let box = sec;
  for (let step = 0; step < 6; step++) {
    const kids = [...box.children].filter((e) => e !== host && e.offsetHeight > 0);
    if (!kids.length) return;
    // порядок берём по факту отрисовки: на телефоне grid-areas и order уже
    // переставили колонки, и DOM-порядок с экранным не совпадает
    kids.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
    if (kids.length === 1) { box = kids[0]; continue; }
    const hit = kids.find((e) => e.getBoundingClientRect().bottom + scrollY > limit);
    if (!hit) return;                                   // контента на экран не набралось
    // сначала спуск, и только потом проверка «последний»: раздел обычно
    // завёрнут в один общий контейнер, и он же последний ребёнок — выходить на
    // нём значило бы никогда никуда не переехать
    if (hit.offsetHeight > vh * 1.6 && hit.children.length > 1
        && !hit.matches("section, article")) { box = hit; continue; }
    if (hit === kids[kids.length - 1]) return;          // после него всё равно низ
    hit.after(host);
    return;
  }
}

function adBottomReset() {
  if (!adHost) return;
  adHost.hidden = true;
  adHost.innerHTML = "";
  if (adMain && adHost.parentElement !== adMain) adMain.appendChild(adHost);
}

function adBottomShow(path) {
  if (!adHost || location.pathname !== path) return;
  adPlaceMobile(adHost);
  adHost.hidden = false;
  adBottomAt = Date.now();
  adMount(adHost, AD_BOTTOM, adBottomReset);
}

function adBottomRoute(path) {
  if (!adHost) return;
  clearTimeout(adBottomTimer);
  adBottomReset();                     // на новом роуте старый показ не годится
  if (!AD_BOTTOM || !adBottomOk(path)) return;
  // ждём, пока раздел догрузится: route() отрабатывает раньше данных, и без
  // паузы блок на секунду вылезал бы под спиннером у самого верха экрана
  adBottomTimer = setTimeout(() => adBottomShow(path), 1500);
}

// Разделы перерисовываются целиком (`page.innerHTML = …`) — на смене фильтра,
// а не только при переходе. Переехавшая внутрь врезка уезжает вместе с ними,
// поэтому ловим момент и ставим её заново. Корни живут вечно, меняется только
// их содержимое, так что childList без subtree ловит ровно перерисовки.
if (adHost) {
  const back = new MutationObserver(() => {
    if (adHost.isConnected) return;
    clearTimeout(adBottomTimer);
    adBottomReset();
    // защита от раздела, который перерисовывает себя сам: показ РСЯ не чаще
    // раза в 15 с, иначе накрутили бы показы на ровном месте
    if (!AD_BOTTOM || !adBottomOk(location.pathname)
        || Date.now() - adBottomAt < 15000) return;
    adBottomTimer = setTimeout(() => adBottomShow(location.pathname), 1200);
  });
  [home, page, detail, results].forEach((r) => r && back.observe(r, { childList: true }));
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
  hideSeoBlock();
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
  adInsert(page);
  renderComments(`guide:${slug}`);
}

// ---------- промокоды: страница /promo + модуль на главной ----------
// Клик по коду копирует его в буфер; истёкшие коды бэкенд удаляет сам.

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {  // http / старый браузер — фолбэк через скрытый textarea
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    try { return document.execCommand("copy"); }
    catch (e2) { return false; }
    finally { ta.remove(); }
  }
}

// повесить копирование на все кнопки-коды внутри root (страница, дашборд)
function bindPromoCopy(root) {
  root.querySelectorAll(".promo-code[data-code]").forEach((el) =>
    el.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (el.dataset.ref) ymGoal("promo_ref_click");   // цель Я.Метрики: клик по реферальному промокоду
      const ok = await copyText(el.dataset.code);
      el.classList.add("copied");
      const hint = el.querySelector(".pc-hint");
      if (hint) hint.textContent = ok ? "СКОПИРОВАНО ✓" : "НЕ СКОПИРОВАЛОСЬ";
      setTimeout(() => {
        el.classList.remove("copied");
        if (hint) hint.textContent = "КОПИРОВАТЬ";
      }, 1600);
    }));
}

// код-промокод копируется по клику; промо-ссылка (Steam DLC и т.п.) — открывается
const promoCodeBtn = (p) => {
  if (p.url) {
    const steam = /steampowered\.com|store\.steam/i.test(p.url);
    return `<a class="promo-code promo-link" href="${escapeHtml(p.url)}" target="_blank" rel="noopener nofollow"
      title="Открыть страницу и забрать">
      <span class="pc-code">${steam ? "ЗАБРАТЬ В STEAM" : "ЗАБРАТЬ ПО ССЫЛКЕ"}</span>
      <span class="pc-hint">ОТКРЫТЬ ▸</span></a>`;
  }
  return `<button type="button" class="promo-code" data-code="${escapeHtml(p.code)}"${p.is_ref ? ' data-ref="1"' : ''}
    title="Нажми — код скопируется">
    <span class="pc-code">${escapeHtml(p.code)}</span>
    <span class="pc-hint">КОПИРОВАТЬ</span></button>`;
};

// expires_at: "YYYY-MM-DDTHH:MM" МСК; T23:59 = «весь день включительно»
const promoExpiry = (p) => {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})$/.exec(p.expires_at || "");
  if (!m) return "БЕЗ СРОКА ДЕЙСТВИЯ";
  const date = fmtPatchDate(m[1]).toUpperCase();
  return m[2] === "23:59" ? `ДЕЙСТВУЕТ ДО ${date} ВКЛЮЧИТЕЛЬНО`
                          : `ДЕЙСТВУЕТ ДО ${date}, ${m[2]} МСК`;
};

function promoCard(p) {
  // description — доверенный HTML из DEV-редактора (как тела гайдов/квестов)
  return `<article class="promo-card${p.is_ref ? " promo-ref" : ""}">
    <div class="promo-b">
      ${p.is_ref ? `<div class="promo-ref-badge">★ РЕФЕРАЛЬНЫЙ ПРОМОКОД САЙТА</div>` : ""}
      <div class="promo-t">${escapeHtml(p.title)}</div>
      ${promoCodeBtn(p)}
      ${p.description ? `<div class="promo-d patch-body">${p.description}</div>` : ""}
      <div class="promo-exp">${promoExpiry(p)}</div>
    </div>
    ${p.image ? `<img class="promo-img" loading="lazy" src="${escapeHtml(p.image)}" alt="">` : ""}
  </article>`;
}

async function openPromo() {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА ПРОМОКОДОВ</div>`;
  window.scrollTo(0, 0);
  let d;
  try {
    d = await fetch(api("/promos")).then((r) => r.json());
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`;
    return;
  }
  if (location.pathname !== "/promo") return;
  const items = d.items || [];
  const ref = items.find((p) => p.is_ref);           // место сверху — под реферальный
  const rest = items.filter((p) => !p.is_ref);
  page.innerHTML = `<div class="btmod">
    <div class="section-head">
      <div class="section-title">▸ ПРОМОКОДЫ STALZONE</div>
      <div class="section-note">КЛИК ПО КОДУ — КОПИРУЕТ · ИСТЁКШИЕ УБИРАЮТСЯ АВТОМАТИЧЕСКИ</div>
    </div>
    <div class="promo-list">
      ${ref ? promoCard(ref) : ""}
      ${rest.map(promoCard).join("")
        || (!ref ? `<div class="empty-sm">АКТУАЛЬНЫХ ПРОМОКОДОВ СЕЙЧАС НЕТ — ЗАГЛЯНИ ПОЗЖЕ.</div>` : "")}
    </div>
  </div>`;
  bindPromoCopy(page);
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
const _qLoadSet = (k) => { try { return new Set(JSON.parse(localStorage.getItem(k) || "[]")); } catch (e) { return new Set(); } };
let questExpanded = _qLoadSet("sz_quest_exp");         // раскрытые группы (id)
let questDone = _qLoadSet("sz_quest_done");            // выполненные квесты (id) — память игрока

const questFactionOf = (id) =>
  (questData && questData.factions.find((f) => f.id === id))
  || { id, name: id, color: "#7ce68e" };

// квест виден в линейке fid, если это его основная ИЛИ доп. линейка (общий квест)
const questInFaction = (q, fid) =>
  q.faction === fid || (q.factions || []).includes(fid);

async function openQuests(selId) {
  hideSeoBlock();
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
  // линейка по умолчанию — только из непустых (сохранённая в localStorage могла
  // остаться от фракции, у которой квестов ещё нет)
  const filled = questFilledFactions(d);
  if (!filled.some((f) => f.id === questFaction))
    questFaction = (filled[0] || d.factions[0] || {}).id;
  renderQuests();
  if (selId != null) openQuestModal(selId);
}

// фракции, у которых есть хотя бы один квест (админу видны и черновики).
// Пустые табы не рисуем: заход из поиска попадал в «ЛИНЕЙКА ЕЩЁ ЗАПОЛНЯЕТСЯ»
// и половина визитов закрывалась сразу (аудит Метрики, июль 2026).
function questFilledFactions(d) {
  return d.factions.filter((f) => d.items.some((q) => questInFaction(q, f.id)));
}

function renderQuests() {
  const d = questData;
  const tabs = questFilledFactions(d).map((f) => {
    const n = d.items.filter((q) => questInFaction(q, f.id)).length;
    return `<button class="qst-tab${f.id === questFaction ? " on" : ""}" data-f="${f.id}"
      style="--fc:${f.color}">${escapeHtml(f.name.toUpperCase())} <span>${n}</span></button>`;
  }).join("");
  page.innerHTML = `<div class="btmod">
    <div class="section-head">
      <div class="section-title">▸ КВЕСТЫ · СХЕМЫ ЛИНЕЕК</div>
      <div class="section-note">КЛИК ПО КВЕСТУ — ПРОХОЖДЕНИЕ, НАГРАДА И ТОЧКИ НА КАРТЕ</div>
    </div>
    <div class="qst-tabs">${tabs}</div>
    <div class="qst-wrap" id="qstWrap"></div>
    <div class="map-legend">Схема идёт сверху вниз, стрелка — «открывается после». Блоки с
      <b style="color:var(--amber)">янтарной</b> рамкой — основная линейка, серые — побочные.
      📍 — у квеста есть точки на карте. Колесо — зум, тяни пустое поле — двигать схему.${d.is_admin
        ? " Пунктирные — черновики (видны только админам). <b style=\"color:var(--green)\">Расставлять блоки и связи — в ДЕВ · КВЕСТЫ → КАРТА ЛИНЕЕК.</b>"
        : ""}</div>
  </div>`;
  page.querySelectorAll(".qst-tab").forEach((b) => b.addEventListener("click", () => {
    questFaction = b.dataset.f;
    localStorage.setItem("sz_quest_f", questFaction);
    renderQuests();
  }));
  renderQuestChart(questFaction);
}

// публичная схема (read-only, клик → модал)
function renderQuestChart(faction) {
  renderQuestGraph($("qstWrap"), faction, { edit: false });
}

// pan/zoom-граф линейки. edit=false — публично (клик по блоку → модал);
// edit=true — дев-карта: тянуть блоки, рисовать стрелки от точки снизу к
// другому блоку, клик по стрелке — удалить связь. Колесо — зум, тянуть пустое
// место — двигать полотно. Ручные позиции pos[faction] важнее авто-раскладки.
function renderQuestGraph(host, faction, opts) {
  const edit = !!(opts && opts.edit);
  const items = questData.items.filter((q) => questInFaction(q, faction));
  if (!items.length) {
    host.innerHTML = `<div class="empty-sm" style="padding:24px 10px">ЛИНЕЙКА ЕЩЁ ЗАПОЛНЯЕТСЯ — КВЕСТЫ ПОЯВЯТСЯ ПОЗЖЕ.</div>`;
    return;
  }
  const byId = new Map(items.map((q) => [q.id, q]));

  // --- группы: свёрнутая группа = один «модуль»-юнит, раскрытая = участники по одному
  const groups = (questData.groups || []).filter((g) => items.some((q) => q.group_id === g.id));
  const groupById = new Map(groups.map((g) => [g.id, g]));
  const membersOf = new Map(groups.map((g) => [g.id, items.filter((q) => q.group_id === g.id)]));
  const groupOfQ = new Map();
  items.forEach((q) => { if (q.group_id && groupById.has(q.group_id)) groupOfQ.set(q.id, groupById.get(q.group_id)); });
  const isCollapsed = (gid) => !questExpanded.has(gid);
  const unitOfQ = (qid) => { const g = groupOfQ.get(qid); return (g && isCollapsed(g.id)) ? "g" + g.id : "q" + qid; };
  const isGroupUnit = (u) => u[0] === "g";
  const groupOfUnit = (u) => groupById.get(+u.slice(1));
  const questOfUnit = (u) => byId.get(+u.slice(1));

  const unitIds = new Set();
  items.forEach((q) => unitIds.add(unitOfQ(q.id)));
  const uSort = (u) => isGroupUnit(u) ? -1 : (questOfUnit(u).sort || 0);
  const uMain = (u) => isGroupUnit(u) || questOfUnit(u).kind === "main";
  const uParents = new Map();
  const depth = new Map();      // глубина юнита по связям = ряд сверху вниз
  const autoCol = new Map();    // авто-колонка внутри ряда

  // Пересобирается после каждой правки стрелок: раньше карта связей считалась
  // один раз при сборке графа, а paint() рисовал именно её — удалённая связь
  // оставалась на экране до перезагрузки страницы.
  const relinkGraph = () => {
    uParents.clear(); depth.clear(); autoCol.clear();
    unitIds.forEach((u) => uParents.set(u, new Set()));
    items.forEach((q) => (q.parents || []).forEach((pid) => {
      if (!byId.has(pid)) return;
      const uq = unitOfQ(q.id), up = unitOfQ(pid);
      if (uq !== up) uParents.get(uq).add(up);
    }));
    const dep = (u, stack) => {
      if (depth.has(u)) return depth.get(u);
      if (stack.has(u)) return 0;
      stack.add(u);
      const ps = [...uParents.get(u)];
      const dv = ps.length ? Math.max(...ps.map((p) => dep(p, stack))) + 1 : 0;
      stack.delete(u); depth.set(u, dv); return dv;
    };
    unitIds.forEach((u) => dep(u, new Set()));
    const bands = [];
    unitIds.forEach((u) => (bands[depth.get(u)] ||= []).push(u));
    bands.forEach((band) => {
      const near = (u) => {
        const ps = [...uParents.get(u)].filter((p) => autoCol.has(p));
        return ps.length ? ps.reduce((s, p) => s + autoCol.get(p), 0) / ps.length : 1e9;
      };
      band.sort((a, b) => (uSort(a) - uSort(b)) || (near(a) - near(b))
        || (uMain(a) ? 0 : 1) - (uMain(b) ? 0 : 1) || (a < b ? -1 : 1));
      band.forEach((u, i) => autoCol.set(u, i));
    });
  };
  relinkGraph();

  const W = 190, H = 72, cellW = 220, cellH = 118, PAD = 20;
  const posOfUnit = (u) => {
    const src = isGroupUnit(u) ? groupOfUnit(u) : questOfUnit(u);
    const m = src && src.pos && src.pos[faction];
    return (Array.isArray(m) && m.length === 2)
      ? { col: m[0], row: m[1] }
      : { col: autoCol.get(u), row: depth.get(u) };
  };
  const cell = new Map([...unitIds].map((u) => [u, posOfUnit(u)]));
  // Колонка и ряд бывают отрицательными: иначе блок нельзя подвинуть левее
  // самого левого, и приходилось расталкивать вправо всю остальную линейку.
  // Начало координат — самый левый/верхний блок, отрисовка от него.
  let orgCol = 0, orgRow = 0;
  const recalcOrigin = () => {
    const us = [...unitIds];
    orgCol = Math.min(0, ...us.map((u) => cell.get(u).col));
    orgRow = Math.min(0, ...us.map((u) => cell.get(u).row));
  };
  recalcOrigin();
  // связи изменились: пересобрать карту, глубины и авто-колонки, а блокам без
  // ручной позиции выдать новое авто-место — ровно то, что раньше показывал F5
  const relayout = () => {
    relinkGraph();
    unitIds.forEach((u) => cell.set(u, posOfUnit(u)));
  };
  const xOf = (u) => PAD + (cell.get(u).col - orgCol) * cellW;
  const yOf = (u) => PAD + (cell.get(u).row - orgRow) * cellH;
  const canvasSize = () => ({
    // orgCol/orgRow затравкой: у пустой линейки Math.max() без аргументов
    // вернул бы -Infinity и размеры уехали бы в NaN
    cw: PAD * 2 + (Math.max(orgCol, ...[...unitIds].map((u) => cell.get(u).col)) - orgCol) * cellW + W,
    ch: PAD * 2 + (Math.max(orgRow, ...[...unitIds].map((u) => cell.get(u).row)) - orgRow) * cellH + H + 34,
  });

  host.innerHTML = `<div class="qgraph${edit ? " is-edit" : ""}">
    ${edit ? `<div class="qgraph-selbar"></div>` : ""}
    <div class="qgraph-view"><div class="qgraph-stage"></div></div>
    <div class="qgraph-ctl">
      <button type="button" class="qgraph-zb" data-z="out" title="Отдалить">－</button>
      <button type="button" class="qgraph-zb" data-z="fit" title="Уместить">⤢ по размеру</button>
      <button type="button" class="qgraph-zb" data-z="in" title="Приблизить">＋</button>
      ${edit ? `<span class="qgraph-hint">клик — выбрать · двойной клик — открыть · тяни блок — двигать · тяни точку снизу — связать · выбери 2+ блока и «сгруппировать»</span>` : ""}
    </div>
  </div>`;
  const view = host.querySelector(".qgraph-view");
  const stage = host.querySelector(".qgraph-stage");
  const T = { s: 1, tx: 0, ty: 12 };
  const applyT = () => { stage.style.transform = `translate(${T.tx}px,${T.ty}px) scale(${T.s})`; };
  const curZoom = () => parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue("--zoom")) || 1;
  const toStage = (cx, cy) => {                       // клиентские px → координаты сцены
    const r = view.getBoundingClientRect(), z = curZoom();
    return { x: ((cx - r.left) / z - T.tx) / T.s, y: ((cy - r.top) / z - T.ty) / T.s };
  };

  const selected = new Set();                 // выбранные юниты (дев-карта)
  let lastClick = { u: null, t: 0 };          // для различения клик/двойной клик
  const savePos = (qid, col, row) => {
    const q = byId.get(qid); if (q) { q.pos = q.pos || {}; q.pos[faction] = [col, row]; }
    fetch(api(`/admin/quests/${qid}/pos`), { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ faction, col, row }) }).catch(() => {});
  };
  const saveGroupPos = (gid, col, row) => {
    const g = groupById.get(gid); if (g) { g.pos = g.pos || {}; g.pos[faction] = [col, row]; }
    fetch(api(`/admin/quest-groups/${gid}/pos`), { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ faction, col, row }) }).catch(() => {});
  };
  const saveParents = async (child) => {
    try {
      const r = await fetch(api(`/admin/quests/${child.id}/parents`), { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ parents: child.parents }) });
      if (!r.ok) { const j = await r.json().catch(() => ({})); alert(j.detail || "не удалось изменить связь"); return false; }
      return true;
    } catch (e) { return false; }
  };
  // память игрока: отметить квест выполненным вместе с обязательными предшественниками
  const ancestorsOf = (qid) => {
    const res = new Set(), stack = [qid];
    while (stack.length) {
      const cq = questData.items.find((x) => x.id === stack.pop());
      ((cq && cq.parents) || []).forEach((p) => { if (!res.has(p)) { res.add(p); stack.push(p); } });
    }
    return res;
  };
  const saveDone = () => { try { localStorage.setItem("sz_quest_done", JSON.stringify([...questDone])); } catch (e) {} };
  const markDone = (qid) => { questDone.add(qid); ancestorsOf(qid).forEach((a) => questDone.add(a)); };
  const groupIsDone = (g) => { const m = membersOf.get(g.id) || []; return m.length > 0 && m.every((q) => questDone.has(q.id)); };
  const toggleExpand = (gid) => {
    if (questExpanded.has(gid)) questExpanded.delete(gid); else questExpanded.add(gid);
    try { localStorage.setItem("sz_quest_exp", JSON.stringify([...questExpanded])); } catch (e) {}
    renderQuestGraph(host, faction, opts);    // юниты меняются — полный перестрой
  };

  const renderUnit = (u) => {
    const pos = `left:${xOf(u)}px;top:${yOf(u)}px;width:${W}px;height:${H}px`;
    const sel = edit && selected.has(u) ? " selected" : "";
    if (isGroupUnit(u)) {
      const g = groupOfUnit(u), cnt = (membersOf.get(g.id) || []).length;
      const done = !edit && groupIsDone(g) ? " done" : "";
      return `<div class="qst-node qgraph-node qgraph-group${done}${sel}" data-unit="${u}" data-gid="${g.id}"
        style="${pos}" title="Группа: ${escapeHtml(g.title)} (${cnt})">
        <div class="qst-kind">ГРУППА · ${cnt} кв.</div>
        <div class="qst-name">${escapeHtml(g.title)}</div>
        <button type="button" class="qgraph-chev" data-expand="${g.id}" title="Раскрыть группу">▸</button>
        ${!edit ? `<button type="button" class="qgraph-done" title="Отметить группу выполненной">✓</button>` : ""}
      </div>`;
    }
    const q = questOfUnit(u);
    const ext = (q.parents || []).filter((pid) => !byId.has(pid))
      .map((pid) => questData.items.find((x) => x.id === pid)).filter(Boolean);
    const extHtml = ext.length ? `<div class="qst-ext" title="После: ${escapeHtml(ext.map((x) =>
      `${x.title} (${questFactionOf(x.faction).name})`).join(", "))}">⇠</div>` : "";
    const shared = (q.factions || []).length ? `<div class="qst-shared" title="Также в линейках: ${escapeHtml(
      (q.factions || []).map((fx) => questFactionOf(fx).name).join(", "))}">⇄</div>` : "";
    const done = !edit && questDone.has(q.id) ? " done" : "";
    return `<div class="qst-node qgraph-node is-${q.kind}${done}${sel}" data-unit="${u}" data-id="${q.id}"
      style="${pos}" title="${escapeHtml(q.summary || q.title)}">
      <div class="qst-kind">${q.kind === "main" ? "ОСНОВНОЙ" : "ПОБОЧНЫЙ"}</div>
      <div class="qst-name">${escapeHtml(q.title)}</div>
      ${q.has_map ? `<div class="qst-map-i">📍</div>` : ""}${extHtml}${shared}
      ${!edit ? `<button type="button" class="qgraph-done" title="Отметить выполненным">✓</button>` : ""}
      ${edit ? `<div class="qgraph-editbar" title="Открыть редактор квеста">✎</div><button type="button" class="qgraph-add" title="Добавить следующий квест">＋</button><div class="qgraph-handle" title="Потяни на другой квест, чтобы связать"></div>` : ""}
    </div>`;
  };

  const paint = () => {
    recalcOrigin();               // после переезда влево сетка едет вместе с блоком
    const { cw, ch } = canvasSize();
    let edges = "";
    unitIds.forEach((u) => uParents.get(u).forEach((pu) => {
      const x1 = xOf(pu) + W / 2, y1 = yOf(pu) + H;
      const x2 = xOf(u) + W / 2, y2 = yOf(u);
      const my = (y1 + y2) / 2;
      const d = `M${x1} ${y1} C${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`;
      const side = !isGroupUnit(u) && questOfUnit(u).kind === "side";
      edges += `<path d="${d}" class="qst-edge${side ? " is-side" : ""}"/><circle cx="${x2}" cy="${y2}" r="3" class="qst-dot${side ? " is-side" : ""}"/>`;
      if (edit && !isGroupUnit(u) && !isGroupUnit(pu))     // удалять можно только прямую связь
        edges += `<path d="${d}" class="qgraph-edge-hit" data-child="${questOfUnit(u).id}" data-parent="${questOfUnit(pu).id}"/>`;
    }));
    let boxes = "", hdrs = "";
    groups.forEach((g) => {
      if (isCollapsed(g.id)) return;
      const mem = (membersOf.get(g.id) || []).map((q) => "q" + q.id).filter((u) => unitIds.has(u));
      if (!mem.length) return;
      const xs = mem.map((u) => xOf(u)), ys = mem.map((u) => yOf(u));
      const bx = Math.min(...xs) - 14, by = Math.min(...ys) - 30;
      const bw = Math.max(...xs) - Math.min(...xs) + W + 28, bh = Math.max(...ys) - Math.min(...ys) + H + 44;
      boxes += `<rect x="${bx}" y="${by}" width="${bw}" height="${bh}" rx="8" class="qgraph-groupbox"/>`;
      hdrs += `<div class="qgraph-boxhdr" style="left:${bx}px;top:${by}px;max-width:${bw}px">
        <span class="qgraph-chev" data-collapse="${g.id}" title="Свернуть группу">▾</span>
        <b>${escapeHtml(g.title)}</b> · группа${edit ? ` <span class="qgraph-boxungroup" data-ungroup="${g.id}">разгруппировать</span>` : ""}</div>`;
    });
    const nodes = [...unitIds].map((u) => renderUnit(u)).join("");
    stage.style.width = cw + "px"; stage.style.height = ch + "px";
    stage.innerHTML = `<svg width="${cw}" height="${ch}" viewBox="0 0 ${cw} ${ch}">${boxes}${edges}<path class="qgraph-temp" d=""/></svg>${nodes}${hdrs}`;
    wire();
    updateSelbar();
  };

  const fit = () => {
    const { cw, ch } = canvasSize();
    const r = view.getBoundingClientRect(), z = curZoom();
    const vw = r.width / z, vh = r.height / z;
    T.s = Math.max(0.25, Math.min(1, Math.min(vw / cw, vh / ch)));
    T.tx = Math.max(0, (vw - cw * T.s) / 2); T.ty = 12;
    applyT();
  };

  const zoomAt = (cx, cy, factor) => {
    const p = toStage(cx, cy);
    const r = view.getBoundingClientRect(), z = curZoom();
    const s2 = Math.max(0.25, Math.min(2, T.s * factor));
    T.tx = (cx - r.left) / z - p.x * s2;
    T.ty = (cy - r.top) / z - p.y * s2;
    T.s = s2; applyT();
  };

  const toggleSelect = (u, n) => {
    if (selected.has(u)) { selected.delete(u); if (n) n.classList.remove("selected"); }
    else { selected.add(u); if (n) n.classList.add("selected"); }
    updateSelbar();
  };
  const handleUnitClick = (n) => {              // клик = выбрать; двойной по группе = раскрыть
    const u = n.dataset.unit, now = Date.now();
    const dbl = lastClick.u === u && now - lastClick.t < 320;
    lastClick = dbl ? { u: null, t: 0 } : { u, t: now };
    if (dbl && n.dataset.gid) { toggleExpand(+n.dataset.gid); return; }
    if (dbl) return;                            // квест: редактор открывается полоской слева
    toggleSelect(u, n);
  };
  const doGroup = async (qUnits) => {
    const ids = qUnits.map((u) => +u.slice(1));
    const title = prompt("Название группы (как назвать модуль на схеме):", "Группа квестов");
    if (title === null) return;
    try {
      const r = await fetch(api("/admin/quest-groups"), { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ faction, title: title.trim() || "Группа квестов", members: ids }) });
      const j = await r.json();
      if (!r.ok) { alert(j.detail || "не удалось сгруппировать"); return; }
      questData.groups.push(j);
      ids.forEach((mid) => { const q = byId.get(mid); if (q) q.group_id = j.id; });
      renderQuestGraph(host, faction, opts);
    } catch (e) { alert("ошибка сети"); }
  };
  const doUngroup = async (gUnits) => {
    if (!confirm("Разгруппировать? Квесты останутся, модуль исчезнет.")) return;
    for (const u of gUnits) {
      const gid = +u.slice(1);
      try { await fetch(api(`/admin/quest-groups/${gid}`), { method: "DELETE" }); } catch (e) {}
      questData.groups = questData.groups.filter((g) => g.id !== gid);
      items.forEach((q) => { if (q.group_id === gid) q.group_id = null; });
    }
    renderQuestGraph(host, faction, opts);
  };
  const updateSelbar = () => {
    const bar = host.querySelector(".qgraph-selbar");
    if (!bar) return;
    [...selected].forEach((u) => { if (!unitIds.has(u)) selected.delete(u); });
    const sel = [...selected];
    if (!sel.length) { bar.classList.remove("on"); bar.innerHTML = ""; return; }
    const qU = sel.filter((u) => !isGroupUnit(u)), gU = sel.filter(isGroupUnit);
    let btns = "";
    if (qU.length >= 2 && !gU.length) btns += `<button type="button" class="qgraph-selb hot" data-a="group">СГРУППИРОВАТЬ (${qU.length})</button>`;
    if (gU.length) btns += `<button type="button" class="qgraph-selb" data-a="ungroup">РАЗГРУППИРОВАТЬ (${gU.length})</button>`;
    bar.classList.add("on");
    bar.innerHTML = `<span class="qgraph-selc">Выбрано: ${sel.length}</span>${btns}<button type="button" class="qgraph-selb" data-a="clear">СНЯТЬ</button>`;
    bar.querySelectorAll(".qgraph-selb").forEach((b) => b.addEventListener("click", () => {
      const a = b.dataset.a;
      if (a === "clear") { selected.clear(); paint(); applyT(); }
      else if (a === "group") doGroup(qU);
      else if (a === "ungroup") doUngroup(gU);
    }));
  };

  function wire() {
    // отметки «выполнено» (публично)
    if (!edit) stage.querySelectorAll(".qgraph-done").forEach((btn) => {
      btn.addEventListener("pointerdown", (e) => e.stopPropagation());
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const node = btn.closest(".qgraph-node");
        if (node.dataset.gid) {
          const mem = membersOf.get(+node.dataset.gid) || [];
          const all = mem.length && mem.every((q) => questDone.has(q.id));
          if (all) mem.forEach((q) => questDone.delete(q.id)); else mem.forEach((q) => markDone(q.id));
        } else {
          const id = +node.dataset.id;
          if (questDone.has(id)) questDone.delete(id); else markDone(id);
        }
        saveDone(); paint(); applyT();
      });
    });

    stage.querySelectorAll(".qgraph-node").forEach((n) => {
      const isGrp = !!n.dataset.gid;
      const chev = n.querySelector(".qgraph-chev");
      if (chev) {
        chev.addEventListener("pointerdown", (e) => e.stopPropagation());
        chev.addEventListener("click", (e) => { e.stopPropagation(); toggleExpand(+chev.dataset.expand); });
      }
      if (!edit) {
        n.addEventListener("click", (e) => {
          if (e.target.closest(".qgraph-done") || e.target.closest(".qgraph-chev")) return;
          if (isGrp) toggleExpand(+n.dataset.gid); else openQuestModal(+n.dataset.id);
        });
        return;
      }
      if (!isGrp) {
        const addBtn = n.querySelector(".qgraph-add");
        addBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
        addBtn.addEventListener("click", (e) => { e.stopPropagation(); renderDevQuestForm(null, { parent: +n.dataset.id, faction }); });
        const editBar = n.querySelector(".qgraph-editbar");   // широкая полоска слева → редактор
        editBar.addEventListener("pointerdown", (e) => e.stopPropagation());
        editBar.addEventListener("click", (e) => { e.stopPropagation(); renderDevQuestForm(+n.dataset.id); });
      }
      // тянуть = двигать; короткий клик = выбрать (редактор — полоской слева)
      n.addEventListener("pointerdown", (e) => {
        if (e.button !== 0 || e.target.closest(".qgraph-handle") || e.target.closest(".qgraph-add")
          || e.target.closest(".qgraph-chev") || e.target.closest(".qgraph-editbar")) return;
        e.stopPropagation();
        const z = curZoom(), sx = e.clientX, sy = e.clientY;
        const ox = parseFloat(n.style.left), oy = parseFloat(n.style.top);
        let moved = false;
        n.setPointerCapture(e.pointerId);
        const mv = (ev) => {
          const dx = ev.clientX - sx, dy = ev.clientY - sy;
          if (!moved && Math.hypot(dx, dy) < 5) return;
          moved = true; n.classList.add("dragging");
          const lx = ox + dx / (z * T.s), ly = oy + dy / (z * T.s);
          n.style.left = Math.max(-cellW * 3, lx) + "px";
          n.style.top = Math.max(-cellH * 3, ly) + "px";
          // уехали левее/выше сцены — сдвигаем саму сцену, иначе блок ушёл бы
          // под край окна (у .qgraph-view overflow: hidden) и тащить вслепую
          if (lx < 0 && T.tx < -lx * T.s) { T.tx = -lx * T.s; applyT(); }
          if (ly < 0 && T.ty < -ly * T.s) { T.ty = -ly * T.s; applyT(); }
        };
        const up = () => {
          n.removeEventListener("pointermove", mv); n.removeEventListener("pointerup", up);
          n.classList.remove("dragging");
          if (!moved) { handleUnitClick(n); return; }
          // обратно в координаты линейки: на экране считали от левого блока
          const col = Math.round((parseFloat(n.style.left) - PAD) / cellW) + orgCol;
          const row = Math.round((parseFloat(n.style.top) - PAD) / cellH) + orgRow;
          cell.set(n.dataset.unit, { col, row });
          if (isGrp) saveGroupPos(+n.dataset.gid, col, row); else savePos(+n.dataset.id, col, row);
          paint(); applyT();
        };
        n.addEventListener("pointermove", mv); n.addEventListener("pointerup", up);
      });
      if (isGrp) return;                        // стрелки тянем только между квестами
      const id = +n.dataset.id;
      const handle = n.querySelector(".qgraph-handle");
      handle.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        e.stopPropagation(); e.preventDefault();
        const temp = stage.querySelector(".qgraph-temp");
        const sx0 = xOf("q" + id) + W / 2, sy0 = yOf("q" + id) + H;
        let target = null;
        handle.setPointerCapture(e.pointerId);
        const setTarget = (tid, tn) => {
          if (target && target !== tid) {
            const pn = stage.querySelector(`.qgraph-node[data-id="${target}"]`);
            if (pn) pn.classList.remove("link-target");
          }
          target = tid;
          if (tid && tn) tn.classList.add("link-target");
        };
        const mv = (ev) => {
          const p = toStage(ev.clientX, ev.clientY);
          temp.setAttribute("d", `M${sx0} ${sy0} C${sx0} ${(sy0 + p.y) / 2}, ${p.x} ${(sy0 + p.y) / 2}, ${p.x} ${p.y}`);
          temp.classList.add("on");
          const el = document.elementFromPoint(ev.clientX, ev.clientY);
          const tn = el && el.closest(".qgraph-node");
          const tid = tn && tn.dataset.id ? +tn.dataset.id : null;
          setTarget(tid && tid !== id ? tid : null, tn);
        };
        const up = async () => {
          handle.removeEventListener("pointermove", mv); handle.removeEventListener("pointerup", up);
          temp.classList.remove("on"); temp.setAttribute("d", "");
          const tid = target;
          if (target) { const pn = stage.querySelector(`.qgraph-node[data-id="${target}"]`); if (pn) pn.classList.remove("link-target"); }
          if (!tid) return;
          const child = byId.get(tid);
          if (!child || (child.parents || []).includes(id)) return;
          const prev = (child.parents || []).slice();
          child.parents = [...(child.parents || []), id];
          if (!(await saveParents(child))) child.parents = prev;
          relayout(); paint(); applyT();
        };
        handle.addEventListener("pointermove", mv); handle.addEventListener("pointerup", up);
      });
    });

    // заголовки раскрытых групп: свернуть / разгруппировать
    stage.querySelectorAll(".qgraph-chev[data-collapse]").forEach((c) => {
      c.addEventListener("pointerdown", (e) => e.stopPropagation());
      c.addEventListener("click", (e) => { e.stopPropagation(); toggleExpand(+c.dataset.collapse); });
    });
    stage.querySelectorAll(".qgraph-boxungroup").forEach((c) => {
      c.addEventListener("pointerdown", (e) => e.stopPropagation());
      c.addEventListener("click", (e) => { e.stopPropagation(); doUngroup(["g" + c.dataset.ungroup]); });
    });

    if (edit) stage.querySelectorAll(".qgraph-edge-hit").forEach((p) =>
      p.addEventListener("click", async (e) => {
        e.stopPropagation();
        const child = byId.get(+p.dataset.child), parent = +p.dataset.parent;
        if (!child || !confirm("Удалить связь (стрелку)?")) return;
        const prev = (child.parents || []).slice();
        child.parents = (child.parents || []).filter((x) => x !== parent);
        if (!(await saveParents(child))) child.parents = prev;
        relayout(); paint(); applyT();
      }));
  }

  // пан полотна левой кнопкой по пустому месту
  view.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest(".qgraph-node") || e.target.closest(".qgraph-edge-hit")
      || e.target.closest(".qgraph-boxhdr")) return;
    const z = curZoom(), sx = e.clientX, sy = e.clientY, tx0 = T.tx, ty0 = T.ty;
    view.classList.add("panning");
    view.setPointerCapture(e.pointerId);
    const mv = (ev) => { T.tx = tx0 + (ev.clientX - sx) / z; T.ty = ty0 + (ev.clientY - sy) / z; applyT(); };
    const up = () => { view.removeEventListener("pointermove", mv); view.removeEventListener("pointerup", up); view.classList.remove("panning"); };
    view.addEventListener("pointermove", mv); view.addEventListener("pointerup", up);
  });
  view.addEventListener("wheel", (e) => {
    e.preventDefault();
    zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.12 : 1 / 1.12);
  }, { passive: false });
  host.querySelectorAll(".qgraph-zb").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.z === "fit") { fit(); return; }
    const r = view.getBoundingClientRect();
    zoomAt(r.left + r.width / 2, r.top + r.height / 2, b.dataset.z === "in" ? 1.2 : 1 / 1.2);
  }));

  paint();
  fit();
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
  // следующие квесты = те, у кого этот в родителях (кнопка «следующий квест»)
  const children = questData.items
    .filter((x) => (x.parents || []).includes(q.id))
    .sort((a, b) => (a.sort - b.sort) || (a.id - b.id));
  const hasMap = q.map_layer && (q.map_points || []).length;
  gModalOpen(`<div class="qm">
    <div class="qm-badges">
      <span class="qm-badge" style="--fc:${f.color}">${escapeHtml(f.name.toUpperCase())}</span>
      <span class="qm-badge is-${q.kind}">${q.kind === "main" ? "ОСНОВНОЙ КВЕСТ" : "ПОБОЧНЫЙ КВЕСТ"}</span>
    </div>
    <h2 class="qm-title">${escapeHtml(q.title)}</h2>
    ${parents.length ? `<div class="qm-after">ОТКРЫВАЕТСЯ ПОСЛЕ: ${parents.map((p) =>
      `<a class="qm-plink" data-id="${p.id}" href="/quests/${p.id}">${escapeHtml(p.title)}</a>`).join(" · ")}</div>` : ""}
    ${q.reward ? `<div class="qm-reward"><span>НАГРАДА</span>${escapeHtml(q.reward)}</div>` : ""}
    <div class="patch-body qm-body">${q.html || `<p style="color:var(--dim)">Прохождение ещё пишется — загляни позже.</p>`}</div>
    ${hasMap ? `<div class="qm-map-h">ТОЧКИ КВЕСТА НА КАРТЕ · наведи на номер</div>
      <div class="qm-map" id="qmMap"></div>` : ""}
    ${children.length ? `<div class="qm-next">
      <span class="qm-next-h">${children.length > 1 ? "СЛЕДУЮЩИЕ КВЕСТЫ" : "СЛЕДУЮЩИЙ КВЕСТ"}</span>
      ${children.map((c) => `<a class="qm-plink qm-nextbtn${c.published ? "" : " draft"}"
        data-id="${c.id}" href="/quests/${c.id}">${escapeHtml(c.title)} →</a>`).join("")}
    </div>` : ""}
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
  const [vx0, vy0, vx1, vy1] = layerView(lm);
  L.tileLayer(asset(lm.tile_url), {
    tileSize: lm.tile_size,
    minNativeZoom: lm.min_zoom, maxNativeZoom: lm.max_zoom,
    bounds: L.latLngBounds(px(0, 0), px(lm.w, lm.h)), noWrap: true,
  }).addTo(map);
  map.setMaxBounds(L.latLngBounds(px(vx0, vy0), px(vx1, vy1)));
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

// data-l — подпись колонки для телефона: там таблица раскладывается карточками
// (.obm-table в styles.css), и шапки, из которой понятно значение числа, уже нет
const OBM_BASIS_RU = { vendor: "СКУПЩИК", auction: "АУК", market: "РАЗБОР" };

function obmenRow(r, extra = "") {
  // рыночная цена выведена из родителя разбора — предмет личный, на аук не попадает
  const mkt = r.value_market != null;
  const priceCell = mkt ? r.value_market : r.value_auction;
  const priceTitle = mkt && r.disasm
    ? `цена замещения: ${r.disasm.count}× из «${r.disasm.parent_name}» по ${fmt(r.disasm.parent_unit)} ₽ на ауке`
    : r.sell_basis === "sales" ? "по сделкам аука, минус комиссия"
    : r.sell_basis === "buyout" ? "по мин. выкупу, минус комиссия" : "";
  const chip = r.basis ? `<span class="obm-basis ${r.basis}">${OBM_BASIS_RU[r.basis] || r.basis}</span>` : "";
  return `<tr class="brt-row" data-id="${r.id}">
    <td class="c-itm"><div class="bt-item"><img loading="lazy" src="${asset(r.icon)}" alt="">
      <span class="nm" style="color:${rank(r.color).color}">${r.amount > 1 ? r.amount + "× " : ""}${escapeHtml(r.name)}</span>
      ${r.note ? `<span class="bt-cur">${escapeHtml(r.note)}</span>` : ""}</div></td>
    <td class="r c-coins">${fmt(r.coins)} <span class="c-unit">МОН</span></td>
    <td class="r c-auc" data-l="РЫНОК~" title="${escapeHtml(priceTitle)}">${priceCell != null ? fmt(priceCell) + " ₽" : "—"}</td>
    <td class="r c-ven" data-l="СКУПЩИК" title="мгновенная продажа NPC, без комиссии">${r.value_vendor != null ? fmt(r.value_vendor) + " ₽" : "—"}</td>
    <td class="r c-key">${r.rate != null ? `<span class="pct ${r.rate >= 1 ? "up" : "down"}">${r.rate.toLocaleString("ru-RU")}</span>
      <span class="c-unit">₽/МОН</span> ${chip}` : "—"}</td>
    ${extra}
  </tr>`;
}

const OBM_HEAD = `<tr><th style="width:38%">ПРЕДМЕТ</th><th class="r" style="width:13%">МОНЕТ</th>
  <th class="r" style="width:16%">РЫНОК~</th><th class="r" style="width:16%">СКУПЩИК</th>
  <th class="r" style="width:17%">₽/МОНЕТА</th></tr>`;
const OBM_PLAN_HEAD = `<tr><th style="width:30%">ПРЕДМЕТ</th><th class="r" style="width:10%">МОНЕТ</th>
  <th class="r" style="width:12%">РЫНОК~</th><th class="r" style="width:12%">СКУПЩИК</th>
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
      <div class="section-note">КУРС = ЖИВЫЕ ДЕНЬГИ: АУК (−${d.fee_pct}%) ИЛИ СКУПЩИК · РЫНОК~ СПРАВОЧНО${
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
    <div class="bt-wrap"><table class="bt-table bt-cards">
      <thead>${OBM_HEAD}</thead>
      <tbody>${rows}</tbody>
    </table></div>
    <div class="bt-note" style="margin-top:8px">ЭТИ ПРЕДМЕТЫ ЛИЧНЫЕ — НА АУКЦИОН ИХ НЕ ВЫСТАВИТЬ.
      РЫНОК~ — СКОЛЬКО СТОИЛО БЫ ДОБЫТЬ ТО ЖЕ САМОЕ БЕЗ ПЕРЕКУПЩИКА: КУПИТЬ РОДИТЕЛЯ НА АУКЕ
      И РАЗОБРАТЬ. ЭТО ЭКОНОМИЯ, А НЕ ВЫРУЧКА, ПОЭТОМУ КУРС ₽/МОНЕТА СЧИТАЕТСЯ ПО ЖИВЫМ
      ДЕНЬГАМ (СКУПЩИК). КЛИК ПО СТРОКЕ — ДЕТАЛИ ПОЗИЦИИ.</div>
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
    `<td class="r c-buys" data-l="ПОКУПОК">${r.buys}×</td>
     <td class="r c-total" data-l="ИТОГО">${fmt(r.total_value)} ₽</td>`)).join("");
  box.innerHTML = d.basket && d.basket.length ? `<div class="obm-plan">
    <div class="reqs-lbl">КОРЗИНА НА ${fmt(d.coins)} МОНЕТ → ~${fmt(d.value)} ₽ ЖИВЫМИ${
      d.market ? ` · ПО РЫНКУ ~${fmt(d.market)} ₽` : ""}${
      d.left ? ` · ОСТАНЕТСЯ ${fmt(d.left)}` : ""}</div>
    <div class="bt-wrap"><table class="bt-table bt-cards">
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
// котировки заточек — корзинами: 0-4 → +0, 5-9 → +5, 10-14 → +10, 15 → +15
const ptnBucket = (p) => Math.min(p - (p % 5), 15);
// подпись диапазона корзины: +0…+4, +5…+9, +10…+14, +15
const ptnRange = (p) => (p >= 15 ? "+15" : `+${p}…+${p + 4}`);

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
      <div class="meta">СР. ${fmt(e.avg)} ₽ <span class="m-was">· БЫЛО ${fmt(e.prev_avg)} ₽</span> · ${e.n} ПРОД</div>
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
    ПРОМЕЖУТОЧНЫЕ ЗАТОЧКИ ИДУТ В НИЖНЮЮ КОРЗИНУ (+7 → +5, +14 → +10).
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
      <button class="bucket-chip ${b === sel ? "on" : ""}"
              data-q="${b.qlt}" data-p="${b.ptn}" title="${qltLabel(b.qlt)}, заточка ${ptnRange(b.ptn)}">
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
let READY_BUILDS = null; // /api/build/ready — готовые сборки для верха страницы
let readyLoading = false;
let buildTab = "manual";
const buildState = { container: null, slots: [] };  // слот: {id, ptn, m} | null
const autoState = { budget: 500000, stats: [{ key: "", weight: 60 }],
                    exclude: [], noNeg: false, result: null };
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
// доп-свойства порогов заточки: значение фиксировано (base×M×заточка, как обычный
// стат), рандомен только порядок разблокировки (+5 одно из пула, +10 второе, +15 третье)
const bonusVal = (bp, m, ptn) => bp.base * m * sharp(ptn);
const bonusUnlocked = (ptn, pool) => Math.min([5, 10, 15].filter((t) => ptn >= t).length, pool.length);
// активные допы слота: на +15 обычного арта (пул ≤ 3 порогов) — весь пул,
// ниже — отмеченные пользователем галочки (s.bx), не больше разблокированного
function slotBonusActive(s, art) {
  const pool = art.bonus || [];
  const unlocked = bonusUnlocked(s.ptn, pool);
  if (!unlocked) return [];
  if (unlocked >= pool.length) return pool;
  const sel = new Set((s.bx || []).slice(0, unlocked));
  return pool.filter((b) => sel.has(b.key));
}
const fmtStat = (v) => (v > 0 ? "+" : "") + (Math.abs(v) >= 100 ? Math.round(v) : v.toFixed(2));
// контейнеры + рюкзаки со слотами под арты — равноправные «хранилища» сборки
const STORAGES = () => [...(BUILD_DICT.containers || []), ...(BUILD_DICT.backpacks || [])];
const KIND_LBL = { container: "КОНТЕЙНЕР", backpack: "РЮКЗАК" };
const isContamKey = (k) => (BUILD_DICT.contamination || []).some((c) => c.key === k);
// собственные полезные статы хранилища (кроме заражений) — короткой строкой в лейбл
const selfBonusStr = (c) => (c.self_stats || [])
  .filter((s) => !isContamKey(s.key))
  .map((s) => `${fmtStat(s.val)} ${s.name}`).join(" · ");
// имя хранилища красится в цвет редкости; тип + слоты/эфф/защита + собственные бонусы
const contLabel = (c) => {
  const bonus = selfBonusStr(c);
  return `<span style="color:${rank(c.color).color}">${escapeHtml(c.name)}</span>` +
    ` · ${KIND_LBL[c.kind] || "ХРАНИЛИЩЕ"} · ${c.slots} СЛОТ${c.slots > 1 ? "А" : ""}` +
    ` · ЭФФ ${c.efficiency ?? "—"}% · ЗАЩ ${c.protection ?? "—"}%` +
    (bonus ? ` · <span style="color:#5fd67a">${escapeHtml(bonus)}</span>` : "");
};
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
    for (const s of slots) {  // допы-защиты порогов заточки (отрицательные accumulation)
      if (!s) continue;
      const art = BUILD_DICT.artefacts.find((a) => a.id === s.id);
      if (!art) continue;
      for (const b of slotBonusActive(s, art)) {
        if (b.key !== c.key) continue;
        present = true;
        const val = bonusVal(b, s.m, s.ptn);
        if (val > 0) emit += val; else protect += val * eff;
      }
    }
    // собственный вклад хранилища (эмиссия +, защита −) — без гашения защитой и ×эфф
    const selfV = (cont.self_stats || []).reduce((a, s) => a + (s.key === c.key ? s.val : 0), 0);
    if (selfV) present = true;
    if (!present) continue;
    const net = emit * (c.key === FROST_KEY ? 1 : (1 - prot)) + protect + selfV;
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

// допы порогов на карточке результата: полное значение; в итогах учтено ×factor
function bonusRowsRO(bonus) {
  if (!bonus || !bonus.length) return "";
  const f = bonus[0].factor;
  const note = f >= 1 ? "ВСЕ АКТИВНЫ (+15)"
    : f > 0 ? `АКТИВНО ${Math.round(f * bonus.length)} ИЗ ${bonus.length} (СЛУЧАЙНЫЙ ПОРЯДОК) — В ИТОГАХ МАТОЖИДАНИЕ`
    : "ОТКРОЮТСЯ С ЗАТОЧКИ +5";
  return `<div class="bs-ms">ДОП. СВОЙСТВА — ${note}</div>` + bonus.map((b) =>
    `<div class="bstat bx ${f > 0 ? "" : "off"}">
      <span class="sn">${escapeHtml(b.name)}</span>
      <span class="sv">${fmtStat(b.val)}</span></div>`).join("");
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
    const first = STORAGES()[0];
    buildState.container = first ? first.id : null;
    buildState.slots = first ? Array(first.slots).fill(null) : [];
  }
  renderBuilds();
  loadReadyBuilds();
}

// Готовые сборки для верха страницы: холодный посетитель из поиска попадал на
// пустую сетку слотов и уходил. Грузим отдельно от справочника — расчёт на
// живых ценах идёт ~1.5 с, держать из-за него первую отрисовку незачем.
async function loadReadyBuilds() {
  if (READY_BUILDS || readyLoading) return;
  readyLoading = true;
  try {
    READY_BUILDS = await fetch(api("/build/ready")).then((r) => r.json());
  } catch (e) {
    READY_BUILDS = { presets: [] };   // сеть отвалилась — просто не показываем блок
  }
  readyLoading = false;
  // ушли со страницы, переключили вкладку или уже выбирают артефакт — не трогаем
  // DOM: перерисовка закрыла бы открытый пикер прямо под руками
  if (location.pathname === "/builds" && buildTab === "manual" && pickerSlot < 0)
    renderBuilds();
}

function buildContainer() {
  return STORAGES().find((c) => c.id === buildState.container);
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

// эффективная цена корзины: {price, n, src} или null (источник решает бэк).
// заточка котируется корзиной (+7 стоит как +5), статы — по точной заточке
function slotPrice(s) {
  return (artPriceCache[s.id] || {})[`${qltFromM(s.m)}:${ptnBucket(s.ptn)}`] || null;
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
    for (const b of slotBonusActive(s, art)) {  // выбранные допы порогов — как полезные статы
      if (isContamKey(b.key)) continue;         // допы-защиты заражений — в блоке contamination
      const t = stats[b.key] || (stats[b.key] = { name: b.name, harmful: false, total: 0 });
      t.total += bonusVal(b, s.m, s.ptn) * eff;
    }
    const p = slotPrice(s);
    if (p) out.cost += p.price; else out.unpriced++;
  }
  for (const s of (cont.self_stats || [])) {  // собственные статы хранилища — плоско
    if (isContamKey(s.key)) continue;         // заражения — в блоке contamination
    const t = stats[s.key] || (stats[s.key] = { name: s.name, harmful: s.harmful, total: 0 });
    t.total += s.val;
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
  return `<div class="reqs-lbl" style="margin-top:10px">ЗАРАЖЕНИЕ (после защиты хранилища)</div>${rows}`;
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
    <div class="bt-row"><span class="k">ВЕС (С ХРАНИЛИЩЕМ)</span><span class="v">${t.weight.toFixed(2)} КГ</span></div>
    <div class="bt-row"><span class="k">ЗАЩИТА ${(KIND_LBL[cont.kind] || "ХРАНИЛИЩА").replace("КОНТЕЙНЕР", "КОНТЕЙНЕРА").replace("РЮКЗАК", "РЮКЗАКА")}</span><span class="v">${cont.protection ?? "—"}%</span></div>
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
  // доп-свойства порогов: на +15 обычного арта — все (без галочек), ниже —
  // пользователь отмечает выпавшие (не больше разблокированных порогов)
  const pool = art.bonus || [];
  const unlocked = bonusUnlocked(s.ptn, pool);
  const forced = unlocked > 0 && unlocked >= pool.length;
  const active = new Set(slotBonusActive(s, art).map((b) => b.key));
  const bonusRows = pool.map((b) => `<label class="bstat bx ${active.has(b.key) ? "" : "off"}">
      <input type="checkbox" class="bs-bx" data-slot="${idx}" data-bx="${b.key}"
        ${active.has(b.key) ? "checked" : ""} ${forced || !unlocked ? "disabled" : ""}>
      <span class="sn">${escapeHtml(b.name)}</span>
      <span class="sv">${fmtStat(bonusVal(b, s.m, s.ptn))}</span></label>`).join("");
  const bonusHead = !pool.length ? "" :
    `<div class="bs-ms">ДОП. СВОЙСТВА${!unlocked ? " — С ЗАТОЧКИ +5"
      : forced ? " — ВСЕ АКТИВНЫ (+15)"
      : ` — ОТМЕТЬТЕ ВЫПАВШИЕ (${active.size}/${unlocked})`}</div>`;
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
    ${bonusHead}${bonusRows}
    <div class="bs-price">${price ? `${fmt(price.price)} ₽ · ${srcLabel(price.src)}` : "НЕТ ЦЕНЫ (НЕТ ЛОТОВ И ИСТОРИИ)"}</div>
  </div>`;
}

// ---------- готовые сборки (верх страницы) ----------
function readyCard(p) {
  const t = p.build.totals;
  // Сперва статы профиля — карточка обещает именно их; отсутствующие (бюджет
  // ушёл в первый стат) пропускаем, вместо «Живучесть —». Добор — крупнейшим из
  // остальных: сортировать всё подряд по модулю нельзя, единицы разные, и «под
  // ходки» выносило защиту от радиации вперёд скорости передвижения.
  const shown = new Set();
  const pick = [];
  for (const s of p.stats_req) {
    const st = t.stats[s.key];
    if (st) { pick.push(st); shown.add(s.key); }
  }
  const rest = Object.keys(t.stats).filter((k) => !shown.has(k))
    .map((k) => t.stats[k])
    .sort((a, b) => Math.abs(b.total) - Math.abs(a.total));
  while (pick.length < 3 && rest.length) pick.push(rest.shift());
  const rows = pick.map((st) => `<div class="rc-stat ${st.harmful ? "bad" : ""}">
      <span class="k">${escapeHtml(st.name)}</span>
      <span class="v">${fmtStat(st.total)}</span></div>`).join("");
  // сборки сверх лимитов не выдаются, но оптимизатор упирается в них вплотную —
  // умолчать об этом нельзя, игрок должен знать, чем платит
  const maxed = (t.contamination || [])
    .filter((c) => c.limit && c.net >= c.limit * 0.95).map((c) => c.name);
  const arts = p.build.slots.map((s) =>
    `<img loading="lazy" src="${asset(s.icon)}" alt="${escapeHtml(s.name)}"
       title="${escapeHtml(s.name)} · ${bucketBadge(s.qlt, s.ptn)}"
       style="border-color:${qltColor(s.qlt)}">`).join("");
  // одинаковые арты занимают несколько слотов — схлопываем с количеством,
  // иначе список названий короче ряда иконок и выглядит ошибкой
  const cnt = new Map();
  for (const s of p.build.slots) cnt.set(s.name, (cnt.get(s.name) || 0) + 1);
  const names = [...cnt].map(([n, c]) => (c > 1 ? `${n} ×${c}` : n)).join(", ");
  return `<article class="ready-card">
    <div class="rc-title">${escapeHtml(p.title)}</div>
    <div class="rc-note">${escapeHtml(p.note)}</div>
    <div class="rc-arts">${arts}</div>
    <div class="rc-names">${escapeHtml(names)}</div>
    <div class="rc-stats">${rows}</div>
    ${maxed.length ? `<div class="rc-warn">У ПРЕДЕЛА: ${escapeHtml(maxed.join(", ").toUpperCase())}</div>` : ""}
    <div class="rc-cost">${fmt(t.cost)} ₽</div>
    <div class="rc-act">
      <button class="rc-go" data-ropen="${p.id}">ОТКРЫТЬ В КАЛЬКУЛЯТОРЕ</button>
      <button class="rc-alt" data-rauto="${p.id}">ПОД СВОЙ БЮДЖЕТ</button>
    </div>
  </article>`;
}

function readyStrip() {
  if (!READY_BUILDS) return `<div class="ready-load">// СЧИТАЮ ГОТОВЫЕ СБОРКИ НА ЖИВЫХ ЦЕНАХ…</div>`;
  const ps = READY_BUILDS.presets || [];
  if (!ps.length) return "";   // биржа не прогрелась — блока просто нет
  const c = READY_BUILDS.container || {};
  return `<section class="ready">
    <div class="ready-head">
      <h2 class="ready-title">ГОТОВЫЕ СБОРКИ ПОД БЮДЖЕТ ${fmt(READY_BUILDS.budget)} ₽</h2>
      <div class="ready-sub">Подобраны по живым ценам аукциона${c.name ? ` · хранилище ${escapeHtml(c.name)}` : ""} · ниже можно собрать свою</div>
    </div>
    <div class="ready-grid">${ps.map(readyCard).join("")}</div>
  </section>`;
}

// перенос готовой сборки в ручной конструктор: качество — верх тира (бэк в пуле
// вариантов берёт ровно его), заточка как подобрана
function readyOpen(pid) {
  const p = (READY_BUILDS.presets || []).find((x) => x.id === pid);
  if (!p) return;
  const cont = READY_BUILDS.container || {};
  const n = cont.slots || p.build.slots.length;
  buildState.container = cont.id || buildState.container;
  buildState.slots = Array(n).fill(null);
  p.build.slots.slice(0, n).forEach((s, i) => {
    buildState.slots[i] = { id: s.item, ptn: s.ptn, m: tierTop(s.qlt) };
  });
  buildTab = "manual";
  ymGoal("build_ready_open");
  renderBuilds();
  p.build.slots.forEach((s) => loadArtPrices(s.item));   // цены подтянутся и перерисуют
}

// та же сборка в автоподборе: профиль и результат уже посчитаны — посетителю
// остаётся поменять бюджет и пересчитать
function readyAuto(pid) {
  const p = (READY_BUILDS.presets || []).find((x) => x.id === pid);
  if (!p) return;
  const cont = READY_BUILDS.container || {};
  if (cont.id) {
    buildState.container = cont.id;
    buildState.slots = Array(cont.slots || 0).fill(null);
  }
  autoState.budget = READY_BUILDS.budget;
  autoState.stats = p.stats_req.map((s) => ({ key: s.key, weight: s.weight }));
  autoState.exclude = [];
  autoState.noNeg = false;
  autoState.result = { container: cont, builds: [p.build],
                       warnings: READY_BUILDS.price_note ? [READY_BUILDS.price_note] : [] };
  buildTab = "auto";
  ymGoal("build_ready_auto");
  renderBuilds();
}

function renderBuilds() {
  const cont = buildContainer();
  if (!cont) { page.innerHTML = `<div class="empty">НЕТ ДАННЫХ ХРАНИЛИЩ</div>`; return; }

  // Развилка интента. По Метрике «калькулятор артефактов сталкрафт» и соседние
  // фразы дают отказы 44–60% при глубине 1.0: человек ищет ЦЕНУ артефакта, а страница
  // сразу требует выбрать контейнер и набивать слоты. Одна строка выше сгиба
  // уводит их туда, где ответ, вместо того чтобы терять визит целиком.
  let h = `<div class="section-head">
      <div class="section-title">▸ КАЛЬКУЛЯТОР СБОРОК АРТЕФАКТОВ</div>
      <div class="section-note">ЦЕНЫ: 5 ДЕШЁВЫХ ЛОТОВ → СР. 7Д ПОСЛЕ НАКОПЛЕНИЯ БИРЖИ</div>
    </div>
    <div class="bs-intent">ИСКАЛИ НЕ СБОРКУ? →
      <a href="/auction">ЦЕНЫ АРТЕФАКТОВ НА АУКЦИОНЕ</a> ·
      <a href="/compare">СРАВНИТЬ ДВА АРТЕФАКТА</a> ·
      <a href="/guides/zatochka-artefaktov-cena">СКОЛЬКО СТОИТ ЗАТОЧКА</a></div>
    <div class="btabs">
      <button class="btab ${buildTab === "manual" ? "on" : ""}" data-tab="manual">СОБРАТЬ ВРУЧНУЮ</button>
      <button class="btab ${buildTab === "auto" ? "on" : ""}" data-tab="auto">АВТОПОДБОР ПОД БЮДЖЕТ</button>
      <button class="btab ${buildTab === "hp" ? "on" : ""}" data-tab="hp">ПРИВЕДЁННОЕ ХП</button>
    </div>
    ${buildTab === "manual" ? readyStrip() : ""}
    <div class="bbar"><div class="isel" id="bContSel"></div></div>`;

  h += buildTab === "manual" ? renderManual(cont)
     : buildTab === "auto" ? renderAuto(cont) : renderHP(cont);
  const footer = buildTab === "manual"
    ? `КАЧЕСТВО — РЕДКОСТЬ ИЛИ ПОЛЕ % (85–175%): ВЫХОД ЗА ТИР МЕНЯЕТ РЕДКОСТЬ. ЦВЕТ ИМЕНИ — РЕДКОСТЬ.
       ЭФФЕКТИВНОСТЬ КОНТЕЙНЕРА УСИЛИВАЕТ ПОЛОЖИТЕЛЬНЫЕ СТАТЫ; ВНУТР. ЗАЩИТА ГАСИТ ЗАРАЖЕНИЯ (КРОМЕ ХОЛОДА).
       ЛИМИТЫ ИГРОКА: РАД/ТЕМП/БИО/ХОЛОД — 1.0, ПСИ — 3.0; МИНУС — ЗАПАС ЗАЩИТЫ, НЕ ВРЕДЕН.
       ДОП. СВОЙСТВА ЗАТОЧКИ: +5/+10/+15 ОТКРЫВАЮТ ПО ОДНОМУ ИЗ ПУЛА АРТА В СЛУЧАЙНОМ ПОРЯДКЕ —
       НА +15 АКТИВНЫ ВСЕ (УЧТУТСЯ САМИ), НИЖЕ — ОТМЕТЬТЕ ВЫПАВШИЕ ГАЛОЧКАМИ.`
    : `ПОЛОЖИТЕЛЬНЫЕ СТАТЫ АРТОВ × ЭФФЕКТИВНОСТЬ КОНТЕЙНЕРА; ЗАРАЖЕНИЯ ГАСЯТСЯ ВНУТР. ЗАЩИТОЙ (КРОМЕ ХОЛОДА).
       ЛИМИТЫ РАД/ТЕМП/БИО/ХОЛОД — 1.0, ПСИ — 3.0 — ЖЁСТКИЕ: СБОРКИ СВЕРХ ЛИМИТА НЕ ВЫДАЮТСЯ,
       ПРИ НУЖДЕ ДОБАВЛЯЮТСЯ КОНТРАРТЫ. ДОП. СВОЙСТВА ЗАТОЧКИ УЧТЕНЫ: НА +15 — ВСЕ (ДЕТЕРМИНИРОВАНО),
       НА +5/+10 — МАТОЖИДАНИЕМ (ПОРЯДОК ВЫПАДЕНИЯ СЛУЧАЕН).`;
  h += `<div class="side-foot">${footer}</div>`;
  page.innerHTML = h;
  wireBuilds(cont);
}

function renderManual(cont) {
  const t = manualTotals(cont);
  return `<div class="bgrid">${buildState.slots.map((s, i) => manualSlotCard(s, i)).join("")}</div>
    ${totalsBlock(t, cont, null)}`;
}

// Обычные статы, встречающиеся хотя бы на одном артефакте в красной (вредной)
// версии — кандидаты на исключение в автоподборе («не нужны эти минусы»).
// Заражения (пси/рад/…) в список не входят: их держат лимиты и контрарты.
function negStats() {
  const seen = new Map();
  for (const a of BUILD_DICT.artefacts)
    for (const [k, st] of Object.entries(a.stats))
      if (st.harmful && !isContamKey(k) && !seen.has(k)) seen.set(k, st.name);
  return [...seen].map(([key, name]) => ({ key, name }))
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
}

function renderAuto(cont) {
  const rows = autoState.stats.map((row, i) => `<div class="arow">
      <div class="isel aStatSel" data-i="${i}"></div>
      <input class="aW" data-i="${i}" type="range" min="0" max="100" value="${row.weight}">
      <span class="aWv">${row.weight}</span>
      ${autoState.stats.length > 1 ? `<button class="bs-x" data-rmstat="${i}">✕</button>` : ""}
    </div>`).join("");
  const negs = negStats();
  // Заражения (пси/рад/био/темп/холод) под этот флажок НЕ попадают: их держат
  // лимиты игрока и контрарты, а не «минус не в итоге» (builds.py, CONTAM_KEYS).
  // Оговорка жила только в title родителя, и «БЕЗ ВСЕХ ОТРИЦАТЕЛЬНЫХ» с пси 1.5
  // в результате читалось как баг (Sanshiai, чат багов 12.08). Пишем в форме.
  const contamNote = autoState.noNeg
    ? `<div class="aexc-note">ЗАРАЖЕНИЯ (ПСИ · РАД · БИО · ТЕМП · ХОЛОД) СЮДА НЕ ВХОДЯТ —
         ИХ ДЕРЖАТ ЛИМИТЫ ИГРОКА И КОНТРАРТЫ, СМ. БЛОК ЗАРАЖЕНИЯ В СБОРКЕ</div>` : "";
  const chips = autoState.noNeg
    ? `<button class="xchip" data-nonegoff title="Убрать исключение">БЕЗ ВСЕХ ОТРИЦАТЕЛЬНЫХ, КРОМЕ ЗАРАЖЕНИЙ ✕</button>`
    : autoState.exclude.map((k) => {
        const s = negs.find((n) => n.key === k);
        return `<button class="xchip" data-unx="${k}" title="Убрать исключение">${escapeHtml(s ? s.name : k)} ✕</button>`;
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
      <div class="aexc" title="Итог сборки по этим статам не уйдёт в минус: арты с минусом допускаются, если его перекрывает плюс других артов. Заражения (пси/рад и т.п.) не исключаются — их гасят лимиты и контрарты.">
        <span class="albl">БЕЗ МИНУСА В ИТОГЕ:</span>
        ${chips}
        ${autoState.noNeg ? "" : `<div class="isel" id="aExcSel"></div>`}
      </div>
      ${contamNote}
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
    ${s.bonus && s.bonus.length ? bonusRowsRO(s.bonus) : milestoneNote(s.milestones)}
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
        <div class="isel" id="hArmorSel"></div>
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
      ${(hp.container_bullet || hp.container_vitality) ? `<div class="bt-row"><span class="k">ХРАНИЛИЩЕ</span>
        <span class="v">${hp.container_bullet ? `ПУЛЕСТОЙ ${fmtStat(hp.container_bullet)}` : ""}${hp.container_bullet && hp.container_vitality ? " · " : ""}${hp.container_vitality ? `ЖИВУЧ ${fmtStat(hp.container_vitality)}%` : ""}</span></div>` : ""}
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

// кастомный выпадающий список (нативный <select> не умеет иконки и поиск):
// сортировка по редкости (сверху крутое) + живой поиск по названию.
// Иконка опциональна — списки статов идут без неё.
function iconSelect(host, items, curId, onPick) {
  items = items.map((it, i) => ({ ...it, _i: i }))
    .sort((a, b) => (rankWeight(b.color) - rankWeight(a.color)) || (a._i - b._i));
  const cur = items.find((it) => it.id === curId) || items[0];
  if (!cur) { host.innerHTML = ""; return; }
  const lbl = (it) => it.labelHtml || escapeHtml(it.label);  // labelHtml — уже экранирован вызывающим
  const searchOf = (it) => (it.search != null ? it.search
    : String(it.labelHtml || it.label || "").replace(/<[^>]*>/g, "")).toLowerCase();
  host.innerHTML = `<button type="button" class="isel-btn">
      ${cur.icon ? `<img src="${asset(cur.icon)}" alt="">` : ""}
      <span class="isel-lbl">${lbl(cur)}</span><span class="isel-arr">▾</span></button>
    <div class="isel-list hidden">
      <div class="isel-search"><input type="text" class="isel-q" placeholder="Поиск…" autocomplete="off"></div>
      <div class="isel-opts">${items.map((it) => `
        <div class="isel-opt${it.id === cur.id ? " on" : ""}" data-id="${it.id}" data-s="${escapeHtml(searchOf(it))}">
          ${it.icon ? `<img loading="lazy" src="${asset(it.icon)}" alt="">` : ""}<span>${lbl(it)}</span>
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
    STORAGES().map((c) => ({ id: c.id, icon: c.icon, color: c.color,
                             search: `${c.name} ${KIND_LBL[c.kind] || ""}`, labelHtml: contLabel(c) })),
    buildState.container, (id) => {
      buildState.container = id;
      const c = buildContainer();
      const old = buildState.slots;
      buildState.slots = Array(c.slots).fill(null).map((_, i) => old[i] || null);
      renderBuilds();
    });

  page.querySelectorAll("[data-ropen]").forEach((b) =>
    b.addEventListener("click", () => readyOpen(b.dataset.ropen)));
  page.querySelectorAll("[data-rauto]").forEach((b) =>
    b.addEventListener("click", () => readyAuto(b.dataset.rauto)));

  if (buildTab === "auto") {
    wireBudget($("aBudget"), (v) => { autoState.budget = v; });
    // выбор стата — выпадающий список с живым поиском (просьба юзеров)
    const beneficial = BUILD_DICT.stats.filter((s) => !s.harmful);
    page.querySelectorAll(".aStatSel").forEach((host) => {
      const i = +host.dataset.i;
      const used = autoState.stats.map((r) => r.key);
      iconSelect(host,
        [{ id: "", label: "— СТАТ —", search: "" }, ...beneficial
          .filter((s) => s.key === autoState.stats[i].key || !used.includes(s.key))
          .map((s) => ({ id: s.key, label: s.name, search: s.name }))],
        autoState.stats[i].key,
        (id) => { autoState.stats[i].key = id; renderBuilds(); });
    });
    // исключение минусов: адаптер-список добавляет чип, клик по чипу снимает;
    // «без всех» — один пункт-выключатель вместо перечисления
    const excHost = $("aExcSel");
    if (excHost) iconSelect(excHost,
      [{ id: "", label: "+ ИСКЛЮЧИТЬ МИНУС", search: "" },
       { id: "__all__", label: "БЕЗ ВСЕХ ОТРИЦАТЕЛЬНЫХ, КРОМЕ ЗАРАЖЕНИЙ",
         search: "без всех отрицательных эффектов заражения пси" },
       ...negStats()
        .filter((s) => !autoState.exclude.includes(s.key))
        .map((s) => ({ id: s.key, label: s.name, search: s.name }))],
      "", (id) => {
        if (id === "__all__") { autoState.noNeg = true; renderBuilds(); }
        else if (id) { autoState.exclude.push(id); renderBuilds(); }
      });
    page.querySelectorAll("[data-unx]").forEach((b) => b.addEventListener("click", () => {
      autoState.exclude = autoState.exclude.filter((k) => k !== b.dataset.unx);
      renderBuilds();
    }));
    const negOff = page.querySelector("[data-nonegoff]");
    if (negOff) negOff.addEventListener("click", () => {
      autoState.noNeg = false;
      renderBuilds();
    });
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
          body: JSON.stringify({ budget: autoState.budget, container: buildState.container,
                                 stats, exclude: autoState.exclude,
                                 no_negatives: autoState.noNeg }),
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
    const s = buildState.slots[+el.dataset.slot];
    s.ptn = +el.value;
    if (s.bx) {  // выбор допов не может превышать разблокированные пороги
      const art = BUILD_DICT.artefacts.find((a) => a.id === s.id);
      s.bx = s.bx.slice(0, bonusUnlocked(s.ptn, (art && art.bonus) || []));
    }
    renderBuilds();
  }));
  // галочки выпавших доп-свойств порогов (+5/+10 — какие именно, знает владелец)
  page.querySelectorAll(".bs-bx").forEach((el) => el.addEventListener("change", () => {
    const s = buildState.slots[+el.dataset.slot];
    const art = BUILD_DICT.artefacts.find((a) => a.id === s.id);
    const pool = (art && art.bonus) || [];
    const unlocked = bonusUnlocked(s.ptn, pool);
    let bx = (s.bx || []).filter((k) => pool.some((b) => b.key === k));
    if (el.checked) {
      if (!bx.includes(el.dataset.bx)) bx.push(el.dataset.bx);
      if (bx.length > unlocked) bx = bx.slice(bx.length - unlocked);  // лишние — старейшие долой
    } else {
      bx = bx.filter((k) => k !== el.dataset.bx);
    }
    s.bx = bx;
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

// Полезная область слоя: view из /map/meta отрезает декоративные поля коллажа
// (мусор по краям global_map); без view — всё изображение.
const layerView = (lm) => lm.view || [0, 0, lm.w, lm.h];

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
  const { map, px } = makeTileMap(g, layerView(g));
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

// ---------- ДЕВ · сканер выгодных лотов аука ----------
// Реалтайм по вебсокету /api/ws/dev/scan: бэкенд-обходчик цен пушит сделки
// (лоты дешевле средней последних продаж у ликвидных предметов) и снимает их,
// когда дешёвые лоты разобрали. Пороги правятся тут же и применяются на лету.
let scanWs = null, scanPing = null, scanRetry = null, scanTick = null, scanBackoff = 1000;
let scanState = null;   // {settings, deals: Map, stats} — живёт, пока открыт /dev/scan

const SCAN_SORTS = {
  margin_lot: ["МАРЖА ЗА ЛОТ", (a, b) => b.margin_lot - a.margin_lot],
  margin_total: ["МАРЖА ∑ ПО ЛОТАМ", (a, b) => b.margin_total - a.margin_total],
  margin: ["МАРЖА/ШТ", (a, b) => b.margin - a.margin],
  discount: ["СКИДКА %", (a, b) => b.discount - a.discount],
  sph: ["ПРОДАЖ/ЧАС", (a, b) => b.sph - a.sph],
  found: ["НОВИЗНА", (a, b) => b.found_ts - a.found_ts],
};
const scanSortKey = () => localStorage.getItem("sz_scan_sort") || "margin_lot";

function scanClose() {
  if (scanPing) { clearInterval(scanPing); scanPing = null; }
  if (scanRetry) { clearTimeout(scanRetry); scanRetry = null; }
  if (scanTick) { clearInterval(scanTick); scanTick = null; }
  if (scanWs) { const ws = scanWs; scanWs = null; try { ws.close(); } catch (e) {} }
  scanState = null;
}

async function openDevScan() {
  if (!devGate()) return;
  page.innerHTML = `<div class="mapmod"><div class="spinner">// ЗАГРУЗКА СКАНЕРА</div></div>`;
  let d;
  try {
    const r = await fetch(api("/admin/scan"));
    if (!r.ok) throw new Error("HTTP " + r.status);
    d = await r.json();
  } catch (e) {
    page.innerHTML = `<div class="empty">[!] СКАНЕР НЕ ЗАГРУЗИЛСЯ (${escapeHtml(e.message)})</div>`;
    return;
  }
  if (location.pathname !== "/dev/scan") return;
  scanState = { settings: d.settings, stats: d.stats || {},
                deals: new Map((d.deals || []).map((x) => [x.id, x])) };
  renderScanFrame();
  scanConnect();
  scanTick = setInterval(scanRenderDeals, 15000);  // тикают «снято N мин назад»
}

function renderScanFrame() {
  const s = scanState.settings;
  const sortCur = scanSortKey();
  const sortSel = Object.entries(SCAN_SORTS).map(([k, v]) =>
    `<option value="${k}"${sortCur === k ? " selected" : ""}>${v[0]}</option>`).join("");
  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · СКАНЕР ВЫГОДНЫХ ЛОТОВ</div>
      <div class="section-note">Ловит на ауке лоты дешевле средней из последних продаж у ликвидных
        предметов. Данные — от фонового обходчика цен: карточка появляется и уходит при его проходе
        по предмету, сюда прилетает по вебсокету. Маржа — при перепродаже по средней, за вычетом
        комиссии аука 5%.</div>
    </div>
    ${devSubnav("scan")}
    <div class="scan-panel">
      <label class="scan-f">ПРОДАЖ/ЧАС ≥ <input id="scF_sph" type="number" min="0" step="1" value="${s.min_sph}"></label>
      <label class="scan-f" title="Броня, оружие, обвесы, контейнеры и рюкзаки продаются штучно — им нужен свой, низкий порог">
        ⚔ БРОНЯ/ОРУЖИЕ/ОБВЕСЫ ≥ <input id="scF_sphg" type="number" min="0" step="0.1" value="${s.min_sph_gear}"> ПРОД/Ч</label>
      <label class="scan-f">ДЕШЕВЛЕ СРЕДНЕЙ НА ≥ <input id="scF_disc" type="number" min="0" max="90" step="1" value="${s.discount_pct}"> %</label>
      <label class="scan-f">СРЕДНЯЯ ИЗ ПОСЛЕДНИХ <input id="scF_n" type="number" min="1" max="20" step="1" value="${s.avg_n}"> ПРОДАЖ</label>
      <label class="scan-f">МАРЖА ≥ <input id="scF_margin" type="number" min="0" step="1" value="${s.min_margin}"> ₽/ШТ</label>
      <label class="scan-f" title="Сколько минут назад сняты лоты. Всё, что может стать сделкой, обновляется примерно раз в 2 минуты — старее значит лот, скорее всего, уже выкупили">
        ⏱ ЛОТЫ НЕ СТАРШЕ <input id="scF_age" type="number" min="1" step="1" value="${s.max_age_min}"> МИН</label>
      <label class="scan-chk" title="Выключен — сделки не ищутся и карточки не показываются">
        <input id="scF_on" type="checkbox"${s.enabled ? " checked" : ""}> СКАНЕР ВКЛ</label>
      <label class="scan-chk" title="Выключить — артефакты пропадут из выдачи и уйдут из обхода цен (их нет в крафт-графе, они там только ради сканера), бюджет запросов освободится">
        <input id="scF_art" type="checkbox"${s.show_artefacts ? " checked" : ""}> 💎 АРТЕФАКТЫ</label>
      <label class="scan-chk" title="История продаж снимается по ВСЕМ предметам крафт-графа — полное покрытие сканера, но цикл обходчика примерно вдвое длиннее">
        <input id="scF_all" type="checkbox"${s.hist_all ? " checked" : ""}> ИСТОРИЯ ПО ВСЕМ ПРЕДМЕТАМ</label>
      <button class="gadm-btn scan-apply" id="scApply">ПРИМЕНИТЬ</button>
      <span class="gform-msg" id="scMsg"></span>
    </div>
    <div class="scan-status">
      <span class="scan-dot off" id="scDot"></span><span id="scWsTxt">ПОДКЛЮЧЕНИЕ…</span>
      <span class="scan-stats" id="scStats"></span>
      <label class="scan-sort">СОРТИРОВКА <select id="scSort">${sortSel}</select></label>
    </div>
    <div class="scan-grid" id="scGrid"></div>
  </div>`;
  $("scApply").addEventListener("click", scanApplySettings);
  $("scSort").addEventListener("change", () => {
    localStorage.setItem("sz_scan_sort", $("scSort").value);
    scanRenderDeals();
  });
  scanRenderStats();
  scanRenderDeals();
}

async function scanApplySettings() {
  const body = {
    min_sph: +$("scF_sph").value,
    min_sph_gear: +$("scF_sphg").value,
    discount_pct: +$("scF_disc").value,
    avg_n: +$("scF_n").value,
    min_margin: +$("scF_margin").value,
    max_age_min: +$("scF_age").value,
    enabled: $("scF_on").checked,
    show_artefacts: $("scF_art").checked,
    hist_all: $("scF_all").checked,
  };
  $("scApply").disabled = true;
  $("scMsg").textContent = "…";
  try {
    const r = await fetch(api("/admin/scan/settings"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();       // сделки придут снапшотом по вебсокету
    if (scanState) scanState.settings = d.settings;
    scanSyncForm();
    const m = $("scMsg");
    if (m) {
      m.textContent = "✓ СОХРАНЕНО";
      setTimeout(() => { const x = $("scMsg"); if (x) x.textContent = ""; }, 2500);
    }
  } catch (e) {
    const m = $("scMsg");
    if (m) m.textContent = "[!] НЕ СОХРАНИЛОСЬ: " + e.message;
  }
  const b = $("scApply");
  if (b) b.disabled = false;
}

function scanSyncForm() {
  if (!scanState) return;
  const s = scanState.settings;
  const setv = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = v; };
  const setc = (id, v) => { const el = $(id); if (el) el.checked = v; };
  setv("scF_sph", s.min_sph); setv("scF_sphg", s.min_sph_gear);
  setv("scF_disc", s.discount_pct);
  setv("scF_n", s.avg_n); setv("scF_margin", s.min_margin);
  setv("scF_age", s.max_age_min);
  setc("scF_on", s.enabled); setc("scF_all", s.hist_all);
  setc("scF_art", s.show_artefacts);
}

function scanSetWs(state, txt) {
  const dot = $("scDot"), t = $("scWsTxt");
  if (!dot || !t) return;
  dot.className = "scan-dot " + state;
  t.textContent = txt;
}

function scanConnect() {
  if (!scanState || location.pathname !== "/dev/scan") return;
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://")
    + location.host + "/api/ws/dev/scan");
  scanWs = ws;
  scanSetWs("off", "ПОДКЛЮЧЕНИЕ…");
  ws.onopen = () => {
    scanBackoff = 1000;
    scanSetWs("on", "ОНЛАЙН");
    scanPing = setInterval(() => { try { ws.send("ping"); } catch (e) {} }, 25000);
  };
  ws.onmessage = (ev) => {
    if (!scanState) return;
    let m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.type === "snapshot") {
      scanState.settings = m.settings;
      scanState.stats = m.stats || {};
      scanState.deals = new Map((m.deals || []).map((x) => [x.id, x]));
      scanSyncForm(); scanRenderStats(); scanRenderDeals();
    } else if (m.type === "deal") {
      const old = scanState.deals.get(m.deal.id);
      m.deal._flash = old ? old._flash : Date.now();   // подсветка только новых
      scanState.deals.set(m.deal.id, m.deal);
      scanRenderStats(); scanRenderDeals();
    } else if (m.type === "remove") {
      scanState.deals.delete(m.id);
      scanRenderStats(); scanRenderDeals();
    }
  };
  ws.onclose = () => {
    if (scanPing) { clearInterval(scanPing); scanPing = null; }
    if (scanWs !== ws) return;   // закрыли сами при уходе со страницы
    scanSetWs("off", "ПЕРЕПОДКЛЮЧЕНИЕ…");
    scanRetry = setTimeout(scanConnect, scanBackoff);
    scanBackoff = Math.min(scanBackoff * 2, 15000);
  };
}

function scanRenderStats() {
  const el = $("scStats");
  if (!el || !scanState) return;
  const st = scanState.stats || {};
  const round = st.hot_round_sec == null ? "СЧИТАЕТСЯ"
    : st.hot_round_sec < 90 ? `${st.hot_round_sec} С` : `${(st.hot_round_sec / 60).toFixed(1)} МИН`;
  el.textContent = `СДЕЛОК ${scanState.deals.size} · ЛИКВИДНЫХ В КРУГЕ ${fmt(st.hot)}`
    + ` · КРУГ ${round} · ИСТОРИЯ ${fmt(st.hist_items)} ПРЕДМ.`;
}

const scanAge = (ts) => {
  if (!ts) return "—";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return `${s} с`;
  if (s < 3600) return `${Math.floor(s / 60)} мин`;
  return `${Math.floor(s / 3600)} ч ${Math.floor((s % 3600) / 60)} мин`;
};

// лоты на исходе актуальности (>60% лимита) — подсветить возраст: следующий
// замер либо подтвердит сделку, либо снимет карточку
const scanStale = (ts) => {
  const lim = (scanState && scanState.settings.max_age_min) || 15;
  return ts && Date.now() / 1000 - ts > lim * 60 * 0.6;
};

// маржа компактно: тысячи сокращаются до «т» (1500 → 1,5т; 23400 → 23т)
const fmtT = (n) => {
  if (n == null) return "—";
  const v = Math.round(n);
  if (Math.abs(v) < 1000) return v.toLocaleString("ru-RU");
  const t = v / 1000;
  return (Math.abs(t) >= 10 ? Math.round(t).toLocaleString("ru-RU")
                            : t.toFixed(1).replace(".", ",").replace(",0", "")) + "т";
};

function scanRenderDeals() {
  const grid = $("scGrid");
  if (!grid || !scanState) return;
  const deals = [...scanState.deals.values()];
  if (!deals.length) {
    grid.innerHTML = `<div class="empty-sm">${scanState.settings.enabled
      ? "СДЕЛОК ПОКА НЕТ — карточки появляются по мере прохода обходчика по ауку (полный круг ~10–20 мин)."
      : "СКАНЕР ВЫКЛЮЧЕН — включи галку выше и нажми ПРИМЕНИТЬ."}</div>`;
    return;
  }
  deals.sort((SCAN_SORTS[scanSortKey()] || SCAN_SORTS.margin_lot)[1]);
  // до 3 конкретных лотов на карточке: кол-во, маржа лота и цена лота целиком
  // (по ней лот опознаётся в ауке — там видна цена выкупа).
  // Маржа лота = (средняя×0.95 − цена/шт) × кол-во; avg×0.95 = d.margin + d.price.
  const lotRows = (d) => {
    const top = d.top_lots || [];
    const rows = top.map(([u, a]) => `<div class="scan-lot">
      <b>${fmt(a)} шт</b><span class="scan-lot-u">маржа ${fmtT((d.margin + d.price - u) * a)} ₽</span>
      <span class="scan-lot-t">лот ${fmt(u * a)} ₽</span></div>`).join("");
    const rest = d.lots - top.length;
    return rows + (rest > 0
      ? `<div class="scan-lot scan-lot-more">…ещё ${rest} лот${rest === 1 ? "" : rest < 5 ? "а" : "ов"} · всего ${fmt(d.qty)} шт ≤ порога</div>` : "");
  };
  grid.innerHTML = deals.map((d) => `
    <div class="scan-card${Date.now() - (d._flash || 0) < 8000 ? " new" : ""}" data-id="${d.id}"
      title="Открыть карточку аукциона: живые лоты, продажи и график">
      <div class="scan-head">
        <img loading="lazy" src="${asset(d.icon)}" alt="">
        <span class="scan-name" style="color:${rank(d.color).color}">${escapeHtml(d.name)}</span>
        <button class="scan-copy" data-copy="${escapeHtml(d.name)}"
          title="Скопировать название — вбить в поиск аука в игре">⧉</button>
      </div>
      ${d.qlt || d.ptn ? `<div class="scan-bucket" title="Сравнение идёт только внутри этой корзины: у другого качества/заточки цена другая">
        ${d.qlt ? `КАЧЕСТВО ${d.qlt}` : "БЕЗ КАЧЕСТВА"}${d.ptn ? ` · ЗАТОЧКА +${d.ptn}` : ""}</div>` : ""}
      <div class="scan-lots">${lotRows(d)}</div>
      <div class="scan-rows">
        <span>${d.avg_src === "7д" ? "СРЕДНЯЯ ЗА НЕДЕЛЮ" : `СРЕДНЯЯ ${d.n} ПРОДАЖ`} <b>${fmt(d.avg)} ₽</b></span>
        <span>ДЕШЕВЛЕ НА <b class="scan-disc">−${d.discount}%</b></span>
        <span>ПРОДАЖ/ЧАС <b>${fmtSales(d.sph)}</b></span>
        <span>МАРЖА/ШТ <b class="scan-m">${fmtT(d.margin)} ₽</b></span>
        <span>ЛУЧШИЙ ЛОТ <b class="scan-m">${fmtT(d.margin_lot)} ₽</b></span>
        <span>МАРЖА ∑ <b class="scan-m">${fmtT(d.margin_total)} ₽</b></span>
      </div>
      ${(d.recent_sales || []).length ? `<div class="scan-sales">ПОСЛЕДНИЕ ПРОДАЖИ ЭТОЙ КОРЗИНЫ:
        ${d.recent_sales.map(([u, a]) => `<span class="scan-sale"><b>${fmt(a)} шт</b> за ${fmt(u * a)} ₽</span>`).join(" · ")}</div>` : ""}
      <div class="scan-age${scanStale(d.ts) ? " old" : ""}">лоты сняты ${scanAge(d.ts)} назад · найдено ${scanAge(d.found_ts)} назад</div>
    </div>`).join("");
  grid.querySelectorAll(".scan-card[data-id]").forEach((c) =>
    c.addEventListener("click", (e) => {
      if (e.target.closest(".scan-copy")) return;   // кнопка копирования — не открывает
      openMarketModal(c.dataset.id);
    }));
  grid.querySelectorAll(".scan-copy").forEach((b) =>
    b.addEventListener("click", () => {
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(b.dataset.copy).then(() => {
        b.textContent = "✓";
        setTimeout(() => { b.textContent = "⧉"; }, 1200);
      }).catch(() => {});
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
// ---------- картинки редактора: сжатие 4K-скринов + загрузка ----------
// 4K-PNG весит десятки МБ — не влезает в лимит загрузки и забивает диск.
// Перед отправкой ужимаем по большей стороне и перекодируем в WebP:
// обычно выходит 100–300 КБ без заметной потери читаемости.
const EDITOR_IMG_MAXDIM = 1920;
const EDITOR_IMG_QUALITY = 0.85;

function fileToDataURL(file) {
  return new Promise((res, rej) => {
    const rd = new FileReader();
    rd.onload = () => res(rd.result);
    rd.onerror = () => rej(new Error("не удалось прочитать файл"));
    rd.readAsDataURL(file);
  });
}

function loadImage(src) {
  return new Promise((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = () => rej(new Error("не удалось декодировать картинку"));
    im.src = src;
  });
}

function blobToDataURL(blob) {
  return new Promise((res, rej) => {
    const rd = new FileReader();
    rd.onload = () => res(rd.result);
    rd.onerror = () => rej(new Error("не удалось прочитать blob"));
    rd.readAsDataURL(blob);
  });
}

// data-URL сжатой картинки (webp); gif и любые осечки отдаём как есть
async function compressImageFile(file) {
  const original = await fileToDataURL(file);
  if (!file.type || !file.type.startsWith("image/") || file.type === "image/gif")
    return original;                              // gif — canvas убьёт анимацию
  try {
    const img = await loadImage(original);
    const big = Math.max(img.width, img.height) || 1;
    const scale = Math.min(1, EDITOR_IMG_MAXDIM / big);
    const w = Math.max(1, Math.round(img.width * scale));
    const h = Math.max(1, Math.round(img.height * scale));
    const cv = document.createElement("canvas");
    cv.width = w; cv.height = h;
    cv.getContext("2d").drawImage(img, 0, 0, w, h);
    const blob = await new Promise((r) => cv.toBlob(r, "image/webp", EDITOR_IMG_QUALITY));
    if (!blob) return original;                   // webp не поддержан браузером
    if (blob.size >= file.size) return original;  // не помогло — не раздуваем
    return await blobToDataURL(blob);
  } catch (e) {
    return original;                              // любая осечка — шлём оригинал
  }
}

// сжать + отправить; вернуть URL в /guide-uploads или бросить ошибку
async function uploadEditorImage(file) {
  const data = await compressImageFile(file);
  const r = await fetch(api("/admin/guides/image"), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data, filename: file.name || "paste.webp" }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || "ошибка загрузки");
  return j.url;
}

// вставить текст в позицию курсора (или в конец, если фокуса в поле нет)
function insertAtCursor(ta, text) {
  const len = ta.value.length;
  const s = Number.isInteger(ta.selectionStart) ? ta.selectionStart : len;
  const e = Number.isInteger(ta.selectionEnd) ? ta.selectionEnd : len;
  ta.setRangeText(text, s, e, "end");
}

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
    + `<span class="fmt-tip">выдели текст → кнопка обернёт его в тег · Ctrl+V — вставить скриншот прямо в текст</span>`;
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
  // Ctrl+V скриншотом: ловим картинку из буфера, сжимаем, грузим, вставляем
  // <img> на месте курсора. Пока идёт загрузка — держим уникальный маркер.
  ta.addEventListener("paste", (ev) => {
    const items = ev.clipboardData && ev.clipboardData.items;
    if (!items) return;
    const it = [...items].find((x) => x.kind === "file" && x.type.startsWith("image/"));
    if (!it) return;                              // не картинка — обычная вставка
    const file = it.getAsFile();
    if (!file) return;
    ev.preventDefault();
    const tok = `<!-- upl-${Math.random().toString(36).slice(2)} -->`;
    insertAtCursor(ta, `\n${tok}\n`);
    if (onChange) onChange();
    (async () => {
      try {
        const url = await uploadEditorImage(file);
        ta.value = ta.value.replace(tok, `<img src="${url}" alt="">`);
      } catch (e) {
        ta.value = ta.value.replace(tok, `<!-- не загрузилось: ${e.message} -->`);
      }
      if (onChange) onChange();
    })();
  });
}

// ---------- ДЕВ · редактор гайдов (только админ) ----------
const devSubnav = (on) => `<div class="dev-subnav">
  <a href="/dev/map"${on === "map" ? ' class="on"' : ""}>КАРТА</a>
  <a href="/dev/ab"${on === "ab" ? ' class="on"' : ""}>A/B-ТЕСТ</a>
  <a href="/dev/guides"${on === "guides" ? ' class="on"' : ""}>ГАЙДЫ</a>
  <a href="/dev/quests"${on === "quests" ? ' class="on"' : ""}>КВЕСТЫ</a>
  <a href="/dev/promo"${on === "promo" ? ' class="on"' : ""}>ПРОМОКОДЫ</a>
  <a href="/dev/craft"${on === "craft" ? ' class="on"' : ""}>РЕЦЕПТЫ</a>
  <a href="/dev/scan"${on === "scan" ? ' class="on"' : ""}>СКАНЕР</a>
  <a href="/dev/news"${on === "news" ? ' class="on"' : ""}>НОВОСТИ</a>
  <a href="/home2">МАКЕТЫ ↗</a>
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
        <textarea id="gfHtml" rows="18" class="gform-html" spellcheck="true" lang="ru">${escapeHtml(g.html)}</textarea></div>
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

  $("gfUpload").addEventListener("click", async () => {
    const f = $("gfImg").files[0], msg = $("gfUpMsg");
    if (!f) { msg.textContent = "выбери файл"; return; }
    msg.textContent = "сжатие и загрузка…";
    try {
      const url = await uploadEditorImage(f);
      insertAtCursor($("gfHtml"), `\n<img src="${url}" alt="">\n`);
      if (!$("gfCover").value.trim()) setCover(url);
      msg.innerHTML = `готово, вставлено в тело: <b>${escapeHtml(url)}</b>`;
      renderPrev();
    } catch (e) { msg.textContent = e.message || "ошибка сети"; }
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

// ---------- ДЕВ · редактор промокодов (только админ) ----------
async function openDevPromos() {
  if (!devGate()) return;
  await renderDevPromosList();
}

async function renderDevPromosList() {
  page.innerHTML = `<div class="mapmod"><div class="spinner">// ЗАГРУЗКА ПРОМОКОДОВ</div></div>`;
  let d;
  try { d = await fetch(api("/promos")).then((r) => r.json()); }
  catch (e) { page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`; return; }
  if (location.pathname !== "/dev/promo") return;
  const items = d.items || [];
  const rows = items.map((p) => `
    <div class="gadm-row">
      <div class="gadm-row-i">
        <div class="gadm-row-t">${p.is_ref ? `<span class="dash-promo-ref">★ РЕФ</span> ` : ""}${escapeHtml(p.title)}
          · <b>${escapeHtml(p.code)}</b></div>
        <div class="gadm-row-s">${p.expires_at
          ? `до ${escapeHtml(p.expires_at.replace("T", " "))} МСК (потом удалится сам)` : "бессрочный"}</div>
      </div>
      <div class="gadm-row-a">
        <button class="gadm-btn" data-edit="${p.id}">РЕД.</button>
        <button class="gadm-btn gadm-del" data-del="${p.id}" title="Удалить">✕</button>
      </div>
    </div>`).join("");
  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · ПРОМОКОДЫ</div>
      <div class="section-note">Модуль на главной + страница /promo. Истёкшие удаляются автоматически
        (по дате МСК). «Реферальный» — всегда один и закреплён сверху.</div>
    </div>
    ${devSubnav("promo")}
    <button class="gadm-new" id="padmNew">＋ НОВЫЙ ПРОМОКОД</button>
    <div class="gadm-list">${rows || `<div class="empty-sm">ПРОМОКОДОВ ПОКА НЕТ.</div>`}</div>
  </div>`;
  $("padmNew").addEventListener("click", () => renderDevPromoForm(null));
  page.querySelectorAll("[data-edit]").forEach((b) =>
    b.addEventListener("click", () =>
      renderDevPromoForm(items.find((p) => p.id === +b.dataset.edit) || null)));
  page.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm("Удалить промокод? Он уйдёт с главной и со страницы /promo.")) return;
      await fetch(api(`/admin/promos/${b.dataset.del}`), { method: "DELETE" }).catch(() => {});
      renderDevPromosList();
    }));
}

function renderDevPromoForm(p) {
  const isNew = !p;
  p = p || { title: "", code: "", url: "", description: "", image: "", expires_at: "", is_ref: false };
  // expires_at "YYYY-MM-DDTHH:MM" → инпуты даты и времени (23:59 = «весь день», время пустое)
  const em = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})$/.exec(p.expires_at || "");
  const expDate = em ? em[1] : "", expTime = em && em[2] !== "23:59" ? em[2] : "";
  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · ПРОМОКОДЫ · ${isNew ? "НОВЫЙ" : "РЕДАКТИРОВАНИЕ"}</div>
    </div>
    ${devSubnav("promo")}
    <div class="gform">
      <label class="gform-l">НАЗВАНИЕ · что даёт промокод
        <input id="pfTitle" value="${escapeHtml(p.title)}" placeholder="Промокод ко дню рождения STALCRAFT"></label>
      <label class="gform-l">ПРОМОКОД · оставь пустым, если это ссылка (Steam DLC)
        <input id="pfCode" value="${escapeHtml(p.code)}" placeholder="STALZONE2026" autocomplete="off"></label>
      <label class="gform-l">ССЫЛКА · если задана — вместо кода будет кнопка «Забрать» (Steam DLC / внешняя)
        <input id="pfUrl" value="${escapeHtml(p.url || "")}" placeholder="https://store.steampowered.com/app/…" autocomplete="off"></label>
      <div class="gform-l">ОПИСАНИЕ · HTML-новость для страницы /promo (на главной не показывается)
        <div id="pfBar"></div>
        <textarea id="pfDesc" rows="10" class="gform-html" spellcheck="true" lang="ru">${escapeHtml(p.description)}</textarea></div>
      <div class="gform-upload">
        <input type="file" id="pfImg" accept="image/png,image/jpeg,image/webp,image/gif">
        <button type="button" class="gadm-btn" id="pfUpload">ЗАГРУЗИТЬ И ВСТАВИТЬ В ОПИСАНИЕ</button>
        <span id="pfUpMsg" class="gform-msg"></span>
      </div>
      <label class="gform-l">КАРТИНКА КАРТОЧКИ · URL (не обязательно, справа от текста)
        <input id="pfImage" value="${escapeHtml(p.image)}" placeholder="/guide-uploads/… или /guide-img/…"></label>
      <div class="gform-cover"><img id="pfImageImg" alt="" src="${escapeHtml(p.image || "")}" ${p.image ? "" : 'style="display:none"'}></div>
      <div class="gform-row">
        <label class="gform-l">ДЕЙСТВУЕТ ДО · дата (пусто = бессрочный)
          <input id="pfExp" type="date" value="${escapeHtml(expDate)}"></label>
        <label class="gform-l">ВРЕМЯ МСК · пусто = весь день включительно
          <input id="pfExpT" type="time" value="${escapeHtml(expTime)}"></label>
        <label class="gform-chk"><input id="pfRef" type="checkbox" ${p.is_ref ? "checked" : ""}>
          РЕФЕРАЛЬНЫЙ · закрепить сверху (единственный)</label>
      </div>
      <div class="gform-actions">
        <button type="button" class="gadm-save" id="pfSave">СОХРАНИТЬ</button>
        <button type="button" class="gadm-btn" id="pfPrevBtn">ОБНОВИТЬ ПРЕДПРОСМОТР ⟳</button>
        <button type="button" class="gadm-btn" id="pfCancel">◂ К СПИСКУ</button>
        <span id="pfMsg" class="gform-msg"></span>
      </div>
      <div class="gform-prev-h">ПРЕДПРОСМОТР ОПИСАНИЯ</div>
      <article class="patch-article"><div class="patch-body gform-prev" id="pfPrev"></div></article>
    </div>
  </div>`;

  $("pfCancel").addEventListener("click", () => renderDevPromosList());
  $("pfImage").addEventListener("input", () => {
    const im = $("pfImageImg"), v = $("pfImage").value.trim();
    im.src = v; im.style.display = v ? "" : "none";
  });
  const renderPrev = () => { $("pfPrev").innerHTML = $("pfDesc").value; };
  fmtToolbar($("pfBar"), $("pfDesc"), renderPrev);
  $("pfPrevBtn").addEventListener("click", renderPrev);
  renderPrev();

  // загрузка картинки — тем же аплоадом, что у гайдов (кладёт в /guide-uploads);
  // тег <img> вставляется в конец описания
  $("pfUpload").addEventListener("click", async () => {
    const f = $("pfImg").files[0], msg = $("pfUpMsg");
    if (!f) { msg.textContent = "выбери файл"; return; }
    msg.textContent = "сжатие и загрузка…";
    try {
      const url = await uploadEditorImage(f);
      insertAtCursor($("pfDesc"), `\n<img src="${url}" alt="">\n`);
      msg.innerHTML = `готово, вставлено в описание: <b>${escapeHtml(url)}</b>`;
      renderPrev();
    } catch (e) { msg.textContent = e.message || "ошибка сети"; }
  });

  $("pfSave").addEventListener("click", async () => {
    const msg = $("pfMsg");
    if (!$("pfTitle").value.trim()) { msg.textContent = "нужно название"; return; }
    if (!$("pfCode").value.trim() && !$("pfUrl").value.trim()) {
      msg.textContent = "нужен промокод или ссылка"; return;
    }
    const expD = $("pfExp").value, expT = $("pfExpT").value;
    const body = {
      id: isNew ? undefined : p.id,
      title: $("pfTitle").value.trim(), code: $("pfCode").value.trim(),
      url: $("pfUrl").value.trim(),
      description: $("pfDesc").value.trim(), image: $("pfImage").value.trim(),
      expires_at: expD ? (expT ? `${expD}T${expT}` : expD) : "",
      is_ref: $("pfRef").checked,
    };
    $("pfSave").disabled = true; msg.textContent = "сохранение…";
    try {
      const r = await fetch(api("/admin/promos"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) { msg.textContent = j.detail || "ошибка сохранения"; $("pfSave").disabled = false; return; }
      renderDevPromosList();
    } catch (e) { msg.textContent = "ошибка сети"; $("pfSave").disabled = false; }
  });
}

// ---------- ДЕВ · новости САЙТА (только админ) ----------
// Ручные посты ленты на новой главной. Автособытия (гайды/промокоды/патчи)
// сюда не попадают — они подмешиваются на бэке при чтении /news/feed.
const NEWS_TAGS = ["ОБНОВЛЕНИЕ", "НОВЫЙ РАЗДЕЛ", "ФИКС", "АНОНС"];

async function openDevNews() {
  if (!devGate()) return;
  await renderDevNewsList();
}

async function renderDevNewsList() {
  page.innerHTML = `<div class="mapmod"><div class="spinner">// ЗАГРУЗКА НОВОСТЕЙ</div></div>`;
  let d;
  try { d = await fetch(api("/admin/news")).then((r) => r.json()); }
  catch (e) { page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`; return; }
  if (location.pathname !== "/dev/news") return;
  const items = d.items || [];
  const rows = items.map((n) => `
    <div class="gadm-row">
      <div class="gadm-row-i">
        <div class="gadm-row-t">${n.pinned ? `<span class="dash-promo-ref">★ ЗАКРЕП</span> ` : ""}${
          escapeHtml(n.title)}${n.published ? "" : ` <span class="gadm-draft">ЧЕРНОВИК</span>`}</div>
        <div class="gadm-row-s">${escapeHtml(n.created_at)}${
          n.tag ? ` · ${escapeHtml(n.tag)}` : ""}${n.url ? ` · ${escapeHtml(n.url)}` : ""}</div>
      </div>
      <div class="gadm-row-a">
        <button class="gadm-btn" data-edit="${n.id}">РЕД.</button>
        <button class="gadm-btn gadm-del" data-del="${n.id}" title="Удалить">✕</button>
      </div>
    </div>`).join("");
  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · НОВОСТИ САЙТА</div>
      <div class="section-note">Колонка новостей на новой главной (/home2). К этим постам лента
        сама подмешивает свежие гайды, промокоды и патчи игры — писать про них руками не нужно.</div>
    </div>
    ${devSubnav("news")}
    <button class="gadm-new" id="nadmNew">＋ НОВАЯ НОВОСТЬ</button>
    <div class="gadm-list">${rows || `<div class="empty-sm">РУЧНЫХ ПОСТОВ ПОКА НЕТ — ЛЕНТА ИДЁТ НА АВТОСОБЫТИЯХ.</div>`}</div>
  </div>`;
  $("nadmNew").addEventListener("click", () => renderDevNewsForm(null));
  page.querySelectorAll("[data-edit]").forEach((b) =>
    b.addEventListener("click", () =>
      renderDevNewsForm(items.find((n) => n.id === +b.dataset.edit) || null)));
  page.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm("Удалить новость? Она пропадёт из ленты на главной.")) return;
      await fetch(api(`/admin/news/${b.dataset.del}`), { method: "DELETE" }).catch(() => {});
      renderDevNewsList();
    }));
}

function renderDevNewsForm(n) {
  const isNew = !n;
  n = n || { title: "", body: "", url: "", tag: "", pinned: false, published: true,
             created_at: todayISO() };
  const tagOpts = NEWS_TAGS.map((t) =>
    `<option value="${t}"${n.tag === t ? " selected" : ""}>${t}</option>`).join("");
  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · НОВОСТИ · ${isNew ? "НОВАЯ" : "РЕДАКТИРОВАНИЕ"}</div>
      <div class="section-note">Формат ленты — короткая заметка: заголовок в одну строку и
        пара предложений. Длинный текст лучше оформить гайдом и дать сюда ссылку.</div>
    </div>
    ${devSubnav("news")}
    <div class="gform">
      <label class="gform-l">ЗАГОЛОВОК
        <input id="nfTitle" value="${escapeHtml(n.title)}" placeholder="Починили расчёт выгоды бартера"></label>
      <label class="gform-l">ТЕКСТ · пара предложений, без HTML
        <textarea id="nfBody" rows="4" spellcheck="true" lang="ru">${escapeHtml(n.body)}</textarea></label>
      <div class="gform-row">
        <label class="gform-l">ССЫЛКА · внутренний путь (не обязательно)
          <input id="nfUrl" value="${escapeHtml(n.url)}" placeholder="/barter" autocomplete="off"></label>
        <label class="gform-l">МЕТКА
          <select id="nfTag"><option value="">— без метки —</option>${tagOpts}</select></label>
        <label class="gform-l">ДАТА
          <input id="nfDate" type="date" value="${escapeHtml(n.created_at)}"></label>
      </div>
      <div class="gform-row">
        <label class="gform-chk"><input id="nfPin" type="checkbox" ${n.pinned ? "checked" : ""}>
          ЗАКРЕПИТЬ СВЕРХУ ЛЕНТЫ</label>
        <label class="gform-chk"><input id="nfPub" type="checkbox" ${n.published ? "checked" : ""}>
          ОПУБЛИКОВАНО · снять = черновик</label>
      </div>
      <div class="gform-actions">
        <button type="button" class="gadm-save" id="nfSave">СОХРАНИТЬ</button>
        <button type="button" class="gadm-btn" id="nfCancel">◂ К СПИСКУ</button>
        <span id="nfMsg" class="gform-msg"></span>
      </div>
    </div>
  </div>`;
  $("nfCancel").addEventListener("click", () => renderDevNewsList());
  $("nfSave").addEventListener("click", async () => {
    const msg = $("nfMsg");
    if (!$("nfTitle").value.trim()) { msg.textContent = "нужен заголовок"; return; }
    const body = {
      id: isNew ? undefined : n.id,
      title: $("nfTitle").value.trim(), body: $("nfBody").value.trim(),
      url: $("nfUrl").value.trim(), tag: $("nfTag").value,
      created_at: $("nfDate").value, pinned: $("nfPin").checked,
      published: $("nfPub").checked,
    };
    $("nfSave").disabled = true; msg.textContent = "сохранение…";
    try {
      const r = await fetch(api("/admin/news"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) { msg.textContent = j.detail || "ошибка сохранения"; $("nfSave").disabled = false; return; }
      renderDevNewsList();
    } catch (e) { msg.textContent = "ошибка сети"; $("nfSave").disabled = false; }
  });
}

// ---------- ДЕВ · сверка рецептов верстака с игрой (только админ) ----------
// Чек-лист «бонусный крафт есть/нет» (в базе EXBO этого признака нет) +
// правка данных рецепта (энергия, выход, уровень навыка, количества входов).
// Калькулятор применяет бонус ТОЛЬКО к рецептам с галкой «ЕСТЬ».
let cadmData = null;   // {items, perk_names} — живёт, пока открыт /dev/craft

async function openDevCraft() {
  if (!devGate()) return;
  page.innerHTML = `<div class="mapmod"><div class="spinner">// ЗАГРУЗКА РЕЦЕПТОВ</div></div>`;
  try { cadmData = await fetch(api("/admin/craft/recipes")).then((r) => r.json()); }
  catch (e) { page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`; return; }
  if (location.pathname !== "/dev/craft") return;
  renderDevCraft();
}

function cadmRowHtml(it) {
  const t = it.tuned || {};
  const perk = Object.entries(it.perks)[0];   // у рецептов верстака навык один
  const bonusBtn = (val, lbl, cls) => `<button class="cadm-b ${cls} ${it.bonus === val ? "on" : ""}"
      data-bonus="${val === null ? "" : val}">${lbl}</button>`;
  const ings = it.ingredients.map((i) => `
      <span class="cadm-ing" title="${escapeHtml(i.name)} (EXBO: ×${i.amount})">
        <img loading="lazy" src="${asset(i.icon)}" alt="">${escapeHtml(i.name)}
        ×<input type="number" min="0" max="10000" data-ing="${i.id}" data-orig="${i.amount}"
           value="${(t.ingredients || {})[i.id] ?? i.amount}">
      </span>`).join("");
  return `<div class="cadm-row ${it.bonus == null ? "" : "checked"}" data-key="${it.key}">
    <div class="cadm-main">
      <img loading="lazy" src="${asset(it.result.icon)}" alt="">
      <span class="cadm-name" title="${it.key}">${escapeHtml(it.result.name)}</span>
      <span class="x">×<input type="number" min="1" max="10000" data-f="result_amount"
        data-orig="${it.result.amount}" value="${t.result_amount ?? it.result.amount}"
        title="Выход за крафт (EXBO: ${it.result.amount})"></span>
      ${perk ? `<span class="cadm-perk">${escapeHtml(perkName(perk[0]))} ур.
        <input type="number" min="1" max="10" data-f="perk_level" data-orig="${perk[1]}"
          value="${t.perk_level ?? perk[1]}" title="Требуемый уровень (EXBO: ${perk[1]})"></span>` : ""}
      <span class="cadm-perk">⚡<input type="number" min="0" max="1000000" data-f="energy"
        data-orig="${it.energy ?? ""}" value="${t.energy ?? it.energy ?? ""}"
        title="Энергия крафта (EXBO: ${it.energy})"></span>
      ${it.tuned ? `<span class="cadm-tag" title="Есть правки поверх данных EXBO">ПРАВКА</span>` : ""}
    </div>
    <div class="cadm-ings">${ings}</div>
    <div class="cadm-act">
      <span class="cadm-lbl" title="Есть ли у рецепта в игре шкала «Бонусный крафт»">БОНУС:</span>
      ${bonusBtn(1, "ЕСТЬ", "yes")}${bonusBtn(0, "НЕТ", "no")}${bonusBtn(null, "?", "")}
      <button class="cadm-b cadm-save" data-save hidden>💾 СОХР.</button>
      <span class="cadm-msg"></span>
    </div>
  </div>`;
}

function renderDevCraft() {
  const d = cadmData;
  const q = (page.querySelector("#cadmQ") || {}).value || "";
  const fp = (page.querySelector("#cadmPerk") || {}).value || "";
  const fs = (page.querySelector("#cadmSt") || {}).value || "";
  const items = (d.items || []).filter((it) => {
    if (q && !it.result.name.toLowerCase().includes(q.toLowerCase())) return false;
    const pk = Object.keys(it.perks)[0] || "";
    if (fp && pk !== fp) return false;
    if (fs === "un" && it.bonus != null) return false;
    if (fs === "yes" && it.bonus !== 1) return false;
    if (fs === "no" && it.bonus !== 0) return false;
    if (fs === "tuned" && !it.tuned) return false;
    return true;
  });
  const total = (d.items || []).length;
  const checked = (d.items || []).filter((i) => i.bonus != null).length;
  const perkOpts = Object.entries(d.perk_names || {}).map(([id, nm]) =>
    `<option value="${id}" ${fp === id ? "selected" : ""}>${escapeHtml(nm)}</option>`).join("");
  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · РЕЦЕПТЫ / БОНУСНЫЙ КРАФТ</div>
      <div class="section-note">ПРОВЕРЕНО ${checked} / ${total}</div>
    </div>
    ${devSubnav("craft")}
    <div class="cadm-note">Сверка с игрой. «БОНУС: ЕСТЬ/НЕТ» — есть ли у рецепта шкала бонусного
      крафта (калькулятор учитывает бонус только при «ЕСТЬ», «?» = не проверено). Числа можно
      править, если EXBO расходится с игрой — правка применяется к калькулятору сразу; вернуть
      исходное значение = ввести число как в EXBO (подсказка в наведении).</div>
    <div class="cadm-filters">
      <input id="cadmQ" placeholder="ПОИСК ПО НАЗВАНИЮ…" value="${escapeHtml(q)}" autocomplete="off">
      <select id="cadmPerk"><option value="">ВСЕ НАВЫКИ</option>${perkOpts}</select>
      <select id="cadmSt">
        <option value="">ВСЕ СТАТУСЫ</option>
        <option value="un" ${fs === "un" ? "selected" : ""}>НЕ ПРОВЕРЕНО</option>
        <option value="yes" ${fs === "yes" ? "selected" : ""}>БОНУС ЕСТЬ</option>
        <option value="no" ${fs === "no" ? "selected" : ""}>БОНУСА НЕТ</option>
        <option value="tuned" ${fs === "tuned" ? "selected" : ""}>С ПРАВКАМИ</option>
      </select>
    </div>
    <div class="cadm-list">${items.map(cadmRowHtml).join("")
      || `<div class="empty-sm">НИЧЕГО НЕ НАЙДЕНО.</div>`}</div>
  </div>`;
  $("cadmQ").addEventListener("input", () => renderDevCraftListOnly());
  $("cadmPerk").addEventListener("change", () => renderDevCraftListOnly());
  $("cadmSt").addEventListener("change", () => renderDevCraftListOnly());
  wireDevCraftRows();
}

function renderDevCraftListOnly() {
  // перерисовать только список, не трогая фокус в фильтрах
  const q = $("cadmQ").value, fp = $("cadmPerk").value, fs = $("cadmSt").value;
  const items = (cadmData.items || []).filter((it) => {
    if (q && !it.result.name.toLowerCase().includes(q.toLowerCase())) return false;
    const pk = Object.keys(it.perks)[0] || "";
    if (fp && pk !== fp) return false;
    if (fs === "un" && it.bonus != null) return false;
    if (fs === "yes" && it.bonus !== 1) return false;
    if (fs === "no" && it.bonus !== 0) return false;
    if (fs === "tuned" && !it.tuned) return false;
    return true;
  });
  page.querySelector(".cadm-list").innerHTML =
    items.map(cadmRowHtml).join("") || `<div class="empty-sm">НИЧЕГО НЕ НАЙДЕНО.</div>`;
  wireDevCraftRows();
}

async function cadmSaveRow(row, bonusOverride) {
  const key = row.dataset.key;
  const it = cadmData.items.find((i) => i.key === key);
  const msg = row.querySelector(".cadm-msg");
  const num = (inp) => {
    const v = inp.value.trim();
    return v === "" ? null : +v;
  };
  // поля шлём только если отличаются от EXBO-исходника (равно = снять правку)
  const body = { bonus: bonusOverride !== undefined ? bonusOverride : it.bonus };
  for (const inp of row.querySelectorAll("input[data-f]")) {
    const v = num(inp);
    body[inp.dataset.f] = v != null && String(v) !== inp.dataset.orig ? v : null;
  }
  const ings = {};
  for (const inp of row.querySelectorAll("input[data-ing]")) {
    const v = num(inp);
    if (v != null && String(v) !== inp.dataset.orig) ings[inp.dataset.ing] = v;
  }
  if (Object.keys(ings).length) body.ingredients = ings;
  msg.textContent = "…";
  try {
    const r = await fetch(api(`/admin/craft/recipes/${key}`), {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!r.ok) { msg.textContent = j.detail || "ошибка"; return; }
    it.bonus = j.bonus;
    it.tuned = j.tuned;
    msg.textContent = "✓";
    setTimeout(() => { if (msg.isConnected) msg.textContent = ""; }, 1500);
    row.classList.toggle("checked", it.bonus != null);
    row.querySelectorAll("[data-bonus]").forEach((b) =>
      b.classList.toggle("on", String(it.bonus ?? "") === b.dataset.bonus));
    row.querySelector("[data-save]").hidden = true;
    const noteEl = page.querySelector(".section-note");
    if (noteEl) noteEl.textContent =
      `ПРОВЕРЕНО ${cadmData.items.filter((i) => i.bonus != null).length} / ${cadmData.items.length}`;
  } catch (e) { msg.textContent = "ошибка сети"; }
}

function wireDevCraftRows() {
  page.querySelectorAll(".cadm-row").forEach((row) => {
    row.querySelectorAll("[data-bonus]").forEach((b) =>
      b.addEventListener("click", () =>
        cadmSaveRow(row, b.dataset.bonus === "" ? null : +b.dataset.bonus)));
    row.querySelectorAll("input[type=number]").forEach((inp) =>
      inp.addEventListener("input", () => { row.querySelector("[data-save]").hidden = false; }));
    row.querySelector("[data-save]").addEventListener("click", () => cadmSaveRow(row));
  });
}

// ---------- ДЕВ · редактор квестов (только админ) ----------
async function openDevQuests() {
  if (!devGate()) return;
  const sp = new URLSearchParams(location.search);
  const editId = sp.get("edit");
  if (editId && /^\d+$/.test(editId)) { await renderDevQuestForm(+editId); return; }
  if (sp.get("list")) { await renderDevQuestsList(); return; }
  await renderDevQuestMap();               // карта линеек — основной экран дева
}

// уйти из формы: убить Leaflet формы, автосейв черновика и вернуть масштаб
let qfAutosaveTimer = null;
function qfCleanup() {
  if (qfAutosaveTimer) { clearInterval(qfAutosaveTimer); qfAutosaveTimer = null; }
  if (mapCleanup) { mapCleanup(); mapCleanup = null; }
  document.documentElement.classList.remove("on-map");
}

async function renderDevQuestsList() {
  qfCleanup();
  history.replaceState(null, "", "/dev/quests?list=1");
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
          <div class="gadm-row-t">${q.kind === "main" ? `<span style="color:var(--amber)">★</span> ` : ""}${escapeHtml(q.title)}${q.published ? "" : ` <span class="gadm-hidden" title="Не опубликован — не виден игрокам">скрыт</span>`}</div>
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
    <div class="qadm-nav">
      <button class="gadm-new" id="qadmNew">＋ НОВЫЙ КВЕСТ</button>
      <button class="gadm-btn qadm-addnext" id="qadmMap" title="Расставить блоки и связи мышкой">◱ КАРТА ЛИНЕЕК</button>
    </div>
    <div class="gadm-list">${groups}</div>
  </div>`;
  $("qadmNew").addEventListener("click", () => renderDevQuestForm(null));
  $("qadmMap").addEventListener("click", () => renderDevQuestMap());
  page.querySelectorAll("[data-edit]").forEach((b) =>
    b.addEventListener("click", () => renderDevQuestForm(+b.dataset.edit)));
  page.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm(`Удалить квест «${b.dataset.t}»? Связи на него у других квестов очистятся.`)) return;
      await fetch(api(`/admin/quests/${b.dataset.del}`), { method: "DELETE" }).catch(() => {});
      renderDevQuestsList();
    }));
}

// дев-карта линеек: полноценный редактор графа (двигать блоки, тянуть/удалять связи)
let devQuestMapFaction = localStorage.getItem("sz_qdev_f") || "stalkers";
async function renderDevQuestMap() {
  qfCleanup();
  page.innerHTML = `<div class="mapmod"><div class="spinner">// ЗАГРУЗКА КАРТЫ</div></div>`;
  let d;
  try { d = await fetch(api("/quests")).then((r) => r.json()); }
  catch (e) { page.innerHTML = `<div class="empty">[!] ОШИБКА СЕТИ</div>`; return; }
  if (location.pathname !== "/dev/quests") return;
  questData = d;
  if (!d.is_admin) { page.innerHTML = `<div class="empty">[!] НЕТ ДОСТУПА</div>`; return; }
  if (!d.factions.some((f) => f.id === devQuestMapFaction)) devQuestMapFaction = d.factions[0].id;
  history.replaceState(null, "", "/dev/quests");
  const tabs = d.factions.map((f) => {
    const n = d.items.filter((q) => questInFaction(q, f.id)).length;
    return `<button class="qst-tab${f.id === devQuestMapFaction ? " on" : ""}" data-f="${f.id}"
      style="--fc:${f.color}">${escapeHtml(f.name.toUpperCase())}${n ? ` <span>${n}</span>` : ""}</button>`;
  }).join("");
  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · КВЕСТЫ · КАРТА ЛИНЕЕК</div>
      <div class="section-note">Расставь блоки и связи мышкой — как видят игроки на /quests.</div>
    </div>
    ${devSubnav("quests")}
    <div class="qadm-nav">
      <button type="button" class="gadm-btn qadm-addnext" id="qdmNew">＋ НОВЫЙ КВЕСТ</button>
      <button type="button" class="gadm-btn" id="qdmList">☰ СПИСОК</button>
    </div>
    <div class="qst-tabs">${tabs}</div>
    <div id="qdevmap"></div>
    <div class="map-legend">Тяни блок — двигать (прилипает к сетке), сохраняется для этой линейки.
      Тяни <b style="color:var(--amber)">точку снизу</b> блока на другой блок — связать (тот откроется после).
      <b style="color:var(--green)">＋</b> на блоке — добавить следующий квест. Клик по стрелке — удалить связь.
      Клик по блоку — открыть редактор. Колесо — зум, тяни пустое поле — двигать полотно.</div>
  </div>`;
  page.querySelectorAll(".qst-tab").forEach((b) => b.addEventListener("click", () => {
    devQuestMapFaction = b.dataset.f;
    localStorage.setItem("sz_qdev_f", devQuestMapFaction);
    renderDevQuestMap();
  }));
  $("qdmList").addEventListener("click", () => renderDevQuestsList());
  $("qdmNew").addEventListener("click", () => renderDevQuestForm(null, { faction: devQuestMapFaction }));
  renderQuestGraph($("qdevmap"), devQuestMapFaction, { edit: true });
}

async function renderDevQuestForm(qid, preset) {
  qfCleanup();
  page.innerHTML = `<div class="mapmod"><div class="spinner">// ЗАГРУЗКА</div></div>`;
  let all, q = { id: null, title: "", faction: "stalkers", factions: [], kind: "main",
                 summary: "", reward: "", html: "", parents: [], map_layer: "",
                 map_points: [], pos: {}, sort: 0, published: true };   // сразу виден на /quests
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
  history.replaceState(null, "", qid != null ? `/dev/quests?edit=${qid}` : "/dev/quests");
  const isNew = qid == null;
  // «＋ создать следующий» открывает новый квест, предзаполнив родителя и линейку
  if (isNew && preset) {
    if (preset.faction) q.faction = preset.faction;
    if (preset.parent != null) q.parents = [preset.parent];
  }

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

  // навигация по цепочке: предыдущие (родители) и следующие (дети)
  const parentItems = (q.parents || [])
    .map((pid) => all.items.find((x) => x.id === pid)).filter(Boolean);
  const childItems = qid != null
    ? all.items.filter((x) => (x.parents || []).includes(qid))
        .sort((a, b) => (a.sort - b.sort) || (a.id - b.id)) : [];
  const goBtns = (arr) => arr.map((x) =>
    `<button type="button" class="gadm-btn qadm-go" data-go="${x.id}">${escapeHtml(x.title)}</button>`).join("");
  const navHtml = isNew ? "" : `<div class="qadm-nav">
    ${parentItems.length ? `<span class="qadm-nav-g"><span class="qadm-nav-l">◂ ПРЕДЫДУЩИЙ</span>${goBtns(parentItems)}</span>` : ""}
    ${childItems.length ? `<span class="qadm-nav-g"><span class="qadm-nav-l">СЛЕДУЮЩИЙ ▸</span>${goBtns(childItems)}</span>` : ""}
  </div>`;
  // «также в линейках» — общий/вступительный квест дублируется в выбранных линейках
  const factionsXBox = all.factions.map((f) =>
    `<label class="qadm-p qadm-facx-i" data-fx="${f.id}" style="--fc:${f.color}">
      <input type="checkbox" data-fx="${f.id}"${(f.id === q.faction || (q.factions || []).includes(f.id)) ? " checked" : ""}>
      ${escapeHtml(f.name)}</label>`).join("");

  page.innerHTML = `<div class="mapmod">
    <div class="section-head">
      <div class="section-title">▸ ДЕВ · КВЕСТЫ · ${isNew ? "НОВЫЙ" : `РЕДАКТИРОВАНИЕ #${qid}`}</div>
    </div>
    ${devSubnav("quests")}
    ${navHtml}
    <div class="gform">
      <label class="gform-l">НАЗВАНИЕ КВЕСТА
        <input id="qfTitle" value="${escapeHtml(q.title)}" spellcheck="true" lang="ru" placeholder="Например: Первый выход в Зону"></label>
      <div class="gform-row">
        <label class="gform-l">ТИП <select id="qfKind">
          <option value="main"${q.kind === "main" ? " selected" : ""}>Основной</option>
          <option value="side"${q.kind === "side" ? " selected" : ""}>Побочный</option>
        </select></label>
        <label class="gform-l" title="Ветки на одном уровне сортируются по этому числу (меньше — выше)">
          ПОРЯДОК <input id="qfSort" type="number" value="${q.sort || 0}" style="width:80px"></label>
        <label class="gform-chk"><input id="qfPub" type="checkbox"${q.published ? " checked" : ""}> ОПУБЛИКОВАН</label>
      </div>
      <div class="gform-l">ЛИНЕЙКИ КВЕСТА · отметь, к каким линейкам относится квест (в них он и покажется на схеме)
        <div class="qadm-parents qadm-facx" id="qfFactionsX">${factionsXBox}</div>
      </div>
      <div class="gform-l">ОТКРЫВАЕТСЯ ПОСЛЕ · отметь квесты-предшественники (стрелки на схеме)
        <div class="qadm-parents" id="qfParents">${parentsBox || `<div class="empty-sm">других квестов пока нет — этот будет стартовым</div>`}</div>
      </div>
      <label class="gform-l">КРАТКО · подсказка при наведении на блок схемы (до 400 симв.)
        <textarea id="qfSummary" rows="2" spellcheck="true" lang="ru">${escapeHtml(q.summary)}</textarea></label>
      <label class="gform-l">НАГРАДА · текст (деньги, предметы, репутация)
        <input id="qfReward" value="${escapeHtml(q.reward)}" spellcheck="true" lang="ru" placeholder="15 000 ₽ · Аптечка армейская ×2 · +репутация у барменов"></label>
      <div class="gform-l">ПРОХОЖДЕНИЕ · HTML — выдели текст и жми кнопки форматирования
        <div id="qfBar"></div>
        <textarea id="qfHtml" rows="14" class="gform-html" spellcheck="true" lang="ru">${escapeHtml(q.html)}</textarea>
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
        <button type="button" class="gadm-save qadm-savenext" id="qfSaveNext" title="Сохранить этот квест и сразу создать следующий (откроется после него)">СОХРАНИТЬ И ＋СЛЕДУЮЩИЙ ▸</button>
        <button type="button" class="gadm-btn" id="qfPrevBtn">ОБНОВИТЬ ПРЕДПРОСМОТР ⟳</button>
        <button type="button" class="gadm-btn" id="qfCancel">◂ К КАРТЕ</button>
        <span id="qfMsg" class="gform-msg"></span>
        <span id="qfDraftStat" class="gform-msg qdraft-stat"></span>
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
  $("qfCancel").addEventListener("click", () => renderDevQuestMap());

  // навигация по цепочке (предыдущий/следующий квест из связей)
  page.querySelectorAll(".qadm-go").forEach((b) =>
    b.addEventListener("click", () => renderDevQuestForm(+b.dataset.go)));

  // основная линейка = первая отмеченная (или прежняя, если ещё отмечена); из галок
  const questFactions = () => [...page.querySelectorAll("#qfFactionsX input:checked")].map((c) => c.dataset.fx);
  const primaryFaction = () => { const ch = questFactions(); return ch.includes(q.faction) ? q.faction : ch[0]; };

  $("qfUpload").addEventListener("click", async () => {
    const f = $("qfImg").files[0], msg = $("qfUpMsg");
    if (!f) { msg.textContent = "выбери файл"; return; }
    msg.textContent = "сжатие и загрузка…";
    try {
      const url = await uploadEditorImage(f);          // общий загрузчик картинок
      insertAtCursor($("qfHtml"), `\n<img src="${url}" alt="">\n`);
      msg.innerHTML = `готово, вставлено в текст: <b>${escapeHtml(url)}</b>`;
      renderPrev();
    } catch (e) { msg.textContent = e.message || "ошибка сети"; }
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
    qem = makeTileMap(lm, layerView(lm), "qfMap");
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

  // --- автосейв черновика в localStorage (защита от обрыва сети/вылета) ---
  // при пропаже инета серверный сейв не доедет, поэтому пишем локально каждые
  // 20 с (+ дебаунс на ввод) и предлагаем восстановить при следующем открытии.
  const DRAFT_KEY = `sz_qdraft_${qid == null ? "new" : qid}`;
  const collectDraft = () => ({
    v: 1, ts: Date.now(),
    title: $("qfTitle").value, kind: $("qfKind").value,
    factions: questFactions(),
    sort: $("qfSort").value, published: $("qfPub").checked,
    parents: [...page.querySelectorAll("#qfParents input:checked")].map((c) => +c.dataset.pid),
    summary: $("qfSummary").value, reward: $("qfReward").value, html: $("qfHtml").value,
    map_layer: $("qfLayer").value, map_points: pts.map((p) => [p[0], p[1], p[2] || ""]),
  });
  const draftIsEmpty = (d) => !((d.title || "").trim() || (d.summary || "").trim()
    || (d.reward || "").trim() || (d.html || "").trim() || (d.map_points || []).length);
  const clearDraft = () => { try { localStorage.removeItem(DRAFT_KEY); } catch (e) {} };
  let restorePending = false;   // пока висит баннер — не перетираем найденный черновик
  const saveDraft = () => {
    if (!document.getElementById("qfHtml")) {          // форма закрыта — самоочистка
      if (qfAutosaveTimer) { clearInterval(qfAutosaveTimer); qfAutosaveTimer = null; }
      return;
    }
    if (restorePending) return;
    try {
      const d = collectDraft();
      if (draftIsEmpty(d)) { clearDraft(); return; }
      localStorage.setItem(DRAFT_KEY, JSON.stringify(d));
      const st = $("qfDraftStat");
      if (st) st.textContent = `● черновик сохранён ${new Date(d.ts)
        .toLocaleTimeString("ru-RU").slice(0, 5)}`;
    } catch (e) { /* квота/приватный режим — тихо игнорим */ }
  };
  qfAutosaveTimer = setInterval(saveDraft, 20000);
  let draftDebounce = null;
  const kickDraft = () => { clearTimeout(draftDebounce); draftDebounce = setTimeout(saveDraft, 2000); };
  ["qfTitle", "qfSummary", "qfReward", "qfHtml", "qfSort"].forEach((id) =>
    $(id).addEventListener("input", kickDraft));

  // применить черновик к форме (текст + чекбоксы + слой и точки карты)
  const applyDraft = (d) => {
    $("qfTitle").value = d.title || "";
    $("qfKind").value = d.kind || "main";
    $("qfSort").value = d.sort || 0;
    $("qfPub").checked = !!d.published;
    $("qfSummary").value = d.summary || "";
    $("qfReward").value = d.reward || "";
    $("qfHtml").value = d.html || "";
    page.querySelectorAll("#qfParents input").forEach((c) => {
      c.checked = (d.parents || []).includes(+c.dataset.pid);
    });
    page.querySelectorAll("#qfFactionsX input").forEach((c) => {
      c.checked = (d.factions || []).includes(c.dataset.fx);
    });
    pts.length = 0;
    (d.map_points || []).forEach((p) => pts.push([p[0], p[1], p[2] || ""]));
    $("qfLayer").value = d.map_layer || "";
    syncMapBlock();
    renderPrev();
  };

  // если при открытии нашёлся черновик, отличный от загруженного, — предложить
  let existingDraft = null;
  try { existingDraft = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null"); } catch (e) {}
  if (existingDraft && !draftIsEmpty(existingDraft)
      && (existingDraft.html !== $("qfHtml").value || existingDraft.title !== $("qfTitle").value)) {
    const gform = page.querySelector(".gform");
    const bar = document.createElement("div");
    bar.className = "qdraft-bar";
    const when = new Date(existingDraft.ts).toLocaleString("ru-RU");
    bar.innerHTML = `<span>Найден несохранённый черновик от <b>${escapeHtml(when)}</b> —
        похоже, прошлый раз не сохранился. Восстановить?</span>
      <span class="qdraft-actions">
        <button type="button" class="gadm-save" id="qdRestore">ВОССТАНОВИТЬ</button>
        <button type="button" class="gadm-btn" id="qdDismiss">ОТКЛОНИТЬ</button>
      </span>`;
    gform.insertBefore(bar, gform.firstChild);
    restorePending = true;        // до решения не даём автосейву затереть черновик
    $("qdRestore").addEventListener("click", () => {
      applyDraft(existingDraft); restorePending = false; bar.remove(); saveDraft();
    });
    $("qdDismiss").addEventListener("click", () => {
      clearDraft(); restorePending = false; bar.remove();
    });
  }

  // --- сохранение ---
  // сохранить квест на сервер; вернуть сохранённый объект или null (ошибку показывает)
  const saveQuest = async () => {
    const msg = $("qfMsg");
    if (!$("qfTitle").value.trim()) { msg.textContent = "нужно название"; return null; }
    const primary = primaryFaction();
    if (!primary) { msg.textContent = "отметь хотя бы одну линейку"; return null; }
    const parents = [...page.querySelectorAll("#qfParents input:checked")]
      .map((c) => +c.dataset.pid);
    const layer = $("qfLayer").value;
    const factions = questFactions().filter((fx) => fx !== primary);
    const body = {
      id: qid, title: $("qfTitle").value.trim(),
      faction: primary, factions, kind: $("qfKind").value,
      summary: $("qfSummary").value.trim(), reward: $("qfReward").value.trim(),
      html: $("qfHtml").value, parents,
      map_layer: layer, map_points: layer ? pts : [],
      sort: +$("qfSort").value || 0, published: $("qfPub").checked,
    };
    $("qfSave").disabled = true; $("qfSaveNext").disabled = true;
    msg.textContent = "сохранение…";
    try {
      const r = await fetch(api("/admin/quests"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (!r.ok) {
        msg.textContent = j.detail || "ошибка сохранения";
        $("qfSave").disabled = false; $("qfSaveNext").disabled = false;
        return null;
      }
      clearDraft();                 // сохранилось на сервере — черновик больше не нужен
      return j;
    } catch (e) {
      msg.textContent = "ошибка сети";
      $("qfSave").disabled = false; $("qfSaveNext").disabled = false;
      return null;
    }
  };
  $("qfSave").addEventListener("click", async () => {
    if (await saveQuest()) renderDevQuestMap();
  });
  // сохранить текущий и сразу открыть новый квест, открывающийся после него
  $("qfSaveNext").addEventListener("click", async () => {
    const s = await saveQuest();
    if (s) renderDevQuestForm(null, { parent: s.id, faction: s.faction });
  });
}

function initEditorMap() {
  const lm = mapMeta[ed.layer];
  const { map, px, toPx } = makeTileMap(lm, layerView(lm));
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
  const cats = MAP_CATS.map((c, i) =>
    `<button class="mp-cat ${ed.cat === c.id ? "on" : ""}" data-cat="${c.id}"
       title="${i < 9 ? `[${i + 1}] ` : ""}${escapeHtml(c.name)}" style="--mo:${c.color}"><span>${c.emoji}</span></button>`).join("");
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
    </div>` : ""}
    <div class="mp-group" id="mpBulk"></div>`;
  renderBulk();
}

// ---------- массовые операции над черновиками (разбор импорта) ----------
// Слои-фильтры: категория (метки) или имя (области). Опубликованное не трогаем.
function renderBulk() {
  const box = $("mpBulk");
  if (!box) return;
  const drafts = ed.objects.filter((o) => !o.published);
  if (!drafts.length) { box.innerHTML = ""; return; }
  const byCat = {};
  const byName = {};
  drafts.forEach((o) => {
    if (o.kind === "marker") byCat[o.category] = (byCat[o.category] || 0) + 1;
    else if (o.name) byName[o.name] = (byName[o.name] || 0) + 1;
  });
  const opts = [`<option value="">— все черновики (${drafts.length}) —</option>`]
    .concat(MAP_CATS.filter((c) => byCat[c.id]).map((c) =>
      `<option value="cat:${c.id}">${c.emoji} ${escapeHtml(c.name)} (${byCat[c.id]})</option>`))
    .concat(Object.keys(byName).sort().map((n) =>
      `<option value="name:${escapeHtml(n)}">▱ ${escapeHtml(n)} (${byName[n]})</option>`));
  box.innerHTML = `<span class="mp-lbl">ЧЕРНОВИКИ</span>
    <select class="mp-terr" id="mpBulkSel">${opts.join("")}</select>
    <button class="mp-tool" id="mpBulkPub">ОПУБЛИКОВАТЬ</button>
    <button class="mp-tool" id="mpBulkDel">УДАЛИТЬ</button>`;
  const pick = () => {
    const v = $("mpBulkSel").value;
    const body = { layer: ed.layer };
    let label = "все черновики слоя";
    let n = drafts.length;
    if (v.startsWith("cat:")) {
      body.category = v.slice(4);
      n = byCat[body.category];
      label = `черновики «${catById(body.category).name}»`;
    } else if (v.startsWith("name:")) {
      body.name = v.slice(5);
      n = byName[body.name];
      label = `черновики «${body.name}»`;
    }
    return { body, label, n };
  };
  const run = async (action, verb) => {
    const { body, label, n } = pick();
    if (!n) return;
    if (!confirm(`${verb} ${n} шт. — ${label}?` +
                 (action === "delete" ? " Это необратимо." : ""))) return;
    try {
      const r = await apiJson("/map/objects/bulk", "POST", { action, ...body });
      selectObject(null);
      await loadEditorObjects();
      flashHint(`✓ ${verb.toLowerCase()}: ${r.changed}`);
    } catch (e) { alert("Не получилось: " + e.message); }
  };
  $("mpBulkPub").addEventListener("click", () => run("publish", "Опубликовать"));
  $("mpBulkDel").addEventListener("click", () => run("delete", "Удалить"));
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
    txt = `Клик по карте — поставить метку «${catById(ed.cat).name}». Имя — сразу в панели,
      Enter — сохранить и ставить дальше. Esc — курсор.`;
  } else if (ed.mode === "area" || ed.mode === "line") {
    txt = `Клик — вершина. Двойной клик, Enter или «ГОТОВО» — завершить (нужно ≥${need}).
      Esc — отмена. Точек: ${ed.draftPts.length}.`;
  } else {
    txt = `Клик по объекту — редактировать. Тяни метку или вершины — переместить.
      Хоткеи: 1–9 — метка нужной категории, Del — удалить выбранное.`;
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
    // серийная расстановка: сразу вводить имя, Enter в поле сохранит и закроет
    const nm = $("pfName");
    if (nm && payload.kind === "marker") nm.focus();
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

// ---------- хоткеи редактора: серийная расстановка без тулбара ----------
// 1–9 — метка категории (порядок тулбара), Esc — отмена/курсор, Enter —
// завершить область/линию, Del — удалить выбранное. В полях ввода Enter на
// «Названии» сохраняет объект и закрывает панель — серия кликов не прерывается.
document.addEventListener("keydown", (e) => {
  if (!document.getElementById("mapedBar")) return;          // редактор закрыт
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) {
    if (e.key === "Enter" && t.id === "pfName" && ed.selected != null) {
      e.preventDefault();
      const o = ed.byId(ed.selected);
      if (o) savePanel(o).then(() => selectObject(null));
    } else if (e.key === "Escape") t.blur();
    return;
  }
  if (e.key >= "1" && e.key <= "9") {
    const c = MAP_CATS[+e.key - 1];
    if (c) { ed.cat = c.id; setMode("marker"); }
  } else if (e.key === "Escape") {
    if (ed.draftPts.length) { clearDraft(); updateHint(); }
    else if (ed.selected != null) selectObject(null);
    else setMode("view");
  } else if (e.key === "Enter" && (ed.mode === "area" || ed.mode === "line") && ed.draftPts.length) {
    finishDraft();
  } else if (e.key === "Delete" && ed.mode === "view" && ed.selected != null) {
    const o = ed.byId(ed.selected);
    if (o) deleteObject(o);
  }
});

function updateStatus() {
  renderBulk();                     // счётчики черновиков в массовых операциях
  const total = ed.objects.length;
  const drafts = ed.objects.filter((o) => !o.published).length;
  const n = (k) => ed.objects.filter((o) => o.kind === k).length;
  ed.el.status.innerHTML = `Слой: <b>${ed.layer === "detail" ? "детальная" : "глобальная"}</b> ·
    объектов: <b>${total}</b> (метки ${n("marker")}, области ${n("area")}, линии ${n("line")}) ·
    черновиков: <b>${drafts}</b>. Черновики видны только тебе (пунктир/полупрозрачные),
    опубликованные — всем на <a href="/map">/map</a>.`;
}

// ---------- Операции (PvE-режим): мета снаряжения + лента забегов ----------
const opsTierColor = (t) => t === 2 ? "var(--red)" : t === 1 ? "var(--amber)" : "var(--green)";
const opsTierName = (t) => ({ low: "НИЗКИЙ", mid: "СРЕДНИЙ", high: "ВЫСОКИЙ" }[t.key] || t.label);
// класс брони из API (combat/scientist/combined) → русское название
const OPS_CLASS_RU = { combat: "БОЕВАЯ", scientist: "НАУЧНАЯ", combined: "КОМБИНИРОВАННАЯ" };
const opsClassName = (k) => OPS_CLASS_RU[k] || (k ? String(k).toUpperCase() : "—");
// карты операций (ключ API → название)
const OPS_MAP_RU = { big_cleanup: "Большая уборка", sea_alienation: "Море отчуждения",
                     shock_therapy: "Шоковая терапия" };
const opsMapName = (m) => (m
  ? (OPS_MAP_RU[m] || String(m).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()))
  : "—");
// подпись меты-недели: «НЕДЕЛЯ С 22.07 · СБРОС СР»
const OPS_DOW_RU = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"];
function opsWeekLabel(week) {
  if (!week) return "МЕТА ЗА НЕДЕЛЮ";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(week.start || "");
  const dd = m ? ` С ${m[3]}.${m[2]}` : "";
  const dow = OPS_DOW_RU[week.reset_dow] != null ? OPS_DOW_RU[week.reset_dow] : "СР";
  return `НЕДЕЛЯ${dd} · СБРОС ${dow}`;
}

// время прохождения: секунды → «M:СС» (или «Ч М» на длинных забегах)
function fmtDur(sec) {
  if (sec == null) return "—";
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h} Ч ${String(m).padStart(2, "0")} М` : `${m}:${String(s).padStart(2, "0")}`;
}

// плитка снаряжения: иконка + имя (цвет по редкости) + заточка.
// кликабельна — ведёт на карточку предмета (/item/{id}); нераспознанный id
// (скрытый предмет не из базы) — плейсхолдер без ссылки и битой иконки
function opsGear(g, lvl) {
  if (!g) return `<span class="ops-gear ops-gear-empty">—</span>`;
  const ptn = lvl ? `<span class="ops-lvl">+${lvl}</span>` : "";
  const icon = g.icon
    ? `<img loading="lazy" src="${asset(g.icon)}" alt="">`
    : `<span class="ops-gear-ph" aria-hidden="true"></span>`;
  if (g.unknown)
    return `<span class="ops-gear ops-gear-unknown" title="Предмета нет в базе игры: ${escapeHtml(g.id)}">
      ${icon}<span class="nm">неизв. предмет</span>${ptn}</span>`;
  return `<a class="ops-gear" href="/item/${encodeURIComponent(g.id)}"
      title="${escapeHtml(g.name)}${lvl ? " +" + lvl : ""} — открыть карточку">
    ${icon}<span class="nm" style="color:${rank(g.color).color}">${escapeHtml(g.name)}</span>${ptn}</a>`;
}

// ===== модуль на главной: мета по классам брони (все классы стопкой) =====
function opsDashNote(ov) {
  if (!ov || !ov.classes || !ov.classes.length) return "СНАРЯЖЕНИЕ ПО КЛАССАМ · В РОТАЦИИ";
  return `${ov.tier ? `ЭТАП ${ov.tier.label}` : "ВСЕ ЭТАПЫ"} · ${opsWeekLabel(ov.week)}`;
}

function opsDashBody(ov) {
  if (!ov || !ov.classes || !ov.classes.length)
    return `<div class="empty-sm">НАКАПЛИВАЕМ ЗАБЕГИ ОПЕРАЦИЙ — МЕТА ПОЯВИТСЯ, КАК СОБЕРЁТСЯ ВЫБОРКА.</div>`;
  // все классы брони — стопкой (места на карточке хватает, ротация не нужна)
  const panels = ov.classes.map((c) => {
    const a = (c.armors || [])[0];
    const weaps = (c.weapons || []).slice(0, 2).map((w) => opsGear(w.gear, w.avg_lvl)).join("");
    return `<div class="odp">
      <div class="odp-cls"><span class="odp-cls-n">${escapeHtml(opsClassName(c.armor_class))}</span>
        <span class="odp-cls-s">${c.sessions} ЗАБ.</span></div>
      <div class="odp-row"><span class="odp-k">БРОНЯ</span>${a ? opsGear(a.gear, a.avg_lvl) : "—"}</div>
      <div class="odp-row"><span class="odp-k">ОРУЖИЕ</span><span class="odp-weaps">${weaps || "—"}</span></div>
    </div>`;
  }).join("");
  return `<div class="ops-dash">${panels}</div>`;
}

// ===== страница /operations =====
const opsState = { tier: "high", map: "", offset: 0, total: 0, user: "" };

async function openOperations() {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = `<div class="spinner">// ЗАГРУЗКА ОПЕРАЦИЙ</div>`;
  window.scrollTo(0, 0);
  opsState.tier = "high"; opsState.map = ""; opsState.user = "";
  const [meta, feed] = await opsFetch();
  if (location.pathname !== "/operations") return;
  opsRenderShell(meta, feed);
}

function opsFetch() {
  return Promise.all([
    fetch(api(`/operations/meta?tier=${opsState.tier}`)).then((r) => r.json()).catch(() => null),
    fetch(api(`/operations/sessions?tier=${opsState.tier}`
      + `${opsState.map ? "&map=" + encodeURIComponent(opsState.map) : ""}&limit=30`))
      .then((r) => r.json()).catch(() => null),
  ]);
}

function opsRenderShell(meta, feed) {
  const tiers = (meta && meta.tiers) || (feed && feed.tiers) || [];
  const tabs = [`<button class="ops-tab" data-tier="all">ВСЕ</button>`]
    .concat(tiers.map((t) => `<button class="ops-tab" data-tier="${t.key}">${opsTierName(t)}`
      + `${t.sessions != null ? `<span class="ops-tab-n">${t.sessions}</span>` : ""}</button>`)).join("");
  const maps = (feed && feed.maps) || [];
  const mapOpts = [`<option value="">ВСЕ КАРТЫ</option>`]
    .concat(maps.map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(opsMapName(m))}</option>`)).join("");
  page.innerHTML = `<div class="ops">
    <div class="section-head">
      <div class="section-title">▸ ОПЕРАЦИИ · МЕТА И СТАТИСТИКА ЗАБЕГОВ</div>
      <div class="section-note" id="opsNote"></div>
    </div>
    <div class="ops-intro">С каким снаряжением и на каком этапе сложности операции проходят
      быстрее всего — по завершённым забегам игроков (регион RU).</div>
    <div class="ops-tabs" id="opsTabs">${tabs}</div>
    <div id="opsMeta"></div>
    <div class="section-head ops-feed-head">
      <div class="section-title">▸ ЛЕНТА ЗАБЕГОВ</div>
      <div class="ops-filters">
        <input id="opsUser" class="ops-user" type="search" autocomplete="off" placeholder="ПОИСК ПО НИКУ…">
        <select id="opsMap" class="ops-map">${mapOpts}</select>
      </div>
    </div>
    <div id="opsFeed"></div>
    <button id="opsMore" class="bt-more hidden">ПОКАЗАТЬ ЕЩЁ</button>
  </div>`;
  opsRenderMeta(meta);
  opsRenderFeed(feed, true);
  opsSyncTabs();
  $("opsTabs").querySelectorAll(".ops-tab").forEach((b) => b.addEventListener("click", async () => {
    opsState.tier = b.dataset.tier; opsState.user = "";
    const u = $("opsUser"); if (u) u.value = "";
    opsSyncTabs();
    const [meta2, feed2] = await opsFetch();
    if (location.pathname !== "/operations") return;
    opsRenderMeta(meta2); opsRenderFeed(feed2, true);
  }));
  $("opsMap").addEventListener("change", (e) => { opsState.map = e.target.value; opsFeedReload(); });
  let ut = null;
  $("opsUser").addEventListener("input", (e) => {
    clearTimeout(ut); const q = e.target.value.trim();
    ut = setTimeout(() => { opsState.user = q; opsFeedReload(); }, 350);
  });
  $("opsMore").addEventListener("click", opsMore);
}

function opsSyncTabs() {
  const tabs = document.getElementById("opsTabs");
  if (tabs) tabs.querySelectorAll(".ops-tab").forEach((b) =>
    b.classList.toggle("on", b.dataset.tier === opsState.tier));
}

function opsCurTierLabel(meta) {
  if (opsState.tier === "all") return "";
  const t = ((meta && meta.tiers) || []).find((x) => x.key === opsState.tier);
  return t ? `${opsTierName(t)} (${t.label})` : "";
}

function opsRenderMeta(meta) {
  const box = document.getElementById("opsMeta");
  const note = document.getElementById("opsNote");
  if (!box) return;
  if (!meta) { box.innerHTML = `<div class="empty-sm">МЕТА ВРЕМЕННО НЕДОСТУПНА.</div>`; return; }
  if (note) note.textContent = `МЕТА ЗА ${opsWeekLabel(meta.week)} · МИН. ВЫБОРКА КОМБО ${meta.min_sample} ЗАБ.`;
  const tierLabel = opsCurTierLabel(meta);
  const fast = meta.fastest || [];
  const fastRows = fast.length ? fast.map((c, i) => `
    <div class="ops-combo">
      <span class="ops-combo-r">${i + 1}</span>
      <div class="ops-combo-g">${opsGear(c.armor, c.armor_lvl)}<span class="ops-plus">+</span>${opsGear(c.weapon, c.prim_lvl)}</div>
      <span class="ops-combo-t" title="СРЕДНЕЕ ВРЕМЯ ПРОХОЖДЕНИЯ">⏱ ${fmtDur(c.avg_dur)}</span>
      <span class="ops-combo-u">${c.uses} ЗАБ.</span>
    </div>`).join("")
    : `<div class="empty-sm">НА ЭТОМ ЭТАПЕ ПОКА МАЛО ЗАБЕГОВ ДЛЯ РЕЙТИНГА СЕТАПОВ.</div>`;
  const cls = meta.classes || [];
  const clsCards = cls.length ? cls.map((c) => {
    const a = (c.armors || [])[0];
    const weaps = (c.weapons || []).slice(0, 3).map((w) =>
      `<div class="ops-cc-row">${opsGear(w.gear, w.avg_lvl)}<span class="ops-cc-u">${w.uses}</span></div>`).join("");
    return `<div class="ops-cc">
      <div class="ops-cc-h"><span class="ops-cc-n">${escapeHtml(opsClassName(c.armor_class))}</span>
        <span class="ops-cc-s">${c.sessions} ЗАБ.</span></div>
      <div class="ops-cc-k">БРОНЯ</div>
      <div class="ops-cc-row">${a ? opsGear(a.gear, a.avg_lvl) : "—"}${a ? `<span class="ops-cc-u">${a.uses}</span>` : ""}</div>
      <div class="ops-cc-k">ОРУЖИЕ</div>
      ${weaps || `<div class="ops-cc-row">—</div>`}
    </div>`;
  }).join("")
    : `<div class="empty-sm">КЛАССЫ БРОНИ НАБИРАЮТ ВЫБОРКУ.</div>`;
  box.innerHTML = `
    <div class="ops-meta-block">
      <div class="ops-sub">САМЫЕ БЫСТРЫЕ СЕТАПЫ${tierLabel ? ` · ЭТАП ${tierLabel}` : ""}</div>
      <div class="ops-combos">${fastRows}</div>
    </div>
    <div class="ops-meta-block">
      <div class="ops-sub">МЕТА ПО КЛАССАМ БРОНИ</div>
      <div class="ops-cc-grid">${clsCards}</div>
    </div>`;
}

function opsSessionCard(s) {
  const col = opsTierColor(s.tier);
  // ник сверху (+ K/D справа), снаряжение стопкой под ником — кликабельно
  const parts = (s.parts || []).map((p) => {
    const stats = [
      p.mob_kills != null ? `☠ ${p.mob_kills}` : "",
      p.deaths != null ? `💀 ${p.deaths}` : "",
    ].filter(Boolean).join(" · ");
    // только броня + основное оружие (второе — пистолет — не показываем)
    const gear = [
      opsGear(p.armor, p.armor_level),
      opsGear(p.primary, p.prim_level),
    ].filter(Boolean).join("");
    return `<div class="ops-part">
      <div class="ops-part-top">
        <span class="ops-part-u">${escapeHtml(p.username || "—")}</span>
        ${stats ? `<span class="ops-part-s">${stats}</span>` : ""}
      </div>
      <div class="ops-part-gear">${gear}</div>
    </div>`;
  }).join("");
  return `<div class="ops-sess">
    <div class="ops-sess-h">
      <span class="ops-diff" style="color:${col};border-color:${col}">СЛ ${s.difficulty}</span>
      <span class="ops-map">${escapeHtml(opsMapName(s.map))}</span>
      <span class="ops-dur" title="ВРЕМЯ ПРОХОЖДЕНИЯ">⏱ ${fmtDur(s.duration)}</span>
      ${s.reward != null ? `<span class="ops-rew" title="НАГРАДА ЗА СЛОЖНОСТЬ">🏅 ${fmt(s.reward)}</span>` : ""}
      <span class="ops-when">${s.end_time ? fmtMsk(s.end_time) : ""}</span>
    </div>
    <div class="ops-parts">${parts}</div>
  </div>`;
}

async function opsFeedReload() {
  const box = document.getElementById("opsFeed");
  if (box) box.innerHTML = `<div class="spinner-sm">// ЗАГРУЗКА</div>`;
  let feed;
  if (opsState.user) {
    const d = await fetch(api(`/operations/player/${encodeURIComponent(opsState.user)}`))
      .then((r) => r.json()).catch(() => null);
    feed = d ? { items: d.items, total: d.count, player: opsState.user } : null;
  } else {
    feed = await fetch(api(`/operations/sessions?tier=${opsState.tier}`
      + `${opsState.map ? "&map=" + encodeURIComponent(opsState.map) : ""}&limit=30`))
      .then((r) => r.json()).catch(() => null);
  }
  if (location.pathname !== "/operations") return;
  opsRenderFeed(feed, true);
}

function opsRenderFeed(feed, reset) {
  const box = document.getElementById("opsFeed");
  if (!box) return;
  const items = (feed && feed.items) || [];
  if (reset) { box.innerHTML = ""; opsState.offset = 0; opsState.total = feed ? (feed.total || items.length) : 0; }
  const more = document.getElementById("opsMore");
  if (!items.length && reset) {
    box.innerHTML = feed && feed.player
      ? `<div class="empty-sm">У ИГРОКА «${escapeHtml(feed.player)}» ЗАБЕГОВ НЕ НАЙДЕНО (ИЛИ ЕЩЁ НЕ ПОПАЛИ В ВЫБОРКУ).</div>`
      : `<div class="empty-sm">ЗАБЕГИ ЕЩЁ НАКАПЛИВАЮТСЯ. ДАННЫЕ ИДУТ ПО ЗАВЕРШЁННЫМ СЕССИЯМ ОПЕРАЦИЙ — ЗАГЛЯНИ ПОЗЖЕ.</div>`;
    if (more) more.classList.add("hidden");
    return;
  }
  box.insertAdjacentHTML("beforeend", items.map(opsSessionCard).join(""));
  opsState.offset += items.length;
  if (more) more.classList.toggle("hidden", !!opsState.user || opsState.offset >= opsState.total);
}

async function opsMore() {
  const feed = await fetch(api(`/operations/sessions?tier=${opsState.tier}`
    + `${opsState.map ? "&map=" + encodeURIComponent(opsState.map) : ""}&limit=30&offset=${opsState.offset}`))
    .then((r) => r.json()).catch(() => null);
  if (location.pathname !== "/operations") return;
  opsRenderFeed(feed, false);
}

// ---------- База предметов: каталог всех предметов ----------
const IDB_CATS = [
  { key: "", label: "ВСЕ" }, { key: "weapon", label: "ОРУЖИЕ" },
  { key: "armor", label: "БРОНЯ" }, { key: "container", label: "КОНТЕЙНЕРЫ" },
  { key: "artefact", label: "АРТЕФАКТЫ" }, { key: "attachment", label: "ОБВЕСЫ" },
  { key: "bullet", label: "ПАТРОНЫ" }, { key: "medicine", label: "МЕДИЦИНА" },
  { key: "grenade", label: "ГРАНАТЫ" }, { key: "misc", label: "ПРОЧЕЕ" },
];
const IDB_CAT_RU = {
  weapon: "Оружие", armor: "Броня", containers: "Контейнер", backpacks: "Рюкзак",
  artefact: "Артефакт", attachment: "Обвес", weapon_modules: "Модуль",
  bullet: "Патроны", medicine: "Медицина", grenade: "Граната", supply: "Припасы",
  device: "Устройство", misc: "Прочее", other: "Прочее",
};
const idbState = { cat: "", q: "", offset: 0, total: 0, byId: {} };

async function openItemDb() {
  home.classList.add("hidden"); detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  window.scrollTo(0, 0);
  const sp = new URLSearchParams(location.search);
  idbState.cat = sp.get("cat") || "";
  idbState.q = sp.get("q") || "";
  idbState.offset = 0;
  const chips = IDB_CATS.map((c) =>
    `<button class="idb-chip" data-cat="${c.key}">${c.label}</button>`).join("");
  page.innerHTML = `<div class="idb">
    <div class="section-head">
      <div class="section-title">▸ БАЗА ПРЕДМЕТОВ</div>
      <div class="section-note" id="idbNote"></div>
      <a class="idb-cmp-link" href="/compare">⇄ СРАВНЕНИЕ</a>
    </div>
    <div class="idb-search"><span class="idb-prompt">&gt;_</span>
      <input id="idbInput" type="search" autocomplete="off" placeholder="ПОИСК ПРЕДМЕТА…" value="${escapeHtml(idbState.q)}"></div>
    <div class="idb-chips" id="idbChips">${chips}</div>
    <div id="idbGrid" class="idb-grid"></div>
    <button id="idbMore" class="bt-more hidden">ПОКАЗАТЬ ЕЩЁ</button>
  </div>`;
  idbSyncChips();
  $("idbChips").querySelectorAll(".idb-chip").forEach((b) => b.addEventListener("click", () => {
    idbState.cat = b.dataset.cat; idbSyncChips(); idbReload();
  }));
  let t = null;
  $("idbInput").addEventListener("input", (e) => {
    clearTimeout(t); const q = e.target.value.trim();
    t = setTimeout(() => { idbState.q = q; idbReload(); }, 300);
  });
  $("idbMore").addEventListener("click", idbMore);
  idbReload();
}

function idbSyncChips() {
  const box = document.getElementById("idbChips");
  if (box) box.querySelectorAll(".idb-chip").forEach((b) =>
    b.classList.toggle("on", b.dataset.cat === idbState.cat));
}

function idbUrl() {
  return api(`/items?cat=${encodeURIComponent(idbState.cat)}`
    + `&q=${encodeURIComponent(idbState.q)}&limit=60&offset=${idbState.offset}`);
}

async function idbReload() {
  idbState.offset = 0;
  const grid = $("idbGrid");
  if (grid) grid.innerHTML = `<div class="spinner-sm">// ЗАГРУЗКА</div>`;
  const d = await fetch(idbUrl()).then((r) => r.json()).catch(() => null);
  if (location.pathname !== "/items") return;
  if (grid) grid.innerHTML = "";
  idbRender(d, true);
}

async function idbMore() {
  const d = await fetch(idbUrl()).then((r) => r.json()).catch(() => null);
  if (location.pathname !== "/items") return;
  idbRender(d, false);
}

function idbCard(it) {
  const rk = rank(it.color);
  // ⇄ — добавить к сравнению, не уходя из каталога (только там, где есть статы)
  const cmp = CMP_CATS.has(it.category)
    ? `<button class="idb-cmp" data-cmp-id="${escapeHtml(it.id)}" title="Добавить к сравнению">⇄</button>`
    : "";
  return `<div class="idb-cell" style="--rar:${rk.color}">
    <a class="idb-card" href="/item/${encodeURIComponent(it.id)}">
      <div class="idb-ic"><img loading="lazy" src="${asset(it.icon)}" alt=""></div>
      <div class="idb-nm" style="color:${rk.color}">${escapeHtml(it.name)}</div>
      <div class="idb-cat">${escapeHtml(IDB_CAT_RU[it.category] || it.category || "")}</div>
    </a>${cmp}
  </div>`;
}

function idbRender(d, reset) {
  const grid = $("idbGrid");
  if (!grid || !d) return;
  const items = d.items || [];
  if (reset) idbState.total = d.total || 0;
  const more = $("idbMore");
  if (!items.length && reset) {
    grid.innerHTML = `<div class="empty-sm">НИЧЕГО НЕ НАЙДЕНО.</div>`;
    if (more) more.classList.add("hidden");
    const note = $("idbNote"); if (note) note.textContent = "";
    return;
  }
  grid.insertAdjacentHTML("beforeend", items.map(idbCard).join(""));
  items.forEach((it) => { idbState.byId[it.id] = it; });
  grid.querySelectorAll(".idb-cmp[data-cmp-id]").forEach((b) => {
    if (b.dataset.wired) return;
    b.dataset.wired = "1";
    b.addEventListener("click", (e) => {
      e.preventDefault();
      const it = idbState.byId[b.dataset.cmpId];
      if (it && !cmpToggle(it)) authNotice(`В СРАВНЕНИИ УЖЕ ${CMP_MAX} ПРЕДМЕТА — УБЕРИТЕ ЛИШНЕЕ`, "err");
    });
  });
  syncCmpButtons();
  idbState.offset += items.length;
  const note = $("idbNote");
  if (note) note.textContent = `${idbState.total} ПРЕДМЕТОВ${idbState.q ? ` · «${idbState.q}»` : ""}`;
  if (more) more.classList.toggle("hidden", idbState.offset >= idbState.total);
}

// ---------- сравнение снаряжения ----------
// Набор живёт в localStorage объектами {id,name,icon,color} — панель внизу рисует
// иконки без похода на бэк. Адрес /compare?ids=…&ptn=… — шарится ссылкой.
const CMP_MAX = 4;
const CMP_KEY = "sz_cmp";
// у остальных категорий нет тултип-статов — сравнивать нечего
const CMP_CATS = new Set(["weapon", "armor", "attachment", "weapon_modules",
                          "containers", "backpacks", "artefact"]);
const CMP_PICK_CATS = [
  { key: "gear", label: "ВСЁ СНАРЯЖЕНИЕ" }, { key: "weapon", label: "ОРУЖИЕ" },
  { key: "armor", label: "БРОНЯ" }, { key: "attachment", label: "ОБВЕСЫ" },
  { key: "container", label: "КОНТЕЙНЕРЫ" }, { key: "artefact", label: "АРТЕФАКТЫ" },
];
const cmpState = { ptn: 0, data: null, cat: "gear", q: "", picks: null };
// уровень заточки помним между заходами: сравнивают обычно на своём уровне
const cmpPtnSaved = () => {
  try { return Math.max(0, Math.min(15, +localStorage.getItem("sz_cmp_ptn") || 0)); }
  catch (e) { return 0; }
};

function cmpList() {
  try {
    const raw = JSON.parse(localStorage.getItem(CMP_KEY)) || [];
    return raw.filter((x) => x && x.id).slice(0, CMP_MAX);
  } catch (e) { return []; }
}

function cmpStore(items) {
  try { localStorage.setItem(CMP_KEY, JSON.stringify(items.slice(0, CMP_MAX))); }
  catch (e) { /* приватный режим — набор живёт до перезагрузки */ }
  renderCmpTray();
  syncCmpButtons();
}

// true — предмет добавлен/убран, false — набор уже полон
function cmpToggle(it) {
  const items = cmpList();
  const i = items.findIndex((x) => x.id === it.id);
  if (i >= 0) items.splice(i, 1);
  else if (items.length >= CMP_MAX) return false;
  else items.push({ id: it.id, name: it.name, icon: it.icon, color: it.color });
  cmpStore(items);
  if (location.pathname === "/compare") cmpLoad();
  return true;
}

// кнопки «в сравнение» разбросаны по каталогу и карточкам — держим их в курсе
function syncCmpButtons() {
  const ids = new Set(cmpList().map((x) => x.id));
  document.querySelectorAll("[data-cmp-id]").forEach((b) => {
    const on = ids.has(b.dataset.cmpId);
    b.classList.toggle("on", on);
    b.title = on ? "Убрать из сравнения" : "Добавить к сравнению";
    if (b.dataset.cmpLabel) b.textContent = on ? "⇄ В СРАВНЕНИИ" : "⇄ К СРАВНЕНИЮ";
  });
}

let cmpTrayEl = null;
function renderCmpTray() {
  const items = cmpList();
  const hide = !items.length || location.pathname === "/compare";
  if (!cmpTrayEl) {
    if (hide) return;
    cmpTrayEl = document.createElement("div");
    cmpTrayEl.className = "cmp-tray";
    cmpTrayEl.setAttribute("aria-label", "Набор для сравнения");
    document.body.appendChild(cmpTrayEl);
  }
  cmpTrayEl.classList.toggle("hidden", hide);
  if (hide) return;
  const chips = items.map((x) => `<button class="cmp-chip" data-rm="${escapeHtml(x.id)}"
      title="Убрать «${escapeHtml(x.name)}»" style="--rar:${rank(x.color).color}">
      <img src="${asset(x.icon)}" alt=""><span class="cmp-chip-x">✕</span></button>`).join("");
  cmpTrayEl.innerHTML = `<div class="cmp-tray-lbl">СРАВНЕНИЕ</div>
    <div class="cmp-tray-items">${chips}</div>
    <a class="cmp-tray-go" href="${cmpUrl(items.map((x) => x.id), cmpPtnSaved())}">СРАВНИТЬ ${items.length}/${CMP_MAX} ▸</a>
    <button class="cmp-tray-clear" title="Очистить набор">✕</button>`;
  cmpTrayEl.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => {
    cmpStore(cmpList().filter((x) => x.id !== b.dataset.rm));
  }));
  cmpTrayEl.querySelector(".cmp-tray-clear").addEventListener("click", () => cmpStore([]));
}

const cmpUrl = (ids, ptn) =>
  `/compare?ids=${encodeURIComponent(ids.join(","))}${ptn ? `&ptn=${ptn}` : ""}`;

async function openCompare() {
  home.classList.add("hidden"); detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  window.scrollTo(0, 0);
  const sp = new URLSearchParams(location.search);
  cmpState.ptn = sp.has("ptn")
    ? Math.max(0, Math.min(15, +sp.get("ptn") || 0))
    : cmpPtnSaved();
  const urlIds = (sp.get("ids") || "").split(",").map((s) => s.trim()).filter(Boolean);
  if (urlIds.length) {
    // пришли по ссылке — набор из адреса главнее локального (имена/иконки
    // подставит ответ бэка, пока их нет — id как подпись)
    const cur = cmpList();
    cmpStore(urlIds.slice(0, CMP_MAX).map((id) =>
      cur.find((x) => x.id === id) || { id, name: id, icon: "", color: "DEFAULT" }));
  }
  cmpState.data = null;
  cmpState.picks = null;
  cmpRender();
  cmpLoad();
  cmpLoadPicks();
}

async function cmpLoad() {
  const ids = cmpList().map((x) => x.id);
  if (!ids.length) { cmpState.data = null; cmpSyncUrl(); cmpRender(); return; }
  const d = await fetch(api(`/compare?ids=${encodeURIComponent(ids.join(","))}&ptn=${cmpState.ptn}`))
    .then((r) => r.json()).catch(() => null);
  if (location.pathname !== "/compare") return;
  cmpState.data = d;
  if (d && d.items && d.items.length) {
    // бэк вернул настоящие имена/иконки (важно для набора, пришедшего ссылкой)
    cmpStore(d.items.map((i) => ({ id: i.id, name: i.name, icon: i.icon, color: i.color })));
  } else if (d && d.missing && d.missing.length) {
    cmpStore([]);   // в ссылке одни неизвестные id — не держим фантомный набор
    authNotice("ЭТИ ПРЕДМЕТЫ НЕЛЬЗЯ СРАВНИТЬ: НЕТ ИГРОВЫХ ХАРАКТЕРИСТИК", "err");
  }
  cmpSyncUrl();
  cmpRender();
}

function cmpSyncUrl() {
  const ids = cmpList().map((x) => x.id);
  const url = ids.length ? cmpUrl(ids, cmpState.ptn) : "/compare";
  if (url !== location.pathname + location.search) history.replaceState(null, "", url);
}

// полоса «насколько хорошо» — длиннее всегда значит лучше, даже когда лучше
// меньше (отдача, разброс): для таких строк берём обратное отношение
function cmpBars(row) {
  const nums = row.cells.filter((c) => c && c.num != null).map((c) => c.num);
  if (!row.dir || nums.length < 2 || nums.some((n) => n <= 0)) return null;
  const mx = Math.max(...nums), mn = Math.min(...nums);
  if (mx === mn) return null;
  return (n) => Math.round((row.dir > 0 ? n / mx : mn / n) * 100);
}

function cmpCol(it) {
  const rk = rank(it.color);
  const p = it.price || {};
  const cat = IDB_CAT_RU[it.category] || "";
  const price = p.min_buyout != null ? `${fmt(p.min_buyout)} ₽`
    : p.known ? "НЕТ ЛОТОВ" : "ЦЕНА СЧИТАЕТСЯ…";
  const sub = [];
  if (p.recent != null) sub.push(`СДЕЛКИ ~${fmt(p.recent)} ₽`);
  if (p.sales_per_hour) sub.push(`${fmtSales(p.sales_per_hour)} ПРОД/Ч`);
  const href = `/item/${encodeURIComponent(it.id)}`;
  return `<div class="cmp-col" style="--rar:${rk.color}">
    <button class="cmp-x" data-rm="${escapeHtml(it.id)}" title="Убрать из сравнения">✕</button>
    <a class="cmp-ic" href="${href}"><img loading="lazy" src="${asset(it.icon)}" alt=""></a>
    <a class="cmp-nm" href="${href}" style="color:${rk.color}">${escapeHtml(it.name)}</a>
    <div class="cmp-meta">${rk.label}${cat ? ` · ${escapeHtml(cat).toUpperCase()}` : ""}</div>
    <div class="cmp-price">${price}</div>
    ${sub.length ? `<div class="cmp-price-sub">${sub.join(" · ")}</div>` : ""}
    ${it.max_ptn && !it.ptn_exact
      ? `<div class="cmp-flag" title="В игровой базе нет этого уровня заточки — показаны базовые значения">БЕЗ ЗАТОЧКИ</div>` : ""}
    ${!it.max_ptn && cmpState.ptn
      ? `<div class="cmp-flag" title="Предмет не затачивается">ЗАТОЧКИ НЕТ</div>` : ""}
  </div>`;
}

function cmpTable(d) {
  const n = d.items.length;
  let h = `<div class="cmp-wrap"><div class="cmp-grid" style="--cols:${n}">
    <div class="cmp-corner">${n} ИЗ ${CMP_MAX}</div>
    ${d.items.map(cmpCol).join("")}`;
  let group = null, i = 0;
  for (const row of d.rows) {
    if (row.group !== group) {
      group = row.group;
      i = 0;
      h += `<div class="cmp-sep"><span>${group === "info" ? "ИНФОРМАЦИЯ" : "ХАРАКТЕРИСТИКИ"}</span></div>`;
    }
    const alt = i++ % 2 ? " alt" : "";       // зебра: строк много, глазу нужна опора
    const bar = cmpBars(row);
    h += `<div class="cmp-name${alt}">${escapeHtml(row.name)}${row.unit ? `<span class="cmp-u">, ${escapeHtml(row.unit)}</span>` : ""}
      ${row.calc ? `<span class="cmp-calc" title="Расчёт: урон × скорострельность ÷ 60 (в игре не показывается)">РАСЧЁТ</span>` : ""}</div>`;
    for (const c of row.cells) {
      if (!c) { h += `<div class="cmp-cell empty${alt}">—</div>`; continue; }
      const cls = c.best ? " best" : c.worst ? " worst" : "";
      const w = bar && c.num != null ? bar(c.num) : null;
      h += `<div class="cmp-cell${cls}${alt}${c.harmful ? " bad" : ""}">
        ${w != null ? `<span class="cmp-bar" style="width:${w}%"></span>` : ""}
        <span class="cmp-val">${escapeHtml(c.value)}</span></div>`;
    }
  }
  return h + `</div></div>`;
}

function cmpRender() {
  const items = cmpList();
  const d = cmpState.data;
  const optP = Array.from({ length: 16 }, (_, i) =>
    `<option value="${i}" ${cmpState.ptn === i ? "selected" : ""}>ЗАТОЧКА +${i}</option>`).join("");
  let h = `<div class="cmp">
    <div class="section-head">
      <div class="section-title">▸ СРАВНЕНИЕ СНАРЯЖЕНИЯ</div>
      <div class="section-note">ДО ${CMP_MAX} ПРЕДМЕТОВ · ЗЕЛЁНОЕ — ЛУЧШЕЕ В СТРОКЕ</div>
    </div>
    <div class="cmp-bar-tools">
      <select id="cmpPtn" title="Уровень заточки, общий для всех колонок">${optP}</select>
      <button id="cmpCopy" class="cmp-tool">СКОПИРОВАТЬ ССЫЛКУ</button>
      <button id="cmpClear" class="cmp-tool" ${items.length ? "" : "disabled"}>ОЧИСТИТЬ</button>
    </div>`;

  if (!items.length) {
    h += `<div class="cmp-empty">
      <div class="cmp-empty-t">НАБОР ПУСТ</div>
      <div class="cmp-empty-d">Найдите оружие, броню, обвесы, контейнеры или артефакты
        в списке ниже — или добавляйте их кнопкой ⇄ в базе предметов и в карточке предмета.
        Ссылку на готовое сравнение можно скопировать и отправить.</div></div>`;
  } else if (!d) {
    h += `<div class="spinner-sm">// СЧИТАЕМ ХАРАКТЕРИСТИКИ</div>`;
  } else if (!d.items.length) {
    h += `<div class="empty-sm">У ВЫБРАННЫХ ПРЕДМЕТОВ НЕТ ХАРАКТЕРИСТИК ДЛЯ СРАВНЕНИЯ.</div>`;
  } else {
    if (d.mixed)
      h += `<div class="cmp-note">⚠ ПРЕДМЕТЫ РАЗНЫХ ТИПОВ — ОБЩИХ СТРОК МАЛО, ПРОЧЕРК ЗНАЧИТ «СТАТА НЕТ»</div>`;
    h += cmpTable(d);
    h += `<div class="side-foot">ЗНАЧЕНИЯ — ИЗ ИГРОВОЙ БАЗЫ НА ВЫБРАННОМ УРОВНЕ ЗАТОЧКИ.
      ПОДСВЕТКА УЧИТЫВАЕТ НАПРАВЛЕНИЕ ПОЛЬЗЫ: У УРОНА И ЗАЩИТ ЛУЧШЕ БОЛЬШЕ,
      У ОТДАЧИ, РАЗБРОСА, ВРЕМЕНИ ПЕРЕЗАРЯДКИ И ВЕСА — МЕНЬШЕ.
      ЦЕНА — МИНИМАЛЬНЫЙ ВЫКУП НА АУКЕ ПО ВСЕМ ЗАТОЧКАМ.</div>`;
  }

  h += cmpPickHtml(items.length);
  page.innerHTML = h + `</div>`;
  cmpWire();
}

function cmpPickHtml(count) {
  const chips = CMP_PICK_CATS.map((c) =>
    `<button class="idb-chip ${cmpState.cat === c.key ? "on" : ""}" data-pcat="${c.key}">${c.label}</button>`).join("");
  const full = count >= CMP_MAX;
  return `<div class="cmp-pick">
    <div class="section-head">
      <div class="section-title">▸ ДОБАВИТЬ ПРЕДМЕТ</div>
      <div class="section-note">${full ? `НАБОР ПОЛОН — УБЕРИТЕ ЛИШНЕЕ` : `СВОБОДНО МЕСТ: ${CMP_MAX - count}`}</div>
    </div>
    <div class="idb-search"><span class="idb-prompt">&gt;_</span>
      <input id="cmpQ" type="search" autocomplete="off" placeholder="ПОИСК ОРУЖИЯ, БРОНИ, ОБВЕСОВ…" value="${escapeHtml(cmpState.q)}"></div>
    <div class="idb-chips">${chips}</div>
    <div id="cmpPickGrid" class="idb-grid ${full ? "dimmed" : ""}">${cmpPickGridHtml()}</div>
  </div>`;
}

function cmpPickGridHtml() {
  const rows = cmpState.picks;
  if (rows == null) return `<div class="spinner-sm">// ЗАГРУЗКА</div>`;
  if (!rows.length) return `<div class="empty-sm">НИЧЕГО НЕ НАЙДЕНО.</div>`;
  const ids = new Set(cmpList().map((x) => x.id));
  return rows.map((it) => {
    const rk = rank(it.color);
    return `<button class="idb-card cmp-pick-card ${ids.has(it.id) ? "on" : ""}"
        data-add="${escapeHtml(it.id)}" style="--rar:${rk.color}">
      <div class="idb-ic"><img loading="lazy" src="${asset(it.icon)}" alt=""></div>
      <div class="idb-nm" style="color:${rk.color}">${escapeHtml(it.name)}</div>
      <div class="idb-cat">${escapeHtml(IDB_CAT_RU[it.category] || it.category || "")}</div>
    </button>`;
  }).join("");
}

async function cmpLoadPicks() {
  const d = await fetch(api(`/items?cat=${encodeURIComponent(cmpState.cat)}`
    + `&q=${encodeURIComponent(cmpState.q)}&limit=24`))
    .then((r) => r.json()).catch(() => null);
  if (location.pathname !== "/compare") return;
  cmpState.picks = (d && d.items ? d.items : []).filter((it) => CMP_CATS.has(it.category));
  const grid = $("cmpPickGrid");
  if (grid) { grid.innerHTML = cmpPickGridHtml(); cmpWirePicks(); }
}

function cmpWirePicks() {
  page.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", () => {
    const it = (cmpState.picks || []).find((x) => x.id === b.dataset.add);
    if (!it) return;
    if (!cmpToggle(it)) { authNotice(`В СРАВНЕНИИ УЖЕ ${CMP_MAX} ПРЕДМЕТА — УБЕРИТЕ ЛИШНЕЕ`, "err"); return; }
    cmpRender();
  }));
}

function cmpWire() {
  const sel = $("cmpPtn");
  if (sel) sel.addEventListener("change", (e) => {
    cmpState.ptn = +e.target.value;
    try { localStorage.setItem("sz_cmp_ptn", String(cmpState.ptn)); } catch (err) { /* приватный режим */ }
    cmpSyncUrl(); cmpLoad();
  });
  const copy = $("cmpCopy");
  if (copy) copy.addEventListener("click", () => {
    navigator.clipboard.writeText(location.href)
      .then(() => authNotice("ССЫЛКА НА СРАВНЕНИЕ СКОПИРОВАНА"))
      .catch(() => authNotice("СКОПИРУЙТЕ ССЫЛКУ ИЗ АДРЕСНОЙ СТРОКИ", "err"));
  });
  const clr = $("cmpClear");
  if (clr) clr.addEventListener("click", () => { cmpStore([]); cmpState.data = null; cmpSyncUrl(); cmpRender(); });
  page.querySelectorAll(".cmp-x[data-rm]").forEach((b) => b.addEventListener("click", () => {
    cmpStore(cmpList().filter((x) => x.id !== b.dataset.rm));
    cmpLoad();
  }));
  page.querySelectorAll("[data-pcat]").forEach((b) => b.addEventListener("click", () => {
    cmpState.cat = b.dataset.pcat; cmpState.picks = null; cmpRender(); cmpLoadPicks();
  }));
  const q = $("cmpQ");
  if (q) {
    let t = null;
    q.addEventListener("input", (e) => {
      clearTimeout(t);
      const v = e.target.value.trim();
      t = setTimeout(() => { cmpState.q = v; cmpState.picks = null; cmpLoadPicks(); }, 300);
    });
  }
  cmpWirePicks();
}

// ---------- разделы в разработке: заглушки с описанием модуля ----------
const PAGES = {};

function setNav(sec) {
  document.querySelectorAll("#topnav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.sec === sec));
  navCenterActive();
}

// Полоса разделов уезжает за экран, но выглядела целой (скроллбар спрятан).
// Классы can-l/can-r включают подтаявший край — CSS сам не знает, докручена
// полоса или нет. Пересчитываем на скролл, ресайз и подгрузку шрифта: ширина
// пунктов до JetBrains Mono другая, и первый замер соврал бы.
function navScrollHint() {
  const nav = document.getElementById("topnav");
  if (!nav) return;
  const max = nav.scrollWidth - nav.clientWidth;
  nav.classList.toggle("can-l", max > 2 && nav.scrollLeft > 2);
  nav.classList.toggle("can-r", max > 2 && nav.scrollLeft < max - 2);
}

// активный раздел — в центр полосы: и видно, где ты, и по бокам торчат соседи,
// то есть прокрутка становится очевидной без всяких стрелок
function navCenterActive() {
  const nav = document.getElementById("topnav");
  const on = nav && nav.querySelector("a.active");
  if (!on) { navScrollHint(); return; }
  // scrollLeft вручную: scrollIntoView дёргает ещё и вертикаль всей страницы
  const to = on.offsetLeft - (nav.clientWidth - on.offsetWidth) / 2;
  nav.scrollLeft = Math.max(0, to);
  navScrollHint();
}

(() => {
  const nav = document.getElementById("topnav");
  if (!nav) return;
  nav.addEventListener("scroll", navScrollHint, { passive: true });
  addEventListener("resize", navScrollHint);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(navScrollHint);
  navScrollHint();
})();

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

// ---------- юридические страницы (Политика / Соглашение) ----------
// Текст лежит статикой в /legal/*.html — правится без пересборки app.js.
const _legalCache = {};
async function openLegal(kind) {
  home.classList.add("hidden");
  detail.classList.add("hidden");
  results.innerHTML = "";
  page.classList.remove("hidden");
  page.innerHTML = '<div class="legal legal-loading">Загрузка…</div>';
  window.scrollTo(0, 0);
  try {
    if (!_legalCache[kind]) {
      const r = await fetch(`${BASE}/legal/${kind}.html`, { cache: "no-cache" });
      if (!r.ok) throw new Error(String(r.status));
      _legalCache[kind] = await r.text();
    }
    page.innerHTML = _legalCache[kind];
  } catch (e) {
    page.innerHTML = '<div class="legal"><a class="legal-back" href="/">◂ НА ГЛАВНУЮ</a>'
      + '<p>Не удалось загрузить документ. Попробуйте обновить страницу.</p></div>';
  }
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
  ymHit();          // SPA-переход = просмотр страницы для Метрики
  renderOnboard();  // подсказка прячется на профиле, заглушках и в других разделах
  gModalClose();    // навигация закрывает модалы разделов
  renderCmpTray();  // панель набора сравнения (на самой /compare не нужна)
  const path = location.pathname;
  // серверный SEO-блок виден только на своём роуте: SPA-навигация его прячет,
  // чтобы чужой текст не «залипал» при переходах (краулер грузит каждый URL заново)
  mkModalClose();   // навигация закрывает карточку аука (в т.ч. созданную вне /market)
  const seoProse = document.getElementById("seoProse");
  if (seoProse) seoProse.hidden = seoProse.dataset.seoPath !== path;
  adBottomRoute(path);   // нижняя врезка: своя секция, живёт мимо перерисовок
  const strip = document.querySelector(".search-strip");
  let mm;

  // десктопный масштаб 120% ломает координаты Leaflet — на карте отключаем
  const onMap = path.startsWith("/map") || path === "/dev/map";
  document.documentElement.classList.toggle("on-map", onMap);
  document.documentElement.classList.remove("map-drawing");

  if (mapCleanup && !onMap) { mapCleanup(); mapCleanup = null; }
  if (scanState && path !== "/dev/scan") scanClose();   // ушли со сканера — гасим WS
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
  if (path === "/dev/promo") {
    strip.classList.add("hidden");
    setNav("dev"); openDevPromos(); return;
  }
  if (path === "/dev/craft") {
    strip.classList.add("hidden");
    setNav("dev"); openDevCraft(); return;
  }
  if (path === "/dev/scan") {
    strip.classList.add("hidden");
    setNav("dev"); openDevScan(); return;
  }
  if (path === "/dev/news") {
    strip.classList.add("hidden");
    setNav("dev"); openDevNews(); return;
  }
  // черновик новой главной: своя страница, боевая «/» не меняется
  if (path === "/home2") {
    strip.classList.add("hidden"); page.classList.add("hidden");
    detail.classList.add("hidden"); results.innerHTML = "";
    setNav("home2"); openHome2(); return;
  }
  if ((mm = path.match(/^\/map(?:\/([a-z0-9_-]+))?$/))) {
    strip.classList.add("hidden");
    setNav("map"); openMap(mm[1] || null); return;
  }

  if (path === "/items") {
    strip.classList.add("hidden"); detail.classList.add("hidden");
    setNav("itemdb"); openItemDb(); return;
  }
  if (path === "/compare") {
    strip.classList.add("hidden"); detail.classList.add("hidden");
    setNav("compare"); openCompare(); return;
  }
  // отдельная страница предмета — в разделе «База предметов»
  if ((mm = path.match(/^\/item\/(.+)$/))) {
    strip.classList.add("hidden"); page.classList.add("hidden");
    home.classList.add("hidden"); results.innerHTML = "";
    setNav("itemdb"); openItem(decodeURIComponent(mm[1])); return;
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
  if (path === "/promo") {
    strip.classList.add("hidden"); detail.classList.add("hidden");
    setNav("promo"); openPromo(); return;
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
  if (path === "/operations") {
    strip.classList.add("hidden"); detail.classList.add("hidden");
    setNav("operations"); openOperations(); return;
  }
  if (path === "/privacy" || path === "/terms") {
    strip.classList.add("hidden");
    setNav(""); openLegal(path === "/privacy" ? "privacy" : "terms"); return;
  }
  if (PAGES[path.slice(1)]) {
    strip.classList.add("hidden"); page.classList.add("hidden");
    setNav(path.slice(1)); openPage(path.slice(1)); return;
  }

  // "/" — главная-терминал (макет ПУЛЬТ)
  if (path === "/") {
    strip.classList.add("hidden"); page.classList.add("hidden");
    setNav("home");
    detail.classList.add("hidden"); results.innerHTML = "";
    home.classList.remove("hidden");
    openHomeMain(); return;
  }

  // крафт-контекст: раздел / лендинг / поиск / карточка / профиль
  strip.classList.remove("hidden");
  page.classList.add("hidden");
  setNav("craft");
  if (path === "/profile") { openProfile(); return; }
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

// ---------- cookie-баннер (152-ФЗ: информирование об использовании cookie) ----------
(function cookieBanner() {
  try { if (localStorage.getItem("sz_cookie_ok") === "1") return; } catch (e) { return; }
  const bar = document.createElement("div");
  bar.className = "cookie-bar";
  bar.setAttribute("role", "region");
  bar.setAttribute("aria-label", "Уведомление о cookie");
  bar.innerHTML = `<span class="cookie-txt">Мы используем файлы cookie и сервис
    Яндекс.Метрика для работы сайта и аналитики. Продолжая пользоваться сайтом, вы
    соглашаетесь с этим и принимаете
    <a href="/privacy">Политику конфиденциальности</a>.</span>
    <button class="cookie-ok" type="button">ПРИНЯТЬ</button>`;
  bar.querySelector(".cookie-ok").addEventListener("click", () => {
    try { localStorage.setItem("sz_cookie_ok", "1"); } catch (e) { /* приватный режим */ }
    bar.remove();
  });
  document.body.appendChild(bar);
})();

window.addEventListener("popstate", route);
migrateLegacyHash();
route();
