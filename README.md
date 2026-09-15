HrParser (Не доделан)
Что это

Внутренний сайт HR-команды: сам собирает анкеты соискателей из Telegram, SuperJob, LinkedIn и hh.ru по заданным ключевым словам и показывает их в общей ленте с реалтайм-обновлением, статусами и комментариями.

Где лежит проект

- Сервер — этот Linux-каталог, /srv/forter/HrParser, ветка main

Как проходит один цикл сбора

1. Планировщик просыпается раз в POLL_INTERVAL_SECONDS — app/worker/scheduler.py
2. Берёт все активные поиски (SearchQuery.status == active)
3. Для каждого источника фильтрует, какие поиски вообще выбрали этот источник (SearchQuery.sources, пусто = все)
4. Источник ищет новое, отдаёт (поиск, запись) — app/sources/*.py
5. Дедупликация по sender_id или нечёткому сходству текста (rapidfuzz) — app/services/dedup.py
6. Запись кандидата/апдейта в БД — app/services/ingest.py
7. Рассылка всем открытым вкладкам по WebSocket — app/realtime.py

Ядро (app/)

- main.py — точка входа, поднимает роутеры, запускает фоновый планировщик через lifespan
- config.py — все настройки (pydantic-settings, читает .env)
- db.py — SQLAlchemy engine/session
- models.py — таблицы: users, search_queries, telegram_channels, candidates, candidate_entries, comments, source_seen_entries
- auth.py / deps.py — хеширование пароля, проверка сессии
- realtime.py — ConnectionManager для WebSocket, in-process (без Redis)
- services/dedup.py — дедуп кандидатов
- services/ingest.py — приём сырой записи в кандидата/апдейт

Роутеры (app/routers/)

- auth.py — /login, /logout
- feed.py — / (лента), смена статуса, карточка кандидата, удаление
- searches.py — /searches — создание поиска, выбор источников, пауза/закрытие
- channels.py — /channels — общий пул Telegram-каналов
- comments.py — комментарии под карточкой
- ws.py — /ws/feed

Источники (app/sources/)

- base.py — интерфейс Source, реестр SOURCE_CHOICES (ключи для выбора источников в поиске)
- telegram_source.py — Telethon, сканирует все каналы из пула
- superjob_source.py — официальный API SuperJob (платно, ~72 000 ₽/мес)
- superjob_scraper_source.py — бесплатный скрапер публичного поиска резюме через Vision (антидетект-браузер, Playwright по CDP)
- linkedin_source.py — неофициальная библиотека linkedin-api, логин email/пароль
- hh_source.py — официальный OAuth API hh.ru, нужна платная «База резюме»
- hh_scraper_source.py — бесплатный скрапер публичного поиска резюме hh.ru, свой отдельный Vision-профиль

Доступ

Одна роль, без иерархии — просто email/пароль. Self-signup нет, пользователей создаёт CLI-скрипт:
python scripts/create_user.py email "Имя" пароль

Переменные окружения (ключевые)

- SECRET_KEY — подпись сессионных cookie
- DATABASE_URL — Postgres (прод) или SQLite (локально)
- TELEGRAM_API_ID / TELEGRAM_API_HASH — my.telegram.org, плюс разовый scripts/telegram_login.py
- SUPERJOB_CLIENT_ID/SECRET, SUPERJOB_LOGIN/PASSWORD — платный API SuperJob
- LINKEDIN_EMAIL/PASSWORD — неофициальный доступ
- HH_CLIENT_ID/SECRET, HH_ACCESS_TOKEN/REFRESH_TOKEN — OAuth hh.ru
- HH_REQUEST_DELAY_SECONDS, HH_MAX_SEARCHES_PER_CYCLE — защита hh.ru-аккаунта от бана
- VISION_API_HOST/PORT/TOKEN, VISION_FOLDER_ID/PROFILE_ID — скрапер SuperJob через Vision
- HH_VISION_FOLDER_ID/PROFILE_ID, HH_SCRAPER_CAPTCHA_WAIT_SECONDS — скрапер hh.ru через Vision
- POLL_INTERVAL_SECONDS, DEDUP_SIMILARITY_THRESHOLD — частота опроса, порог дедупа