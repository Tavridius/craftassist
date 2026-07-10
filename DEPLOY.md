# 🚀 Деплой StalZone Craft — операционная справка

**Живой URL:** https://pmcgame.ru/mvp/  (и http://pmcgame.ru/mvp/)

> ⚠️ По «голому» IP `88.87.70.167/mvp` **не открывается** — nginx сервера отвечает
> только на Host `pmcgame.ru` (по IP соединение рвётся, так настроен их конфиг).
> Пользоваться доменом.

---

## Как это развёрнуто

- **Контейнер** `stalzone_craft` (образ `stalzone-craft:latest`), слушает `:8000`,
  проброшен на хост `127.0.0.1:8100` (для curl-проверок).
- Подключён к docker-сети `backend_rpg_network` — поэтому `rpg_nginx` достаёт его
  по имени контейнера.
- Код на сервере: `/home/pavel/stalzone-craft/`
- Игровая БД (142МБ) + иконки — в docker-volume `stalzone-craft_craft_data`
  (`/app/backend/data`). Скачивается один раз при первом старте.
- **nginx**: в `/home/pavel/text_rpg/eblia/backend/nginx/ssl.conf` в оба server-блока
  (`listen 80` и `listen 443`) добавлены `location = /mvp` и `location /mvp/`
  (proxy на `http://stalzone_craft:8000/`). Бэкапы: `ssl.conf.bak-mvp*`.

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

> **Дерево крафта** (`services/craft.py`): рекурсивно считает `min(купить, скрафтить)` на каждом
> узле, перебирая все варианты рецепта. На демо (~2 запроса/с) глубокое дерево грузится холодным
> 40-60с → кэшируется на 600с. Env-ручки `CRAFT_MAX_DEPTH` / `CRAFT_MAX_VARIANTS` /
> `AUCTION_MIN_INTERVAL` регулируют глубину/ширину/скорость. Поэтому nginx `/mvp` таймаут = 120с.

## Проверки

```bash
ssh pavel@88.87.70.167 "curl -s http://127.0.0.1:8100/api/health"      # контейнер
curl -s https://pmcgame.ru/mvp/api/health                              # через nginx
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
