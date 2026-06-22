"""
Scenario engine + plan mutation core — port of skills/scenario/index.ts.

apply_set / apply_add / apply_remove / apply_assumption  — direct plan edits
pin / diff                                                — Plan A/B compare
run_monte_carlo                                           — paths sim
recompute                                                 — refresh derived state
"""
from __future__ import annotations

import asyncio
import math
import random
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..db import get_plan, save_plan


# ── per-household mutation lock ────────────────────────────────────────────


# LangGraph's ToolNode runs the AIMessage's tool_calls concurrently — when the
# agent emits 5 plan_set's in one turn, they all start with the SAME `get_plan`
# read, each modifies its own copy, then race-saves. Only the last save wins,
# silently dropping 4 of the 5 writes. We serialize mutations per household to
# prevent this read-modify-write race.
_household_locks: dict[str, asyncio.Lock] = {}


def _lock_for(household_id: str) -> asyncio.Lock:
    lock = _household_locks.get(household_id)
    if lock is None:
        lock = asyncio.Lock()
        _household_locks[household_id] = lock
    return lock
from ..types import (
    ComputedSnapshot,
    EvidenceRow,
    Goal,
    GoalSuccessProb,
    MCResult,
    NetWorth,
    NetWorthSeriesPoint,
    PlanState,
    Scenario,
    ScenarioMutation,
    SourceType,
    source_rank,
)
from pydantic import ValidationError

from .cashflow import compute_cashflow
from .cfp import compute_cfp
from .freedom import compute_freedom


# ── path helpers ───────────────────────────────────────────────────────────


_INDEX_RE = re.compile(r"^\d+$")


def _is_index(s: str) -> bool:
    return bool(_INDEX_RE.match(s))


def _to_dict(plan: PlanState) -> dict:
    return plan.model_dump(mode="python")


def _from_dict(d: dict) -> PlanState:
    return PlanState.model_validate(d)


def get_path(o: Any, path: str) -> Any:
    parts = path.split(".")
    acc: Any = o
    for k in parts:
        if acc is None:
            return None
        if isinstance(acc, list) and _is_index(k):
            idx = int(k)
            if 0 <= idx < len(acc):
                acc = acc[idx]
            else:
                return None
        elif isinstance(acc, dict):
            acc = acc.get(k)
        else:
            return None
    return acc


def set_path(o: Any, path: str, value: Any) -> bool:
    """Write `value` into `o` at dotted `path`.

    Returns True on success, False when the path is unreachable (e.g. an index
    points past the end of a list, or a parent segment hits a scalar). The
    caller can surface a clean error to the agent instead of bubbling an
    IndexError up the SSE stream as a generic "Something went wrong".
    """
    parts = path.split(".")
    cur: Any = o
    for i in range(len(parts) - 1):
        k = parts[i]
        next_k = parts[i + 1]
        if isinstance(cur, list) and _is_index(k):
            idx = int(k)
            if not (0 <= idx < len(cur)):
                return False
            cur = cur[idx]
        else:
            if not isinstance(cur, dict):
                return False
            if cur.get(k) is None:
                cur[k] = [] if _is_index(next_k) else {}
            cur = cur[k]
    last = parts[-1]
    if isinstance(cur, list) and _is_index(last):
        idx = int(last)
        if not (0 <= idx < len(cur)):
            return False
        cur[idx] = value
        return True
    if isinstance(cur, dict):
        cur[last] = value
        return True
    return False


# ── duplicate detection (mirrors TS findDuplicate) ─────────────────────────


