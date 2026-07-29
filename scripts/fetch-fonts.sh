#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Самохост JetBrains Mono: тянет вариативный woff2 из Google Fonts в
# frontend/fonts/ и печатает готовый блок @font-face для styles.css.
#
# Зачем: <link> на fonts.googleapis.com блокировал первую отрисовку, а сами
# файлы ехали с fonts.gstatic.com — два чужих хоста в критическом пути, у
# российских провайдеров регулярно медленные. Вариативный шрифт = один файл на
# подмножество (вместо 4 начертаний × N подмножеств).
#
# Запускать вручную из корня репозитория при обновлении шрифта:
#   bash scripts/fetch-fonts.sh
# В рантайме сайт Google Fonts больше не дёргает.
# ---------------------------------------------------------------------------
set -euo pipefail

# Современный UA — иначе Google отдаёт ttf/woff вместо woff2
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
SRC='https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@100..800&display=swap'
DIR="frontend/fonts"
OUT="$DIR/jetbrains-mono.generated.css"

# Подмножества: cyrillic+latin нужны всегда, *-ext браузер скачает только если
# на странице реально встретятся такие символы (за это отвечает unicode-range).
SUBSETS="cyrillic cyrillic-ext latin latin-ext"

mkdir -p "$DIR"
css=$(curl -fsS -A "$UA" "$SRC")

: > "$OUT"
for sub in $SUBSETS; do
  url=$(printf '%s\n' "$css" | awk -v s="/* $sub */" 'index($0,s){f=1} f && /src:/{print; exit}' \
        | grep -oE 'https://[^)]+\.woff2')
  range=$(printf '%s\n' "$css" | awk -v s="/* $sub */" 'index($0,s){f=1} f && /unicode-range:/{print; exit}' \
          | sed 's/.*unicode-range: *//; s/;.*//')
  if [ -z "$url" ] || [ -z "$range" ]; then
    echo "!! подмножество $sub не найдено в ответе Google — пропускаю" >&2
    continue
  fi
  file="jetbrains-mono-$sub.woff2"
  curl -fsS -o "$DIR/$file" "$url"
  printf '  %-28s %7d B\n' "$file" "$(wc -c < "$DIR/$file")" >&2
  cat >> "$OUT" <<EOF
@font-face {
  font-family: "JetBrains Mono";
  font-style: normal;
  font-weight: 100 800;          /* вариативный: одно начертание на все веса */
  font-display: swap;
  src: url("/fonts/$file") format("woff2");
  unicode-range: $range;
}
EOF
done

echo >&2
echo "Готово. Блок @font-face: $OUT" >&2
echo "Его содержимое должно лежать в начале frontend/styles.css (отдельный файл" >&2
echo "= лишний блокирующий запрос, поэтому инлайним в styles.css)." >&2
