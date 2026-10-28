# instagram-agent

Агент для просмотра и анализа Instagram-аккаунта.

## Планы

- Получение данных аккаунта (посты, Reels, сторис, статистика) через Instagram Graph API
- Анализ охватов, вовлечённости и лучшего времени публикации
- Отчёты и рекомендации по контенту

## Структура

```
src/instagram_agent/
  config.py      настройки из .env
  graph_api.py   клиент Instagram Graph API
  analysis.py    анализ публикаций и отчёт
  recommend.py   рекомендации по контенту от Claude
  cli.py         команды выгрузки и анализа
  telegram_bot.py  Telegram-бот для отчётов
tests/           тесты
data/            локальные выгрузки (не коммитятся)
```

## Установка

```bash
python3 -m venv .venv && source .venv/bin/activate
```

```bash
pip install -e '.[dev]'
```

```bash
cp .env.example .env
```

## Как получить токен

Нужен профессиональный аккаунт Instagram (Business или Creator).

1. Создайте приложение на [developers.facebook.com](https://developers.facebook.com/apps) и добавьте продукт **Instagram**.
2. Проще всего выбрать вариант **API setup with Instagram login**. Добавьте свой аккаунт и сгенерируйте токен с правами `instagram_business_basic` и `instagram_business_manage_insights`.
3. Вставьте токен в `INSTAGRAM_ACCESS_TOKEN`, оставьте `INSTAGRAM_API_HOST=graph.instagram.com`.

Если используете вход через Facebook (страница Facebook связана с Instagram), укажите `INSTAGRAM_API_HOST=graph.facebook.com` и `INSTAGRAM_BUSINESS_ACCOUNT_ID`. Нужны права `instagram_basic`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`.

## Использование

Каждая команда сохраняет JSON в `data/`.

```bash
instagram-agent profile                    # профиль и число подписчиков
```

```bash
instagram-agent media --limit 50 --insights  # публикации и Reels со статистикой
```

```bash
instagram-agent stories                    # активные сторис (последние 24 часа)
```

```bash
instagram-agent insights --days 28         # статистика аккаунта за период (до 30 дней)
```

## Анализ постов

```bash
instagram-agent analyze --fetch
```

Выгружает свежие посты со статистикой и строит отчёт `data/report-*.md`. Без `--fetch` берётся последняя выгрузка `media-*.json` из `data/` (или файл из `--file`).

Что в отчёте:
- вовлечённость: (лайки + комментарии + сохранения + репосты) / охват; без статистики — к подписчикам;
- сравнение форматов: Reels, карусели, фото, видео;
- лучшие дни недели и время публикации (часовой пояс — `--tz` или `INSTAGRAM_TIMEZONE`);
- влияние длины подписи и количества хэштегов, частые хэштеги;
- лучшие и слабые посты, динамика вовлечённости, частота публикаций;
- краткие выводы (только по группам от 3 постов).

## Рекомендации от Claude

```bash
instagram-agent recommend --fetch --goal "больше заявок на консультации"
```

Строит отчёт, передаёт его вместе с подписями и метриками постов в Claude (`claude-opus-5-5`) и сохраняет ответ в `data/recommendations-*.md`. Нужен `ANTHROPIC_API_KEY` в `.env` (ключ — на [platform.claude.com](https://platform.claude.com/)). `--goal` необязателен: с ним рекомендации подчинены цели аккаунта.

В ответе: что работает и что нет, какие темы, хуки и призывы заходят, 5–7 приоритетных действий, 5 идей постов с хуками и план на неделю.

Один запуск — один запрос к Claude; стоимость зависит от числа постов (подписи длиннее 1500 символов обрезаются).

## Telegram-бот

Бот присылает отчёты и рекомендации в Telegram — по команде и раз в неделю.

1. Создайте бота у [@BotFather](https://t.me/BotFather) и впишите токен в `TELEGRAM_BOT_TOKEN`.
2. Запустите бота и отправьте ему любую команду — он ответит ID вашего чата.
3. Впишите этот ID в `TELEGRAM_ALLOWED_CHAT_IDS` и перезапустите бота. Остальным чатам бот данные не отдаёт.

```bash
instagram-agent-bot
```

Команды:
- `/report` — краткая сводка (выводы, лучшие посты) и полный отчёт файлом;
- `/recommend [цель]` — рекомендации от Claude, например `/recommend больше заявок`;
- `/profile` — профиль и число подписчиков;
- `/help` — справка.

Еженедельный отчёт: `TELEGRAM_REPORT_SCHEDULE=mon 10:00` (день `mon`…`sun`, время в `INSTAGRAM_TIMEZONE`). Пустое значение выключает рассылку. Если бот был выключен в момент рассылки и включился позже чем через пару часов, отчёт за этот день пропускается.

Бот работает, пока запущен процесс, — держите его на компьютере, который не выключается, или на сервере (например, через `systemd`, `tmux` или `screen`).

## Тесты

```bash
pytest
```
