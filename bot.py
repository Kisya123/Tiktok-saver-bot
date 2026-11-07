import asyncio
import logging
import os
import re
import uuid

import aiohttp
import aiogram
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyParameters,
    MessageEntity,
    InputMediaPhoto,
    URLInputFile,
    InlineQuery,
    InlineQueryResultVideo,
    InlineQueryResultPhoto,
)
from dotenv import load_dotenv

try:
    from tg_rich import build_tiktok_message, send_rich
except ImportError:
    # Старая версия aiogram без rich-блоков — работаем по-старому
    logging.getLogger(__name__).warning(
        "rich messages unavailable (update aiogram>=3.31.0), using classic send"
    )
    build_tiktok_message = send_rich = None

from extras import (
    MODES,
    ephemeral_for,
    ephemeral_supported,
    get_mode,
    get_pending,
    set_mode,
    store_pending,
)

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]

logging.basicConfig(level=logging.INFO)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
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

# ---- Премиум-эмодзи в инлайн-кнопках (icon_custom_emoji_id) ----
# Нужен Telegram Premium у владельца бота. None — кнопка с обычным эмодзи в тексте.
# Узнать ID: пришли боту сообщение с премиум-эмодзи, он ответит их ID.
BTN_ICONS = {
    "ask": "5309763270842784848",    # ❓ Спрашивать каждый раз
    "media": EMOJI_DOWNLOAD[1],      # 🎬 Только медиа
    "both": "6255917280224349118",   # 🎬+🎵 Медиа и аудио / С аудио
    "audio": "5271627010681108586",  # 🎵 Только аудио
}


# ---- Скачивание с CDN TikTok: без нормальных заголовков он отвечает 403 ----
DL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": "https://www.tiktok.com/",
}


def tt_file(url: str, filename: str | None = None) -> URLInputFile:
    return URLInputFile(url, headers=DL_HEADERS, filename=filename, timeout=120)


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


def build_caption_with_quote(title: str):
    """
    Оборачивает описание в сворачиваемую цитату (expandable blockquote).
    Возвращает (caption, caption_entities) или (None, None), если описания нет.
    """
    title = (title or "").strip()
    if not title:
        return None, None
    if len(title) > 1024:
        title = title[:1021] + "..."
    length = len(title.encode("utf-16-le")) // 2
    entities = [
        MessageEntity(
            type="expandable_blockquote",
            offset=0,
            length=length,
        )
    ]
    return title, entities


def _btn(label: str, data: str, icon_key: str | None = None, icons: bool = True) -> InlineKeyboardButton:
    """label вида '🎬 Текст'. С иконкой: эмодзи убирается из текста, иконка рисуется отдельно."""
    icon_id = BTN_ICONS.get(icon_key) if (icons and icon_key) else None
    if icon_id and " " in label:
        label = label.split(" ", 1)[1]
        return InlineKeyboardButton(text=label, icon_custom_emoji_id=icon_id, callback_data=data)
    return InlineKeyboardButton(text=label, callback_data=data)


async def send_private(chat_id, user_id, chat_type, thread_id, text, markup_factory):
    """
    Сообщение «только тебе» (эфемерное) в группе; в личке — обычное.
    markup_factory(icons: bool) -> клавиатура. Если Telegram отклонил премиум-иконки — повтор без них.
    """
    kwargs = {"chat_id": chat_id, "text": text}
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    eph = ephemeral_for(chat_type, user_id)
    if eph:
        kwargs["ephemeral_message_parameters"] = eph

    attempts = [True, False] if any(BTN_ICONS.values()) else [False]
    for i, icons in enumerate(attempts):
        try:
            return await bot.send_message(reply_markup=markup_factory(icons), **kwargs)
        except Exception:
            if i == len(attempts) - 1:
                raise
            logging.exception("send with premium button icons failed, retrying without icons")


# ---- /mode: что присылать после ссылки (настройка на пользователя) ----
def mode_keyboard(current: str, icons: bool = True) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(label + (" ✓" if key == current else ""), f"mode:{key}", key, icons)]
            for key, label in MODES.items()
        ]
    )


@dp.message(Command("mode"))
async def mode_handler(message: Message):
    if not message.from_user:
        return

    # Режим — личная настройка, меняется только в личке с ботом; в группах молчим
    if message.chat.type != "private":
        return

    current = get_mode(message.from_user.id)
    await send_private(
        message.chat.id,
        message.from_user.id,
        message.chat.type,
        None,
        f"Что присылать после ссылки?\nСейчас: {MODES[current]}\n\n"
        "Настройка действует везде: и в личке, и в группах.",
        lambda icons: mode_keyboard(current, icons),
    )


