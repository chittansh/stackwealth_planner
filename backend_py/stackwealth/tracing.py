"""
Granular calculation tracing on top of Langfuse.

The chat agent already produces a trace per conversation, a span per turn, and a
span per tool call (see agent/planner.py). This module makes the *inside* of the
calculations observable too: every CFP step (per-goal FV/SIP, retirement corpus,
the three retirement cases, insurance), and each top-level engine (risk,
allocation, freedom, tax, debt, scenarios, Monte-Carlo) emit nested spans with
their inputs and outputs.

How it nests
------------
A contextvar holds the current parent observation `(trace_id, observation_id)`.
`span(...)` opens a child observation under it and, for its lifetime, makes
itself the parent — so calls nest naturally. Entry points establish the root:

  - the chat planner sets it to the turn span (set_context / reset_context);
  - HTTP endpoints / the upload pipeline use `trace_root(...)` to open a fresh
    trace so canvas- and upload-triggered calculations are captured too.

Everything degrades to a cheap no-op when Langfuse is disabled or no trace is
active, so calculation code can wrap freely without guards.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
from functools import wraps
from typing import Any, Optional

from .langfuse_client import flush_langfuse, get_langfuse

# (trace_id, parent_observation_id | None)
_ctx: contextvars.ContextVar[Optional[tuple[str, Optional[str]]]] = contextvars.ContextVar(
    "lf_calc_ctx", default=None
)

# Cap on serialized input/output payloads per observation, and on the number of
# per-step spans a single calculation may emit (a runaway-loop backstop).
_MAX_PAYLOAD = 6000
_MAX_STEPS = 200


def set_context(trace_id: str, observation_id: Optional[str]) -> contextvars.Token:
    """Point subsequent spans at `(trace_id, observation_id)`. Returns a token to
    pass to `reset_context`."""
    return _ctx.set((trace_id, observation_id))


def reset_context(token: contextvars.Token) -> None:
    try:
        _ctx.reset(token)
    except Exception:
        pass


def is_active() -> bool:
    return _ctx.get() is not None and get_langfuse() is not None


def _jsonable(v: Any) -> Any:
    """Best-effort JSON-friendly + size-bounded rendering of a payload."""
    if v is None:
        return None
    try:
        from pydantic import BaseModel

        if isinstance(v, BaseModel):
            v = v.model_dump(mode="python", exclude_none=True)
    except Exception:
        pass
    if hasattr(v, "__dict__") and not isinstance(v, (dict, list, tuple, str, int, float, bool)):
        try:
            v = vars(v)
        except Exception:
            v = str(v)
    try:
        s = json.dumps(v, default=str)
    except Exception:
        s = str(v)
    if len(s) <= _MAX_PAYLOAD:
        return v
    return {"_truncated": True, "chars": len(s), "preview": s[:_MAX_PAYLOAD]}


class _Handle:
    """Thin wrapper around a Langfuse observation (or None when tracing is off)."""

    __slots__ = ("_obs",)

    def __init__(self, obs: Any) -> None:
        self._obs = obs

    def set_output(self, output: Any) -> None:
        if self._obs is not None:
            try:
                self._obs.update(output=_jsonable(output))
            except Exception:
                pass

    def update(self, **kwargs: Any) -> None:
        if self._obs is not None:
            try:
                self._obs.update(**kwargs)
            except Exception:
                pass


@contextlib.contextmanager
def span(name: str, *, input: Any = None, metadata: Optional[dict] = None):
    """Open a child span under the current parent. No-op when tracing is off or
    no trace is active. Within the block, this span becomes the parent so nested
    `span(...)` calls form a tree."""
    lf = get_langfuse()
    ctx = _ctx.get()
    if lf is None or ctx is None:
        yield _Handle(None)
        return
    trace_id, parent_id = ctx
    obs = None
    try:
        obs = lf.span(
            trace_id=trace_id,
            parent_observation_id=parent_id,
            name=name,
            input=_jsonable(input),
            metadata=metadata,
        )
    except Exception:
        obs = None
    token = _ctx.set((trace_id, getattr(obs, "id", None) or parent_id))
    handle = _Handle(obs)
    try:
        yield handle
    finally:
        _ctx.reset(token)
        if obs is not None:
            try:
                obs.end()
            except Exception:
                pass


def event(name: str, *, input: Any = None, output: Any = None, metadata: Optional[dict] = None) -> None:
    """Emit a point-in-time observation (a calculation step) under the current
    parent. Cheaper than a span; use for leaf formula steps."""
    lf = get_langfuse()
    ctx = _ctx.get()
    if lf is None or ctx is None:
        return
    trace_id, parent_id = ctx
    try:
        lf.event(
            trace_id=trace_id,
            parent_observation_id=parent_id,
            name=name,
            input=_jsonable(input),
            output=_jsonable(output),
            metadata=metadata,
        )
    except Exception:
        pass


def emit_steps(steps: list[dict], *, label_key: str = "label") -> None:
    """Emit a list of `_trace`-shaped calculation steps
    ({label, formula, inputs, value, unit}) as nested events under the current
    span — the formula-by-formula detail of a calculation."""
    if not steps:
        return
    for st in steps[:_MAX_STEPS]:
        if not isinstance(st, dict):
            continue
        nm = str(st.get(label_key) or st.get("formula") or "step")
        event(
            f"· {nm[:80]}",
            input=st.get("inputs"),
            output={k: st.get(k) for k in ("formula", "value", "unit") if st.get(k) is not None},
        )
    if len(steps) > _MAX_STEPS:
        event(f"· … {len(steps) - _MAX_STEPS} more steps omitted")


@contextlib.contextmanager
def trace_root(
    name: str,
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    tags: Optional[list[str]] = None,
    input: Any = None,
):
    """Open a fresh root trace and point the context at it — for entry points
    outside the chat agent (HTTP skill/excel endpoints, the upload pipeline).
    Flushes on exit. No-op when Langfuse is disabled."""
    lf = get_langfuse()
    if lf is None:
        yield None
        return
    tr = None
    try:
        tr = lf.trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata,
            tags=tags,
            input=_jsonable(input),
        )
    except Exception:
        tr = None
    if tr is None:
        yield None
        return
    token = _ctx.set((tr.id, None))
    try:
        yield tr
    finally:
        reset_context(token)
        flush_langfuse()


def traced_calc(name: str):
    """Decorator: wrap a synchronous compute function so it emits a span with its
    return value as output. Input is omitted (callers pass large PlanState
    objects); the granular inputs live in the nested CFP steps instead."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            with span(name) as h:
                result = fn(*args, **kwargs)
                h.set_output(result)
                return result

        return wrapper

    return deco