def _find_duplicate(path: str, list_: list[Any], row: Any) -> dict | None:
    if not isinstance(list_, list) or not isinstance(row, dict):
        return None
    r = row

    if path == "assumptions.persons":
        incoming_name = str(r.get("name") or "").strip().lower()
        incoming_dob = str(r.get("date_of_birth") or "").strip()
        for i, e in enumerate(list_):
            if not isinstance(e, dict):
                continue
            same = (incoming_name and (e.get("name") or "").strip().lower() == incoming_name) or (
                incoming_dob and (e.get("date_of_birth") or "").strip() == incoming_dob
            )
            if same:
                return {
                    "reason": (
                        f"A person with name \"{e.get('name')}\" already exists"
                        if incoming_name
                        else f"A person with DOB {e.get('date_of_birth')} already exists"
                    ),
                    "id": e.get("id") or "",
                    "index": i,
                    "hint": f"Use plan_set on assumptions.persons.{i}.<field> to update, or plan_remove first.",
                }

    if path == "financial_goals":
        incoming_name = str(r.get("goal_name") or "").strip().lower()
        incoming_year = r.get("target_year")
        incoming_kind = str(r.get("kind") or "").strip()
        for i, e in enumerate(list_):
            if not isinstance(e, dict):
                continue
            same_name = incoming_name and (e.get("goal_name") or "").strip().lower() == incoming_name
            same_yk = (
                incoming_year
                and e.get("target_year") == incoming_year
                and incoming_kind
                and e.get("kind") == incoming_kind
            )
            if same_name or same_yk:
                return {
                    "reason": (
                        f"Goal \"{e.get('goal_name')}\" already exists"
                        if same_name
                        else f"A {e.get('kind')} goal in {e.get('target_year')} already exists (\"{e.get('goal_name')}\")"
                    ),
                    "id": e.get("id") or "",
                    "index": i,
                    "hint": f"Use plan_set on financial_goals.{i}.<field> to update, or plan_remove first.",
                }

    if path == "assumptions.lumpsum_events":
        yr = r.get("year")
        amt = r.get("amount")
        lbl = str(r.get("label") or "").strip().lower()
        for i, e in enumerate(list_):
            if not isinstance(e, dict):
                continue
            if e.get("year") == yr and e.get("amount") == amt and str(e.get("label") or "").strip().lower() == lbl:
                return {
                    "reason": f"A lumpsum event for {yr} ({lbl or 'unlabelled'}) already exists",
                    "id": e.get("id") or "",
                    "index": i,
                    "hint": f"Use plan_set on assumptions.lumpsum_events.{i}.<field> to update, or plan_remove first.",
                }

    # Asset / recurring lists — idempotency guard. Re-uploading the same file (or
    # re-running an import) must not append duplicate holdings. A row is a
    # duplicate when its identifying label AND its principal value match an
    # existing row (two genuinely distinct holdings won't share both).
    _ASSET_LIST_PATHS = {
        "mutual_funds", "equity_stocks", "fixed_income",
        "real_estate", "gold", "recurring_investments",
    }
    if path in _ASSET_LIST_PATHS:
        sig = _row_signature(r)
        if sig[0] or sig[1]:  # need at least a label or a value to compare
            for i, e in enumerate(list_):
                if isinstance(e, dict) and _row_signature(e) == sig:
                    return {
                        "reason": f"An identical {path} entry already exists ({sig[0] or 'unnamed'})",
                        "id": e.get("id") or "",
                        "index": i,
                        "hint": f"Use plan_set on {path}.{i}.<field> to update, or plan_remove first.",
                    }
    return None


def _row_signature(row: Any) -> tuple[str, str]:
    """(label, principal-value) signature for asset/recurring rows — used to
    detect re-uploaded duplicates regardless of row id."""
    if not isinstance(row, dict):
        return ("", "")
    label = str(
        row.get("fund_name") or row.get("stock_name") or row.get("instrument")
        or row.get("label") or row.get("name") or ""
    ).strip().lower()
    val = (
        row.get("current_value") if row.get("current_value") is not None
        else row.get("invested_amount") if row.get("invested_amount") is not None
        else row.get("monthly_amount") if row.get("monthly_amount") is not None
        else row.get("amount")
    )
    try:
        val_s = str(int(round(float(val)))) if val is not None else ""
    except (TypeError, ValueError):
        val_s = str(val or "")
    return (label, val_s)


# ── apply_* ────────────────────────────────────────────────────────────────


def _enforce_source_priority(plan_d: dict, path: str, incoming: SourceType) -> bool:
    """True → caller may write. False → existing higher-priority evidence wins."""
    existing = [e for e in plan_d.get("evidence", []) if e.get("field") == path]
    if not existing:
        return True
    best = min(existing, key=lambda e: source_rank(e.get("source_type", "inferred")))
    if source_rank(incoming) > source_rank(best.get("source_type", "inferred")):
        return False
    return True


def _push_evidence(plan_d: dict, path: str, value: Any, source_type: SourceType) -> None:
    plan_d.setdefault("evidence", []).append(
        EvidenceRow(
            field=path,
            value=value,
            source_file=None,
            source_type=source_type,
            parser_tier="manual",
            confidence=1.0,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ).model_dump(mode="python")
    )


_NUMERIC_PREFIX_RE = re.compile(r"^[-+]?\d+(?:\.\d+)?")

# Common enum aliases the LLM uses interchangeably. Coerced before write so
# `priority: "High"` lands as `"essential"` instead of being rejected.
_ENUM_ALIASES: dict[str, str] = {
    "high": "essential",
    "medium": "important",
    "med": "important",
    "low": "aspirational",
    "must": "essential",
    "must-have": "essential",
    "must have": "essential",
    "nice-to-have": "aspirational",
    "nice to have": "aspirational",
    "optional": "aspirational",
}


def _coerce_scalar_for_path(value: Any) -> Any:
    """Best-effort coerce LLM-extracted strings to schema-friendly values:

    - "12 years" / "5 lakh" / "3 months" → numeric prefix
    - "High" / "Medium" / "Low" → canonical priority enum
    - Anything else → unchanged (Pydantic decides whether it passes)
    """
    if not isinstance(value, str):
        return value
    s = value.strip()

    # 1. Enum aliases (priority, etc.)
    alias = _ENUM_ALIASES.get(s.lower())
    if alias is not None:
        return alias

    # 2. Numeric-with-unit prefix
    m = _NUMERIC_PREFIX_RE.match(s)
    if not m:
        return value
    num_str = m.group(0)
    rest = s[len(num_str):].strip().lower()
    unit_words = {"yr", "yrs", "year", "years", "mo", "mos", "month", "months", "%", "lakh", "lakhs", "l", "cr", "crore", "crores", "k"}
    if rest and rest.split()[0].rstrip(",.:;") not in unit_words:
        return value
    try:
        n = float(num_str)
        return int(n) if n.is_integer() else n
    except ValueError:
        return value


