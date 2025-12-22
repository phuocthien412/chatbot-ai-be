from pydantic import BaseModel

class TranscribeResponse(BaseModel):
    text: str
    confidence: float | None = None
    lang: str
    duration_ms: int | None = None
    engine: str
