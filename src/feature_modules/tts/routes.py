from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Literal
from .service import synthesize_and_optionally_save
from fastapi.responses import Response, JSONResponse

router = APIRouter(prefix="/tts", tags=["tts"])

class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to synthesize")
    voice: Optional[str] = Field(None, description="Logical voice name; provider maps to concrete voice")
    format: Literal["mp3", "opus", "wav"] = Field("mp3", description="Audio format")
    speed: Optional[float] = Field(1.0, ge=0.5, le=2.0, description="Playback speed multiplier")
    pitch: Optional[int] = Field(0, ge=-12, le=12, description="Semitone shift (provider support varies)")
    provider: Literal["openai"] = Field("openai", description="TTS backend provider")
    session_id: Optional[str] = Field(None, description="Optional session to attach saved audio to")
    save: bool = Field(True, description="If true, persist and return a /files/{id}/content URL")

@router.post("/speak")
async def speak(req: SpeakRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required")
    if len(text) > 8000:
        raise HTTPException(status_code=413, detail="Text too long (max 8000 chars)")

    result = await synthesize_and_optionally_save(
        text=text,
        voice=req.voice,
        fmt=req.format,
        speed=req.speed,
        pitch=req.pitch,
        provider=req.provider,
        session_id=req.session_id,
        save=req.save,
    )
    # If not saving, return raw bytes for immediate playback
    if not req.save and "bytes" in result:
        media = {
            "mp3": "audio/mpeg",
            "opus": "audio/ogg",
            "wav": "audio/wav",
        }.get(req.format, "audio/mpeg")
        return Response(content=result["bytes"], media_type=media)
    return JSONResponse(result)
