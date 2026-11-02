// Cloudflare Worker: прокси Bot API для бота канала (см. DEPLOY.md, «Telegram-бот канала»).
// С сервера Telegram недоступен целиком, а Cloudflare открывается, поэтому бот
// ходит сюда (TG_API_BASE=https://<воркер>.workers.dev), а воркер — в api.telegram.org.
// Пропускаем только /bot<токен>/<метод>, чтобы воркер не стал открытым прокси.
export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (!/^\/bot\d+:[\w-]+\/\w+$/.test(url.pathname)) {
      return new Response("not found", { status: 404 });
    }
    const upstream = "https://api.telegram.org" + url.pathname + url.search;
    return fetch(upstream, {
      method: request.method,
      headers: { "Content-Type": request.headers.get("Content-Type") || "application/json" },
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    });
  },
};
