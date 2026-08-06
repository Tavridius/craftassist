# 🚀 Деплой StalZone Craft — операционная справка

**Живой URL:** https://stalzone-helper.ru/ (приложение на КОРНЕ домена).
Пути `/mvp/*` на новом домене 301-редиректятся на корень (query сохраняется).
Старый `pmcgame.ru/mvp/*` — 301 на новый домен (с 11 июля 2026, SEO: без дублей).

> ⚠️ По «голому» IP `88.87.70.167` **не открывается** — nginx сервера отвечает
> только на известные ему Host-домены (по IP соединение рвётся, так настроен их конфиг).
> Пользоваться доменом.

**Сертификат (выпущен 10 июля 2026):** Let's Encrypt на stalzone-helper.ru + www,
живёт в docker-томе `backend_certbot_certs`, выпуск — через certbot-сервис compose игры
(webroot `/var/www/certbot`, том `backend_certbot_www`). **Автообновление:** cron у
pavel (пн/чт 03:17) — `certbot renew` для ВСЕХ сертов сервера + reload nginx,
лог `~/certbot-renew.log`.

**nginx нового домена:** отдельный файл `stalzone-helper.conf` (копия в репо —
`nginx/stalzone-helper.conf`) рядом с ssl.conf игры: 80 (ACME + редирект на https)
и 443 (серт + proxy корня на `stalzone_craft:8000`, /mvp-совместимость).

---

## Как это развёрнуто

- **Контейнер** `stalzone_craft` (образ `stalzone-craft:latest`), слушает `:8000`,
  проброшен на хост `127.0.0.1:8100` (для curl-проверок).
- Подключён к docker-сети `backend_rpg_network` — поэтому `rpg_nginx` достаёт его
  по имени контейнера.
- Код на сервере: `/home/pavel/stalzone-craft/`
- Игровая БД (142МБ) + иконки — в docker-volume `stalzone-craft_craft_data`
  (`/app/backend/data`). Скачивается один раз при первом старте.
- **nginx**: в `/home/pavel/text_rpg/eblia/backend/nginx/ssl.conf` в обоих server-блоках
  (`listen 80` и `listen 443`) `location /mvp*` — теперь 301 на `stalzone-helper.ru`
  (см. `nginx/mvp.conf` в репо). Бэкапы: `ssl.conf.bak-mvp*` (последний —
  `bak-mvp-redirect-20260710-231436`, там ещё старый proxy-вариант).
- **IndexNow**: ключ `97039c9de184bc7a352531c1f0545e49` (файл-подтверждение в
  `frontend/`). Пинг при обновлениях:
  `curl "https://yandex.com/indexnow?url=<URL>&key=<ключ>"` (Bing —
  api.indexnow.org, с локальной машины не открывается — пинговать с сервера).

## Обновить код (redeploy)

**Через git — основной способ** (с 01.08.2026). `/home/pavel/stalzone-craft` —
клон этого репозитория, репозиторий публичный, поэтому сервер тянет код сам, и
заливать архивы с локальной машины больше не нужно.

```bash
# 1) локально: всё закоммичено и уехало на GitHub
cd "d:/stalzone craft" && git push origin main
# origin — по SSH (git@github.com:...): для https креды не сохранены и push
# висит на невидимом окне Git Credential Manager

# 2) на сервере: подтянуть и пересобрать (данные в volume сохранятся)
ssh pavel@88.87.70.167 "cd /home/pavel/stalzone-craft \
  && tar czf ../stalzone-craft-predeploy-\$(date +%F-%H%M).tgz --exclude=.git . \
  && git fetch origin && git reset --hard origin/main \
  && docker compose up -d --build"
```

`git reset --hard` не трогает неотслеживаемые файлы, поэтому боевой `.env`
(он в .gitignore) переживает раскатку. Проверка после: `curl
http://127.0.0.1:8100/api/health` (demo:false, token:true) + `docker logs
stalzone_craft`.

⚠️ Всё, что задеплоено, но не закоммичено, при `reset --hard` пропадёт. Перед
первым таким деплоем сверяйте prod-файлы с локальными (`ssh ... cat file | diff
- local`) — исторически часть фич уезжала на прод архивом мимо git.

