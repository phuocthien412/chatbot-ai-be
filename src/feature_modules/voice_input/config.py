import os
from typing import Set

def _as_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _as_set(name: str, default_csv: str) -> Set[str]:
    raw = os.getenv(name, default_csv)
    return {x.strip().lower() for x in raw.split(",") if x.strip()}

class VoiceInputConfig:
    # Static defaults
    DEFAULT_LANG: str = os.getenv("STT_DEFAULT_LANG", "vi-VN")
    MAX_DURATION_S: int = _as_int("STT_MAX_DURATION_S", 60)
    MAX_BYTES: int = _as_int("STT_MAX_BYTES", 5 * 1024 * 1024)  # 5 MB
    DEBUG_ERRORS: bool = os.getenv("STT_DEBUG_ERRORS", "true").lower() == "true"

    # MIME acceptance (real-world labels)
    ALLOWED_MIME: Set[str] = _as_set(
        "STT_ALLOWED_MIME",
        ",".join([
            "audio/webm","audio/ogg","audio/wav",
            "audio/mpeg","audio/mp3",
            "audio/mp4","audio/x-m4a","audio/aac",
            "video/mp4","application/octet-stream",
        ]),
    )
    ALLOWED_EXT: Set[str] = _as_set(
        "STT_ALLOWED_EXT",
        ".webm,.ogg,.wav,.mp3,.m4a,.aac,.mp4",
    )

    # Rate limits
    PER_IP_PER_MIN: int = _as_int("STT_RATE_PER_IP_PER_MIN", 30)
    PER_CLIENT_PER_MIN: int = _as_int("STT_RATE_PER_CLIENT_PER_MIN", 10)

    # Optional: force ffmpeg transcode to WAV (off by default)
    FORCE_WAV: bool = os.getenv("STT_FORCE_WAV", "false").lower() == "true"

    # -------- dynamic getters --------
    @staticmethod
    def enabled() -> bool:
        return os.getenv("STT_ENABLED", "true").lower() == "true"

    @staticmethod
    def provider_chain() -> list[str]:
        raw = os.getenv("STT_PROVIDER_CHAIN", "openai-4o-mini,openai-4o,whisper-1")
        return [x.strip().lower() for x in raw.split(",") if x.strip()]

    # OpenAI
    @staticmethod
    def openai_api_key() -> str | None:
        return os.getenv("OPENAI_API_KEY")

    @staticmethod
    def openai_api_base() -> str:
        return os.getenv("OPENAI_API_BASE", "https://api.openai.com")

    # Security / multi-tenant
    @staticmethod
    def allowed_access_keys() -> set[str]:
        raw = os.getenv("STT_ACCESS_KEYS", "")
        return {x.strip() for x in raw.split(",") if x.strip()}

    @staticmethod
    def cors_allowed_origins() -> set[str]:
        raw = os.getenv("STT_CORS_ORIGINS", "")
        return {x.strip() for x in raw.split(",") if x.strip()}
