"""
Scenario engine + plan mutation core — port of skills/scenario/index.ts.

apply_set / apply_add / apply_remove / apply_assumption  — direct plan edits
pin / diff                                                — Plan A/B compare
run_monte_carlo                                           — paths sim
recompute                                                 — refresh derived state
"""
from __future__ import annotations

import math
import random
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..db import get_plan, save_plan
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
from .cashflow import compute_cashflow
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


def set_path(o: Any, path: str, value: Any) -> None:
    parts = path.split(".")
    cur: Any = o
    for i in range(len(parts) - 1):
        k = parts[i]
        next_k = parts[i + 1]
        if isinstance(cur, list) and _is_index(k):
            cur = cur[int(k)]
        else:
            if not isinstance(cur, dict):
                return  # path not navigable
            if cur.get(k) is None:
                cur[k] = [] if _is_index(next_k) else {}
            cur = cur[k]
    last = parts[-1]
    if isinstance(cur, list) and _is_index(last):
        cur[int(last)] = value
    elif isinstance(cur, dict):
        cur[last] = value


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
    return None


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


async def apply_set(args: dict[str, Any]) -> dict[str, Any]:
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"ok": False, "updated_path": args["path"]}
    plan_d = _to_dict(plan)
    if _enforce_source_priority(plan_d, args["path"], args.get("source_type", "user")):
        set_path(plan_d, args["path"], args["value"])
        _push_evidence(plan_d, args["path"], get_path(plan_d, args["path"]), args.get("source_type", "user"))
    plan_d = recompute(plan_d)
    await save_plan(_from_dict(plan_d))
    out: dict[str, Any] = {"ok": True, "updated_path": args["path"]}
    warning = _maybe_warn_monthly_expenses(plan_d, args["path"], args["value"])
    if warning:
        out["warning"] = warning
    return out


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
    for k, v in me.items():
        if not isinstance(v, (int, float)) or v <= 0:
            continue
        if k in ("other_emis", "sip_investments"):
            excluded_total += v
            excluded_keys.append(k)
            continue
        expected += v
    if expected == 0:
        # No breakdown yet — nothing to compare.
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
    set_path(plan_d, args["path"], list_ + [row])
    plan_d = recompute(plan_d)
    await save_plan(_from_dict(plan_d))
    return {"ok": True, "id": row_id}


async def apply_remove(args: dict[str, Any]) -> dict[str, Any]:
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
    plan = await get_plan(args["household_id"])
    if not plan:
        return {"ok": False, "updated_path": args["path"]}
    plan_d = _to_dict(plan)
    set_path(plan_d, args["path"], args["value"])
    plan_d = recompute(plan_d)
    await save_plan(_from_dict(plan_d))
    return {"ok": True, "updated_path": args["path"]}


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
    fsi = plan_d.get("freedom_score_inputs") or {}
    lc = plan_d.get("liquid_capital") or {}
    cash_from_sections = (
        (lc.get("savings_account_balance") or 0)
        + (lc.get("idle_cash_for_investment") or 0)
        + (lc.get("fd_breakable_for_investment") or 0)
        + (lc.get("bonus_expected_for_investment") or 0)
    )
    liquid = cash_from_sections if cash_from_sections > 0 else (fsi.get("liquid_assets_current_value") or 0)

    mf_total = sum((h.get("current_value") or 0) for h in plan_d.get("mutual_funds", []))
    eq_total = sum((h.get("current_value") or 0) for h in plan_d.get("equity_stocks", []))
    fi_total = sum((h.get("current_value") or 0) for h in plan_d.get("fixed_income", []))
    portfolio_from_holdings = mf_total + eq_total + fi_total
    investments = portfolio_from_holdings if portfolio_from_holdings > 0 else (
        fsi.get("portfolio_current_value") or 0
    )

    assets_total = liquid + investments
    l = plan_d.get("loans_liabilities") or {}
    debts_total = (
        ((l.get("home_loan") or {}).get("outstanding_amount") or 0)
        + ((l.get("car_loan") or {}).get("outstanding_amount") or 0)
        + ((l.get("personal_loan") or {}).get("outstanding_amount") or 0)
        + ((l.get("credit_card_dues") or {}).get("outstanding_amount") or 0)
    )
    return {
        "total": assets_total - debts_total,
        "liquid": liquid,
        "non_liquid": max(0, assets_total - liquid),
        "assets_total": assets_total,
        "debts_total": debts_total,
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
    plan_d["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    return plan_d
