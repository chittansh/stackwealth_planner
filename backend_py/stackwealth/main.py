"""FastAPI app — mirror of TS index.ts. Mounts every route the frontend calls."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .api import (
    advisor,
    chat,
    excel,
    feedback,
    household,
    knowledge,
    news,
    plan,
    report,
    scenario,
    skill,
    upload,
)
from .db import close_db, init_db

app = FastAPI(title="stackwealth-planner-backend", version="0.1.0")


@app.on_event("startup")
async def _on_startup() -> None:
    # Bootstrap the Postgres schema if DATABASE_URL is set. Safe to call
    # on every restart — every CREATE TABLE is IF NOT EXISTS.
    # **Fire-and-forget** so a slow first-time Postgres connection (5-15s
    # for `.flycast` DNS + IPv6 negotiation) doesn't delay uvicorn opening
    # port 4000. Fly's proxy gives up on the machine after ~10s of port
    # 4000 being unreachable, so blocking startup on Postgres = 503s.
    import asyncio
    asyncio.create_task(init_db())


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    await close_db()

# CORS — allow the Next.js frontend (and the deployed prod origin via env).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_ORIGIN or "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Open a Langfuse trace around calculation-triggering API calls (canvas widgets,
# the computed-Excel engine, scenarios, report) so the granular calc spans emitted
# deep inside the compute functions land somewhere. Streaming endpoints are
# excluded: /api/chat self-traces, and /api/upload wraps its own stream.
_CALC_TRACE_PREFIXES = ("/api/skill", "/api/excel", "/api/scenario", "/api/report")


@app.middleware("http")
async def _calc_trace_middleware(request, call_next):
    path = request.url.path
    if not path.startswith(_CALC_TRACE_PREFIXES):
        return await call_next(request)
    from .tracing import trace_root

    segs = [p for p in path.split("/") if p]
    hid = next((p for p in reversed(segs) if p.startswith("h_")), segs[-1] if segs else None)
    surface = segs[1] if len(segs) > 1 else "api"
    with trace_root(
        f"api {request.method} /{'/'.join(segs[:3])}",
        user_id=hid,
        tags=["api", surface],
        metadata={"path": path, "method": request.method},
    ):
        return await call_next(request)


@app.get("/")
async def root() -> dict:
    return {"name": "stackwealth-planner-backend", "status": "ok"}


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


app.include_router(chat.router, prefix="/api/chat")
app.include_router(plan.router, prefix="/api/plan")
app.include_router(upload.router, prefix="/api/upload")
app.include_router(scenario.router, prefix="/api/scenario")
app.include_router(skill.router, prefix="/api/skill")
app.include_router(advisor.router, prefix="/api/advisor")
app.include_router(household.router, prefix="/api/household")
app.include_router(knowledge.router, prefix="/api/knowledge")
app.include_router(news.router, prefix="/api/news")
app.include_router(report.router, prefix="/api/report")
app.include_router(feedback.router, prefix="/api/feedback")
app.include_router(excel.router, prefix="/api/excel")
