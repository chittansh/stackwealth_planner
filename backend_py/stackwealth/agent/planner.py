"""
Stackwealth planner — LangGraph state machine.

Mirror of the TS planner.ts contract: SAME tool surface, SAME conversation
memory model (per-household-chat, capped at 60 messages), SAME Langfuse
trace structure (one persistent trace per chat, per-turn span, tool spans
nested under the turn).

The frontend's SSE event shape is:
   status     "thinking"
   tool_call  { id, name, args }
   tool_result{ id, name, result }
   trace      { trace_id, observation_id, turn }
   message    { role: 'assistant', text }
   done       "ok"
   error      { message }

`run_planner_turn` is an async generator that yields these as plain dicts;
the chat route wraps each into an SSE frame. This keeps the streaming logic
(LangGraph) decoupled from the wire format.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import Annotated, TypedDict

from .. import config
from ..db import get_plan
from ..langfuse_client import (
    flush_langfuse,
    get_langfuse,
    reset_trace,
    session_id_for,
    trace_meta,
    transcript_for_trace,
)
from ..logging_config import get_logger
from ..tracing import reset_context, set_context

_log = get_logger(__name__)
from .prompt import SYSTEM_PROMPT, render_state_summary
from .tools import make_tools


# ── State ──────────────────────────────────────────────────────────────────


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# ── Graph ──────────────────────────────────────────────────────────────────


_TOOLS = make_tools()


def _build_graph(llm_with_tools: Any) -> Any:
    async def call_model(state: AgentState) -> dict:
        response = await llm_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None)
        if tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(_TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


# ── Conversation memory (per household + chat) ─────────────────────────────


_convo: dict[str, list[BaseMessage]] = {}
# A second dict tracking which conversations have already been hydrated
# from the DB in this process lifetime — without it we'd re-read the
# DB on every turn instead of just the first.
_hydrated_from_db: set[str] = set()
# Track whether a per-message DB persist is even possible (DATABASE_URL
# set). Computed lazily on first turn.
_db_persist_enabled: Optional[bool] = None
MAX_HISTORY_MESSAGES = 60


def _key(household_id: str, chat_id: Optional[str]) -> str:
    return f"{household_id}::{chat_id or 'main'}"


def clear_convo(household_id: str, chat_id: Optional[str] = None) -> None:
    """Synchronous wipe of in-memory state. The HTTP reset endpoint should
    additionally call `clear_convo_db` (async) to wipe the persisted chat
    history."""
    k = _key(household_id, chat_id)
    _convo.pop(k, None)
    _hydrated_from_db.discard(k)
    reset_trace(k)


async def clear_convo_db(household_id: str, chat_id: Optional[str] = None) -> None:
    """Wipe both in-memory and persisted chat history."""
    from ..db import clear_chat_history

    clear_convo(household_id, chat_id)
    try:
        await clear_chat_history(household_id=household_id, chat_id=chat_id or "main")
    except Exception as e:
        _log.warning("planner.db_clear.failed", exc_info=True)


def get_convo(household_id: str, chat_id: Optional[str] = None) -> list[BaseMessage]:
    return _convo.get(_key(household_id, chat_id), [])


def hydrate_convo(
    household_id: str, chat_id: Optional[str], turns: list[dict]
) -> None:
    """Restore client transcript after a backend restart. Plain user/assistant
    text only — tool calls aren't replayed."""
    msgs: list[BaseMessage] = []
    for t in turns[-MAX_HISTORY_MESSAGES:]:
        text = (t.get("text") or "").strip()
        if not text:
            continue
        if t.get("role") == "user":
            msgs.append(HumanMessage(content=f"[household_id={household_id}]\n\n{text}"))
        elif t.get("role") == "assistant":
            msgs.append(AIMessage(content=text))
    k = _key(household_id, chat_id)
    _convo[k] = msgs
    _hydrated_from_db.add(k)  # client explicitly hydrated — don't override from DB
    reset_trace(k)


async def _ensure_db_hydrated(household_id: str, chat_id: Optional[str]) -> list[BaseMessage]:
    """First-touch DB hydration for a conversation. If the in-memory `_convo`
    has no entry for this household/chat (e.g. fresh process after a deploy),
    pull the persisted chat history from Postgres and rebuild
    HumanMessage/AIMessage entries. Runs at most once per (household,chat)
    per process — subsequent turns hit the in-memory cache."""
    from ..db import load_chat_history

    k = _key(household_id, chat_id)
    if k in _hydrated_from_db or k in _convo:
        _hydrated_from_db.add(k)
        return _convo.get(k, [])
    try:
        rows = await load_chat_history(
            household_id=household_id,
            chat_id=chat_id or "main",
            limit=MAX_HISTORY_MESSAGES,
        )
    except Exception as e:
        _log.warning("planner.db_hydrate.failed", extra={"key": k}, exc_info=True)
        rows = []
    msgs: list[BaseMessage] = []
    for r in rows:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        role = r.get("role")
        if role == "user":
            msgs.append(HumanMessage(content=f"[household_id={household_id}]\n\n{text}"))
        elif role == "assistant":
            msgs.append(AIMessage(content=text))
    _convo[k] = msgs
    _hydrated_from_db.add(k)
    return msgs


