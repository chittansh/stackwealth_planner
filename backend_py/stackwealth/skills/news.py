"""
News relevance — port of skills/news/index.ts.
"""
from __future__ import annotations

from typing import Any

from ..db import get_plan, list_all_households
from ..types import PlanState

_STORE: list[dict] = []


def seed_news(items: list[dict]) -> None:
    _STORE.clear()
    _STORE.extend(items)


def list_news() -> list[dict]:
    return sorted(list(_STORE), key=lambda i: i.get("published_at", ""), reverse=True)


def score_item_for_plan(item: dict, plan: PlanState) -> dict:
    score = 0.0
    reasons: list[str] = []

    isins = set()
    for h in plan.mutual_funds:
        if h.isin:
            isins.add(h.isin)
    for h in plan.equity_stocks:
        if h.isin:
            isins.add(h.isin)
    direct_hits = [i for i in (item.get("isins") or []) if i in isins]
    if direct_hits:
        score += min(0.6, len(direct_hits) * 0.25)
        reasons.append(f"direct holding ({len(direct_hits)})")

    all_names = [
        (h.fund_name or "").lower() for h in plan.mutual_funds
    ] + [(h.stock_name or "").lower() for h in plan.equity_stocks]
    sector_hits = [s for s in (item.get("sectors") or []) if any(s.lower() in n for n in all_names)]
    if sector_hits:
        score += min(0.3, len(sector_hits) * 0.1)
        reasons.append(f"sector overlap ({', '.join(sector_hits)})")

    eq = (
        plan.computed.allocation.recommended_allocation.equity if plan.computed.allocation else 50
    )
    if item.get("asset_class") == "equity" and eq >= 50:
        score += 0.2
        reasons.append("high equity exposure")
    if item.get("asset_class") == "macro":
        score += 0.1
        reasons.append("macro")

    return {
        "relevance": round(max(0.0, min(1.0, score)), 2),
        "rationale": " · ".join(reasons) if reasons else "no direct exposure",
    }


async def relevance_for_household(args: dict[str, Any]) -> dict:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"items": []}
    scored = []
    for it in _STORE:
        s = score_item_for_plan(it, plan)
        scored.append({"news_id": it.get("id"), "title": it.get("title"), **s})
    scored.sort(key=lambda x: -x["relevance"])
    return {"items": scored[: args.get("top_k") or 5]}


async def affected_clients_for_item(item: dict) -> list[dict]:
    ids = await list_all_households()
    out: list[dict] = []
    for hid in ids:
        plan = await get_plan(hid)
        if not plan:
            continue
        s = score_item_for_plan(item, plan)
        if s["relevance"] >= 0.15:
            out.append(
                {
                    "household_id": hid,
                    "name": plan.personal_details.full_name or hid,
                    **s,
                }
            )
    out.sort(key=lambda x: -x["relevance"])
    return out
