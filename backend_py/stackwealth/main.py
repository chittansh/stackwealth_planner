"""FastAPI app — mirror of TS index.ts. Mounts every route the frontend calls."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .api import (
    advisor,
    chat,
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
    await init_db()


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
