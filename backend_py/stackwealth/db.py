"""
DB client — Postgres-backed when `DATABASE_URL` is set, otherwise an
in-memory store for local dev.

Surface (unchanged across backends):
    await get_plan(household_id)        -> Optional[PlanState]
    await save_plan(plan)               -> None
    await list_all_households()         -> list[str]
    seed_memory(plan)                   -> None   (testing helper)

Plus a Postgres-only chat history surface used by the planner module:
    await save_chat_message(household_id, chat_id, role, text, turn=?)
    await load_chat_history(household_id, chat_id, limit=60)

Schema is one JSONB row per household plus a chat_messages table. The
PlanState round-trips via Pydantic's `model_dump(mode='json')` /
`model_validate` so the DB never holds anything more structured than
plain JSON — drift-tolerant against schema additions.

Connection lifecycle:
    `_pool` is a single asyncpg pool, lazily initialized on first call.
    `init_db()` creates the schema if missing — called from FastAPI's
    `on_startup` so the first request never races the schema bootstrap.
    `close_db()` releases the pool on shutdown.

When `DATABASE_URL` is unset (e.g. local dev without a Postgres), every
call falls back to the in-memory `_memory` dict so existing test paths
keep working.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from .types import PlanState, empty_plan_state


# ── In-memory fallback (no DATABASE_URL) ──────────────────────────────────


_memory: dict[str, PlanState] = {}


# ── Postgres pool (lazy) ──────────────────────────────────────────────────


import asyncio

_pool: Any | None = None  # asyncpg.Pool when initialized
_pool_lock: asyncio.Lock | None = None  # serializes the first create_pool


def _database_url() -> Optional[str]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    # Fly's `.flycast` haproxy was RST'ing plain-TCP asyncpg handshakes; use
    # `.internal` 6PN hostname instead. Same-org private mesh, no TLS needed.
    url = url.replace(".flycast:", ".internal:")
    # Strip libpq-style sslmode from the query — asyncpg accepts it but the
    # actual SSL choice is forced off via the `ssl=False` kwarg passed to
    # `create_pool` (Fly's internal mesh is plain TCP; SSL handshakes there
    # silently RST and surface later as "unexpected connection_lost()").
    if "?sslmode=" in url:
        url = url.split("?sslmode=", 1)[0]
    return url


async def _get_pool() -> Any | None:
    """Lazy pool. Returns None when DATABASE_URL is unset OR when this attempt
    couldn't connect. We don't cache the failure — the next request gets a
    fresh attempt — so a transient blip doesn't pin the server to in-memory
    mode for its entire lifetime. The `_pool_lock` still serializes concurrent
    creators."""
    global _pool, _pool_lock
    if _pool is not None:
        return _pool
    url = _database_url()
    if not url:
        return None

    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    async with _pool_lock:
        if _pool is not None:
            return _pool
        import asyncpg  # type: ignore
        try:
            # Fly's internal `.flycast` DNS + IPv6 negotiation can take
            # 5-15s on the FIRST attempt after a cold deploy. 30s gives the
            # cold path room; the FastAPI startup hook calls this in a
            # fire-and-forget task so uvicorn opens port 4000 immediately
            # rather than waiting on Postgres.
            _pool = await asyncpg.create_pool(
                dsn=url,
                min_size=1,
                max_size=5,
                command_timeout=10,
                timeout=30.0,
                # Recycle idle connections every 5 min so we don't acquire a
                # silently-dead socket. Fly's egress + Postgres-side idle
                # timeout was tripping `ConnectionError: unexpected
                # connection_lost()` during longer uploads.
                max_inactive_connection_lifetime=300.0,
                # Fly's `.internal` 6PN mesh is plain TCP — asyncpg's default
                # SSL upgrade probe was being silently dropped and surfacing
                # later as the connection_lost error.
                ssl=False,
            )
        except Exception as e:
            print(
                f"[db] Postgres unreachable this attempt, falling back to "
                f"in-memory for THIS request. err={type(e).__name__}: {e!r}"
            )
            return None
    return _pool


async def init_db() -> None:
    """Bootstrap the schema. Idempotent — safe to call on every startup.
    No-op when DATABASE_URL is unset. **Non-fatal**: if Postgres is
    unreachable at startup the app still serves requests (degraded to
    in-memory) rather than crashing. The asyncpg pool will retry on the
    next request indirectly through the `_pool_init_failed` flag being
    cleared between processes."""
    try:
        pool = await _get_pool()
    except Exception as e:
        print(f"[db] init_db pool failed: {e}")
        return
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS households (
                    id          TEXT        PRIMARY KEY,
                    plan        JSONB       NOT NULL,
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id            BIGSERIAL   PRIMARY KEY,
                    household_id  TEXT        NOT NULL,
                    chat_id       TEXT        NOT NULL DEFAULT 'main',
                    role          TEXT        NOT NULL,
                    text          TEXT        NOT NULL,
                    turn          INTEGER,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS chat_messages_lookup
                    ON chat_messages (household_id, chat_id, id);
                """
            )
    except Exception as e:
        print(f"[db] schema bootstrap failed: {e}")


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ── PlanState round-trip ──────────────────────────────────────────────────


