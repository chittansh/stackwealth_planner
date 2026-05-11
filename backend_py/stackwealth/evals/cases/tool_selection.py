"""
Layer 2 — Single-turn agent tool-call assertions.

These cases send one user message and assert on the tool calls the agent
chose to emit, the args it filled in, and the assistant text it returned.

Each case maps to a specific prompt rule we shipped. When a prompt edit
silently regresses one of these rules, this layer is what catches it.
"""
from __future__ import annotations

from ..core import Case, UserMessage
from ..fixtures import as_fixture, bengaluru_single_21yo, empty
from ..judges import NoToolError, ProseDoesNotContain, ToolCalled


def _willingness_complete(args: dict) -> bool:
    """run_full_analysis with a complete willingness payload."""
    w = args.get("willingness") or {}
    return all(
        k in w for k in ("volatility_reaction", "risk_return_tradeoff", "max_tolerable_loss")
    )


CASES = [
    Case(
        id="L2.indian_numbers.crore_conversion",
        name="₹2.5 Cr is captured as 25,000,000 (not 25 lakhs)",
        layer=2,
        description=(
            "The eval-feedback bug: 'i want a 2.5 cr goa house in 2036'. The agent must "
            "call `plan_add` for the goal with target_amount = 25,000,000 (₹2.5 Cr), "
            "NOT 2,500,000 (₹25 lakhs, the silent 10× error)."
        ),
        tags=["indian-numbers", "regression-prone"],
        fixture=as_fixture(empty),
        steps=[
            UserMessage(
                text="i want to buy a 2.5 cr goa house by 2036, that's my goal. also im 21 in bengaluru.",
                label="2.5 Cr goal",
            )
        ],
        judges=[
            ToolCalled(
                tool_name="plan_add",
                arg_predicate=lambda a: (
                    isinstance(a.get("row"), dict)
                    and a["row"].get("target_amount") == 25000000
                ),
                predicate_label="row.target_amount == 25_000_000 (₹2.5 Cr)",
            ),
            NoToolError(),
        ],
    ),
    Case(
        id="L2.dob.full_date_asked",
        name="DOB is asked for as DD-MM-YYYY (no Jan 1 placeholder)",
        layer=2,
        description=(
            "When the user gives just their age, the agent should set "
            "`freedom_score_inputs.age` and ASK for the full DOB rather than "
            "fabricating `01-01-{year}`. Asserts on assistant prose mentioning "
            "the DOB ask and on `plan_add(assumptions.persons, ...)` NOT firing yet."
        ),
        tags=["dob", "regression-prone"],
        fixture=as_fixture(empty),
        steps=[UserMessage(text="im 22", label="age only")],
        judges=[
            ToolCalled(
                tool_name="plan_set",
                arg_predicate=lambda a: a.get("path") == "freedom_score_inputs.age"
                and a.get("value") == 22,
                predicate_label="freedom_score_inputs.age = 22",
            ),
            # The prompt forbids the Jan-1 placeholder — `plan_add` for persons[]
            # should NOT carry a fabricated date_of_birth.
            ProseDoesNotContain(
                forbidden=["01-01-2003", "01-01-2004"],
                description_override="Assistant must not surface a fabricated DOB placeholder",
            ),
        ],
    ),
    Case(
        id="L2.full_analysis.preferred_for_run_the_plan",
        name="'Run the analysis' triggers run_full_analysis with willingness",
        layer=2,
        description=(
            "When the user has answered the 3 willingness questions and asks for "
            "'the full analysis' or 'run the plan', the agent should pick "
            "`run_full_analysis` (the orchestrator) over a manual sequence of "
            "risk_assess + allocate + tax + montecarlo in one turn (which races)."
        ),
        tags=["orchestrator", "race-prevention"],
        fixture=as_fixture(bengaluru_single_21yo),
        steps=[
            UserMessage(
                text=(
                    "ok run the full analysis now — for the willingness questions: "
                    "hold steady on a drop, option C for risk/return, max loss 20%."
                ),
                label="ask for full analysis with willingness",
            )
        ],
        judges=[
            ToolCalled(
                tool_name="run_full_analysis",
                arg_predicate=_willingness_complete,
                predicate_label="willingness has volatility_reaction + risk_return_tradeoff + max_tolerable_loss",
            ),
            NoToolError(),
        ],
    ),
]