**Архивом (запасной путь, если git на сервере недоступен).** Однострочный пайп
`tar | ssh` с этой Windows-машины блокируется, а `scp` из временной папки — не
всегда проходит; тогда собирать архив в каталоге проекта и слать его оттуда:

```bash
cd "d:/stalzone craft"
# ⚠️ ИСКЛЮЧАЕМ .env (локальный обрезан — затрёт боевые креды) и
#    stalzone-database (569МБ, качается в volume при старте)
tar czf - --force-local --exclude=.venv --exclude=data --exclude=.wheels \
  --exclude=__pycache__ --exclude='*.pyc' --exclude=.env --exclude=.git \
  --exclude=stalzone-database . > deploy.tgz
scp deploy.tgz pavel@88.87.70.167:/tmp/
ssh pavel@88.87.70.167 "tar xzf /tmp/deploy.tgz -C /home/pavel/stalzone-craft \
  && rm /tmp/deploy.tgz && cd /home/pavel/stalzone-craft && docker compose up -d --build"
```

## Реклама РСЯ — включение / выключение

Два места, оба включаются своей переменной и независимо:

| переменная | место | где показывается |
|---|---|---|
| `RSYA_BLOCK_ID` | врезка в тексте, после третьего блока | `/guides/*`, `/patches/*`; статьи короче 8 блоков пропускаются |
| `RSYA_BLOCK_BOTTOM` | под контентом раздела (секция `#adBottom`) | главная, `/market`, `/auction`, `/barter`, `/obmen`, `/builds`, `/compare`, `/operations`, `/items`, `/item/*`, `/quests*`, `/guides*`, `/patches*`, `/promo` |

Принцип размещения: реклама всегда **после** того, как человек получил ответ, и
никогда не выше него. Внутри калькуляторов блоков нет — только под результатом.
Без рекламы намеренно: `/search` (самый вовлечённый вход, глубина 18.5),
`/profile`, `/map`, `/dev/*`, юридические страницы.

Незаполненный блок (стратегия «максимальный доход» заполняет не все показы) и
блокировщик убирают врезку целиком — пустая рамка не остаётся.

По умолчанию ВЫКЛЮЧЕНО: обе переменные пусты → `<html>` без `data-ads*`, скрипт
`context.js` вообще не грузится.

```bash
# включить: идентификаторы блоков из интерфейса РСЯ (Мои площадки → блок → код)
ssh pavel@88.87.70.167 "cd /home/pavel/stalzone-craft && \
  sed -i '/^RSYA_BLOCK_/d' .env && \
  printf 'RSYA_BLOCK_ID=R-A-19714669-1\nRSYA_BLOCK_BOTTOM=R-A-19714669-2\n' >> .env"
ssh pavel@88.87.70.167 "cd /home/pavel/stalzone-craft && docker compose up -d"
```

Проверка живьём (публично, без ssh):
```bash
curl -s https://stalzone-helper.ru/guides/vygodnyy-kraft | grep -o 'data-ads[^ >]*'   # оба блока
```
В браузере: открыть гайд → в тексте появится врезка с подписью «РЕКЛАМА»;
перейти на другой гайд, не перезагружая страницу → врезка должна перерисоваться
(в РСЯ показы растут). Если не растут — смотреть консоль: `Ya.Context` не
загрузился (блокировщик) или id блока неверный.

Выключить мгновенно (обе врезки; чтобы убрать одну — чистить только её строку):
```bash
ssh pavel@88.87.70.167 "cd /home/pavel/stalzone-craft && sed -i 's/^RSYA_BLOCK_ID=.*/RSYA_BLOCK_ID=/;s/^RSYA_BLOCK_BOTTOM=.*/RSYA_BLOCK_BOTTOM=/' .env && docker compose up -d"
```

## A/B-тест дизайна — запуск / остановка