# Errors that indicate a stale / broken pool connection. We rebuild the pool
# and retry once when we see them. Anything else propagates.
def _is_transient_pg_error(e: BaseException) -> bool:
    if isinstance(e, ConnectionError):
        return True
    name = type(e).__name__
    return name in {
        "ConnectionFailureError",
        "ConnectionDoesNotExistError",
        "InterfaceError",
        "PostgresConnectionError",
        "TooManyConnectionsError",
        "CannotConnectNowError",
    }


async def _reset_pool() -> None:
    """Tear down the cached pool so the next `_get_pool()` rebuilds it. Used
    after a transient connection failure that left dead sockets behind."""
    global _pool
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass
    _pool = None


async def get_plan(household_id: str) -> Optional[PlanState]:
    """Auto-creates an empty plan if missing — same behaviour the TS port
    relied on. The first call from a fresh household ID materialises a
    blank PlanState rather than 404'ing."""
    for attempt in (0, 1):
        pool = await _get_pool()
        if pool is None:
            if household_id not in _memory:
                _memory[household_id] = empty_plan_state(household_id)
            return _memory[household_id]
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT plan FROM households WHERE id = $1", household_id
                )
                if row is None:
                    blank = empty_plan_state(household_id)
                    await _save_plan_via_conn(conn, blank)
                    return blank
                data = row["plan"]
                if isinstance(data, str):
                    data = json.loads(data)
                return PlanState.model_validate(data)
        except Exception as e:
            if attempt == 0 and _is_transient_pg_error(e):
                print(f"[db] transient pg err in get_plan, rebuilding pool: {type(e).__name__}: {e}")
                await _reset_pool()
                continue
            raise
    return None  # unreachable


async def save_plan(plan: PlanState) -> None:
    for attempt in (0, 1):
        pool = await _get_pool()
        if pool is None:
            _memory[plan.household_id] = plan
            return
        try:
            async with pool.acquire() as conn:
                await _save_plan_via_conn(conn, plan)
            return
        except Exception as e:
            if attempt == 0 and _is_transient_pg_error(e):
                print(f"[db] transient pg err in save_plan, rebuilding pool: {type(e).__name__}: {e}")
                await _reset_pool()
                continue
            raise


async def _save_plan_via_conn(conn: Any, plan: PlanState) -> None:
    payload = json.dumps(plan.model_dump(mode="json"))
    await conn.execute(
        """
        INSERT INTO households (id, plan, updated_at)
        VALUES ($1, $2::jsonb, NOW())
        ON CONFLICT (id) DO UPDATE
          SET plan = EXCLUDED.plan,
              updated_at = NOW()
        """,
        plan.household_id,
        payload,
    )


async def list_all_households() -> list[str]:
    pool = await _get_pool()
    if pool is None:
        return list(_memory.keys())
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM households ORDER BY updated_at DESC")
        return [r["id"] for r in rows]


def seed_memory(plan: PlanState) -> None:
    """Test helper — bypasses the DB. Only meaningful in in-memory mode."""
    _memory[plan.household_id] = plan


# ── Chat history persistence ──────────────────────────────────────────────


async def save_chat_message(
    *,
    household_id: str,
    chat_id: str,
    role: str,
    text: str,
    turn: Optional[int] = None,
) -> None:
    """Append a single chat message (user or assistant). In-memory mode is
    a no-op — the frontend already stores transcripts in localStorage and
    hydrates the in-process `_convo` via `/api/chat/{id}/hydrate`. The DB
    path is what makes the server-side history survive a deploy."""
    pool = await _get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO chat_messages (household_id, chat_id, role, text, turn)
            VALUES ($1, $2, $3, $4, $5)
            """,
            household_id,
            chat_id or "main",
            role,
            text,
            turn,
        )


async def load_chat_history(
    *,
    household_id: str,
    chat_id: str,
    limit: int = 60,
) -> list[dict[str, Any]]:
    """Return the most recent `limit` user/assistant messages in
    chronological order. Used to rehydrate the agent's conversation
    memory after a backend restart."""
    pool = await _get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, text, turn FROM chat_messages
            WHERE household_id = $1 AND chat_id = $2
            ORDER BY id DESC
            LIMIT $3
            """,
            household_id,
            chat_id or "main",
            limit,
        )
        rows.reverse()
        return [
            {"role": r["role"], "text": r["text"], "turn": r["turn"]} for r in rows
        ]


async def clear_chat_history(*, household_id: str, chat_id: str) -> None:
    pool = await _get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM chat_messages WHERE household_id = $1 AND chat_id = $2",
            household_id,
            chat_id or "main",
        )
