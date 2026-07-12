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

```bash
# с локальной машины: залить проект (без data/.venv/.wheels)
cd "d:/stalzone craft"
tar czf - --exclude=.venv --exclude=data --exclude=.wheels --exclude=__pycache__ --exclude='*.pyc' . \
  | ssh pavel@88.87.70.167 "tar xzf - -C /home/pavel/stalzone-craft"
# пересобрать (данные в volume сохранятся)
ssh pavel@88.87.70.167 "cd /home/pavel/stalzone-craft && docker compose up -d --build"
```

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

## Авторизация пользователей (OAuth 2.0 через аккаунт EXBO) — ВКЛЮЧЕНА (10 июля 2026)

Код: `routers/auth.py`, `db/users.py`; SQLite `data/users.db` живёт в том же volume.
Использует те же креды TradeAssist. Как развёрнуто:

- В кабинете exbo.net зарегистрирован redirect URI
  `https://stalzone-helper.ru/auth/callback` (корень; старый /mvp-вариант тоже
  зарегистрирован и работает через 301).
- В `.env` на сервере: `PUBLIC_BASE_URL=https://stalzone-helper.ru`
  (переменная прокинута в docker-compose.yml).
- Проверка: `/api/health` → `users`, `/auth/login` → 302 на exbo.net/oauth/authorize.

Без `PUBLIC_BASE_URL`/кред авторизация тихо выключена (кнопки нет) — ничего не ломает.

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