@dp.callback_query(F.data.startswith("mode:"))
async def mode_choice_handler(callback: CallbackQuery):
    mode = callback.data.split(":", 1)[1]
    if mode not in MODES:
        await callback.answer()
        return
    set_mode(callback.from_user.id, mode)
    await callback.answer(f"Готово: {MODES[mode]}")
    # В личке сообщение можно обновить; у эфемерного в группе — нельзя, тогда оставляем как есть
    try:
        await callback.message.edit_text(
            f"Что присылать после ссылки?\nСейчас: {MODES[mode]}\n\n"
            "Настройка действует везде: и в личке, и в группах.",
            reply_markup=mode_keyboard(mode),
        )
    except Exception:
        pass


# ---- Отправка результата ----
async def deliver(info: dict, mode: str, status_msg: Message | None = None):
    """mode: media — только медиа, both — медиа + аудио, audio — только аудио."""
    data = info["data"]
    chat_id = info["chat_id"]
    base = {
        "chat_id": chat_id,
        "message_thread_id": info["thread_id"],
        "reply_parameters": ReplyParameters(
            message_id=info["message_id"], allow_sending_without_reply=True
        ),
    }

    async def fail(text_after_emoji: str):
        text, entities = build_message([EMOJI_CROSS, text_after_emoji])
        if status_msg:
            await status_msg.edit_text(text, entities=entities)
        else:
            await bot.send_message(text=text, entities=entities, **base)

    caption, caption_entities = build_caption_with_quote(data.get("title"))
    images = data.get("images") or []
    video_url = None if images else (data.get("hdplay") or data.get("play"))

    music_info = data.get("music_info") or {}
    music_all = music_info.get("play") or data.get("music")
    music_title = music_info.get("title") or "Звук из TikTok"
    music_author = music_info.get("author") or None
    music_duration = music_info.get("duration")
    music_duration = music_duration if isinstance(music_duration, int) else None

    def audio_file():
        return tt_file(music_all, filename=f"{music_title}.mp3")

    # --- только аудио ---
    if mode == "audio":
        if not music_all:
            await fail(" У этого поста нет отдельного звука.")
            return
        try:
            await bot.send_audio(
                audio=audio_file(),
                title=music_title,
                performer=music_author,
                duration=music_duration,
                **base,
            )
        except Exception:
            logging.exception("failed to send audio")
            await fail(" Не удалось отправить аудио.")
            return
        if status_msg:
            await status_msg.delete()
        return

    # --- медиа (+ аудио) ---
    music_url = music_all if mode == "both" else None

    async def classic(raw: bool):
        """Старый способ. raw=True: ссылки отдаём Telegram — он скачивает сам (если у нас 403 от CDN)."""
        src = (lambda u: u) if raw else tt_file
        if images:
            media = [InputMediaPhoto(media=src(img)) for img in images[:10]]
            media[0] = InputMediaPhoto(
                media=media[0].media,
                caption=caption,
                caption_entities=caption_entities,
            )
            await bot.send_media_group(media=media, **base)
        else:
            await bot.send_video(
                video=src(video_url),
                caption=caption,
                caption_entities=caption_entities,
                **base,
            )

        if music_url:
            try:
                await bot.send_audio(
                    audio=music_url if raw else audio_file(),
                    title=music_title,
                    performer=music_author,
                    duration=music_duration,
                    **base,
                )
            except Exception:
                logging.exception("failed to send music")
                # Не критично — просто пропускаем отправку музыки, если не вышло

    try:
        # 1) Одно rich-сообщение: слайдшоу / видео + описание (свёрнуто) + музыка
        try:
            if build_tiktok_message is None:
                raise ImportError("rich messages are not supported by installed aiogram")
            rich_message = build_tiktok_message(
                photos=[tt_file(img) for img in images[:50]] or None,
                video=tt_file(video_url) if video_url else None,
                description=data.get("title"),
                music=audio_file() if music_url else None,
                music_title=music_title,
                music_author=music_author,
                music_duration=music_duration,
            )
            await send_rich(
                bot,
                chat_id,
                rich_message,
                reply_to=info["message_id"],
                thread_id=info["thread_id"],
            )
        except Exception:
            # 2) Старый способ: media group / видео + отдельное аудио
            logging.exception("rich message failed, falling back to classic send")
            try:
                await classic(raw=False)
            except Exception:
                # 3) Последняя попытка: Telegram сам скачивает по ссылкам
                logging.exception("classic send failed, letting Telegram fetch the URLs")
                await classic(raw=True)
    except Exception:
        logging.exception("failed to send media")
        await fail(" Не удалось отправить файл (возможно, слишком большой).")
        return

    if status_msg:
        await status_msg.delete()


