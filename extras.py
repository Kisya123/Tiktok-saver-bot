import json
import logging
from collections import OrderedDict
from pathlib import Path
from uuid import uuid4

try:
    from aiogram.types import EphemeralMessageParameters
except ImportError:  # aiogram < 3.31
    EphemeralMessageParameters = None

log = logging.getLogger(__name__)

# ---- Режимы пользователя: что присылать после ссылки ----
MODES = {
    "ask": "❓ Спрашивать каждый раз",
    "media": "🎬 Только медиа",
    "both": "🎬+🎵 Медиа и аудио",
    "audio": "🎵 Только аудио",
}
DEFAULT_MODE = "ask"

SETTINGS_FILE = Path(__file__).with_name("user_modes.json")
_user_modes: dict[str, str] = {}

try:
    _user_modes = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
except FileNotFoundError:
    pass
except Exception:
    log.exception("failed to load %s", SETTINGS_FILE)


def get_mode(user_id: int | None) -> str:
    mode = _user_modes.get(str(user_id), DEFAULT_MODE)
    return mode if mode in MODES else DEFAULT_MODE


def set_mode(user_id: int, mode: str) -> None:
    if mode not in MODES:
        return
    _user_modes[str(user_id)] = mode
    try:
        SETTINGS_FILE.write_text(json.dumps(_user_modes), encoding="utf-8")
    except Exception:
        log.exception("failed to save %s", SETTINGS_FILE)


def ephemeral_supported() -> bool:
    return EphemeralMessageParameters is not None


# ---- Эфемерные сообщения («видит только получатель», только в группах) ----
def ephemeral_for(chat_type: str, user_id: int | None):
    """EphemeralMessageParameters для группы/супергруппы, иначе None (в личке не нужно)."""
    if EphemeralMessageParameters is None or user_id is None:
        return None
    if chat_type not in ("group", "supergroup"):
        return None
    return EphemeralMessageParameters(receiver_user_id=user_id)


# ---- Кэш ответа tikwm, пока пользователь выбирает кнопку (callback_data ≤ 64 байт) ----
_PENDING: OrderedDict[str, dict] = OrderedDict()
_PENDING_MAX = 500


def store_pending(info: dict) -> str:
    key = uuid4().hex[:12]
    _PENDING[key] = info
    while len(_PENDING) > _PENDING_MAX:
        _PENDING.popitem(last=False)
    return key


def get_pending(key: str) -> dict | None:
    return _PENDING.get(key)
