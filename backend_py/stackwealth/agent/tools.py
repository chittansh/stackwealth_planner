"""
LangChain tool definitions — each one dispatches to a Python skill module.

The Pydantic args schemas mirror the Zod schemas in agent/planner.ts so the
agent's JSON tool-call shapes are identical to the TS version.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..skills import allocate as allocate_skill
from ..skills import cashflow as cashflow_skill
from ..skills import freedom as freedom_skill
from ..skills import intake as intake_skill
from ..skills import knowledge as knowledge_skill
from ..skills import news as news_skill
from ..skills import risk as risk_skill
from ..skills import scenario as scenario_skill
from ..skills import tax as tax_skill


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
    return await scenario_skill.confirm_field(kwargs)


# ── plan_set / add / remove / assumption ───────────────────────────────────


class PlanSetArgs(BaseModel):
    household_id: str
    path: str
    value: Any
    source_type: SourceType = "user"


async def _plan_set(**kwargs: Any) -> Any:
    return await scenario_skill.apply_set(kwargs)


class PlanAddArgs(BaseModel):
    household_id: str
    path: str
    row: Any
    source_type: SourceType = "user"


async def _plan_add(**kwargs: Any) -> Any:
    return await scenario_skill.apply_add(kwargs)


class PlanRemoveArgs(BaseModel):
    household_id: str
    path: str
    id: str


async def _plan_remove(**kwargs: Any) -> Any:
    return await scenario_skill.apply_remove(kwargs)


class PlanAssumptionArgs(BaseModel):
    household_id: str
    path: str
    value: Any


async def _plan_assumption(**kwargs: Any) -> Any:
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
    w = kwargs.get("willingness")
    if isinstance(w, BaseModel):
        kwargs["willingness"] = w.model_dump(exclude_none=True)
    return await risk_skill.assess(kwargs)


# ── allocate / freedom / tax / cashflow ────────────────────────────────────


class HouseholdOnlyArgs(BaseModel):
    household_id: str


async def _allocate_recommend(**kwargs: Any) -> Any:
    return await allocate_skill.recommend(kwargs)


async def _freedom_score(**kwargs: Any) -> Any:
    return await freedom_skill.score(kwargs)


async def _tax_harvest(**kwargs: Any) -> Any:
    return await tax_skill.harvest(kwargs)


class CashflowArgs(BaseModel):
    household_id: str
    horizon_years: int = 45


async def _cashflow_project(**kwargs: Any) -> Any:
    return await cashflow_skill.project(kwargs)


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
    return await scenario_skill.pin(kwargs)


class ScenarioDiffArgs(BaseModel):
    household_id: str
    a: str
    b: str


async def _scenario_diff(**kwargs: Any) -> Any:
    return await scenario_skill.diff(kwargs)


class MonteCarloArgs(BaseModel):
    household_id: str
    paths: int = 2000


async def _montecarlo_run(**kwargs: Any) -> Any:
    return await scenario_skill.run_monte_carlo(kwargs)


# ── knowledge / news ───────────────────────────────────────────────────────


class KnowledgeRetrieveArgs(BaseModel):
    org_id: str = "main"
    query: str
    top_k: int = 3


async def _knowledge_retrieve(**kwargs: Any) -> Any:
    return await knowledge_skill.retrieve(kwargs)


class NewsRelevanceArgs(BaseModel):
    household_id: str
    top_k: int = 5


async def _news_relevance(**kwargs: Any) -> Any:
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
    ]