def _safe_trim(messages: list[BaseMessage], cap: int) -> list[BaseMessage]:
    """Anthropic refuses a request that opens with a tool_result block having
    no preceding tool_use. Find a clean user-message boundary near the cap."""
    if len(messages) <= cap:
        return messages
    start = len(messages) - cap
    while start < len(messages):
        m = messages[start]
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            return messages[start:]
        if isinstance(m, HumanMessage):
            # multi-part content — only safe if no ToolMessage-style blocks
            if not any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in (m.content if isinstance(m.content, list) else [])
            ):
                return messages[start:]
        start += 1
    # Fallback: last user message we can find, or empty.
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return [m]
    return []


# ── Per-turn driver ────────────────────────────────────────────────────────


async def run_planner_turn(
    *,
    household_id: str,
    chat_id: Optional[str],
    message: str,
) -> AsyncIterator[dict[str, Any]]:
    """Async generator yielding SSE-event dicts:
       {"event":"tool_call","data":...} / "tool_result" / "trace" / "message" / "error"
    """
    user_text = (message or "").strip() or "(empty user turn — read state and ask a clarifying question)"
    k = _key(household_id, chat_id)
    # First-touch DB hydration so a deploy + cold start doesn't drop the
    # session's history. After this the in-memory `_convo` is the cache.
    await _ensure_db_hydrated(household_id, chat_id)
    history = _safe_trim(_convo.get(k, []), MAX_HISTORY_MESSAGES)
    user_msg = HumanMessage(content=f"[household_id={household_id}]\n\n{user_text}")

    plan_snapshot = await get_plan(household_id)
    state_section = render_state_summary(plan_snapshot) if plan_snapshot else ""
    dynamic_system = (
        f"{SYSTEM_PROMPT}\n\n## Current PlanState (snapshot for THIS turn)\n\n{state_section}\n\n"
        "If you would call `plan_add` for an entry that already exists in the snapshot, use "
        "`plan_set` on the existing index instead — the server will refuse duplicates."
        if state_section
        else SYSTEM_PROMPT
    )

    if not config.ANTHROPIC_API_KEY:
        yield {"event": "error", "data": {"message": "ANTHROPIC_API_KEY not set"}}
        return

    llm = ChatAnthropic(
        model=config.PLANNER_MODEL or "claude-sonnet-4-6",
        temperature=0.2,
        max_tokens=4096,
        anthropic_api_key=config.ANTHROPIC_API_KEY,
    ).bind_tools(_TOOLS)
    graph = _build_graph(llm)

    # ── Langfuse trace upsert + turn span ──────────────────────────────────
    lf = get_langfuse()
    meta, is_first = trace_meta(k)
    turn = meta.turn_number
    trace = None
    turn_span = None
    generation = None
    if lf is not None:
        try:
            trace_kwargs = dict(
                id=meta.trace_id,
                name=f"chat {household_id}::{chat_id or 'main'}",
                session_id=session_id_for(household_id, chat_id),
                user_id=household_id,
                metadata={
                    "household_id": household_id,
                    "chat_id": chat_id or "main",
                    "model": config.PLANNER_MODEL,
                    "latest_turn": turn,
                },
                tags=["agent", "chat"],
            )
            if is_first:
                trace_kwargs["input"] = {"opening_user_message": user_text}
            trace = lf.trace(**trace_kwargs)
            turn_span = trace.span(
                name=f"turn {turn}: {user_text[:60]}",
                input={
                    "user_message": user_text,
                    "prior_history": transcript_for_trace(history),
                },
                metadata={"turn": turn, "history_length": len(history)},
            )
            generation = turn_span.generation(
                name="planner.langgraph",
                model=config.PLANNER_MODEL,
                model_parameters={"temperature": 0.2},
            )
        except Exception as e:
            _log.warning("planner.langfuse_setup.failed", exc_info=True)

    # Point granular calculation spans (CFP, risk, allocation, …) at this turn,
    # so the math that the tools run nests inside the turn in Langfuse. Reset in
    # the finally below so context never leaks across turns/requests.
    _calc_token = None
    if trace is not None:
        _calc_token = set_context(meta.trace_id, getattr(turn_span, "id", None))

    # Initial graph state — system + history + new user message.
    initial: list[BaseMessage] = [SystemMessage(content=dynamic_system), *history, user_msg]
    final_text = ""
    seen_tool_call_ids: set[str] = set()
    fresh_messages: list[BaseMessage] = []
    tool_spans: dict[str, Any] = {}

    # NOTE: DB persistence of chat messages is owned by the chat API layer
    # (api/chat.py), which saves the cleaned, user-facing `display_message`
    # eagerly and the validated assistant text after the turn. The planner only
    # maintains the in-memory `_convo` (agent memory) below. Saving here too
    # would double every row → history rendering twice on reopen.
    try:
        async for event in graph.astream({"messages": initial}, stream_mode="updates"):
            for node_name, payload in event.items():
                msgs: list[BaseMessage] = payload.get("messages") or []
                for m in msgs:
                    fresh_messages.append(m)

                    # Agent node may return an AIMessage with tool_calls.
                    if isinstance(m, AIMessage):
                        tcs = getattr(m, "tool_calls", None) or []
                        for tc in tcs:
                            tc_id = tc.get("id") or tc.get("name")
                            if tc_id in seen_tool_call_ids:
                                continue
                            seen_tool_call_ids.add(tc_id)
                            yield {
                                "event": "tool_call",
                                "data": {
                                    "id": tc_id,
                                    "name": tc.get("name"),
                                    "args": tc.get("args") or {},
                                },
                            }
                            if turn_span is not None:
                                try:
                                    tool_spans[tc_id] = turn_span.span(
                                        name=f"tool.{tc.get('name')}",
                                        input=tc.get("args") or {},
                                        metadata={"tool_call_id": tc_id, "turn": turn},
                                    )
                                except Exception:
                                    pass
                        # Capture final assistant text when no tool calls.
                        if not tcs:
                            content = m.content
                            if isinstance(content, str):
                                final_text = content
                            elif isinstance(content, list):
                                final_text = "".join(
                                    c.get("text", "") for c in content if isinstance(c, dict)
                                )

                    # Tool node returns ToolMessage(s) — emit results.
                    if isinstance(m, ToolMessage):
                        tc_id = m.tool_call_id
                        try:
                            import json

                            result = json.loads(m.content) if isinstance(m.content, str) else m.content
                        except Exception:
                            result = m.content
                        yield {
                            "event": "tool_result",
                            "data": {
                                "id": tc_id,
                                "name": getattr(m, "name", "") or "",
                                "result": result,
                            },
                        }
                        span = tool_spans.pop(tc_id, None)
                        if span is not None:
                            try:
                                span.end(output=result)
                            except Exception:
                                pass

        # ── Persist conversation memory ────────────────────────────────────
        merged = list(history) + [user_msg] + fresh_messages
        _convo[k] = _safe_trim(merged, MAX_HISTORY_MESSAGES)

        # DB persistence (user + assistant) is handled by api/chat.py — see the
        # note above. Doing it here as well is what caused every message to be
        # stored (and rendered) twice.

        # ── Emit trace pointers + final message ────────────────────────────
        if trace is not None:
            yield {
                "event": "trace",
                "data": {
                    "trace_id": meta.trace_id,
                    "observation_id": getattr(turn_span, "id", None),
                    "turn": turn,
                },
            }
            try:
                if generation is not None:
                    generation.end(output=final_text)
                if turn_span is not None:
                    turn_span.end(output={"assistant_text": final_text})
                trace.update(
                    output={
                        "assistant_text_latest": final_text,
                        "turns": turn,
                        "full_conversation": transcript_for_trace(merged),
                    }
                )
            except Exception as e:
                _log.warning("planner.langfuse_close.failed", exc_info=True)
            flush_langfuse()

        yield {"event": "_final_text", "data": final_text}

    except Exception as err:
        msg = str(err)
        for span in tool_spans.values():
            try:
                span.end(level="ERROR", status_message=msg)
            except Exception:
                pass
        if generation is not None:
            try:
                generation.end(level="ERROR", status_message=msg)
            except Exception:
                pass
        if turn_span is not None:
            try:
                turn_span.end(
                    level="ERROR",
                    status_message=msg,
                    output={"error": msg},
                )
            except Exception:
                pass
        if trace is not None:
            try:
                trace.update(output={"last_error": msg, "turns": turn})
            except Exception:
                pass
        flush_langfuse()
        yield {"event": "error", "data": {"message": msg}}

    finally:
        if _calc_token is not None:
            reset_context(_calc_token)
