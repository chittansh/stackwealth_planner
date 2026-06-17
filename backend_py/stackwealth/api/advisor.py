"""/api/advisor — dashboard endpoints."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..db import get_plan, list_all_households, list_households_page
from ..skills.news import list_news, score_item_for_plan
from ..types import PlanState

router = APIRouter()


def _biggest_gap(p: PlanState) -> str:
    if not p.computed.freedom_score:
        return "risk profile not set"
    pillars = p.computed.freedom_score.pillars.model_dump()
    lowest = min(pillars.items(), key=lambda kv: kv[1])
    if lowest is None:
        return "—"
    label_map = {
        "liquidity": "liquidity weak",
        "debt": "debt heavy",
        "investment": "investment thin",
        "discipline": "savings rate low",
        "risk": "insurance gap",
    }
    return f"{label_map.get(lowest[0], lowest[0])} ({lowest[1]:.0f}/100)"


def _humanize(d: datetime) -> str:
    now = datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    diff = now - d
    m = round(diff.total_seconds() / 60)
    if m < 1:
        return "just now"
    if m < 60:
        return f"{m} min ago"
    h = round(m / 60)
    if h < 24:
        return f"{h} hr ago"
    days = round(h / 24)
    return f"{days} day{'s' if days != 1 else ''} ago"


@router.get("/clients")
async def clients(limit: int = 25, offset: int = 0) -> JSONResponse:
    """Paginated client list. Default page size 25 — the previous N-roundtrip
    serial scan against `get_plan` for every household was the source of the
    slow initial advisor load. Now Postgres handles the ORDER BY + LIMIT +
    OFFSET server-side and we fetch the page's plans concurrently."""
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))

    ids, total = await list_households_page(limit, offset)
    news = list_news()

    # Fetch the page's plans in parallel — biggest single win.
    plans = await asyncio.gather(*(get_plan(hid) for hid in ids))

    rows = []
    for hid, p in zip(ids, plans):
        if not p:
            continue
        fs = p.computed.freedom_score.final_score if p.computed.freedom_score else None
        news_count = sum(1 for n in news if score_item_for_plan(n, p)["relevance"] >= 0.15)
        try:
            d = datetime.fromisoformat(p.last_updated_at.replace("Z", "+00:00"))
        except Exception:
            d = datetime.now(timezone.utc)
        rows.append(
            {
                "household_id": hid,
                "name": p.personal_details.full_name or hid,
                "freedom_score": fs,
                "headline": p.computed.headline_amount_at_horizon or None,
                "biggest_gap": _biggest_gap(p),
                "last_activity": _humanize(d),
                "news_count": news_count,
            }
        )
    return JSONResponse(
        content={
            "rows": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(rows) < total,
        },
        # 15-second client cache. Browser-side caching means a click into a
        # plan and back to /advisor/clients skips the round-trip entirely.
        # Short enough that fresh writes are visible within seconds.
        headers={"Cache-Control": "private, max-age=15"},
    )


@router.get("/highlights")
async def highlights() -> JSONResponse:
    """Cross-household highlight strip. Was serial (`await get_plan` in a
    for-loop) which scaled linearly with client count and was the main
    cause of the slow /advisor/clients initial paint. Now fans out the
    plan-fetches with asyncio.gather and adds a short cache header so a
    user navigating between dashboard tabs doesn't hammer the endpoint."""
    ids = await list_all_households()
    news = list_news()
    plans = await asyncio.gather(*(get_plan(hid) for hid in ids))

    items: list[dict] = []
    for hid, p in zip(ids, plans):
        if not p:
            continue
        fs = p.computed.freedom_score.final_score if p.computed.freedom_score else 0
        if fs > 0 and fs < 50:
            items.append(
                {
                    "kind": "score_drop",
                    "client": p.personal_details.full_name or hid,
                    "household_id": hid,
                    "text": (
                        f"{p.personal_details.full_name or hid} — Freedom Score "
                        f"{fs:.0f}/100, lowest pillar {_biggest_gap(p)}"
                    ),
                }
            )
        hot = [n for n in news if score_item_for_plan(n, p)["relevance"] >= 0.4]
        if hot:
            items.append(
                {
                    "kind": "news_alert",
                    "client": p.personal_details.full_name or hid,
                    "household_id": hid,
                    "text": (
                        f"{len(hot)} high-relevance news item{'s' if len(hot) > 1 else ''}"
                        f" affect {p.personal_details.full_name or hid}"
                    ),
                }
            )
    m = datetime.now().month  # 1..12
    if m in (1, 2, 3):
        items.insert(
            0,
            {"kind": "tax_window", "text": "FY-end window — review LTCG headroom across all clients."},
        )
    return JSONResponse(
        content={"items": items},
        headers={"Cache-Control": "private, max-age=30"},
    )
