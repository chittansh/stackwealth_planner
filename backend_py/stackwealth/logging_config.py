"""
Diagnostic logging — central setup (see .claude/skills/diagnostic-logging).

The whole point: from the log file alone — no debugger, no re-run — anyone can
reconstruct what happened for a single request and pinpoint the root cause. Every
piece below serves the five root-cause questions:

  WHO   — request_id / household_id / chat_id stamped on every line (ContextFilter)
  WHAT  — a clear event name + semantic level
  WHY   — inputs and the decision/branch, passed as structured `extra={...}`
  WHERE — logger name (__name__), func, line, + stack on errors (exc_info=True)
  WHEN  — timestamp + duration_ms on slow paths (log_timing)

Usage:
    from ..logging_config import get_logger, log_timing
    logger = get_logger(__name__)
    logger.info("op.start", extra={"household_id": hid})

Correlation is bound once at the entry point (HTTP middleware / chat turn /
upload / job) via `bind_context(...)`; call sites never thread IDs manually.
"""
from __future__ import annotations

import functools
import json
import logging
import logging.handlers
import os
import re
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Optional
from uuid import uuid4

# ── Correlation context (asyncio-safe via contextvars) ─────────────────────
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
household_id_ctx: ContextVar[str] = ContextVar("household_id", default="-")
chat_id_ctx: ContextVar[str] = ContextVar("chat_id", default="-")


def new_request_id() -> str:
    return uuid4().hex[:16]


def bind_context(
    *,
    request_id: Optional[str] = None,
    household_id: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> list:
    """Set the correlation ids for the current task. Returns reset tokens to pass
    to `reset_context`. Only the ids provided are changed."""
    tokens = []
    if request_id is not None:
        tokens.append((request_id_ctx, request_id_ctx.set(request_id)))
    if household_id is not None:
        tokens.append((household_id_ctx, household_id_ctx.set(household_id)))
    if chat_id is not None:
        tokens.append((chat_id_ctx, chat_id_ctx.set(chat_id)))
    return tokens


def reset_context(tokens: list) -> None:
    for var, tok in reversed(tokens):
        try:
            var.reset(tok)
        except Exception:
            pass


@contextmanager
def logging_context(
    *,
    request_id: Optional[str] = None,
    household_id: Optional[str] = None,
    chat_id: Optional[str] = None,
):
    """Scope correlation ids for the duration of a block (a request, a chat turn,
    an upload, a job)."""
    tokens = bind_context(request_id=request_id, household_id=household_id, chat_id=chat_id)
    try:
        yield
    finally:
        reset_context(tokens)


# ── Principle 1: stamp correlation ids onto every record ───────────────────
class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        record.household_id = household_id_ctx.get()
        record.chat_id = chat_id_ctx.get()
        record.pid = os.getpid()
        return True


# ── Principles 2,4,7: structured, one-line, bounded, flattened ─────────────
MAX_MESSAGE_LENGTH = {"DEBUG": 10000, "INFO": 5000, "WARNING": 5000, "ERROR": 8000}
_DEFAULT_MAX = 5000

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        cap = MAX_MESSAGE_LENGTH.get(record.levelname, _DEFAULT_MAX)
        if len(message) > cap:
            message = message[:cap] + f"... [truncated, was {len(message)} chars]"

        obj = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "func": record.funcName,
            "line": record.lineno,
            "pid": getattr(record, "pid", "-"),
            "request_id": getattr(record, "request_id", "-"),
            "household_id": getattr(record, "household_id", "-"),
            "chat_id": getattr(record, "chat_id", "-"),
            "event": message,
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in obj:
                obj[key] = value
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info).replace("\n", "\\n")
        return json.dumps(obj, default=str, ensure_ascii=False)


