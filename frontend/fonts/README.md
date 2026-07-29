# JetBrains Mono (самохост)

Файлы `.woff2` здесь — вариативный JetBrains Mono (`wght 100..800`), выкачанный
с Google Fonts скриптом `scripts/fetch-fonts.sh`. Обновить: запустить скрипт из
корня репозитория и перенести содержимое `jetbrains-mono.generated.css` в начало
`frontend/styles.css` (отдельным CSS-файлом держать нельзя — это лишний
блокирующий запрос в критическом пути отрисовки).

Подмножества и что качает браузер (по `unicode-range`):

| файл | размер | когда качается |
|---|---|---|
| `jetbrains-mono-cyrillic.woff2` | 12 КБ | всегда (русский интерфейс) |
| `jetbrains-mono-latin.woff2` | 40 КБ | всегда (латиница, цифры, пунктуация) |
| `jetbrains-mono-cyrillic-ext.woff2` | 2 КБ | редкие кириллические символы |
| `jetbrains-mono-latin-ext.woff2` | 15 КБ | диакритика, символы валют |

Символы `▲ ▼ ▸ ✕` в шрифте отсутствуют (их нет ни в одном подмножестве Google) —
они и раньше, и сейчас рисуются фоллбэком из `font-family` в `styles.css`.

Лицензия: SIL Open Font License 1.1 — https://github.com/JetBrains/JetBrainsMono