Вариант B = «Торговый терминал» (тёплая янтарная тема + тикер), `frontend/styles-b.css`.
Механика: серверный cookie-сплит `sz_ab` (липкая, 90 дней), вариант уходит в
Я.Метрику параметром визита `ab_design`. По умолчанию ВЫКЛ (`AB_TEST_DESIGN=0`).
Флаг уже проброшен в docker-compose.yml (`AB_TEST_DESIGN=${AB_TEST_DESIGN:-0}`).

```bash
# 1) залить код (команда redeploy выше) — привезёт styles-b.css, app.js, pages.py, config.py
# 2) включить тест в БОЕВОМ .env (создаём ручку, боевые креды не трогаем):
ssh pavel@88.87.70.167 "cd /home/pavel/stalzone-craft && \
  grep -q '^AB_TEST_DESIGN=' .env && sed -i 's/^AB_TEST_DESIGN=.*/AB_TEST_DESIGN=1/' .env \
  || echo 'AB_TEST_DESIGN=1' >> .env"
# 3) пересоздать контейнер с новой env (rebuild не обязателен, но не мешает):
ssh pavel@88.87.70.167 "cd /home/pavel/stalzone-craft && docker compose up -d --build"
```

Проверка живьём (публично, без ssh):
```bash
curl -sI https://stalzone-helper.ru/ | grep -i 'set-cookie\|vary'          # есть Set-Cookie sz_ab, Vary: Cookie
curl -s https://stalzone-helper.ru/ --cookie 'sz_ab=B' | grep -o 'data-ab="B"\|styles-b.css' | sort -u  # оба есть
curl -s https://stalzone-helper.ru/ --cookie 'sz_ab=A' | grep -c styles-b.css   # = 0
```

Остановить / откатить (мгновенно все на вариант A):
```bash
ssh pavel@88.87.70.167 "cd /home/pavel/stalzone-craft && sed -i 's/^AB_TEST_DESIGN=.*/AB_TEST_DESIGN=0/' .env && docker compose up -d"
```

Смотреть результаты — Я.Метрика (счётчик 110585101):
- параметр визита `ab_design` = `A` / `B` появляется в отчётах через несколько минут после первого A/B-трафика;
- в любом отчёте вовлечённости (Посещаемость / глубина просмотра / время на сайте / отказы)
  → **Сегментировать → Визиты, в которых → Параметры визита → ab_design**, или
  «Сравнение сегментов»: `ab_design=A` против `ab_design=B`;
- отдельную цель заводить НЕ надо — параметр цепляется ко всем отчётам.

## Главная-терминал + песочница макетов `/home2`

Боевая `/` с 06.08.2026 рисуется макетом **ПУЛЬТ**: приборная строка сверху,
индикаторы слева, главный экран по центру (крафты + самое продаваемое, с
поиском внутри модулей), колонка новостей справа. Старый дашборд из десяти
одинаковых карточек удалён — откат только через `git revert`.

Раскладка задана областями (`grid-template-areas`), а не порядком в DOM:
на ≤1200 px приборы уходят под главный экран, на ≤900 px порядок
центр → приборы → новости. Проверять после любых правок сетки — главный экран
обязан оставаться первым, ради этого центр и переделывали.

`/home2` остался **песочницей макетов под админом** (`ADMIN_USER_IDS`, гейт во
фронте + `noindex`): там переключатель ПУЛЬТ / ПЛАТА и предпросмотр правок, не
трогающий боевую страницу. Вход — пункт меню **◈ МАКЕТЫ** или `/dev` → `МАКЕТЫ ↗`.
Прямые ссылки: `/home2?lay=hud`, `/home2?lay=board`. Второй макет ПЛАТА —
центральная шина новостей, модули по крыльям на дорожках, фон-миллиметровка.
Рекламы на `/home2` нет (её нет в `AD_BOTTOM_PATHS`), на боевой `/` — есть.

Поиск внутри модулей главной ходит в `/api/home/search?kind=craft|market`:
`craft` отсеивает некрафтящееся и отдаёт выгоду за цикл из `rankings.rows`
(полный проход там уже сделан ради топов), `market` — темп продаж и цену.
Внешних запросов не добавляет, всё из тёплых кэшей.