class PipeFormatter(logging.Formatter):
    """Human-readable variant for local dev: ts | LEVEL | logger | rid | hid | message | k=v…"""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        cap = MAX_MESSAGE_LENGTH.get(record.levelname, _DEFAULT_MAX)
        if len(message) > cap:
            message = message[:cap] + f"... [truncated, was {len(message)} chars]"
        parts = [
            self.formatTime(record, self.datefmt),
            record.levelname,
            record.name,
            getattr(record, "request_id", "-"),
            getattr(record, "household_id", "-"),
            message,
        ]
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in ("pid", "request_id", "household_id", "chat_id"):
                parts.append(f"{key}={value}")
        line = " | ".join(map(str, parts))
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


# ── Principle 8: mask PII centrally (safety net) ───────────────────────────
_REDACT_KEYS = re.compile(
    r"^(?:password|token|api_?key|authorization|secret|access_?token|"
    r"pan|aadh?aar|account_?number|ifsc|otp|contents_b64|image_?url)$",
    re.IGNORECASE,
)
_PHONE_KEYS = re.compile(r"^(?:phone|mobile|telephone|contact|whatsapp)$", re.IGNORECASE)
_EMAIL_KEYS = re.compile(r"^(?:email|e_?mail)$", re.IGNORECASE)
# Inline India-relevant patterns in free-text messages.
_PHONE_INLINE = re.compile(r"\b(?:\+?91[\-\s]?)?(\d{5})\d{5}\b")
_EMAIL_INLINE = re.compile(r"\b([A-Za-z0-9._%+\-]{1,3})[A-Za-z0-9._%+\-]*@([A-Za-z0-9.\-]+)\b")
_PAN_INLINE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")


def _mask_str_value(v: str, kind: str) -> str:
    if kind == "phone":
        return (v[:-5] + "XXXXX") if len(v) > 5 else "X" * len(v)
    if kind == "email":
        local, _, dom = v.partition("@")
        return (local[:2] + "***@" + dom) if dom else "<redacted>"
    return "<redacted>"


def _mask_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            ks = str(k)
            if _REDACT_KEYS.match(ks):
                out[k] = "<redacted>"
            elif _PHONE_KEYS.match(ks) and isinstance(v, str):
                out[k] = _mask_str_value(v, "phone")
            elif _EMAIL_KEYS.match(ks) and isinstance(v, str):
                out[k] = _mask_str_value(v, "email")
            else:
                out[k] = _mask_obj(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_mask_obj(i) for i in obj]
    return obj


def _mask_message(msg: str) -> str:
    msg = _PHONE_INLINE.sub(r"\g<1>XXXXX", msg)
    msg = _EMAIL_INLINE.sub(r"\1***@\2", msg)
    msg = _PAN_INLINE.sub("<pan>", msg)
    return msg