# ---- Обработка ссылки ----
@dp.message(F.text.regexp(TIKTOK_URL_RE))
async def tiktok_handler(message: Message):
    match = TIKTOK_URL_RE.search(message.text)
    if not match:
        return

    url = match.group(1)
    user_id = message.from_user.id if message.from_user else None
    mode = get_mode(user_id)

    # В режиме «спрашивать» статуса нет — сначала вопрос, статус ни к чему
    status_msg = None
    if mode != "ask":
        status_text, status_entities = build_message([EMOJI_HOURGLASS, " Скачиваю..."])
        status_msg = await message.answer(status_text, entities=status_entities)

    async def show_error(text_after_emoji: str):
        text, entities = build_message([EMOJI_CROSS, text_after_emoji])
        if status_msg:
            await status_msg.edit_text(text, entities=entities)
        else:
            await message.answer(text, entities=entities)

    try:
        data = await fetch_tikwm(url)
    except Exception:
        logging.exception("tikwm request failed")
        await show_error(" Не получилось обратиться к сервису. Попробуй позже.")
        return

    if not data:
        await show_error(" Не удалось получить видео. Проверь ссылку.")
        return

    if not data.get("images") and not (data.get("hdplay") or data.get("play")):
        await show_error(" Ссылка на видео не найдена.")
        return

    info = {
        "data": data,
        "user_id": user_id,
        "chat_id": message.chat.id,
        "chat_type": message.chat.type,
        "thread_id": message.message_thread_id if message.is_topic_message else None,
        "message_id": message.message_id,
    }

    music_info = data.get("music_info") or {}
    has_music = bool(music_info.get("play") or data.get("music"))

    if mode != "ask":
        await deliver(info, mode, status_msg)
        return

    # Режим «спрашивать»: без звука спрашивать нечего; в группе без эфемерных — не засоряем чат
    in_group = message.chat.type in ("group", "supergroup")
    if not has_music or (in_group and ephemeral_for(message.chat.type, user_id) is None):
        await deliver(info, "media")
        return

    key = store_pending(info)

    def ask_markup(icons: bool) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    _btn("🎬 Только медиа", f"dl:{key}:m", "media", icons),
                    _btn("🎬+🎵 С аудио", f"dl:{key}:b", "both", icons),
                ],
                [_btn("🎵 Только аудио", f"dl:{key}:a", "audio", icons)],
            ]
        )

    try:
        await send_private(
            info["chat_id"], user_id, message.chat.type, info["thread_id"],
            "Хотите скачать с аудио?", ask_markup,
        )
    except Exception:
        logging.exception("failed to send question, sending media only")
        await deliver(info, "media")


@dp.callback_query(F.data.startswith("dl:"))
async def download_choice_handler(callback: CallbackQuery):
    _, key, choice = callback.data.split(":")
    info = get_pending(key)
    if not info:
        await callback.answer("Кнопка устарела — пришли ссылку заново", show_alert=True)
        return
    if callback.from_user.id != info["user_id"]:
        await callback.answer("Это не твоя ссылка", show_alert=True)
        return

    mode = {"m": "media", "b": "both", "a": "audio"}.get(choice)
    if not mode:
        await callback.answer()
        return

    await callback.answer("Скачиваю...")
    # В личке убираем вопрос; эфемерный в группе оставляем — можно нажать ещё вариант
    if info["chat_type"] == "private":
        try:
            await callback.message.delete()
        except Exception:
            pass
    await deliver(info, mode)


# ---- Помощник: пришли сообщение с премиум-эмодзи — бот ответит их ID ----
@dp.message(lambda m: bool(m.entities) and any(e.type == "custom_emoji" for e in m.entities))
async def emoji_id_helper(message: Message):
    ids = [e.custom_emoji_id for e in message.entities if e.type == "custom_emoji"]
    await message.answer("ID премиум-эмодзи:\n" + "\n".join(ids))


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
    caption, caption_entities = build_caption_with_quote(data.get("title"))

    results = []

    if data.get("images"):
        first_image = data["images"][0]
        results.append(
            InlineQueryResultPhoto(
                id=result_id,
                photo_url=first_image,
                thumbnail_url=thumb_url or first_image,
                caption=caption,
                caption_entities=caption_entities,
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
                    caption=caption,
                    caption_entities=caption_entities,
                )
            )

    await inline_query.answer(results, cache_time=1, is_personal=True)


async def setup_commands():
    """Меню команд: /mode видна только в личке, в группах команд нет."""
    try:
        await bot.delete_my_commands()  # общий список (например, из BotFather)
        await bot.delete_my_commands(scope=BotCommandScopeAllGroupChats())
        await bot.set_my_commands(
            [BotCommand(command="mode", description="Что присылать после ссылки")],
            scope=BotCommandScopeAllPrivateChats(),
        )
    except Exception:
        logging.exception("failed to set bot commands")


async def main():
    logging.info(
        "aiogram %s | rich messages: %s | ephemeral messages: %s",
        aiogram.__version__,
        build_tiktok_message is not None,
        ephemeral_supported(),
    )
    await setup_commands()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    