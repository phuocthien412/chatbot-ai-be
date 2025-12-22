from src.config import settings

class TTSConfig:
    """
    Read defaults from Pydantic Settings (backed by your .env), not os.getenv.
    """

    @staticmethod
    def default_format() -> str:
        # .env key: TTS_DEFAULT_FORMAT
        # falls back to "mp3" if not set
        return getattr(settings, "tts_default_format", None) or "mp3"

    @staticmethod
    def default_voice() -> str:
        # .env key: OPENAI_TTS_VOICE
        # falls back to "alloy" if not set
        return getattr(settings, "openai_tts_voice", None) or "alloy"

    @staticmethod
    def max_chars() -> int:
        # optional; if you later add to Settings, this will pick it up
        val = getattr(settings, "tts_max_chars", None)
        try:
            return int(val) if val is not None else 8000
        except Exception:
            return 8000