# Paths that point to LIST-typed fields the canvas reads from. plan_set
# on these would silently wipe rows (LLM agent has been observed doing this
# with an empty/partial list mid-conversation, especially right after an
# upload). Mutating these MUST go through plan_add / plan_remove which
# operate row-by-row and never lose data.
APPEND_ONLY_LIST_PATHS: frozenset[str] = frozenset({
    "financial_goals",
    "mutual_funds",
    "equity_stocks",
    "fixed_income",
    "real_estate",
    "gold",
    "assumptions.persons",
})


async def apply_set(args: dict[str, Any]) -> dict[str, Any]:
    async with _lock_for(args["household_id"]):
        return await _apply_set_locked(args)


async def _apply_set_locked(args: dict[str, Any]) -> dict[str, Any]:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"ok": False, "updated_path": args["path"]}
    plan_d = _to_dict(plan)
    path = args["path"]

    # Guard: plan_set on a whole append-only list path is almost always a
    # data-loss bug (overwrites every existing row, including ones from
    # the upload that just happened). Reject early with a clear hint.
    if path in APPEND_ONLY_LIST_PATHS:
        existing = get_path(plan_d, path) or []
        if isinstance(existing, list):
            return {
                "ok": False,
                "updated_path": path,
                "error": (
                    f"plan_set on '{path}' is blocked — it's a list field and would "
                    f"wipe {len(existing)} existing row(s). Use plan_add to append a "
                    f"new row, or plan_remove(id=...) to delete a specific one. To "
                    f"update a field on an existing row, set the indexed path "
                    f"(e.g. '{path}.0.<field>')."
                ),
                "blocked_existing_rows": len(existing),
            }

    write_ok = True
    coerced_value = _coerce_scalar_for_path(args["value"])
    if _enforce_source_priority(plan_d, path, args.get("source_type", "user")):
        write_ok = set_path(plan_d, path, coerced_value)
        if write_ok:
            _push_evidence(plan_d, path, get_path(plan_d, path), args.get("source_type", "user"))
    if not write_ok:
        return {
            "ok": False,
            "updated_path": path,
            "error": f"could not navigate path '{path}' on plan",
        }
    derived = _sync_fsi_from_breakdown(plan_d, path)
    try:
        plan_d = recompute(plan_d)
    except ValidationError as ve:
        # The write produced a plan that doesn't match the schema (e.g. LLM
        # gave a string for a numeric field). Skip this single field rather
        # than crashing the whole request; the existing saved plan is left
        # untouched.
        errs = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in ve.errors()[:3])
        return {
            "ok": False,
            "updated_path": path,
            "error": f"value rejected by schema: {errs}",
            "rejected_value": args["value"],
        }
    await save_plan(_from_dict(plan_d))
    out: dict[str, Any] = {"ok": True, "updated_path": path}
    if derived:
        out["derived"] = derived
    warning = _maybe_warn_monthly_expenses(plan_d, path, args["value"])
    if warning:
        out["warning"] = warning
    return out


# ── FSI auto-sync ──────────────────────────────────────────────────────────


_INCOME_KEYS = (
    "client_salary_in_hand",
    "spouse_salary_in_hand",
    "client_business_income",
    "spouse_business_income",
    "client_rental_income",
    "spouse_rental_income",
    "client_other_income",
    "spouse_other_income",
)

# Categories that belong in `freedom_score_inputs.monthly_expenses` (the
# cashflow's "expenses" line). EMI and SIP live in their own FSI buckets so
# they aren't double-counted in the projection.
_EXPENSE_KEYS = (
    "household_expenses",
    "rent_or_emi",
    "groceries",
    "utilities",
    "school_fees",
    "insurance_premium",
    "medical",
    "travel_or_lifestyle",
)
_EMI_KEYS = ("other_emis",)


