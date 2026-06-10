"""
/api/chat — SSE streaming chat endpoint.

Emits events the existing TS frontend expects: status / tool_call /
tool_result / trace / message / done / error. The validator runs on the
final text, using numbers from the prior plan + every tool result observed
this turn.
"""
from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ..agent.planner import clear_convo_db, hydrate_convo, run_planner_turn
from ..db import get_plan
from ..validator import collect_numbers, validate_assistant_text

router = APIRouter()


def _validate_list_claims(
    text: str,
    *,
    plan_goals_count: int,
    plan_mfs_count: int,
    plan_stocks_count: int,
    plan_persons_count: int,
    added_paths: set[str],
) -> str:
    """Catch the specific hallucination where the agent narrates list items
    (goals, mutual funds, equity stocks, persons) that it never called
    `plan_add` for. The canvas reads from these lists directly, so a
    narrated-but-not-added item shows up as "No items yet" in the UI even
    though the chat claims it exists.

    Rule: if the assistant text contains a phrase like `Goals: ...` or
    `Mutual funds: ...` listing names, AND the corresponding plan list is
    empty AND no `plan_add(path='financial_goals' | 'mutual_funds' | ...)`
    happened this turn, prepend a system warning to the assistant message.
    """
    warnings: list[str] = []
    lower = text.lower()
    checks = [
        # (pattern in text, plan count, add path the agent should have hit, friendly_label)
        (r"\bgoals?\s*:", plan_goals_count, "financial_goals", "goals"),
        (r"\bmutual funds?\s*:", plan_mfs_count, "mutual_funds", "mutual funds"),
        (r"\bequity stocks?\s*:|\bstocks?\s*:", plan_stocks_count, "equity_stocks", "equity stocks"),
        (r"\bpersons?\s*:|\bfamily\s*:", plan_persons_count, "assumptions.persons", "persons"),
    ]
    for pattern, count, add_path, label in checks:
        if not re.search(pattern, lower):
            continue
        if count > 0:
            continue
        if add_path in added_paths:
            continue
        warnings.append(label)

    if not warnings:
        return text

    notice = (
        "⚠ The agent narrated "
        + ", ".join(warnings)
        + " above but didn't actually `plan_add` them this turn — the canvas "
        "still shows zero. Ask the agent to add them properly, or re-state "
        "them yourself so the agent emits the correct tool calls."
    )
    return f"{text}\n\n{notice}"


@router.post("/{id}/reset")
async def reset(id: str, chat_id: Optional[str] = None) -> dict:
    await clear_convo_db(id, chat_id)
    return {"ok": True}


@router.post("/{id}/hydrate")
async def hydrate(id: str, request: Request, chat_id: Optional[str] = None) -> dict:
    body = await request.json()
    turns = body.get("turns") or []
    hydrate_convo(id, chat_id, turns)
    return {"ok": True, "restored": len(turns)}


@router.post("")
async def chat(request: Request) -> EventSourceResponse:
    body = await request.json()
    household_id: str = body["household_id"]
    chat_id: Optional[str] = body.get("chat_id")
    message: str = body.get("message") or ""

    seen_numbers: set[str] = set()
    prior_plan = await get_plan(household_id)
    if prior_plan:
        collect_numbers(prior_plan.model_dump(mode="python"), seen_numbers)

    async def event_stream() -> AsyncIterator[dict]:
        yield {"event": "status", "data": "thinking"}
        try:
            final_text = ""
            added_paths: set[str] = set()  # plan_add target paths seen this turn
            async for ev in run_planner_turn(
                household_id=household_id, chat_id=chat_id, message=message
            ):
                kind = ev["event"]
                if kind == "tool_call":
                    collect_numbers(ev["data"].get("args"), seen_numbers)
                    if ev["data"].get("name") == "plan_add":
                        path = (ev["data"].get("args") or {}).get("path")
                        if isinstance(path, str):
                            added_paths.add(path)
                    yield {"event": "tool_call", "data": json.dumps(ev["data"])}
                elif kind == "tool_result":
                    collect_numbers(ev["data"].get("result"), seen_numbers)
                    yield {"event": "tool_result", "data": json.dumps(ev["data"])}
                elif kind == "trace":
                    yield {"event": "trace", "data": json.dumps(ev["data"])}
                elif kind == "_final_text":
                    final_text = ev["data"]
                elif kind == "error":
                    yield {"event": "error", "data": json.dumps(ev["data"])}
                    return

            validated = validate_assistant_text(final_text or "", seen_numbers)
            # Catch narrated-but-not-added list items (goals / MFs / stocks /
            # persons). The post-turn plan is the source of truth — if the
            # canvas would render "No items yet" for a section the chat just
            # claimed to populate, surface that mismatch as a notice.
            post_plan = await get_plan(household_id)
            if post_plan is not None:
                validated = _validate_list_claims(
                    validated,
                    plan_goals_count=len(post_plan.financial_goals or []),
                    plan_mfs_count=len(post_plan.mutual_funds or []),
                    plan_stocks_count=len(post_plan.equity_stocks or []),
                    plan_persons_count=len(post_plan.assumptions.persons or []),
                    added_paths=added_paths,
                )
            # Suppress empty assistant messages on the wire. They show up when
            # the LLM ends a turn with thinking-only / tool-only content and
            # no text block — the frontend would otherwise render a blank
            # PLANNER card. The `done` event still fires so the client moves
            # past the in-flight state.
            if validated.strip():
                yield {
                    "event": "message",
                    "data": json.dumps({"role": "assistant", "text": validated}),
                }
            yield {"event": "done", "data": "ok"}
        except Exception as err:
            yield {"event": "error", "data": json.dumps({"message": str(err)})}

    # sep="\n" — the TS frontend's parser splits on `\n\n`. sse-starlette
    # defaults to `\r\n` which the parser doesn't recognize, dropping every
    # event silently. Force LF to match the frontend's expectation.
    return EventSourceResponse(event_stream(), sep="\n")
