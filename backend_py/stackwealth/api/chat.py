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
from ..db import (
    _acquire_conn,
    get_plan,
    load_chat_history,
    save_chat_message,
)
from ..skills.excel_plan import recompute_excel
from ..validator import collect_numbers, validate_assistant_text

router = APIRouter()

# Tools that edit the plan — after a turn that calls any of these, we recompute
# the plan through the firm's Excel engine so the canvas reflects the RM's change
# with the firm's own calculations (not the in-platform Python approximation).
_MUTATION_TOOLS = {"plan_set", "plan_add", "plan_remove", "plan_assumption", "lumpsum_add"}


# The frontend appends an agent-only annotation to the user's chat text when
# files are uploaded ("[Uploaded files (already processed by the intake
# pipeline — DO NOT re-call intake_ingest): ...]"). That block is context FOR
# THE LLM — it must never be shown back to the user. Strip it before persisting
# and when serving history (so already-stored blobs render clean on reopen).
_UPLOAD_ANNOTATION_RE = re.compile(
    r"\n*\[Uploaded files \(already processed by the intake pipeline.*", re.DOTALL
)


def _clean_user_message(text: str | None) -> str:
    if not text:
        return ""
    return _UPLOAD_ANNOTATION_RE.sub("", text).strip()


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


@router.get("/{id}/conversations")
async def list_conversations(id: str) -> dict:
    """List every conversation for this household: chat_id, derived
    title (first user message, truncated), last activity timestamp.
    Sorted most-recent-first so the FE can default to the top entry on
    open. Empty list when DB is unconfigured (dev / local) — the FE
    falls back to its localStorage cache."""
    async with _acquire_conn() as conn:
        if conn is None:
            return {"conversations": []}
        rows = await conn.fetch(
            """
            SELECT
                chat_id,
                MAX(created_at) AS last_active,
                MIN(id) FILTER (WHERE role = 'user') AS first_user_id,
                COUNT(*) AS message_count
            FROM chat_messages
            WHERE household_id = $1
            GROUP BY chat_id
            ORDER BY last_active DESC
            LIMIT 100
            """,
            id,
        )
        # Pull each conversation's first user text in one round-trip.
        titles: dict[str, str] = {}
        first_ids = [r["first_user_id"] for r in rows if r["first_user_id"] is not None]
        if first_ids:
            title_rows = await conn.fetch(
                "SELECT id, text FROM chat_messages WHERE id = ANY($1::bigint[])",
                first_ids,
            )
            id_to_text = {r["id"]: r["text"] for r in title_rows}
            for r in rows:
                t = _clean_user_message(id_to_text.get(r["first_user_id"]))
                if t:
                    line = t.strip().split("\n", 1)[0]
                    titles[r["chat_id"]] = line[:60] + ("…" if len(line) > 60 else "")
        return {
            "conversations": [
                {
                    "chat_id": r["chat_id"],
                    "title": titles.get(r["chat_id"]) or "New chat",
                    "last_active": r["last_active"].isoformat() if r["last_active"] else None,
                    "message_count": r["message_count"],
                }
                for r in rows
            ]
        }


@router.get("/{id}/history")
async def get_history(id: str, chat_id: Optional[str] = None, limit: int = 500) -> dict:
    """Return chronological message history for a (household, chat) pair.
    Defaults to chat_id='main' to match the save path. Used by the FE
    to populate the chat panel when the user opens a household."""
    messages = await load_chat_history(
        household_id=id, chat_id=chat_id or "main", limit=limit
    )
    # Retroactively strip the agent-only upload annotation from any user
    # messages already persisted with it, so reopened chats render clean.
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "user" and m.get("text"):
            m["text"] = _clean_user_message(m["text"])
    return {"chat_id": chat_id or "main", "messages": messages}


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
    # Clean, user-facing version persisted to history (filename-bearing when
    # the FE supplies it). The full `message` — with the agent-only upload
    # annotation — still drives the LLM turn below.
    display_message: str = _clean_user_message(body.get("display_message") or message)

    seen_numbers: set[str] = set()
    prior_plan = await get_plan(household_id)
    if prior_plan:
        collect_numbers(prior_plan.model_dump(mode="python"), seen_numbers)

    # Persist the CLEAN user message ASAP so a mid-turn disconnect or LLM error
    # doesn't drop the input from history. Assistant text is saved after
    # the LLM returns (below, after `validated` is computed).
    if display_message.strip():
        await save_chat_message(
            household_id=household_id,
            chat_id=chat_id or "main",
            role="user",
            text=display_message,
        )

    async def event_stream() -> AsyncIterator[dict]:
        yield {"event": "status", "data": "thinking"}
        try:
            final_text = ""
            added_paths: set[str] = set()  # plan_add target paths seen this turn
            plan_mutated = False  # any plan-editing tool called this turn
            async for ev in run_planner_turn(
                household_id=household_id, chat_id=chat_id, message=message
            ):
                kind = ev["event"]
                if kind == "tool_call":
                    collect_numbers(ev["data"].get("args"), seen_numbers)
                    name = ev["data"].get("name")
                    if name in _MUTATION_TOOLS:
                        plan_mutated = True
                    if name == "plan_add":
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
                # Persist the assistant turn so history survives reload /
                # browser switch / backend redeploy. Failure is swallowed
                # inside save_chat_message — don't fail the user-visible
                # request over a transient PG hiccup.
                await save_chat_message(
                    household_id=household_id,
                    chat_id=chat_id or "main",
                    role="assistant",
                    text=validated,
                )

            # If the RM edited the plan this turn, recompute through the firm's
            # Excel engine so the canvas shows the change with the firm's own
            # calculations. Emit a final tool_result so the frontend refreshes
            # the canvas off the recomputed (Excel) numbers.
            if plan_mutated:
                yield {"event": "status", "data": "recomputing"}
                try:
                    await recompute_excel(household_id)
                except Exception as e:
                    print(f"[chat] excel recompute failed: {e}")
                yield {
                    "event": "tool_result",
                    "data": json.dumps(
                        {"id": "excel_recompute", "name": "excel_recompute", "result": {"ok": True}}
                    ),
                }
            yield {"event": "done", "data": "ok"}
        except Exception as err:
            yield {"event": "error", "data": json.dumps({"message": str(err)})}

    # sep="\n" — the TS frontend's parser splits on `\n\n`. sse-starlette
    # defaults to `\r\n` which the parser doesn't recognize, dropping every
    # event silently. Force LF to match the frontend's expectation.
    return EventSourceResponse(event_stream(), sep="\n")
