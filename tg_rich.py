from pathlib import Path

from aiogram.types import (
    FSInputFile,
    InputFile,
    InputMediaAudio,
    InputMediaPhoto,
    InputMediaVideo,
    InputRichBlockAudio,
    InputRichBlockDetails,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockSlideshow,
    InputRichBlockVideo,
    InputRichMessage,
    Message,
    ReplyParameters,
    RichBlockCaption,
)

MAX_SLIDES = 50
MAX_DESCRIPTION = 1024


def _media(src: Path | str | InputFile):
    # Path -> локальный файл; str (URL / file_id) и InputFile (например, URLInputFile) — как есть
    return FSInputFile(src) if isinstance(src, Path) else src


def _slideshow_block(
    photos: list[Path | str | InputFile],
    caption: str | None = None,
    spoiler: bool = False,
) -> InputRichBlockSlideshow:
    slides = [
        InputRichBlockPhoto(
            photo=InputMediaPhoto(
                media=_media(photo),
                has_spoiler=spoiler,
                parse_mode=None,
            )
        )
        for photo in photos[:MAX_SLIDES]
    ]
    return InputRichBlockSlideshow(
        blocks=slides,
        caption=RichBlockCaption(text=caption) if caption else None,
    )


def build_photo_slideshow(
    photos: list[Path | str | InputFile],
    caption: str | None = None,
    spoiler: bool = False,
) -> InputRichMessage:
    return InputRichMessage(blocks=[_slideshow_block(photos, caption, spoiler)])


def build_tiktok_message(
    *,
    photos: list[Path | str | InputFile] | None = None,
    video: Path | str | InputFile | None = None,
    description: str | None = None,
    music: Path | str | InputFile | None = None,
    music_title: str | None = None,
    music_author: str | None = None,
    music_duration: int | None = None,
) -> InputRichMessage:
    """
    Одно rich-сообщение: слайдшоу фото ИЛИ видео, под ним сворачиваемое
    описание и аудиоблок с музыкой.
    """
    blocks: list = []

    if photos:
        blocks.append(_slideshow_block(photos))
    elif video:
        blocks.append(
            InputRichBlockVideo(
                video=InputMediaVideo(
                    media=_media(video),
                    supports_streaming=True,
                    parse_mode=None,
                )
            )
        )

    description = (description or "").strip()
    if description:
        if len(description) > MAX_DESCRIPTION:
            description = description[: MAX_DESCRIPTION - 3] + "..."
        blocks.append(
            InputRichBlockDetails(
                summary="Описание",
                blocks=[InputRichBlockParagraph(text=description)],
                is_open=False,
            )
        )

    if music:
        blocks.append(
            InputRichBlockAudio(
                audio=InputMediaAudio(
                    media=_media(music),
                    title=music_title,
                    performer=music_author,
                    duration=music_duration,
                    parse_mode=None,
                )
            )
        )

    return InputRichMessage(blocks=blocks)


async def send_rich(
    bot,
    chat_id: int,
    rich_message: InputRichMessage,
    reply_to: int | None = None,
    thread_id: int | None = None,
):
    return await bot.send_rich_message(
        chat_id=chat_id,
        message_thread_id=thread_id,
        rich_message=rich_message,
        reply_parameters=(
            ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)
            if reply_to
            else None
        ),
        request_timeout=120,
    )


async def send_photo_slideshow(message: Message, photos: list[Path | str | InputFile]):
    return await send_rich(
        message.bot, message.chat.id, build_photo_slideshow(photos), reply_to=message.message_id
    )
