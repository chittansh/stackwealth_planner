"""
/api/chat — SSE streaming chat endpoint.

Emits events the existing TS frontend expects: status / tool_call /
tool_result / trace / message / done / error. The validator runs on the
final text, using numbers from the prior plan + every tool result observed
this turn.
"""
from __future__ import annotations

import json
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ..agent.planner import clear_convo, hydrate_convo, run_planner_turn
from ..db import get_plan
from ..validator import collect_numbers, validate_assistant_text

router = APIRouter()


@router.post("/{id}/reset")
async def reset(id: str, chat_id: Optional[str] = None) -> dict:
    clear_convo(id, chat_id)
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
            async for ev in run_planner_turn(
                household_id=household_id, chat_id=chat_id, message=message
            ):
                kind = ev["event"]
                if kind == "tool_call":
                    collect_numbers(ev["data"].get("args"), seen_numbers)
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