class PIIMaskFilter(logging.Filter):
    """Mask PII in both extra-fields and the rendered message — one chokepoint so
    a log line added next week is covered without anyone remembering to redact."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.args:
                args = record.args if isinstance(record.args, tuple) else (record.args,)
                record.args = tuple(
                    _mask_obj(a) if isinstance(a, (dict, list)) else a for a in args
                )
            for key, value in list(record.__dict__.items()):
                if key in _RESERVED:
                    continue
                if isinstance(value, (dict, list, tuple)):
                    setattr(record, key, _mask_obj(value))
                elif isinstance(value, str):
                    # Top-level string extras (e.g. extra={"phone": p}) — mask by key.
                    if _REDACT_KEYS.match(key):
                        setattr(record, key, "<redacted>")
                    elif _PHONE_KEYS.match(key):
                        setattr(record, key, _mask_str_value(value, "phone"))
                    elif _EMAIL_KEYS.match(key):
                        setattr(record, key, _mask_str_value(value, "email"))
            msg = record.getMessage()
            masked = _mask_message(msg)
            if masked != msg:
                record.msg, record.args = masked, ()
        except Exception:
            pass  # a masking bug must never break logging
        return True


# ── Principle 6: timing — duration_ms + category as fields ─────────────────
def log_timing(logger: logging.Logger, category: str = "internal"):
    """Async decorator: emit duration_ms + category for the wrapped coroutine,
    and an ERROR with the stack if it raises."""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = await func(*args, **kwargs)
            except Exception:
                ms = round((time.monotonic() - start) * 1000, 1)
                logger.error(
                    f"{func.__name__}.failed",
                    extra={"func": func.__name__, "category": category, "duration_ms": ms},
                    exc_info=True,
                )
                raise
            else:
                ms = round((time.monotonic() - start) * 1000, 1)
                logger.info(
                    f"{func.__name__}.executed",
                    extra={"func": func.__name__, "category": category, "duration_ms": ms},
                )
                return result

        return wrapper

    return decorator


def log_timing_sync(logger: logging.Logger, category: str = "internal"):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = func(*args, **kwargs)
            except Exception:
                ms = round((time.monotonic() - start) * 1000, 1)
                logger.error(
                    f"{func.__name__}.failed",
                    extra={"func": func.__name__, "category": category, "duration_ms": ms},
                    exc_info=True,
                )
                raise
            else:
                ms = round((time.monotonic() - start) * 1000, 1)
                logger.info(
                    f"{func.__name__}.executed",
                    extra={"func": func.__name__, "category": category, "duration_ms": ms},
                )
                return result

        return wrapper

    return decorator


@contextmanager
def timed(logger: logging.Logger, event: str, *, category: str = "internal", **fields):
    """Time an inline block: emits `<event>.done` with duration_ms (or `<event>.failed`
    with the stack). Use for boundaries that aren't their own function."""
    start = time.monotonic()
    try:
        yield
    except Exception:
        ms = round((time.monotonic() - start) * 1000, 1)
        logger.error(f"{event}.failed", extra={**fields, "category": category, "duration_ms": ms}, exc_info=True)
        raise
    else:
        ms = round((time.monotonic() - start) * 1000, 1)
        logger.info(f"{event}.done", extra={**fields, "category": category, "duration_ms": ms})


# ── Principle 9: one central, idempotent setup ─────────────────────────────
def get_logger(name: str) -> logging.Logger:
    """Always `get_logger(__name__)` at module top — never a hardcoded name."""
    return logging.getLogger(name)


_CONFIGURED = False


def setup_logging(
    level: Optional[str] = None,
    fmt: Optional[str] = None,
) -> None:
    """Configure root + app loggers once at startup. Logs to STDOUT so the
    container runtime (Fly) collects it; idempotent (clears handlers) so reload
    doesn't double-log. Format/level come from env:
      STACKWEALTH_LOG_LEVEL  (default INFO)
      STACKWEALTH_LOG_FORMAT (json | pipe; default json in prod, pipe on a TTY)
    """
    global _CONFIGURED
    level = (level or os.getenv("STACKWEALTH_LOG_LEVEL", "INFO")).upper()
    if fmt is None:
        fmt = os.getenv("STACKWEALTH_LOG_FORMAT") or ("pipe" if sys.stderr.isatty() else "json")

    handler = logging.StreamHandler(sys.stdout)
    formatter = (PipeFormatter if fmt == "pipe" else JsonFormatter)(datefmt="%Y-%m-%dT%H:%M:%S")
    handler.setFormatter(formatter)
    handler.addFilter(ContextFilter())   # WHO + WHERE
    handler.addFilter(PIIMaskFilter())   # safety net (after context)

    # Root catches everything; the app namespace gets the level; noisy libraries
    # are turned down so the firehose stays readable.
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)

    app = logging.getLogger("stackwealth")
    app.setLevel(level)
    app.handlers.clear()
    app.propagate = True

    for noisy, lvl in (
        ("httpx", "WARNING"), ("httpcore", "WARNING"), ("openai", "WARNING"),
        ("anthropic", "WARNING"), ("urllib3", "WARNING"), ("asyncio", "WARNING"),
        ("uvicorn.access", "WARNING"),
    ):
        logging.getLogger(noisy).setLevel(lvl)

    _CONFIGURED = True
    app.info("logging.configured", extra={"fmt": fmt, "level": level})
