# TikTok Downloader Bot

Telegram-бот на [aiogram 3](https://docs.aiogram.dev/), который скачивает видео и фото-слайдшоу из TikTok **без вотермарки** — работает через публичное API [tikwm.com](https://tikwm.com).

## Возможности

- Скачивание TikTok-видео без вотермарки
- Поддержка фото-слайдшоу (TikTok photo mode)
- Поддержка коротких ссылок (`vt.tiktok.com`, `vm.tiktok.com`)
- Файлы стримятся напрямую в Telegram, ничего не сохраняется на диск сервера
- Премиум-эмодзи в интерфейсе (для пользователей с Telegram Premium)

## Как пользоваться

1. Открой TikTok
2. Выбери видео или фото
3. Нажми «Поделиться» → «Копировать ссылку»
4. Пришли ссылку боту

## Установка и запуск

### 1. Установи Docker (если ещё не установлен)

```bash
apt update
apt install ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt update
apt install docker-compose-plugin
```

Проверка:
```bash
docker compose version
```

### 2. Клонировать репозиторий

```bash
git clone https://github.com/Kisya123/Tiktok-saver-bot.git
cd Tiktok-saver-bot
```

### 3. Настроить токен

Создай файл `.env` в корне проекта:

```bash
echo "BOT_TOKEN=твой_токен_от_BotFather" > .env
```

Токен получить у [@BotFather](https://t.me/BotFather) командой `/newbot`.

### 4. Запуск через Docker (рекомендуется)

```bash
docker compose up -d --build
docker compose logs -f
```

В логах должна появиться строка `Start polling` без ошибок — бот запущен.

### 5. Запуск без Docker (альтернатива)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python bot.py
```

### 6. (Опционально) Inline-режим

Чтобы бот работал через `@имя_бота ссылка` в любом чате — включи inline-режим у [@BotFather](https://t.me/BotFather):
```
/setinline
```
выбери бота, укажи любой placeholder-текст.

## Структура проекта

```
.
├── bot.py               # основной код бота
├── requirements.txt     # зависимости Python
├── Dockerfile            # сборка образа
├── docker-compose.yml   # запуск контейнера
└── .env                 # токен бота (не коммитить!)
```

## Стек

- Python 3.12
- [aiogram 3](https://github.com/aiogram/aiogram)
- [aiohttp](https://github.com/aio-libs/aiohttp)
- [tikwm.com API](https://tikwm.com) — скачивание видео/фото без вотермарки

## Лицензия

MIT
