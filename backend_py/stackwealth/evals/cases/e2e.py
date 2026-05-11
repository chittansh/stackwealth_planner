"""
Layer 3 — End-to-end multi-turn flows.

These cases simulate a real user session across several turns and assert on
the final PlanState plus the canonical-order tools the agent should have
called along the way. Slower than Layer 2 (multiple LLM calls per case) but
the only place that catches state-evolution bugs.
"""
from __future__ import annotations

from ..core import Case, UserMessage
from ..fixtures import as_fixture, bengaluru_pro_32yo_ready_for_analysis, empty
from ..judges import (
    ComputedPresent,
    NoToolError,
    PlanFieldSet,
    ToolCalled,
)


CASES = [
    Case(
        id="L3.onboarding.basics_to_canvas",
        name="From-scratch onboarding fills enough for the canvas to light up",
        layer=3,
        description=(
            "Simulates the canonical onboarding script: age+city → DOB → income → "
            "expenses → first goal. After the goal turn the agent should have "
            "enough to call `freedom_score` and `cashflow_project` so the canvas "
            "shows a number. Asserts on PlanState fields populated and on "
            "computed.freedom_score / computed.cashflow being set."
        ),
        tags=["onboarding", "happy-path"],
        fixture=as_fixture(empty),
        steps=[
            UserMessage(text="hi, lets set up my plan from scratch", label="opening"),
            UserMessage(text="im 32 years old and i live in mumbai", label="age + city"),
            UserMessage(text="my full DOB is 14-04-1994", label="DOB"),
            UserMessage(
                text="monthly take-home is 1.5L, im single with no dependents",
                label="income",
            ),
            UserMessage(
                text="rent 25k, groceries 15k, no other big expenses",
                label="expenses",
            ),
            UserMessage(
                text="retirement at 60 with 5 cr corpus, in today's money",
                label="retirement goal",
            ),
        ],
        judges=[
            PlanFieldSet(path="freedom_score_inputs.age"),
            PlanFieldSet(path="freedom_score_inputs.monthly_income"),
            PlanFieldSet(path="freedom_score_inputs.monthly_expenses"),
            PlanFieldSet(path="personal_details.city_of_residence"),
            ToolCalled(tool_name="plan_add"),
            ToolCalled(tool_name="freedom_score"),
            ToolCalled(tool_name="cashflow_project"),
            ComputedPresent(field="freedom_score"),
            ComputedPresent(field="cashflow"),
            NoToolError(),
        ],
    ),
    Case(
        id="L3.full_analysis.persists_every_section",
        name="run_full_analysis populates risk + allocation + tax + MC + freedom + cashflow",
        layer=3,
        description=(
            "Pre-seeded household + a single user message asking for the full analysis "
            "with willingness inline. The orchestrator must persist every section to "
            "PlanState (this was the original 'horizontal integration' acceptance "
            "criterion that the PDF depends on)."
        ),
        tags=["orchestrator", "happy-path"],
        fixture=as_fixture(bengaluru_pro_32yo_ready_for_analysis),
        steps=[
            UserMessage(
                text=(
                    "run the full analysis. for the willingness questions: "
                    "hold steady on a 30% drop, option C for risk-return preference, "
                    "max tolerable single-year loss is 20 percent."
                ),
                label="ask for full analysis",
            )
        ],
        judges=[
            ToolCalled(tool_name="run_full_analysis"),
            ComputedPresent(field="risk_profile"),
            ComputedPresent(field="allocation"),
            ComputedPresent(field="monte_carlo"),
            ComputedPresent(field="freedom_score"),
            ComputedPresent(field="cashflow"),
            NoToolError(),
        ],
    ),
]