**Новости сайта** (колонка на этой странице) — гибрид: ручные посты из
`data/sitenews.db` (редактор `/dev/news`) плюс автособытия из живых источников
(свежие гайды, активные промокоды, патчи игры). Автособытия в базу не пишутся,
собираются на чтении `/api/news/feed` — удалили гайд или протух промокод, запись
уходит из ленты сама.

```bash
curl -s https://stalzone-helper.ru/api/news/feed | head -c 400   # лента отдаётся всем
curl -sI https://stalzone-helper.ru/home2 | head -1               # 200, в теле noindex
curl -s https://stalzone-helper.ru/api/admin/news                 # 403 без админской сессии
```

`sitenews.db` лежит в том же volume, что и остальные базы (`/app/backend/data`) —
раскатка кода посты не трогает.

## Реальные цены — ВКЛЮЧЕНЫ (10 июля 2026)

Прод работает на реальных ценах: `.env` с кредами TradeAssist создан на сервере,
`/api/health` → `"demo": false`. App-токен живёт 365 дней и обновляется сам.
Ниже — как это устроено/восстановить.

> ⚠️ `docker compose` передаёт в контейнер только переменные, явно перечисленные
> в `environment:` секции docker-compose.yml. Новую env-ручку добавлять в ОБА места:
> `.env` и docker-compose.yml.

Бэкенд сам обменивает клиентские креды на app-токен у OAuth-сервера EXBO
(`services/oauth.py`) и обновляет его до истечения; токен кэшируется в
volume (`data/app_token.json`). Статический `API_TOKEN` больше не нужен
(остаётся fallback для демо).

Создать `/home/pavel/stalzone-craft/.env` (креды TradeAssist — client id `3296`,
секрет из письма об одобрении):
```
API_BASE=https://eapi.stalcraft.net
API_CLIENT_ID=3296
API_CLIENT_SECRET=<client secret приложения TradeAssist>
REGION=RU
# Лимит prod-API: 400 ЕДИНИЦ/мин (окно фиксированное 60с), но каждый запрос
# к аукциону стоит 2 единицы (lots и history, любой limit — проверено бёрстами
# при остановленном воркере). Реальный потолок = 200 запросов/мин (~3.3/с).
# 0.35 → ~2.9/с (~344 ед/мин, запас ~14% на /history и внеочередной прогрев);
# полный цикл 989 предметов ≈ 6 мин. Быстрее 5 мин физически нельзя — только
# приоритизацией (греть горячее чаще), см. планы.
AUCTION_MIN_INTERVAL=0.35
CRAFT_MAX_DEPTH=6
CRAFT_MAX_VARIANTS=6
```
затем `docker compose up -d` (пересоздаст контейнер с новыми env). Демо-429 уйдут.
Проверка: в `docker logs stalzone_craft` строка `oauth: obtained app token`,
в `/api/health` → `"demo": false, "token": true`.

## Авторизация пользователей — локальная (email+пароль) + EXBO OAuth

Код: `routers/auth.py`, `db/users.py`, `services/mailer.py`; SQLite `data/users.db`
в том же volume. **Два входа**, кнопка «ВХОД» открывает модал с вкладками:

- **Локальная** (email/ник + пароль). Работает ВСЕГДА, даже без кред EXBO.
  Пароли — pbkdf2 (stdlib). Эндпоинты: `POST /auth/register`, `POST /auth/signin`,
  `POST /auth/reset` + `POST /auth/reset/confirm`, `GET /auth/verify`.
- **EXBO OAuth** (кнопка в модале). Аккаунт создаётся автоматически при первом
  входе (без формы регистрации). Требует кред TradeAssist. Redirect URI
  `https://stalzone-helper.ru/auth/callback` зарегистрирован в кабинете exbo.net.

Схема БД мигрирует автоматически при старте (`exbo_id` стал nullable, добавлены
`email`/`password_hash`/`email_verified` + таблица `email_tokens`) — существующие
EXBO-аккаунты и сессии сохраняются. `/api/me` отдаёт флаги `auth_enabled`
(локальная всегда true), `oauth_enabled`, `mail_enabled`.

