FROM python:3.12-slim

WORKDIR /app

# зависимости отдельно — кэшируется, пока requirements не менялись
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# код бэка и фронта
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
# обслуживающие скрипты (чистка выбросов биржи, пересид гайда) — их запускают
# внутри контейнера через docker exec, там смонтирован том с БД:
#   docker exec -w /app/backend stalzone_craft python /app/scripts/<script>.py
COPY scripts/ /app/scripts/

WORKDIR /app/backend
EXPOSE 8000

# data/ (скачанная БД + иконки) монтируется томом, чтобы не качать 142МБ на каждый старт
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
