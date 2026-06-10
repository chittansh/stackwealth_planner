"""
LangChain tool definitions — each one dispatches to a Python skill module.

The Pydantic args schemas mirror the Zod schemas in agent/planner.ts so the
agent's JSON tool-call shapes are identical to the TS version.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..db import get_plan, save_plan
from ..skills import allocate as allocate_skill
from ..skills import cashflow as cashflow_skill
from ..skills import cfp as cfp_skill
from ..skills import debt as debt_skill
from ..skills import freedom as freedom_skill
from ..skills import intake as intake_skill
from ..skills import knowledge as knowledge_skill
from ..skills import news as news_skill
from ..skills import risk as risk_skill
from ..skills import scenario as scenario_skill
from ..skills import tax as tax_skill
from ..skills.allocate import compute_allocation
from ..skills.report import render_plan_pdf


# ── Helpers ────────────────────────────────────────────────────────────────


def _to_plain(value: Any) -> Any:
    """Recursively convert Pydantic models (and lists/dicts of them) to plain
    Python dicts/lists/scalars. LangChain's StructuredTool validates inbound
    args against the args_schema and hands them to the coroutine as **kwargs
    where nested BaseModel fields stay as model *instances*. Skill functions
    written before this happened call `.get(...)` on those fields and crash
    with `'XxxArgs' object has no attribute 'get'`. Run every wrapper's
    kwargs through `_coerce_kwargs` so the skill layer always sees dicts."""
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    return value


def _coerce_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {k: _to_plain(v) for k, v in kwargs.items()}


async def _persist_computed(household_id: str, field: str, result: Any) -> Any:
    """Save a skill result to plan.computed.<field> so the report PDF and the
    canvas widgets can read it. Errors and non-model results pass through
    unchanged. Mirrors what the /api/skill/* HTTP endpoints do — without
    this, agent-driven runs of allocate/tax/montecarlo never reach PlanState."""
    if isinstance(result, dict) and result.get("error"):
        return result
    plan = await get_plan(household_id)
    if plan is None:
        return result
    setattr(plan.computed, field, result)
    plan.last_updated_at = datetime.now(timezone.utc).isoformat()
    await save_plan(plan)
    return result


SourceType = Literal[
    "user", "transcript", "pdf_aa", "pdf_generic", "xlsx", "csv", "docx",
    "md", "image", "audio", "inferred", "derived",
]


# ── intake_ingest ──────────────────────────────────────────────────────────


class IntakeFileSrc(BaseModel):
    kind: Literal["file"]
    filename: str
    mime: str
    contents_b64: str


class IntakeTextSrc(BaseModel):
    kind: Literal["text"]
    text: str
    source_type: Literal["user", "transcript", "md"] = "user"


class IntakeIngestArgs(BaseModel):
    household_id: str
    source: IntakeFileSrc | IntakeTextSrc


async def _intake_ingest(**kwargs: Any) -> Any:
    return await intake_skill.ingest(IntakeIngestArgs(**kwargs).model_dump())


# ── intake_confirm ─────────────────────────────────────────────────────────


class IntakeConfirmArgs(BaseModel):
    household_id: str
    field: str
    value: Optional[Any] = None


async def _intake_confirm(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await scenario_skill.confirm_field(kwargs)


# ── plan_set / add / remove / assumption ───────────────────────────────────


class PlanSetArgs(BaseModel):
    household_id: str
    path: str
    value: Any
    source_type: SourceType = "user"


async def _plan_set(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await scenario_skill.apply_set(kwargs)


class PlanAddArgs(BaseModel):
    household_id: str
    path: str
    row: Any
    source_type: SourceType = "user"


async def _plan_add(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await scenario_skill.apply_add(kwargs)


class PlanRemoveArgs(BaseModel):
    household_id: str
    path: str
    id: str


async def _plan_remove(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await scenario_skill.apply_remove(kwargs)


class PlanAssumptionArgs(BaseModel):
    household_id: str
    path: str
    value: Any


async def _plan_assumption(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await scenario_skill.apply_assumption(kwargs)


# ── risk_assess ────────────────────────────────────────────────────────────


class WillingnessArgs(BaseModel):
    volatility_reaction: Optional[
        Literal["sell_everything", "sell_some", "hold_steady", "buy_more"]
    ] = None
    risk_return_tradeoff: Optional[Literal["A", "B", "C", "D"]] = None
    max_tolerable_loss: Optional[Literal["0", "10", "20", "30", ">30"]] = None


class RiskAssessArgs(BaseModel):
    household_id: str
    willingness: Optional[WillingnessArgs] = None


async def _risk_assess(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    result = await risk_skill.assess(kwargs)
    if isinstance(result, dict) and result.get("error"):
        return result
    plan = await get_plan(kwargs["household_id"])
    if plan is not None:
        plan.computed.risk_profile = result
        # Risk drives allocation — recompute it eagerly so downstream tools
        # (tax, montecarlo) and the PDF have a consistent picture.
        plan.computed.allocation = compute_allocation(plan)
        plan.last_updated_at = datetime.now(timezone.utc).isoformat()
        await save_plan(plan)
    return result


# ── allocate / freedom / tax / cashflow ────────────────────────────────────


class HouseholdOnlyArgs(BaseModel):
    household_id: str


async def _allocate_recommend(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await _persist_computed(
        kwargs["household_id"], "allocation", await allocate_skill.recommend(kwargs)
    )


async def _freedom_score(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await _persist_computed(
        kwargs["household_id"], "freedom_score", await freedom_skill.score(kwargs)
    )


async def _tax_harvest(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await _persist_computed(
        kwargs["household_id"], "tax", await tax_skill.harvest(kwargs)
    )


async def _debt_paydown(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await _persist_computed(
        kwargs["household_id"], "debt_paydown", await debt_skill.paydown(kwargs)
    )


async def _cfp_plan(**kwargs: Any) -> Any:
    """The Excel-faithful Comprehensive Financial Plan engine. Returns the
    full goal-by-goal breakdown, year-by-year cashflow, retirement corpus,
    insurance need, AND a `computation_trace` array so the agent can render
    the math inline in the tool-call response — every step labelled with
    its formula and the inputs that went into it."""
    kwargs = _coerce_kwargs(kwargs)
    return await cfp_skill.run_cfp(kwargs["household_id"])


class CashflowArgs(BaseModel):
    household_id: str
    horizon_years: int = 45


async def _cashflow_project(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    result = await cashflow_skill.project(kwargs)
    if isinstance(result, dict) and result.get("error"):
        return result
    plan = await get_plan(kwargs["household_id"])
    if plan is not None:
        plan.computed.cashflow = result
        plan.computed.cash_flow_table = result.rows
        plan.last_updated_at = datetime.now(timezone.utc).isoformat()
        await save_plan(plan)
    return result


# ── scenario_pin / diff / monte carlo ──────────────────────────────────────


class ScenarioOpArg(BaseModel):
    path: str
    op: Literal["set", "add", "remove"]
    value: Optional[Any] = None
    row: Optional[Any] = None
    id: Optional[str] = None


class ScenarioMutationArg(BaseModel):
    ops: list[ScenarioOpArg] = Field(default_factory=list)


class ScenarioPinArgs(BaseModel):
    household_id: str
    label: str
    mutation: Optional[ScenarioMutationArg] = None


async def _scenario_pin(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await scenario_skill.pin(kwargs)


class ScenarioDiffArgs(BaseModel):
    household_id: str
    a: str
    b: str


async def _scenario_diff(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await scenario_skill.diff(kwargs)


class MonteCarloArgs(BaseModel):
    household_id: str
    paths: int = 2000


async def _montecarlo_run(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await _persist_computed(
        kwargs["household_id"],
        "monte_carlo",
        await scenario_skill.run_monte_carlo(kwargs),
    )


# ── report_generate ────────────────────────────────────────────────────────


class ReportGenerateArgs(BaseModel):
    household_id: str
    download: bool = False


async def _report_generate(**kwargs: Any) -> Any:
    """Return a downloadable PDF link for the household's plan + which sections
    have been computed. Pass `download=true` to also pre-render the PDF
    server-side (slower; useful only when you want to surface byte_size or
    catch render errors before the user clicks)."""
    household_id = kwargs["household_id"]
    plan = await get_plan(household_id)
    if plan is None:
        return {"ok": False, "error": "household_not_found"}

    sections_present = {
        "risk_profile": plan.computed.risk_profile is not None,
        "allocation": plan.computed.allocation is not None,
        "tax": plan.computed.tax is not None,
        "monte_carlo": plan.computed.monte_carlo is not None,
        "freedom_score": plan.computed.freedom_score is not None,
        "cashflow": plan.computed.cashflow is not None,
    }
    missing = [k for k, v in sections_present.items() if not v]

    out: dict[str, Any] = {
        "ok": True,
        "pdf_url": f"/api/report/{household_id}/pdf",
        "sections_present": sections_present,
        "missing_sections": missing,
    }
    if kwargs.get("download"):
        rendered = await render_plan_pdf(household_id)
        if rendered.get("ok"):
            out["rendered"] = True
            out["byte_size"] = len(rendered["bytes"])
        else:
            out["rendered"] = False
            out["fallback"] = "html"
    return out


# ── run_full_analysis (orchestrator) ───────────────────────────────────────


class RunFullAnalysisArgs(BaseModel):
    household_id: str
    willingness: Optional[WillingnessArgs] = None
    paths: int = 2000


def _alloc_summary(a: Any) -> dict:
    rec = a.recommended_allocation
    return {
        "investor_risk_band": a.investor_risk_band,
        "recommended": {
            "equity": rec.equity,
            "debt": rec.debt,
            "gold": rec.gold,
            "cash": rec.cash,
        },
        "tactical_regime_label": a.tactical_regime_label,
        "tactical_regime_score": a.tactical_regime_score,
        "rebalancing_action_count": len(a.rebalancing_actions),
    }


def _tax_summary(t: Any) -> dict:
    return {
        "ltcg_headroom_remaining": t.ltcg_headroom_remaining,
        "realized_ltcg_fy": t.realized_ltcg_fy,
        "realized_stcg_fy": t.realized_stcg_fy,
        "gain_harvest_count": len(t.gain_harvest_suggestions),
        "loss_harvest_count": len(t.loss_harvest_suggestions),
        "net_post_tax_delta": t.net_post_tax_delta,
    }


def _mc_summary(m: Any) -> dict:
    return {
        "paths_count": m.paths_count,
        "p10_freedom_age": m.p10_freedom_age,
        "p50_freedom_age": m.p50_freedom_age,
        "p90_freedom_age": m.p90_freedom_age,
        "goal_success_probabilities": [g.model_dump() for g in m.goal_success_probabilities],
    }


async def _run_full_analysis(**kwargs: Any) -> Any:
    """Run the full advisor workflow end-to-end and persist every output to
    PlanState so the PDF report includes them: risk → allocation → tax →
    monte_carlo → report URL. If `willingness` is provided we run risk_assess
    first; otherwise we expect the household already passed the risk gate."""
    kwargs = _coerce_kwargs(kwargs)
    household_id = kwargs["household_id"]
    willingness = kwargs.get("willingness")
    paths = int(kwargs.get("paths") or 2000)

    plan = await get_plan(household_id)
    if plan is None:
        return {"ok": False, "error": "household_not_found"}

    out: dict[str, Any] = {"ok": True, "household_id": household_id, "stages": {}}

    # ── Stage 1: risk ──
    has_risk = bool(plan.computed.risk_profile and plan.computed.risk_profile.recommended_score)
    if willingness or not has_risk:
        if not willingness:
            return {
                "ok": False,
                "stage": "risk",
                "error": "risk_gate_required",
                "message": (
                    "Risk profile not set. Pass `willingness` "
                    "(volatility_reaction, risk_return_tradeoff, max_tolerable_loss) "
                    "to run the risk assessment as part of the analysis."
                ),
            }
        risk = await _risk_assess(household_id=household_id, willingness=willingness)
        if isinstance(risk, dict) and risk.get("error"):
            return {"ok": False, "stage": "risk", **risk}
        out["stages"]["risk"] = {
            "recommended_score": risk.recommended_score,
            "recommended_profile": risk.recommended_profile,
        }
    else:
        out["stages"]["risk"] = {
            "reused": True,
            "recommended_score": plan.computed.risk_profile.recommended_score,
            "recommended_profile": plan.computed.risk_profile.recommended_profile,
        }

    # ── Stage 2: allocation ── (always recompute to capture latest tactical signals)
    alloc = await _allocate_recommend(household_id=household_id)
    if isinstance(alloc, dict) and alloc.get("error"):
        return {"ok": False, "stage": "allocation", **alloc}
    out["stages"]["allocation"] = _alloc_summary(alloc)

    # ── Stage 3: tax ── (non-fatal — empty holdings are valid)
    tax = await _tax_harvest(household_id=household_id)
    if isinstance(tax, dict) and tax.get("error"):
        out["stages"]["tax"] = {"skipped": True, **tax}
    else:
        out["stages"]["tax"] = _tax_summary(tax)

    # ── Stage 4: monte carlo ── (uses the recommended allocation set above)
    mc = await _montecarlo_run(household_id=household_id, paths=paths)
    if isinstance(mc, dict) and mc.get("error"):
        out["stages"]["monte_carlo"] = {"skipped": True, **mc}
    else:
        out["stages"]["monte_carlo"] = _mc_summary(mc)

    # ── Stage 5: freedom score + cashflow ── (no risk gate; the PDF needs both)
    fs = await _freedom_score(household_id=household_id)
    if not (isinstance(fs, dict) and fs.get("error")):
        out["stages"]["freedom_score"] = {
            "final_score": fs.final_score,
            "estimated_freedom_age": fs.estimated_freedom_age,
        }
    cf = await _cashflow_project(household_id=household_id, horizon_years=45)
    if not (isinstance(cf, dict) and cf.get("error")):
        out["stages"]["cashflow"] = {"horizon_years": 45, "rows": len(cf.rows)}

    # ── Stage 6: report URL ──
    out["pdf_url"] = f"/api/report/{household_id}/pdf"
    out["stages"]["report"] = {"pdf_url": out["pdf_url"]}
    return out


# ── knowledge / news ───────────────────────────────────────────────────────


class KnowledgeRetrieveArgs(BaseModel):
    org_id: str = "main"
    query: str
    top_k: int = 3


async def _knowledge_retrieve(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await knowledge_skill.retrieve(kwargs)


class NewsRelevanceArgs(BaseModel):
    household_id: str
    top_k: int = 5


async def _news_relevance(**kwargs: Any) -> Any:
    kwargs = _coerce_kwargs(kwargs)
    return await news_skill.relevance_for_household(kwargs)


# ── Tool registry ──────────────────────────────────────────────────────────


def make_tools() -> list[StructuredTool]:
    """Build the StructuredTool list bound to LangChain. Names + arg schemas
    mirror the TS Zod definitions. `coroutine=` makes them async-callable."""
    return [
        StructuredTool.from_function(
            name="intake_ingest",
            description=(
                "Universal intake dispatcher. Accepts a file (PDF, XLSX, CSV, DOCX, MD, TXT, "
                "image, audio) or pasted text/transcript and returns a partial PlanState delta "
                "with evidence and per-field confidence."
            ),
            args_schema=IntakeIngestArgs,
            coroutine=_intake_ingest,
        ),
        StructuredTool.from_function(
            name="intake_confirm",
            description=(
                "Promote an LLM-extracted (low-confidence) field to confirmed when the user "
                "accepts it in chat."
            ),
            args_schema=IntakeConfirmArgs,
            coroutine=_intake_confirm,
        ),
        StructuredTool.from_function(
            name="plan_set",
            description="Set a single canonical field on PlanState (e.g. personal_details.date_of_birth).",
            args_schema=PlanSetArgs,
            coroutine=_plan_set,
        ),
        StructuredTool.from_function(
            name="plan_add",
            description=(
                "Append a row to a list-typed canonical section (income, expenses, events, "
                "holdings, goals)."
            ),
            args_schema=PlanAddArgs,
            coroutine=_plan_add,
        ),
        StructuredTool.from_function(
            name="plan_remove",
            description="Remove a row by id from a list-typed canonical section.",
            args_schema=PlanRemoveArgs,
            coroutine=_plan_remove,
        ),
        StructuredTool.from_function(
            name="plan_assumption",
            description=(
                "Set an assumption value (per-person DOB / life expectancy / retirement age, "
                "growth rates, taxes, inflation)."
            ),
            args_schema=PlanAssumptionArgs,
            coroutine=_plan_assumption,
        ),
        StructuredTool.from_function(
            name="risk_assess",
            description=(
                "Compute the 3-part risk profile (Capacity, Need, Willingness) and the reconciled "
                "recommended_score. Required before allocate / tax / montecarlo."
            ),
            args_schema=RiskAssessArgs,
            coroutine=_risk_assess,
        ),
        StructuredTool.from_function(
            name="allocate_recommend",
            description="Strategic + bounded tactical India allocation. Refuses if risk gate not passed.",
            args_schema=HouseholdOnlyArgs,
            coroutine=_allocate_recommend,
        ),
        StructuredTool.from_function(
            name="freedom_score",
            description="Compute the 5-pillar Freedom Score (0-100) with city-sensitive insurance logic.",
            args_schema=HouseholdOnlyArgs,
            coroutine=_freedom_score,
        ),
        StructuredTool.from_function(
            name="tax_harvest",
            description=(
                "Compute LTCG/STCG harvest suggestions, loss harvesting, combined impact, and "
                "fee-vs-value gates for the current FY. Refuses if risk gate not passed."
            ),
            args_schema=HouseholdOnlyArgs,
            coroutine=_tax_harvest,
        ),
        StructuredTool.from_function(
            name="debt_paydown",
            description=(
                "Per-loan amortization schedules + aggregate year-by-year EMI / interest / "
                "principal breakdown across every entry in `loans_liabilities`. Use this when "
                "the user asks 'when does my car loan end', 'how much interest am I paying on "
                "my home loan', or 'what if I prepay'. Fills `plan.computed.debt_paydown`."
            ),
            args_schema=HouseholdOnlyArgs,
            coroutine=_debt_paydown,
        ),
        StructuredTool.from_function(
            name="cfp_plan",
            description=(
                "Excel-faithful Comprehensive Financial Plan engine — mirrors the firm's "
                "`Format for inputs for CFP_ng_080626.xlsx` cell-for-cell. Returns per-goal "
                "FV/gap/SIP via the documented inflation table (Education 10%, Wedding 9%, "
                "Medical 12%, etc.) and glide-path effective return; the year-by-year cashflow "
                "with each asset class compounding at its own post-tax return; the retirement "
                "corpus via PV(real_return, post_retire_years, -annual_need); and Human Life "
                "Value + Needs-based insurance averaged. Every step is included in "
                "`computation_trace` so the user can see the math, not just the answer. Use "
                "this for the comprehensive financial-plan view; use `cashflow_project` for "
                "the simpler in-platform projection."
            ),
            args_schema=HouseholdOnlyArgs,
            coroutine=_cfp_plan,
        ),
        StructuredTool.from_function(
            name="cashflow_project",
            description="Year-by-year cash flow projection + 12-month forward strip + retirement glide.",
            args_schema=CashflowArgs,
            coroutine=_cashflow_project,
        ),
        StructuredTool.from_function(
            name="scenario_pin",
            description=(
                "Pin the current plan as a scenario (Plan A or Plan B). Adds a second curve and a "
                "second headline line."
            ),
            args_schema=ScenarioPinArgs,
            coroutine=_scenario_pin,
        ),
        StructuredTool.from_function(
            name="scenario_diff",
            description="Diff two scenarios and return per-field deltas + projection deltas.",
            args_schema=ScenarioDiffArgs,
            coroutine=_scenario_diff,
        ),
        StructuredTool.from_function(
            name="montecarlo_run",
            description=(
                "2,000-path Monte Carlo. Outputs P10/P50/P90 freedom-age. Refuses if risk gate not "
                "passed."
            ),
            args_schema=MonteCarloArgs,
            coroutine=_montecarlo_run,
        ),
        StructuredTool.from_function(
            name="knowledge_retrieve",
            description=(
                "Retrieve top-K chunks from the firm knowledge base. Returns chunk text + filename + "
                "heading + similarity score for inline citation."
            ),
            args_schema=KnowledgeRetrieveArgs,
            coroutine=_knowledge_retrieve,
        ),
        StructuredTool.from_function(
            name="news_relevance",
            description=(
                "Score how relevant each news item is for a specific household, using sector × direct "
                "holdings × asset-class exposure."
            ),
            args_schema=NewsRelevanceArgs,
            coroutine=_news_relevance,
        ),
        StructuredTool.from_function(
            name="report_generate",
            description=(
                "Return the downloadable PDF link for the household's plan plus which sections "
                "are populated and which are still missing. Use this after running risk / "
                "allocate / tax / montecarlo to hand the user a concrete download URL. "
                "The link points to the on-demand /api/report/{id}/pdf endpoint — clicking it "
                "renders the PDF with current PlanState. Set download=true to pre-render and "
                "report byte_size; otherwise this is a cheap URL handoff."
            ),
            args_schema=ReportGenerateArgs,
            coroutine=_report_generate,
        ),
        StructuredTool.from_function(
            name="run_full_analysis",
            description=(
                "Orchestrator: runs the canonical advisor flow — risk_assess → allocate_recommend "
                "→ tax_harvest → montecarlo_run — and returns one consolidated summary plus the "
                "PDF link. Every stage's result is persisted to PlanState so the PDF includes them. "
                "Pass `willingness` if the risk profile has not been set yet; otherwise the "
                "existing risk profile is reused. Use this whenever the user asks for 'the plan', "
                "'run the analysis', 'show me the full report', or 'wrap it up'."
            ),
            args_schema=RunFullAnalysisArgs,
            coroutine=_run_full_analysis,
        ),
    ]
