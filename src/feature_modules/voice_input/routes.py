from fastapi import APIRouter, UploadFile, File, Form, Header, Request
from src.feature_modules.voice_input.schemas import TranscribeResponse
from src.feature_modules.voice_input.services import transcribe_request

router = APIRouter(prefix="/stt", tags=["stt"])

@router.post("/transcribe", response_model=TranscribeResponse)
async def post_transcribe(
    request: Request,
    audio: UploadFile = File(..., description="Audio file (≤5MB, ≤60s)"),
    lang: str | None = Form(None, description="BCP47 or short code; e.g., vi-VN"),
    tenant_id: str | None = Form(None),
    x_client_id: str | None = Header(None, convert_underscores=False),
    x_access_key: str | None = Header(None, convert_underscores=False),
):
    """
    Stateless voice typing → text. No session_id required.
    """
    return await transcribe_request(
        request=request,
        upload=audio,
        lang=lang,
        tenant_id=tenant_id,
        x_client_id=x_client_id,
        x_access_key=x_access_key,
    )
