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

from .logging_config import get_logger
from .types import PlanState, empty_plan_state

_log = get_logger(__name__)


# ── In-memory fallback (no DATABASE_URL) ──────────────────────────────────


_memory: dict[str, PlanState] = {}
# In-memory fallback for the CFP workbook store (source + computed xlsx, outputs)
# used when DATABASE_URL is unset. Mirrors `_memory` for plans.
_memory_wb: dict[str, dict[str, Any]] = {}


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


# Rate-limit the "pool acquire failed" log so a single mesh flap doesn't
# carpet-bomb the log with one line per concurrent request. We only need
# to see the FIRST one in a burst to know something happened — the retry
# loop / direct-connect fallback handles the actual recovery.
_last_pool_fail_log_ts: float = 0.0
_POOL_FAIL_LOG_INTERVAL_S: float = 30.0


async def _get_pool() -> Any | None:
    """Lazy pool. Per-request `asyncpg.connect()` was too slow (each fresh
    connect on Fly's `.internal` mesh adds 100-500ms, and a single chat turn
    does many apply_set→get_plan+save_plan pairs, stacking into multi-second
    overhead). Back to a real pool — but with aggressive recycling and an
    on-acquire ping so stale sockets are evicted before the caller sees them.
    """
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
            _pool = await asyncpg.create_pool(
                dsn=url,
                min_size=2,
                max_size=30,
                command_timeout=10,
                timeout=15.0,
                # 5s recycle. Fly's `.internal` mesh silently half-closes
                # idle TCP within seconds — anything older than this is a
                # likely dead socket. We deliberately do NOT install a
                # per-acquire SELECT 1 setup hook: on a dead socket the
                # mesh doesn't send a RST, so the SELECT 1 blocks for
                # the full command_timeout (10s) per connection, which
                # then cascades into pool.acquire() timeouts for every
                # concurrent caller. Lazy detection via the retry loop
                # below is faster — a dead-conn query fails immediately
                # with ConnectionDoesNotExistError, we tear down the
                # pool, rebuild, and retry within a few hundred ms.
                max_inactive_connection_lifetime=5.0,
                ssl=False,
            )
        except Exception as e:
            _log.warning("db.pool.unreachable", extra={"err_type": type(e).__name__}, exc_info=True)
            return None
    return _pool


class _PgConn:
    """Acquires a connection from the shared pool and yields it. Falls back to
    `None` (in-memory mode) when the pool is unavailable. On a transient
    connection error during acquire, the caller's retry loop will try again
    against a freshly-rebuilt pool.
    """

    def __init__(self) -> None:
        self.conn: Any = None
        self._cm: Any = None
        self._direct: bool = False  # True when we bypassed the pool

    async def __aenter__(self) -> Any | None:
        pool = await _get_pool()
        if pool is not None:
            try:
                # 3s acquire timeout (was 10s). On a healthy pool, acquire
                # returns in microseconds; the only reason we'd wait this
                # long is the pool is mid-flap. Fail fast so the
                # direct-connect fallback can serve the request inside
                # Fly's 5s health-check budget.
                self._cm = pool.acquire(timeout=3.0)
                self.conn = await self._cm.__aenter__()
                return self.conn
            except Exception as e:
                # Pool's connections are dying mid-acquire on Fly's `.internal`
                # mesh — fall through to a direct connect so this single
                # request doesn't get silently routed to in-memory mode (which
                # would lose data on a multi-machine deployment).
                global _last_pool_fail_log_ts
                now = asyncio.get_event_loop().time()
                if now - _last_pool_fail_log_ts > _POOL_FAIL_LOG_INTERVAL_S:
                    _log.warning("db.pool.acquire_failed", extra={"err_type": type(e).__name__, "suppress_s": int(_POOL_FAIL_LOG_INTERVAL_S)})
                    _last_pool_fail_log_ts = now
                # Tear the pool down on a flap so the *next* request rebuilds
                # from scratch instead of hitting the same stale sockets.
                await _reset_pool()
                self._cm = None
                self.conn = None

        # Direct-connect fallback. No pool, no stale-socket reuse.
        url = _database_url()
        if not url:
            return None
        import asyncpg  # type: ignore
        try:
            self.conn = await asyncpg.connect(dsn=url, ssl=False, timeout=15.0)
            self._direct = True
            return self.conn
        except Exception as e:
            _log.error("db.direct_connect.failed", extra={"err_type": type(e).__name__}, exc_info=True)
            self.conn = None
            self._direct = False
            return None

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._direct and self.conn is not None:
            try:
                await self.conn.close(timeout=5.0)
            except Exception:
                pass
        elif self._cm is not None:
            try:
                await self._cm.__aexit__(exc_type, exc_val, exc_tb)
            except Exception:
                pass
        self.conn = None
        self._cm = None
        self._direct = False


def _acquire_conn() -> _PgConn:
    return _PgConn()