def _sync_fsi_from_breakdown(plan_d: dict, written_path: str) -> dict[str, float] | None:
    """The cashflow projection reads `freedom_score_inputs.{monthly_income,
    monthly_expenses, monthly_emi}` as ground truth. Historically the agent
    had to dual-write the breakdown AND the FSI aggregate; in practice it
    often forgot, leaving the projection at zero. Here we derive the FSI
    aggregate from the just-written breakdown whenever the agent touches a
    relevant category, so consistency holds without depending on the LLM.

    Only fires for paths under `income_details.*` / `monthly_expenses.*`.
    Returns a dict of FSI keys that were updated (for the tool result), or
    None if no derivation applied.
    """
    fsi = plan_d.setdefault("freedom_score_inputs", {})
    derived: dict[str, float] = {}

    if written_path.startswith("income_details."):
        income = plan_d.get("income_details") or {}
        total = sum(float(income.get(k) or 0) for k in _INCOME_KEYS)
        fsi["monthly_income"] = total
        derived["freedom_score_inputs.monthly_income"] = total

    if written_path.startswith("monthly_expenses."):
        me = plan_d.get("monthly_expenses") or {}
        exp_total = sum(float(me.get(k) or 0) for k in _EXPENSE_KEYS)
        emi_total = sum(float(me.get(k) or 0) for k in _EMI_KEYS)
        fsi["monthly_expenses"] = exp_total
        fsi["monthly_emi"] = emi_total
        derived["freedom_score_inputs.monthly_expenses"] = exp_total
        derived["freedom_score_inputs.monthly_emi"] = emi_total

    return derived or None


async def force_fsi_sync(household_id: str) -> dict[str, float]:
    """Recompute all FSI aggregates from the current breakdown and persist.
    Used at the end of an upload pass so the LLM's direct FSI emission can't
    leave a stale or double-counted aggregate behind."""
    async with _lock_for(household_id):
        plan = await get_plan(household_id)
        if not plan:
            return {}
        plan_d = _to_dict(plan)
        income = plan_d.get("income_details") or {}
        me = plan_d.get("monthly_expenses") or {}
        fsi = plan_d.setdefault("freedom_score_inputs", {})
        fsi["monthly_income"] = sum(float(income.get(k) or 0) for k in _INCOME_KEYS)
        fsi["monthly_expenses"] = sum(float(me.get(k) or 0) for k in _EXPENSE_KEYS)
        fsi["monthly_emi"] = sum(float(me.get(k) or 0) for k in _EMI_KEYS)
        try:
            plan_d = recompute(plan_d)
            await save_plan(_from_dict(plan_d))
        except ValidationError:
            return {}
        return {
            "freedom_score_inputs.monthly_income": fsi["monthly_income"],
            "freedom_score_inputs.monthly_expenses": fsi["monthly_expenses"],
            "freedom_score_inputs.monthly_emi": fsi["monthly_emi"],
        }


def _maybe_warn_monthly_expenses(plan_d: dict, path: str, value: Any) -> str | None:
    """Surface a warning when the agent's set on `freedom_score_inputs
    .monthly_expenses` looks like it double-counts EMI / SIP categories.
    The cashflow projection trusts FSI as ground truth; an inflated value
    here pushes long-horizon net worth to zero from model bias alone.

    Triggers iff the value differs from `sum(non-EMI, non-SIP categories
    in monthly_expenses)` by more than ₹2,000. Returns None when within
    tolerance or when the path/value aren't relevant."""
    if path != "freedom_score_inputs.monthly_expenses":
        return None
    try:
        new_val = float(value or 0)
    except (TypeError, ValueError):
        return None
    me = plan_d.get("monthly_expenses") or {}
    expected = 0.0
    excluded_total = 0.0
    excluded_keys: list[str] = []
    populated_keys = 0
    for k, v in me.items():
        if not isinstance(v, (int, float)) or v <= 0:
            continue
        populated_keys += 1
        if k in ("other_emis", "sip_investments"):
            excluded_total += v
            excluded_keys.append(k)
            continue
        expected += v
    if populated_keys == 0 and new_val > 0:
        # Agent set the FSI aggregate but left the breakdown empty entirely.
        # The frontend's ExpensesCard shows a fallback aggregate row but the
        # detail view + the report PDF can't itemise without the breakdown.
        return (
            f"freedom_score_inputs.monthly_expenses set to ₹{int(new_val):,} but "
            f"`monthly_expenses.*` breakdown is empty — the canvas Expenses card "
            f"and the PDF report can't itemise without category-level plan_set "
            f"calls. Run plan_set on `monthly_expenses.rent_or_emi`, "
            f"`monthly_expenses.groceries`, etc. for each non-loan, non-SIP "
            f"category the user mentioned."
        )
    if expected == 0:
        return None
    diff = new_val - expected
    if abs(diff) <= 2000:
        return None
    excluded_blurb = (
        f" (excluded {' + '.join(excluded_keys)} = ₹{int(excluded_total):,})"
        if excluded_keys
        else ""
    )
    return (
        f"freedom_score_inputs.monthly_expenses set to ₹{int(new_val):,} but the "
        f"sum of non-EMI, non-SIP categories in `monthly_expenses` is "
        f"₹{int(expected):,}{excluded_blurb}. The cashflow projection trusts "
        f"this value as ground truth — recheck and call plan_set again if "
        f"the value is wrong. (Common cause: other_emis or sip_investments "
        f"were rolled into the sum; they belong to monthly_emi / "
        f"monthly_investments.* respectively.)"
    )


async def apply_add(args: dict[str, Any]) -> dict[str, Any]:
    async with _lock_for(args["household_id"]):
        return await _apply_add_locked(args)


