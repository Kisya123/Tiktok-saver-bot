import asyncio
import logging
import os
import re
import uuid

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    MessageEntity,
    InputMediaPhoto,
    URLInputFile,
    InlineQuery,
    InlineQueryResultVideo,
    InlineQueryResultPhoto,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

TIKTOK_URL_RE = re.compile(
    r"(https?://(?:www\.|vt\.|vm\.)?tiktok\.com/\S+)", re.IGNORECASE
)

# ---- Премиум-эмодзи ----
EMOJI_WAVE = ("👋", "5258029071207505708")
EMOJI_DOWNLOAD = ("⬇️", "4967477144973214631")
EMOJI_COMPUTER = ("🖥", "6019608871088167009")
EMOJI_HOURGLASS = ("😭", "5345778951031658558")
EMOJI_CHECK = ("✅", "5386748326240611247")
EMOJI_CROSS = ("❌", "4958526153955476488")


def build_message(parts: list):
    """
    parts: список строк или (emoji_char, custom_emoji_id) кортежей.
    Возвращает (text, entities) для отправки с премиум-эмодзи.
    """
    text = ""
    entities = []
    for part in parts:
        if isinstance(part, tuple):
            emoji_char, emoji_id = part
            offset = len(text.encode("utf-16-le")) // 2
            text += emoji_char
            length = len(emoji_char.encode("utf-16-le")) // 2
            entities.append(
                MessageEntity(
                    type="custom_emoji",
                    offset=offset,
                    length=length,
                    custom_emoji_id=emoji_id,
                )
            )
        else:
            text += part
    return text, entities


WELCOME_PARTS = [
    EMOJI_WAVE, " Привет!\n\n",
    EMOJI_DOWNLOAD, " Я скачиваю видео и фото из TikTok без вотермарки прямо в Telegram\n\n",
    EMOJI_COMPUTER, " Как пользоваться:\nЯ думаю ты сам знаешь.",
]


@dp.message(CommandStart())
async def start_handler(message: Message):
    text, entities = build_message(WELCOME_PARTS)
    await message.answer(text, entities=entities)


async def fetch_tikwm(url: str) -> dict | None:
    api_url = "https://www.tikwm.com/api/"
    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, data={"url": url, "hd": 1}) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if data.get("code") != 0:
                return None
            return data.get("data")


@dp.message(F.text.regexp(TIKTOK_URL_RE))
async def tiktok_handler(message: Message):
    match = TIKTOK_URL_RE.search(message.text)
    if not match:
        return

    url = match.group(1)

    status_text, status_entities = build_message([EMOJI_HOURGLASS, " Скачиваю..."])
    status_msg = await message.answer(status_text, entities=status_entities)

    try:
        data = await fetch_tikwm(url)
    except Exception:
        logging.exception("tikwm request failed")
        err_text, err_entities = build_message(
            [EMOJI_CROSS, " Не получилось обратиться к сервису. Попробуй позже."]
        )
        await status_msg.edit_text(err_text, entities=err_entities)
        return

    if not data:
        err_text, err_entities = build_message(
            [EMOJI_CROSS, " Не удалось получить видео. Проверь ссылку."]
        )
        await status_msg.edit_text(err_text, entities=err_entities)
        return

    done_text, done_entities = build_message([EMOJI_CHECK, " Скачано!"])

    try:
        # Фото-слайдшоу (TikTok photo mode)
        if data.get("images"):
            media = [InputMediaPhoto(media=URLInputFile(img)) for img in data["images"][:10]]
            # caption с entities можно поставить только на первый элемент группы
            media[0] = InputMediaPhoto(
                media=media[0].media,
                caption=done_text,
                caption_entities=done_entities,
            )
            await message.answer_media_group(media)
        else:
            video_url = data.get("hdplay") or data.get("play")
            if not video_url:
                err_text, err_entities = build_message(
                    [EMOJI_CROSS, " Ссылка на видео не найдена."]
                )
                await status_msg.edit_text(err_text, entities=err_entities)
                return
            await message.answer_video(
                URLInputFile(video_url),
                caption=done_text,
                caption_entities=done_entities,
            )
    except Exception:
        logging.exception("failed to send media")
        err_text, err_entities = build_message(
            [EMOJI_CROSS, " Не удалось отправить файл (возможно, слишком большой)."]
        )
        await status_msg.edit_text(err_text, entities=err_entities)
        return

    await status_msg.delete()


# ---- Inline-режим: @имя_бота ссылка_на_тикток ----
@dp.inline_query(F.query.regexp(TIKTOK_URL_RE))
async def inline_tiktok_handler(inline_query: InlineQuery):
    match = TIKTOK_URL_RE.search(inline_query.query)
    if not match:
        await inline_query.answer([], cache_time=1)
        return

    url = match.group(1)

    try:
        data = await fetch_tikwm(url)
    except Exception:
        logging.exception("tikwm request failed (inline)")
        await inline_query.answer([], cache_time=1)
        return

    if not data:
        await inline_query.answer([], cache_time=1)
        return

    result_id = str(uuid.uuid4())
    thumb_url = data.get("cover") or data.get("origin_cover") or ""

    results = []

    if data.get("images"):
        # Фото-слайдшоу: инлайн поддерживает только одиночные результаты,
        # поэтому отдаём первое фото
        first_image = data["images"][0]
        results.append(
            InlineQueryResultPhoto(
                id=result_id,
                photo_url=first_image,
                thumbnail_url=thumb_url or first_image,
                caption="✅ Скачано!",
            )
        )
    else:
        video_url = data.get("hdplay") or data.get("play")
        if video_url:
            results.append(
                InlineQueryResultVideo(
                    id=result_id,
                    video_url=video_url,
                    mime_type="video/mp4",
                    thumbnail_url=thumb_url,
                    title=data.get("title") or "TikTok видео",
                    caption="✅ Скачано!",
                )
            )

    await inline_query.answer(results, cache_time=1, is_personal=True)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    