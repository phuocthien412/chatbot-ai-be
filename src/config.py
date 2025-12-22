from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    app_env: str = Field("dev", alias="APP_ENV")
    app_host: str = Field("0.0.0.0", alias="APP_HOST")
    app_port: int = Field(8000, alias="APP_PORT")

    mongodb_uri: str = Field(..., alias="MONGODB_URI")
    mongodb_db: str = Field("chatbot_ai", alias="MONGODB_DB")

    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_model: str = Field(..., alias="OPENAI_MODEL")
    # Optional per-feature model overrides (fall back to OPENAI_MODEL if unset)
    openai_model_actor: Optional[str] = Field(None, alias="OPENAI_MODEL_ACTOR")
    openai_model_picker: Optional[str] = Field(None, alias="OPENAI_MODEL_PICKER")
    openai_model_stt: Optional[str] = Field(None, alias="OPENAI_MODEL_STT")
    openai_model_ticket_gen: Optional[str] = Field(None, alias="OPENAI_MODEL_TICKET_GEN")
    openai_model_rag: Optional[str] = Field(None, alias="OPENAI_MODEL_RAG")
    openai_model_vision: Optional[str] = Field(None, alias="OPENAI_MODEL_VISION")

    openai_model_tts: Optional[str] = Field(None, alias="OPENAI_MODEL_TTS")
    tts_default_format: str = Field(None, alias="TTS_DEFAULT_FORMAT")
    openai_tts_voice: str = Field(None, alias="OPENAI_TTS_VOICE")

    prompt_char_budget: int = Field(120_000, alias="PROMPT_CHAR_BUDGET")
    single_message_char_limit: int = Field(20_000, alias="SINGLE_MESSAGE_CHAR_LIMIT")
    request_timeout_seconds: int = Field(30, alias="REQUEST_TIMEOUT_SECONDS")

    # --- JWT (new) ---
    # JWT secret is REQUIRED; fail fast if missing.
    jwt_secret: str = Field(..., alias="JWT_SECRET")
    jwt_issuer: Optional[str] = Field(None, alias="JWT_ISSUER")
    jwt_ttl_seconds: Optional[int] = Field(None, alias="JWT_TTL_SECONDS")
    admin_jwt_ttl_seconds: Optional[int] = Field(None, alias="ADMIN_JWT_TTL_SECONDS")

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