async def _apply_add_locked(args: dict[str, Any]) -> dict[str, Any]:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"ok": False, "id": ""}
    plan_d = _to_dict(plan)
    list_ = get_path(plan_d, args["path"]) or []
    dup = _find_duplicate(args["path"], list_, args["row"])
    if dup:
        return {
            "ok": False,
            "error": "duplicate",
            "reason": dup["reason"],
            "existing_id": dup["id"],
            "existing_index": dup["index"],
            "hint": dup["hint"],
        }
    row = dict(args["row"]) if isinstance(args["row"], dict) else {}
    row_id = row.get("id") or str(uuid4())
    row["id"] = row_id
    # Coerce common "<n> <unit>" strings (e.g. "12 years") on numeric subfields
    # before the row gets validated against the model.
    row = {k: _coerce_scalar_for_path(v) for k, v in row.items()}
    set_path(plan_d, args["path"], list_ + [row])
    try:
        plan_d = recompute(plan_d)
    except ValidationError as ve:
        errs = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in ve.errors()[:3])
        return {
            "ok": False,
            "error": f"row rejected by schema: {errs}",
            "rejected_row": row,
        }
    # Breadcrumb evidence row so the audit trail shows what was added.
    # Use a short label rather than the full row to keep the trail small.
    label = row.get("goal_name") or row.get("fund_name") or row.get("stock_name") or row.get("instrument") or row.get("name") or row_id
    _push_evidence(
        plan_d, f"{args['path']}[+]", {"id": row_id, "label": label},
        args.get("source_type", "user"),
    )
    try:
        await save_plan(_from_dict(plan_d))
    except Exception as e:
        # PG flap rode out the retry budget. Surface it explicitly rather
        # than propagating an exception that would error the whole upload
        # stream (and was the root of the "row appeared then vanished"
        # bug — see db.py save_plan comment).
        return {
            "ok": False,
            "error": f"db save failed: {type(e).__name__}: {e}",
            "rejected_row": row,
        }
    return {"ok": True, "id": row_id}


async def apply_remove(args: dict[str, Any]) -> dict[str, Any]:
    async with _lock_for(args["household_id"]):
        return await _apply_remove_locked(args)


async def _apply_remove_locked(args: dict[str, Any]) -> dict[str, Any]:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"ok": False}
    plan_d = _to_dict(plan)
    list_ = get_path(plan_d, args["path"]) or []
    set_path(plan_d, args["path"], [r for r in list_ if isinstance(r, dict) and r.get("id") != args["id"]])
    plan_d = recompute(plan_d)
    await save_plan(_from_dict(plan_d))
    return {"ok": True}


async def apply_assumption(args: dict[str, Any]) -> dict[str, Any]:
    async with _lock_for(args["household_id"]):
        return await _apply_assumption_locked(args)


async def _apply_assumption_locked(args: dict[str, Any]) -> dict[str, Any]:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"ok": False, "updated_path": args["path"], "error": "household_not_found"}
    plan_d = _to_dict(plan)
    # The agent sometimes drops the `assumptions.` prefix (e.g. asks to set
    # `persons.0.retirement_age` or `sip_annual_step_up_pct`). Every assumption
    # path lives under `plan.assumptions`, so normalise here rather than letting
    # set_path crash on an empty top-level list.
    path = args["path"]
    if not path.startswith("assumptions."):
        path = f"assumptions.{path}"
    ok = set_path(plan_d, path, args["value"])
    if not ok:
        return {
            "ok": False,
            "updated_path": path,
            "error": f"could not navigate path '{path}' on plan",
        }
    plan_d = recompute(plan_d)
    await save_plan(_from_dict(plan_d))
    return {"ok": True, "updated_path": path}


