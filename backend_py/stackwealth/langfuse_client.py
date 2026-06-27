"""
Langfuse tracing — Python port of agent/langfuse.ts.

Tracing model:
  - One persistent trace per (household_id, chat_id). Trace ID is generated
    once on the first turn and reused on subsequent turns (langfuse upsert
    via `id=existing`). Whole conversation lives in ONE trace.
  - Each turn = a span under that trace.
  - Each tool call + the LLM generation nest under the turn span.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from . import config

_client: Any = None
_initialized = False


def get_langfuse() -> Optional[Any]:
    """Lazy-init. Returns None if keys missing — SDK becomes a no-op."""
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True

    if not config.LANGFUSE_PUBLIC_KEY or not config.LANGFUSE_SECRET_KEY:
        print("[langfuse] keys not set — tracing disabled")
        _client = None
        return None

    try:
        from langfuse import Langfuse  # type: ignore

        _client = Langfuse(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY,
            host=config.LANGFUSE_BASE_URL,
            # Batch observations — granular calc tracing emits dozens of spans
            # per turn, so flushing after every one (flush_at=1) thrashes. We
            # flush explicitly at the end of each turn / request instead.
            flush_at=25,
        )
        print(f"[langfuse] tracing enabled (host={config.LANGFUSE_BASE_URL})")
    except Exception as e:  # pragma: no cover
        print(f"[langfuse] failed to init: {e}")
        _client = None
    return _client


def session_id_for(household_id: str, chat_id: Optional[str]) -> str:
    return f"{household_id}::{chat_id or 'main'}"


def transcript_for_trace(messages: list[Any]) -> list[dict]:
    """Render the agent's message list into a JSON-friendly transcript so
    Langfuse displays the full conversation as the trace input/output."""
    out = []
    for m in messages:
        # Support both LangChain BaseMessage objects and plain dicts.
        role = getattr(m, "type", None) or (m.get("role") if isinstance(m, dict) else None)
        if role == "human":
            role = "user"
        elif role == "ai":
            role = "assistant"
        content = getattr(m, "content", None)
        if content is None and isinstance(m, dict):
            content = m.get("content")
        tool_calls = getattr(m, "tool_calls", None) or (
            m.get("tool_calls") if isinstance(m, dict) else None
        )
        entry: dict = {"role": role, "content": content}
        if tool_calls:
            entry["tool_calls"] = tool_calls
        out.append(entry)
    return out


def flush_langfuse() -> None:
    lf = get_langfuse()
    if lf is None:
        return
    try:
        lf.flush()
    except Exception as e:
        print(f"[langfuse] flush failed: {e}")


# ── per-chat trace registry ───────────────────────────────────────────────


class TraceMeta:
    __slots__ = ("trace_id", "turn_number")

    def __init__(self) -> None:
        self.trace_id: str = str(uuid4())
        self.turn_number: int = 0


_registry: dict[str, TraceMeta] = {}


def trace_meta(key: str) -> tuple[TraceMeta, bool]:
    """Returns (meta, is_first_turn). Increments turn_number on each call."""
    is_first = key not in _registry
    if is_first:
        _registry[key] = TraceMeta()
    meta = _registry[key]
    meta.turn_number += 1
    return meta, is_first


def reset_trace(key: str) -> None:
    _registry.pop(key, None)