Env в `.env` на сервере (прокинуть в docker-compose.yml): `PUBLIC_BASE_URL=https://stalzone-helper.ru`,
`SESSION_TTL_DAYS`, `PASSWORD_MIN_LEN`, `ADMIN_EMAILS` (локальные админы через запятую).

Проверка: `/api/health` → `users`; `POST /auth/register` с `{email,login,password}` → 200 + кука `sz_session`.

### Метки Я.Метрики (цели)

При успешном входе/регистрации фронт вызывает `ym(110585101,'reachGoal', …)`:
`signup` — регистрация (локальная и первый вход через EXBO), `login` — вход
вернувшегося. **Нужно создать две цели типа «JavaScript-событие»** в счётчике
110585101 (Метрика → Настройка → Цели → идентификаторы ровно `signup` и `login`).
Для EXBO-редиректа цель шлётся по маркеру `#auth=signup|login` (см. `authInit` в app.js).

Дополнительные JS-цели: `promo_ref_click` — клик (копирование) по реферальному
промокоду сайта (модуль на главной и страница `/promo`), `quest_open` — открытие
квеста. Идентификаторы целей — ровно эти строки.

**Воронка регистрации (заводить руками, 06.08.2026).** Три цели типа
«JavaScript-событие», идентификаторы ровно такие:

| цель | когда шлётся |
|---|---|
| `auth_open` | открыт модал авторизации (`openAuthModal`) — верх воронки |
| `auth_try` | нажата «СОЗДАТЬ АККАУНТ» — попытка, независимо от исхода |
| `auth_fail` | попытка отклонена: пароли не совпали, нет галки согласия, или ошибка бэка |

Зачем: автоцель «отправил контактные данные» **не ловит** сабмит этой формы —
она уходит через `fetch` с `preventDefault`, поэтому в июле автоцель показала 8
отправок при 13 успешных регистрациях. Считать по ней воронку нельзя. Связка
`auth_open → auth_try → signup` (плюс `auth_fail`) даёт настоящие доли: сколько
бросили форму не начав и сколько не смогли её пройти.

Текущий `YM_TOKEN` цели создать не может (403, право только на чтение — см.
`scripts/ym_hygiene.py`), поэтому только через интерфейс Метрики.

## Почтовый сервис на домене (verify email + сброс пароля)

**Развёрнуто 06.08.2026.** MTA — контейнер `docker-mailserver`, который раньше
обслуживал `artwood34.ru` (домен был спящий: последнее письмо 11.06, исходящих
ноль). Переведён на `stalzone-helper.ru`: ящики и DKIM-ключ artwood34 удалены,
hostname сменён, roundcube отключён от compose.

Живёт отдельно от сайта: `/home/pavel/mailserver/docker-compose.yml`
(бэкапы конфига и ящиков — в `/home/pavel/mailserver/backups/`).

**Как связаны сайт и MTA.** Оба контейнера в сети `backend_rpg_network`, поэтому
бэкенд ходит к MTA по имени контейнера, порт 25, без auth и TLS — трафик не
выходит за пределы docker-бриджа, а postfix `mynetworks` (172.16.0.0/12) пускает
релей только изнутри. Снаружи 25-й порт релея не даёт. `.env` на проде:
```
SMTP_HOST=mailserver
SMTP_PORT=25
SMTP_SECURITY=none
SMTP_USER=            # пусто: локальный релей
SMTP_PASS=
MAIL_FROM=noreply@stalzone-helper.ru
MAIL_FROM_NAME=StalZone Helper
```
Ящик `noreply@stalzone-helper.ru` заведён (пароль нужен только для IMAP, сайту он
не требуется — релей идёт без auth).

### DNS (внесено 06.08.2026 в рег.ру)