async def confirm_field(args: dict[str, Any]) -> dict[str, Any]:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"ok": False}
    plan_d = _to_dict(plan)
    matches = [e for e in plan_d.get("evidence", []) if e.get("field") == args["field"]]
    if not matches and args.get("value") is None:
        return {"ok": False}
    value_to_write = args.get("value") if args.get("value") is not None else matches[-1].get("value")
    set_path(plan_d, args["field"], value_to_write)
    for e in matches:
        e["parser_tier"] = "manual"
        e["confidence"] = 1.0
        e["value"] = value_to_write
    if not matches:
        plan_d.setdefault("evidence", []).append(
            {
                "field": args["field"],
                "value": value_to_write,
                "source_file": None,
                "source_type": "user",
                "parser_tier": "manual",
                "confidence": 1.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    plan_d["missing_fields"] = [f for f in plan_d.get("missing_fields", []) if f != args["field"]]
    plan_d = recompute(plan_d)
    await save_plan(_from_dict(plan_d))
    return {"ok": True}


# ── scenarios ──────────────────────────────────────────────────────────────


def simulate_mutation(plan: PlanState, mutation: dict | None) -> dict:
    """Apply a ScenarioMutation (dict with `ops`) to a COPY of the plan and
    return the recomputed `computed` snapshot — without persisting anything.
    Shared core of `pin()`; used by the suggestions engine to project the
    effect of an optimisation (suggested net-worth / cashflow / retirement)."""
    cloned = _to_dict(plan)
    if mutation:
        for op in mutation.get("ops", []):
            if op["op"] == "set":
                set_path(cloned, op["path"], op.get("value"))
            elif op["op"] == "add" and op.get("row") is not None:
                list_ = get_path(cloned, op["path"]) or []
                set_path(cloned, op["path"], list_ + [op["row"]])
            elif op["op"] == "remove" and op.get("id"):
                list_ = get_path(cloned, op["path"]) or []
                set_path(
                    cloned,
                    op["path"],
                    [r for r in list_ if isinstance(r, dict) and r.get("id") != op["id"]],
                )
    cloned = recompute(cloned)
    return cloned["computed"]


async def pin(args: dict[str, Any]) -> dict[str, Any]:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"error": "household_not_found"}
    cloned = _to_dict(plan)
    mutation = args.get("mutation")
    if mutation:
        for op in mutation.get("ops", []):
            if op["op"] == "set":
                set_path(cloned, op["path"], op.get("value"))
            elif op["op"] == "add" and op.get("row") is not None:
                list_ = get_path(cloned, op["path"]) or []
                set_path(cloned, op["path"], list_ + [op["row"]])
            elif op["op"] == "remove" and op.get("id"):
                list_ = get_path(cloned, op["path"]) or []
                set_path(
                    cloned,
                    op["path"],
                    [r for r in list_ if isinstance(r, dict) and r.get("id") != op["id"]],
                )
    cloned = recompute(cloned)
    scenario_id = str(uuid4())
    plan_d = _to_dict(plan)
    plan_d.setdefault("scenarios", []).append(
        {
            "id": scenario_id,
            "label": args["label"],
            "mutation": mutation or {"ops": []},
            "computed": cloned["computed"],
        }
    )
    plan_d["active_scenario_ids"] = (plan_d.get("active_scenario_ids") or []) + [scenario_id]
    plan_d["active_scenario_ids"] = plan_d["active_scenario_ids"][-3:]
    # Cap the scenario history at 6. Without this the canvas chip strip
    # accumulates every Plan A / Plan B / Plan B-redux the agent pinned
    # across an iterative conversation, even though only 3 can be active
    # and the chart only renders active ones.
    if len(plan_d["scenarios"]) > 6:
        active_set = set(plan_d["active_scenario_ids"])
        active_keep = [s for s in plan_d["scenarios"] if s["id"] in active_set]
        inactives = [s for s in plan_d["scenarios"] if s["id"] not in active_set]
        # Most recent inactives fill the remaining budget.
        slots = max(0, 6 - len(active_keep))
        inactive_keep_ids = {s["id"] for s in inactives[-slots:]} if slots else set()
        keep_ids = {s["id"] for s in active_keep} | inactive_keep_ids
        plan_d["scenarios"] = [s for s in plan_d["scenarios"] if s["id"] in keep_ids]
    await save_plan(_from_dict(plan_d))
    return {
        "id": scenario_id,
        "label": args["label"],
        "mutation": mutation or {"ops": []},
        "computed": cloned["computed"],
    }


async def diff(args: dict[str, Any]) -> dict[str, Any]:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"error": "household_not_found"}
    a = next((s for s in plan.scenarios if s.id == args["a"]), None)
    b = next((s for s in plan.scenarios if s.id == args["b"]), None)
    if not a or not b:
        return {"error": "scenario_not_found"}
    return {
        "headline_delta": b.computed.headline_amount_at_horizon - a.computed.headline_amount_at_horizon,
        "horizon_years": b.computed.horizon_years,
    }


# ── Monte Carlo ────────────────────────────────────────────────────────────


def _rand_normal() -> float:
    u, v = 0.0, 0.0
    while u == 0:
        u = random.random()
    while v == 0:
        v = random.random()
    return math.sqrt(-2.0 * math.log(u)) * math.cos(2.0 * math.pi * v)


def _equity_pct_for_mc(plan: PlanState) -> float:
    """Prefer the *recommended* equity weight from `plan.computed.allocation`
    if available — a Monte Carlo of the advisor's plan, not the status quo.
    Falls back to the user's current `equity_allocation_percent` input."""
    alloc = plan.computed.allocation
    if alloc and alloc.recommended_allocation:
        eq = alloc.recommended_allocation.equity
        if eq is not None:
            return float(eq) / 100 if eq > 1 else float(eq)
    raw = plan.freedom_score_inputs.equity_allocation_percent
    return (raw or 50) / 100


def _goal_horizon_years(g: Goal, fallback: int) -> int:
    if g.horizon_years and g.horizon_years > 0:
        return int(g.horizon_years)
    if g.target_year:
        from datetime import datetime as _dt
        delta = g.target_year - _dt.now().year
        if delta > 0:
            return delta
    return fallback


