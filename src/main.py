from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from .db.mongo import connect, disconnect

# Public
from .routes.session import router as session_router
from .routes.admin_auth import router as admin_auth_router

# User-protected
from .routes.chat import router as chat_router
from .routes.files import router as files_router
from .AI_tool_call_modules.info_search.routes import router as info_search_router
from .feature_modules.voice_input.routes import router as stt_router
from .feature_modules.tts.routes import router as tts_router
from .feature_modules.file_content.routes import router as file_content_router

# Admin/debug (portal-protected via admin JWT)
from .feature_modules.admin_add_ticket_type.routes.admin_prompts import router as admin_prompts_router
from .feature_modules.admin_add_ticket_type.routes.admin_prompts_files import router as admin_prompts_files_router
from .routes.debug_picker import router as debug_picker_router
from .routes.debug_actor import router as debug_actor_router
from .feature_modules.admin_add_ticket_type.routes.admin_ticket_types_simple import router as admin_simple_ticket
from .routes.notifications import router as notifications_router
from .routes.admin_conversations import router as admin_conversations_router
from .routes.user_ws import router as user_ws_router
from .security.deps import (
    enforce_sid_binding,
    session_alive_guard,
    file_access_guard,
    admin_guard,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    try:
        yield
    finally:
        await disconnect()


app = FastAPI(lifespan=lifespan)

# CORS (tighten in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public
app.include_router(session_router)
# Admin auth (login/logout)
app.include_router(admin_auth_router)

# Protected (JWT + session binding + session not expired)
_protect = [Depends(enforce_sid_binding), Depends(session_alive_guard)]
app.include_router(chat_router, dependencies=_protect)
app.include_router(files_router, dependencies=_protect)
app.include_router(info_search_router, dependencies=_protect)
app.include_router(stt_router, dependencies=_protect)
app.include_router(tts_router, dependencies=_protect)

# File preview: require ownership + session alive (so old sessions cannot fetch files)
app.include_router(
    file_content_router,
    dependencies=[Depends(file_access_guard), Depends(session_alive_guard)],
)

# Admin/debug: protected by admin JWT (admin portal)
_admin_protect = [Depends(admin_guard)]
app.include_router(admin_prompts_router, dependencies=_admin_protect)
app.include_router(admin_prompts_files_router, dependencies=_admin_protect)
app.include_router(debug_picker_router, dependencies=_admin_protect)
app.include_router(debug_actor_router, dependencies=_admin_protect)
app.include_router(admin_simple_ticket, dependencies=_admin_protect)
app.include_router(notifications_router, dependencies=_admin_protect)
app.include_router(admin_conversations_router)
app.include_router(user_ws_router)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def healthz():
    return {"ok": True}
