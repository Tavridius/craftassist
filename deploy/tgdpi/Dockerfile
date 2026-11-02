# ByeDPI — SOCKS-прокси для бота канала: обходит замедление ТСПУ на пути
# сервер → Cloudflare-воркер (прокси Bot API). Напрямую запросы к воркеру
# с сервера то проходят, то висят до таймаута. Та же сборка и стратегия,
# что у соседнего проекта santehno (подобрано там 29.10.2026 на этом сервере).
# Стратегия — в docker-compose.yml (command).
FROM alpine:3.20 AS dl
RUN wget -qO /b.tgz https://github.com/hufrea/byedpi/releases/download/v0.17.3/byedpi-17.3-x86_64.tar.gz \
 && echo "98f73c32eacb571ebd88d790f6376ed9e70f02d44c1fe862472ecea75cd7117d  /b.tgz" | sha256sum -c - \
 && tar -xzf /b.tgz -C / && mv /ciadpi-x86_64 /ciadpi

FROM scratch
COPY --from=dl /ciadpi /ciadpi
ENTRYPOINT ["/ciadpi"]