async def run_monte_carlo(args: dict[str, Any]) -> dict | MCResult:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"error": "household_not_found"}
    if not plan.computed.risk_profile or not plan.computed.risk_profile.recommended_score:
        return {"error": "risk_gate_required"}
    paths = max(500, min(10_000, int(args.get("paths") or 2000)))
    fsi = plan.freedom_score_inputs

    equity_pct = _equity_pct_for_mc(plan)
    mu = equity_pct * 0.10 + (1 - equity_pct) * 0.07
    sigma = equity_pct * 0.18
    horizon = plan.computed.horizon_years or 45
    start_age = fsi.age or 30
    annual_savings = ((fsi.monthly_income or 0) - (fsi.monthly_expenses or 0) - (fsi.monthly_emi or 0)) * 12
    annual_need = (fsi.monthly_expenses or 0) * 12
    target = annual_need * 25

    starting_balance = (fsi.portfolio_current_value or 0) + (fsi.liquid_assets_current_value or 0)

    # Single integrated simulation: each path produces a freedom-age and a
    # year-indexed balance trajectory we can re-use to score every goal.
    paths_balances: list[list[float]] = []
    ages: list[int] = []
    max_horizon = max(
        horizon,
        max((_goal_horizon_years(g, horizon) for g in plan.financial_goals), default=horizon),
    )

    for _ in range(paths):
        bal = starting_balance
        bal_series: list[float] = [bal]
        freedom_yr: int | None = None
        for yr in range(1, max_horizon + 1):
            ret = mu + sigma * _rand_normal()
            bal = bal * (1 + ret) + max(annual_savings, 0)
            bal_series.append(bal)
            if freedom_yr is None and bal >= target:
                freedom_yr = yr
        if freedom_yr is None:
            freedom_yr = max_horizon
        ages.append(start_age + freedom_yr)
        paths_balances.append(bal_series)

    ages.sort()
    n = len(ages)

    def pct(p: int) -> float:
        return ages[int((p / 100) * (n - 1))]

    # Per-goal success probability: fraction of paths where the projected
    # balance at the goal's horizon meets/exceeds the goal target.
    goal_probs: list[GoalSuccessProb] = []
    for g in plan.financial_goals:
        if not g.target_amount or g.target_amount <= 0:
            continue
        h = _goal_horizon_years(g, horizon)
        if h <= 0 or h > max_horizon:
            continue
        target_amt = g.target_amount
        if g.is_target_in_today_money:
            inflation = g.inflation_assumed or plan.assumptions.inflation or 0.06
            target_amt = target_amt * ((1 + inflation) ** h)
        hits = sum(1 for series in paths_balances if series[h] >= target_amt)
        goal_probs.append(GoalSuccessProb(goal_id=g.id, probability=hits / paths))

    return MCResult(
        paths_count=paths,
        p10_freedom_age=pct(10),
        p50_freedom_age=pct(50),
        p90_freedom_age=pct(90),
        goal_success_probabilities=goal_probs,
    )


# ── recompute ──────────────────────────────────────────────────────────────


