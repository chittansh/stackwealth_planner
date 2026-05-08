"""/api/news — list + append."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..skills.news import affected_clients_for_item, list_news, seed_news

router = APIRouter()


@router.get("")
async def list_route() -> JSONResponse:
    items = list_news()
    out = []
    for it in items:
        affected = await affected_clients_for_item(it)
        out.append({**it, "affected": affected})
    return JSONResponse(content={"items": out})


@router.post("")
async def append(request: Request) -> JSONResponse:
    body = await request.json() if (await request.body()) else {"items": []}
    incoming = []
    for it in body.get("items") or []:
        incoming.append(
            {
                "id": it.get("id") or str(uuid4()),
                "title": it.get("title") or "(untitled)",
                "summary": it.get("summary") or "",
                "sectors": it.get("sectors") or [],
                "isins": it.get("isins") or [],
                "asset_class": it.get("asset_class") or "macro",
                "published_at": it.get("published_at")
                or datetime.now(timezone.utc).isoformat(),
            }
        )
    seed_news(list_news() + incoming)
    return JSONResponse(
        content={"ok": True, "added": len(incoming), "total": len(list_news())}
    )
