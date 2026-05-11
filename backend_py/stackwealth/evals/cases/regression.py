"""
Layer 4 — Regression cases.

Each case here is a one-to-one mapping with a bug we've already shipped a fix
for. If any of these fail, a prompt edit or refactor has reopened the wound.
Adding a regression case is the *required* exit criterion when fixing a bug
caught by eval feedback.

Cases are anchored to commits on `main`:
- `fix/risk-assess-willingness`              — Pydantic-on-skill-args 10/05
- `fix/pydantic-coercion-and-pdf-link`       — generic coercion 10/05
- `fix/feedback-pass-1`                       — DOB / INR / recall / race / tone
- `fix/multi-scenario-chart-and-empty-cards` — empty assistant cards
"""
from __future__ import annotations

from ...skills.risk import assess as risk_assess
from ..core import Case, SkillCall, ToolCall
from ..fixtures import as_fixture, bengaluru_single_21yo, with_risk_set
from ..judges import (
    ComputedPresent,
    NoToolError,
    NumericEquals,
    ToolCalled,
)


CASES = [
    Case(
        id="L4.regression.willingness_pydantic_coercion",
        name="risk_assess accepts a Pydantic WillingnessArgs instance without crashing",
        layer=4,
        description=(
            "When the agent calls `risk_assess` via the LangChain StructuredTool "
            "wrapper, the `willingness` field arrives as a `WillingnessArgs` "
            "model instance — not a dict. The skill calls `.get(...)` on it. "
            "Pre-fix this raised `'WillingnessArgs' object has no attribute 'get'`. "
            "Fix lives in `agent/tools._coerce_kwargs`."
        ),
        tags=["pydantic-coercion", "regression-prone"],
        fixture=as_fixture(bengaluru_single_21yo),
        steps=[
            ToolCall(
                tool_name="risk_assess",
                kwargs={
                    "willingness": {
                        "volatility_reaction": "hold_steady",
                        "risk_return_tradeoff": "C",
                        "max_tolerable_loss": "20",
                    }
                },
                label="risk_assess via agent wrapper",
            ),
        ],
        judges=[
            NoToolError(),
            ComputedPresent(field="risk_profile"),
        ],
    ),
    Case(
        id="L4.regression.scenario_mutation_pydantic_coercion",
        name="scenario_pin accepts a Pydantic ScenarioMutationArg without crashing",
        layer=4,
        description=(
            "Same class of bug as the willingness coercion — `scenario_pin`'s "
            "`mutation` field is a nested Pydantic model under LangChain validation. "
            "Pre-fix this raised `'ScenarioMutationArg' object has no attribute 'get'` "
            "every time the user asked to pin a Plan B with explicit mutations."
        ),
        tags=["pydantic-coercion", "regression-prone"],
        fixture=as_fixture(with_risk_set(bengaluru_single_21yo)),
        steps=[
            ToolCall(
                tool_name="scenario_pin",
                kwargs={
                    "label": "Eval Plan B",
                    "mutation": {
                        "ops": [
                            {
                                "path": "monthly_investments.mutual_fund_sip",
                                "op": "set",
                                "value": 40000,
                            }
                        ]
                    },
                },
                label="scenario_pin with mutation",
            )
        ],
        judges=[NoToolError()],
    ),
    Case(
        id="L4.regression.risk_persists_after_chat_tool",
        name="Chat-driven risk_assess persists computed.risk_profile + allocation",
        layer=4,
        description=(
            "Before the persistence pass, the agent-side `_risk_assess` wrapper "
            "returned the result but never saved it. The PDF then rendered an "
            "empty allocation/risk section even after the user answered the 3 "
            "questions. The fix wires persistence + auto-compute-allocation "
            "into the agent wrapper."
        ),
        tags=["persistence", "regression-prone"],
        fixture=as_fixture(bengaluru_single_21yo),
        steps=[
            ToolCall(
                tool_name="risk_assess",
                kwargs={
                    "willingness": {
                        "volatility_reaction": "hold_steady",
                        "risk_return_tradeoff": "C",
                        "max_tolerable_loss": "20",
                    }
                },
                label="risk_assess via agent wrapper",
            )
        ],
        judges=[
            ComputedPresent(field="risk_profile"),
            ComputedPresent(field="allocation"),
            NoToolError(),
        ],
    ),
    Case(
        id="L4.regression.skill_risk_returns_correct_band",
        name="Skill-level risk_assess returns expected score for canonical input",
        layer=4,
        description=(
            "Anchored to PLANNER_GUIDE Scenario A. Bengaluru 21yo with hold_steady/C/20 "
            "should reconcile to a recommended_score around 53 (Moderate band) — "
            "willingness 60.5, capacity binding via emergency-fund cap, "
            "need dominated by the aggressive Goa goal."
        ),
        tags=["math", "reference-persona"],
        fixture=as_fixture(bengaluru_single_21yo),
        steps=[
            SkillCall(
                skill=risk_assess,
                args={
                    "willingness": {
                        "volatility_reaction": "hold_steady",
                        "risk_return_tradeoff": "C",
                        "max_tolerable_loss": "20",
                    }
                },
            )
        ],
        judges=[
            NumericEquals(path="willingness_score", expected=60, tolerance=2),
            NumericEquals(path="recommended_score", expected=53, tolerance=10),
        ],
    ),
]


# Silence the unused-import linter for ToolCalled (kept available for future cases).
_unused = ToolCalled