| тип | имя | значение | статус |
|---|---|---|---|
| A | `mail` | `88.87.70.167` | ✅ |
| MX | `@` | `mail.stalzone-helper.ru.` (приоритет 10) | ✅ |
| TXT | `@` | `v=spf1 a mx ip4:88.87.70.167 -all` | ✅ |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:postmaster@stalzone-helper.ru` | ✅ |
| TXT | `mail._domainkey` | DKIM, селектор `mail`, 2048 бит | ✅ |
| PTR | `88.87.70.167` | `mail.stalzone-helper.ru` | ⏳ всё ещё `mail.artwood34.ru` |

DKIM-ключ одной строкой (если понадобится перевыпуск):
```
ssh pavel@88.87.70.167 "docker exec mailserver cat \
  /tmp/docker-mailserver/opendkim/keys/stalzone-helper.ru/mail.txt \
  | tr -d '\n\t' | sed 's/.*(//; s/).*//; s/\" *\"//g; s/\"//g'"
```

Сертификат `mail.stalzone-helper.ru` выпущен (LE, до 04.11.2026), `SSL_DOMAIN` в
compose MTA переключён на него. Чтобы ACME-проверка проходила, поддомен `mail`
добавлен в `server_name` **HTTP-блока** vhost'а
`text_rpg/eblia/backend/nginx/stalzone-helper.conf` — без этого запрос попадал в
`default_server` с `return 444` и challenge не отдавался.

### Грабли: негативный DNS-кэш Gmail

После публикации записей часть писем всё ещё отбивалась с `550-5.7.26`, хотя
SPF/DKIM уже были в зоне. Причина — **разные фронты Gmail с разным состоянием
кэша**: те, что запрашивали записи до публикации, закэшировали их отсутствие
(negative TTL у reg.ru = 10800 с, 3 часа).

    16:06, 16:11 → 142.250.157.27 — отбито (записей ещё не было)
    16:27        → 173.194.222.27 — принято
    16:32        → 142.250.157.27 — отбито (кэш)

Вывод: **сразу после правки DNS не паниковать и ничего не перенастраивать** —
подождать 3 часа и проверить снова. Настройку проверять не по реакции Gmail, а
независимо: `docker exec mailserver opendkim-testkey -d stalzone-helper.ru -s mail -vvv`
(должно быть `key OK`; `key not secure` — это лишь отсутствие DNSSEC, не ошибка).

### Проверка

```
docker exec stalzone_craft python -c "import sys;sys.path.insert(0,'/app/backend');\
from app.services import mailer;print(mailer.enabled())"
docker exec mailserver tail -30 /var/log/mail/mail.log
```
В логе смотреть `Passed CLEAN` (прошло) против `Blocked BAD-HEADER` (зарезано
фильтром) и финальный `status=sent`. Спам-скор — на mail-tester.com.

**Грабли, уже наступленные.** `mailer._send_sync` не ставил заголовки `Date` и
`Message-ID` — `smtplib` их не добавляет сам, а `Date` обязателен по RFC 5322.
Amavis на MTA резал такие письма как `BAD-HEADER-0` и отправлял в карантин: до
внешнего мира они не доходили вообще. Исправлено 06.08.2026; при правке
`mailer.py` эти два заголовка не терять.

## Профили убежища (11 июля 2026)

У авторизованных: профиль прокачки (`#profile` — перки 0–10 + станки/фичи),
хранится в той же SQLite (`profiles`, JSON). Эндпоинты: `GET /api/hideout`
(справочник), `GET/PUT /api/profile`. Карточка отдаёт `req_check`
(есть/не хватает по выбранному варианту) и `available`; `/api/search` и
`/api/top` принимают `?available=1` — фильтр «на что хватает прокачки»
(тумблер «РЕЦЕПТЫ: ДОСТУПНЫЕ/ВСЕ» в шапке).

## Google Search Console

Верификация домена — HTML-файлом: `frontend/google8788bd5e337192f4.html`
(раздаётся статикой в корень → `https://stalzone-helper.ru/google8788bd5e337192f4.html`).
После деплоя: в GSC добавить ресурс `https://stalzone-helper.ru/`, метод «HTML-файл»,
подтвердить, скормить `https://stalzone-helper.ru/sitemap.xml`. Робот `/api/`, `/auth/`
закрыты в robots.txt; `/profile`, `/search` — noindex.

## Профили убежища (11 июля 2026)