async def init_db() -> None:
    """Bootstrap the schema. Idempotent — safe to call on every startup.
    No-op when DATABASE_URL is unset. **Non-fatal**: if Postgres is
    unreachable at startup the app still serves requests (degraded to
    in-memory) rather than crashing. The asyncpg pool will retry on the
    next request indirectly through the `_pool_init_failed` flag being
    cleared between processes."""
    async with _acquire_conn() as conn:
        if conn is None:
            return
        try:
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
                CREATE TABLE IF NOT EXISTS household_workbooks (
                    household_id  TEXT        PRIMARY KEY,
                    source_xlsx   BYTEA,
                    source_name   TEXT,
                    computed_xlsx BYTEA,
                    outputs       JSONB,
                    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        except Exception as e:
            _log.error("db.schema_bootstrap.failed", exc_info=True)


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


# Retry budget for transient pg errors during a single request. Each attempt
# tears down the pool and rebuilds from scratch.
#
# Trade-off here is real: too few retries and a 2-second mesh flap silently
# loses data (see git history — Findings on the V2 upload). Too many and
# each failing request blocks a uvicorn worker for so long that Fly's HTTP
# health check times out, the machine drops out of the load balancer, and
# the whole app cascades into "no healthy instances" 503s.
#
# Tuned: 3 retries, capped backoff (0.1 + 0.2 + 0.4 = 0.7s max wait per op).
# A multi-row write that hits PG flap will spend at most ~700ms × N rows
# retrying, but each individual request returns within ~1s — well inside
# the 5s health-check timeout.
_MAX_PG_RETRIES = 3
_PG_BACKOFF_BASE_S = 0.1
_PG_BACKOFF_MAX_S = 0.4


async def get_plan(household_id: str) -> Optional[PlanState]:
    """Auto-creates an empty plan if missing — same behaviour the TS port
    relied on. The first call from a fresh household ID materialises a
    blank PlanState rather than 404'ing.

    Wrapped in a retry loop because Fly's `.internal` mesh occasionally
    RST's a live asyncpg connection mid-query (surfaces as
    `ConnectionDoesNotExistError: connection was closed in the middle of
    operation`). Each retry opens a fresh connection from scratch.
    """
    for attempt in range(_MAX_PG_RETRIES + 1):
        try:
            async with _acquire_conn() as conn:
                if conn is None:
                    # `conn is None` means both pool AND direct connect
                    # returned None. If DATABASE_URL is configured this is
                    # a CONNECTIVITY issue — raise to engage the retry
                    # loop. If DATABASE_URL is unset (dev / local) this
                    # is by design — degrade to in-memory.
                    if _database_url():
                        raise ConnectionError("postgres acquire returned None")
                    if household_id not in _memory:
                        _memory[household_id] = empty_plan_state(household_id)
                    return _memory[household_id]
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
            if attempt < _MAX_PG_RETRIES and (_is_transient_pg_error(e) or isinstance(e, ConnectionError)):
                backoff = min(_PG_BACKOFF_MAX_S, _PG_BACKOFF_BASE_S * (2 ** attempt))
                _log.warning("db.get_plan.transient", extra={"attempt": attempt+1, "max": _MAX_PG_RETRIES+1, "err_type": type(e).__name__, "backoff_s": round(backoff,2)})
                await _reset_pool()
                await asyncio.sleep(backoff)
                continue
            raise
    return None  # unreachable


async def save_plan(plan: PlanState) -> None:
    for attempt in range(_MAX_PG_RETRIES + 1):
        try:
            async with _acquire_conn() as conn:
                if conn is None:
                    # See the matching block in get_plan: when DATABASE_URL
                    # is configured, `conn is None` means the .internal
                    # mesh is flapping. Raise so the retry loop engages
                    # rather than silently writing to memory — otherwise
                    # the next get_plan reads PG (when it comes back) and
                    # the row appears to "vanish" because it was never
                    # actually persisted.
                    if _database_url():
                        raise ConnectionError("postgres acquire returned None")
                    _memory[plan.household_id] = plan
                    return
                await _save_plan_via_conn(conn, plan)
                return
        except Exception as e:
            if attempt < _MAX_PG_RETRIES and (_is_transient_pg_error(e) or isinstance(e, ConnectionError)):
                backoff = min(_PG_BACKOFF_MAX_S, _PG_BACKOFF_BASE_S * (2 ** attempt))
                _log.warning("db.save_plan.transient", extra={"attempt": attempt+1, "max": _MAX_PG_RETRIES+1, "err_type": type(e).__name__, "backoff_s": round(backoff,2)})
                await _reset_pool()
                await asyncio.sleep(backoff)
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
    async with _acquire_conn() as conn:
        if conn is None:
            return list(_memory.keys())
        rows = await conn.fetch("SELECT id FROM households ORDER BY updated_at DESC")
        return [r["id"] for r in rows]


async def list_households_page(limit: int, offset: int) -> tuple[list[str], int]:
    """Paginated household IDs — `(ids_for_page, total_count)`.

    Far faster than `list_all_households()` because Postgres handles the
    ORDER BY + LIMIT + OFFSET server-side, and the caller only fetches plans
    for the page they need (not the whole table)."""
    async with _acquire_conn() as conn:
        if conn is None:
            ids = list(_memory.keys())
            return ids[offset : offset + limit], len(ids)
        # Two-roundtrip — paginated rows + total. Both cheap.
        rows = await conn.fetch(
            "SELECT id FROM households ORDER BY updated_at DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
        total = await conn.fetchval("SELECT COUNT(*) FROM households")
        return [r["id"] for r in rows], int(total or 0)


def seed_memory(plan: PlanState) -> None:
    """Test helper — bypasses the DB. Only meaningful in in-memory mode."""
    _memory[plan.household_id] = plan


# ── CFP workbook persistence (Excel engine) ───────────────────────────────
# The raw uploaded firm-template .xlsx and the engine's populated/recalculated
# workbook are stored per household so the engine can recompute and the UI can
# download the computed sheet. Stored as BYTEA — these are ~200KB each.


async def save_source_workbook(household_id: str, filename: str, data: bytes) -> None:
    async with _acquire_conn() as conn:
        if conn is None:
            if not _database_url():
                _memory_wb.setdefault(household_id, {}).update(
                    {"source_xlsx": data, "source_name": filename}
                )
                return
            raise ConnectionError("postgres acquire returned None")
        await conn.execute(
            """
            INSERT INTO household_workbooks (household_id, source_xlsx, source_name, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (household_id) DO UPDATE
              SET source_xlsx = EXCLUDED.source_xlsx,
                  source_name = EXCLUDED.source_name,
                  updated_at = NOW()
            """,
            household_id,
            data,
            filename,
        )


async def get_source_workbook(household_id: str) -> Optional[bytes]:
    async with _acquire_conn() as conn:
        if conn is None:
            return (_memory_wb.get(household_id) or {}).get("source_xlsx")
        row = await conn.fetchrow(
            "SELECT source_xlsx FROM household_workbooks WHERE household_id = $1",
            household_id,
        )
        return bytes(row["source_xlsx"]) if row and row["source_xlsx"] else None


async def save_computed_workbook(
    household_id: str, data: bytes, outputs: dict[str, Any]
) -> None:
    payload = json.dumps(outputs)
    async with _acquire_conn() as conn:
        if conn is None:
            if not _database_url():
                _memory_wb.setdefault(household_id, {}).update(
                    {"computed_xlsx": data, "outputs": outputs}
                )
                return
            raise ConnectionError("postgres acquire returned None")
        await conn.execute(
            """
            INSERT INTO household_workbooks (household_id, computed_xlsx, outputs, updated_at)
            VALUES ($1, $2, $3::jsonb, NOW())
            ON CONFLICT (household_id) DO UPDATE
              SET computed_xlsx = EXCLUDED.computed_xlsx,
                  outputs = EXCLUDED.outputs,
                  updated_at = NOW()
            """,
            household_id,
            data,
            payload,
        )


async def get_computed_workbook(
    household_id: str,
) -> tuple[Optional[bytes], Optional[dict[str, Any]]]:
    async with _acquire_conn() as conn:
        if conn is None:
            rec = _memory_wb.get(household_id) or {}
            return rec.get("computed_xlsx"), rec.get("outputs")
        row = await conn.fetchrow(
            "SELECT computed_xlsx, outputs FROM household_workbooks WHERE household_id = $1",
            household_id,
        )
        if not row:
            return None, None
        data = bytes(row["computed_xlsx"]) if row["computed_xlsx"] else None
        outs = row["outputs"]
        if isinstance(outs, str):
            outs = json.loads(outs)
        return data, outs


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
    for attempt in range(_MAX_PG_RETRIES + 1):
        try:
            async with _acquire_conn() as conn:
                if conn is None:
                    return
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
                return
        except Exception as e:
            if attempt < _MAX_PG_RETRIES and _is_transient_pg_error(e):
                await _reset_pool()
                await asyncio.sleep(0.1)
                continue
            _log.warning("db.save_chat_message.dropped", extra={"err_type": type(e).__name__})
            return


async def load_chat_history(
    *,
    household_id: str,
    chat_id: str,
    limit: int = 60,
) -> list[dict[str, Any]]:
    """Return the most recent `limit` user/assistant messages in
    chronological order. Used to rehydrate the agent's conversation
    memory after a backend restart."""
    async with _acquire_conn() as conn:
        if conn is None:
            return []
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
    async with _acquire_conn() as conn:
        if conn is None:
            return
        await conn.execute(
            "DELETE FROM chat_messages WHERE household_id = $1 AND chat_id = $2",
            household_id,
            chat_id or "main",
        )