def _derive_net_worth(plan_d: dict) -> dict:
    """Full asset/liability breakdown for the canvas.

    The historical contract was: assets_total = liquid + investments, and
    secured loans (home, car) were excluded from net worth on the theory
    that we didn't have the matching asset value. Now that
    `real_estate[]` and `gold[]` are first-class lists on the plan, the
    house and gold ARE tracked. So:

    - Real estate's current_value is added to assets.
    - Gold's current_value is added to assets.
    - Home loan's outstanding is paired against real_estate (net equity).
    - Car loan stays as an unpaired secured debt (we don't yet track a
      vehicles[] list — when we do, this gets the same pairing treatment).

    The user's complaint that motivated this rewrite: their primary
    residence (₹2-3Cr asset, often the household's largest) was
    completely invisible in net worth.
    """
    fsi = plan_d.get("freedom_score_inputs") or {}
    lc = plan_d.get("liquid_capital") or {}

    # ── Liquid (cash-like) ────────────────────────────────────────────
    cash_from_sections = (
        (lc.get("savings_account_balance") or 0)
        + (lc.get("idle_cash_for_investment") or 0)
        + (lc.get("fd_breakable_for_investment") or 0)
        + (lc.get("bonus_expected_for_investment") or 0)
    )
    liquid = cash_from_sections if cash_from_sections > 0 else (fsi.get("liquid_assets_current_value") or 0)

    # ── Investments (MFs + stocks + fixed income) ─────────────────────
    mf_total = sum((h.get("current_value") or 0) for h in plan_d.get("mutual_funds", []))
    eq_total = sum((h.get("current_value") or 0) for h in plan_d.get("equity_stocks", []))
    fi_total = sum((h.get("current_value") or 0) for h in plan_d.get("fixed_income", []))
    portfolio_from_holdings = mf_total + eq_total + fi_total
    investments = portfolio_from_holdings if portfolio_from_holdings > 0 else (
        fsi.get("portfolio_current_value") or 0
    )

    # ── Real estate + Gold (NEW — were missing from net worth) ────────
    real_estate_total = sum((r.get("current_value") or 0) for r in plan_d.get("real_estate", []))
    gold_total = sum((g.get("current_value") or 0) for g in plan_d.get("gold", []))

    gross_assets = liquid + investments + real_estate_total + gold_total

    # ── Liabilities ────────────────────────────────────────────────────
    l = plan_d.get("loans_liabilities") or {}
    home_outstanding = float((l.get("home_loan") or {}).get("outstanding_amount") or 0)
    car_outstanding = float((l.get("car_loan") or {}).get("outstanding_amount") or 0)
    personal_outstanding = float((l.get("personal_loan") or {}).get("outstanding_amount") or 0)
    cc_outstanding = float((l.get("credit_card_dues") or {}).get("outstanding_amount") or 0)
    unsecured_debts = personal_outstanding + cc_outstanding
    secured_debts = home_outstanding + car_outstanding

    # ── Pairing: real_estate ↔ home_loan ──────────────────────────────
    # Equity in the property = market value − outstanding mortgage,
    # clamped ≥ 0 (if you owe more than it's worth you're not negative
    # net-worth on net_worth.total — that money is already in the
    # liability column).
    real_estate_equity = max(0.0, real_estate_total - home_outstanding)

    # ── Net worth total ──────────────────────────────────────────────
    # = liquid + investments + real_estate_equity + gold
    #   − unsecured_debts − car_loan_outstanding
    # (car_loan is the only secured debt not paired with an asset; once
    # we add vehicles[] this term goes away in favour of car equity.)
    total = (
        liquid
        + investments
        + real_estate_equity
        + gold_total
        - unsecured_debts
        - car_outstanding
    )

    return {
        "total": round(total),
        "liquid": round(liquid),
        "non_liquid": round(max(0, gross_assets - liquid)),
        "assets_total": round(gross_assets),
        "investments": round(investments),
        "real_estate_total": round(real_estate_total),
        "gold_total": round(gold_total),
        "real_estate_equity": round(real_estate_equity),
        "debts_total": round(unsecured_debts),
        "secured_debts": round(secured_debts),
        "home_loan_outstanding": round(home_outstanding),
        "car_loan_outstanding": round(car_outstanding),
        "personal_loan_outstanding": round(personal_outstanding),
        "credit_card_outstanding": round(cc_outstanding),
    }


def recompute(plan_d: dict) -> dict:
    """Refresh derived state. Operates on a dict (already model_dumped) so we
    can roundtrip through the algorithms cleanly."""
    plan_d.setdefault("computed", {})
    plan_d["computed"]["net_worth"] = _derive_net_worth(plan_d)

    plan_obj = _from_dict(plan_d)
    plan_d["computed"]["freedom_score"] = compute_freedom(plan_obj).model_dump(mode="python")

    horizon = plan_d["computed"].get("horizon_years") or 45
    cf = compute_cashflow(plan_obj, horizon)
    plan_d["computed"]["cashflow"] = cf.model_dump(mode="python")
    plan_d["computed"]["cash_flow_table"] = cf.model_dump(mode="python")["rows"]
    plan_d["computed"]["net_worth_series"] = [
        {"year": p.year, "value": p.balance} for p in cf.retirement_glide
    ]
    plan_d["computed"]["headline_amount_at_horizon"] = (
        cf.rows[-1].total_net_worth if cf.rows else 0
    )

    pins = []
    kind_map = {
        "house_purchase": "home_purchase",
        "child_education": "education",
        "retirement": "retirement",
        "foreign_travel": "travel",
    }
    for g in plan_d.get("financial_goals", []):
        if g.get("target_year"):
            pins.append(
                {
                    "year": g["target_year"],
                    "label": g["goal_name"],
                    "type": kind_map.get(g.get("kind"), "other"),
                    "goal_id": g.get("id"),
                }
            )
    plan_d["computed"]["milestone_pins"] = pins

    # ── Excel-faithful CFP snapshot (Finding 1 unification) ─────────────
    # The legacy compute_cashflow + compute_freedom pair drove the canvas;
    # compute_cfp is the firm's CFP-Excel-strict engine. Run it on every
    # recompute and stash the result so the canvas, the PDF report, and
    # the agent all see consistent numbers. Failures here are non-fatal —
    # we don't want a CFP edge case to wipe out the rest of the snapshot.
    try:
        cfp_out = compute_cfp(plan_obj)
        plan_d["computed"]["cfp"] = {
            "summary": cfp_out.summary,
            "goal_blocks": cfp_out.goal_blocks,
            "retirement": cfp_out.retirement,
            "insurance": cfp_out.insurance,
            "yoy_cashflow": cfp_out.yoy_cashflow,
            "debt": cfp_out.debt,
            "tax_regime": cfp_out.tax_regime,
            "constants_used": cfp_out.constants_used,
        }
    except Exception:
        plan_d["computed"]["cfp"] = None

    plan_d["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    return plan_d