У авторизованных: профиль прокачки (`#profile` — перки 0–10 + станки/фичи),
хранится в той же SQLite (`profiles`, JSON). Эндпоинты: `GET /api/hideout`
(справочник), `GET/PUT /api/profile`. Карточка отдаёт `req_check`
(есть/не хватает по выбранному варианту) и `available`; `/api/search` и
`/api/top` принимают `?available=1` — фильтр «на что хватает прокачки»
(тумблер «РЕЦЕПТЫ: ДОСТУПНЫЕ/ВСЕ» в шапке).

## History API + SSR-лайт мета (13 июля 2026)

- Фронт на реальных путях (`/item/{id}`, `/auction`, `/artefact/{id}`, `/builds`,
  `/profile`, `/search`, `/vygodno-kraftit`) вместо `#hash`. Старые hash-ссылки
  мигрируют в путь при загрузке.
- `backend/app/routers/pages.py` отдаёт `index.html` с подставленными
  title/description/canonical/og под каждый URL; включён в `main.py` ДО
  StaticFiles-маунта (иначе catch-all перекроет). Генерит `/sitemap.xml`.
- nginx менять НЕ нужно — он и так проксирует `location /` на приложение,
  которое само обслуживает SPA-пути и статику.
- Проверка: `curl https://stalzone-helper.ru/builds | grep '<title>'` — тайтл
  раздела, не главной; `/sitemap.xml` отдаёт 4 URL; `/item/{id}` — имя в тайтле.

## Биржа артефактов + калькулятор сборок (12 июля 2026)

- `services/artefact_watch.py` — снапшоты истории продаж артефактов по корзинам
  качество(qlt)×заточка(ptn) в SQLite `data/market.db` (volume), часы
  `ART_WATCH_HOURS` (1,7,13,19 МСК), пропущенный слот доснимается при старте.
- `services/artefact_lots.py` — живые лоты: средняя из `ART_LOTS_TOP=5` самых
  дешёвых по корзинам, цикл `ART_LOTS_MINUTES=30`, кэш `data/artefact_lots.json`.
- Цены калькулятора: `BUILD_PRICE_SOURCE=auto` — лоты, пока история < 7 дней,
  после — средненедельная поверх лотов (переключается само).
- Эндпоинты: `/api/artmarket/top`, `/api/artmarket/{id}`, `/api/build/dict`,
  `POST /api/build/auto`. Разделы фронта: АУКЦИОН и СБОРКИ.
- Проверка: `/api/health` → `artmarket` (rows/first_slot/last_slot) и
  `artlots` (items/updated); в логах `artefact_watch: snapshot ... done` и
  `ArtefactLots: cycle done`.

> **Дерево крафта** (`services/craft.py`): рекурсивно считает `min(купить, скрафтить)` на каждом
> узле, перебирая все варианты рецепта. На демо (~2 запроса/с) глубокое дерево грузится холодным
> 40-60с → кэшируется на 600с. Env-ручки `CRAFT_MAX_DEPTH` / `CRAFT_MAX_VARIANTS` /
> `AUCTION_MIN_INTERVAL` регулируют глубину/ширину/скорость. Поэтому nginx `/mvp` таймаут = 120с.

## Проверки

```bash
ssh pavel@88.87.70.167 "curl -s http://127.0.0.1:8100/api/health"      # контейнер
curl -s https://stalzone-helper.ru/mvp/api/health                      # через nginx
ssh pavel@88.87.70.167 "docker logs stalzone_craft --tail 30"          # логи
```

## Откат nginx (если что-то сломалось)

```bash
# восстановить последний бэкап ssl.conf и перезагрузить
ssh pavel@88.87.70.167 "cp /home/pavel/text_rpg/eblia/backend/nginx/ssl.conf.bak-mvp443-* /home/pavel/text_rpg/eblia/backend/nginx/ssl.conf"
ssh pavel@88.87.70.167 "docker exec rpg_nginx nginx -t && docker exec rpg_nginx nginx -s reload"
```

## Остановить MVP

```bash
ssh pavel@88.87.70.167 "cd /home/pavel/stalzone-craft && docker compose down"
# + при желании убрать /mvp из ssl.conf (см. откат)
```
