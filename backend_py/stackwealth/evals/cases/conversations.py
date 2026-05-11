"""
Layer 3 (extended) — Twenty full multi-turn conversations.

Each case is a realistic 10-15 turn user session. The conversations split
across three flow families:

  Onboarding (5 cases)         — start from an empty plan, walk to a
                                  populated PlanState with analytics run.
  Mid-funnel analytics (5)     — pre-seeded household, exercise risk
                                  quiz / orchestrator / scenarios.
  Edge cases (5)               — Indian-number stress, casual tone,
                                  goal-risk-mismatch resolution,
                                  re-engagement, validator hygiene.
  Full advisor flows (5)       — onboarding → analysis → scenarios → PDF.

Judges lean on stable signals (tool calls happened, plan fields populated,
computed.* present, no «unverified» leak). Brittle prose-match assertions
are avoided so the suite isn't flaky against LLM phrasing drift.
"""
from __future__ import annotations

from ..core import Case, UserMessage
from ..fixtures import (
    as_fixture,
    bengaluru_pro_32yo_ready_for_analysis,
    bengaluru_single_21yo,
    empty,
    mumbai_family_32yo,
    with_risk_set,
)
from ..judges import (
    ComputedPresent,
    NoToolError,
    PlanFieldSet,
    ProseDoesNotContain,
    ToolCalled,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _goal_amount(expected: int):
    """Predicate: the row in plan_add has the expected target_amount."""

    def _pred(args):
        row = args.get("row") or {}
        return row.get("target_amount") == expected

    return _pred


# Common judges every conversation should pass.
_NO_UNVERIFIED = ProseDoesNotContain(
    forbidden=["«unverified"],
    description_override="No number bled through the validator (no «unverified» tokens)",
)


# ─────────────────────────────────────────────────────────────────────────
# Onboarding family — start from empty, build PlanState end-to-end.
# ─────────────────────────────────────────────────────────────────────────


_C1 = Case(
    id="L3.conv.bengaluru_21yo_onboarding",
    name="Bengaluru 21yo — empty plan → risk quiz → full analysis (13 turns)",
    layer=3,
    description=(
        "The canonical Goa-house persona. Walks from a blank plan to a full "
        "analysis with a ₹2.5 Cr goal, exercising age capture, DOB ask, "
        "city → city_type inference, expense capture, EMI capture, the "
        "₹2.5 Cr → 25,000,000 conversion, and the risk-gate → orchestrator path."
    ),
    tags=["conversation", "onboarding", "bengaluru", "indian-numbers"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("hi, lets build my plan from scratch"),
        UserMessage("im 21, live in bengaluru"),
        UserMessage("my full DOB is 14-04-2005"),
        UserMessage("im single, no dependents, want to retire at 60"),
        UserMessage("my monthly take-home is 1.5L"),
        UserMessage("rent 40k, groceries 20k, no other regular expenses"),
        UserMessage("i pay 13k EMI on a car loan, ₹8L outstanding at 10% interest, 5 years left"),
        UserMessage("i have ₹3L savings in an FD, nothing else invested"),
        UserMessage("no insurance at all yet"),
        UserMessage("my main goal is a 2.5 Cr goa house by 2036"),
        UserMessage("ok ready for risk quiz, ask the questions"),
        UserMessage("hold steady on a drop, option C, max loss i can stomach is 20%"),
        UserMessage("now run the full analysis please"),
    ],
    judges=[
        PlanFieldSet(path="freedom_score_inputs.age"),
        PlanFieldSet(path="personal_details.city_of_residence"),
        PlanFieldSet(path="assumptions.persons.0.date_of_birth"),
        ToolCalled(
            tool_name="plan_add",
            arg_predicate=_goal_amount(25000000),
            predicate_label="Goa house at ₹2.5 Cr → 25,000,000 (not 2,500,000)",
        ),
        ToolCalled(tool_name="run_full_analysis"),
        ComputedPresent(field="risk_profile"),
        ComputedPresent(field="allocation"),
        ComputedPresent(field="monte_carlo"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C2 = Case(
    id="L3.conv.mumbai_family_onboarding",
    name="Mumbai family — dual goals + EMI + insurance gaps (14 turns)",
    layer=3,
    description=(
        "32yo dual-income Mumbai household with two dependents. Two-goal "
        "structure (house in 2032, retirement in 2054) plus a home loan EMI "
        "and an existing term plan. Exercises plan_add for multiple goals, "
        "loans_liabilities capture, and the city × dependent insurance "
        "requirement math."
    ),
    tags=["conversation", "onboarding", "mumbai", "family"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("hi we want to set up our financial plan"),
        UserMessage("im 32, my wife is 30, we live in mumbai with 2 kids"),
        UserMessage("my DOB is 15-09-1993, my wife's is 22-03-1995"),
        UserMessage("im targeting retirement at 60"),
        UserMessage("my monthly take-home is 2L, wife earns 80k"),
        UserMessage("rent EMI is 25k (we have a home loan), groceries 15k, school 15k, utilities 5k"),
        UserMessage("home loan is 14L outstanding at 8.5%, 12 years left, EMI 25k"),
        UserMessage("savings 3L, MFs 5L, equity 2L roughly"),
        UserMessage("i have ₹50L term cover, my wife has ₹25L. health is ₹5L family floater"),
        UserMessage("goal 1: bigger house in 2032 for ₹80L in today's money"),
        UserMessage("goal 2: retirement at 60 with ₹5 Cr corpus"),
        UserMessage("kids education: ₹40L by 2040"),
        UserMessage("ready for risk quiz"),
        UserMessage("hold steady, option C, max loss 20%"),
    ],
    judges=[
        PlanFieldSet(path="personal_details.city_of_residence"),
        PlanFieldSet(path="freedom_score_inputs.monthly_income"),
        PlanFieldSet(path="loans_liabilities.home_loan"),
        ToolCalled(tool_name="plan_add", arg_predicate=_goal_amount(8000000),
                   predicate_label="House goal at ₹80L"),
        ToolCalled(tool_name="plan_add", arg_predicate=_goal_amount(50000000),
                   predicate_label="Retirement goal at ₹5 Cr"),
        ToolCalled(tool_name="risk_assess"),
        ComputedPresent(field="risk_profile"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C3 = Case(
    id="L3.conv.pune_couple_dual_income",
    name="Pune couple — dual income, no kids yet, three goals (12 turns)",
    layer=3,
    description=(
        "Dual-income couple in Pune, both 28, no dependents. Exercises "
        "spouse_salary capture, multiple goals across different horizons, "
        "and the kids-goal-as-future scenario."
    ),
    tags=["conversation", "onboarding", "pune", "couple"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("hey we want to plan our finances as a couple"),
        UserMessage("both 28, live in pune, married, no kids yet but planning"),
        UserMessage("my DOB 05-08-1997, partner's is 12-12-1997"),
        UserMessage("we both work, my take-home 1.2L, hers 1L"),
        UserMessage("rent 30k, groceries 12k, utilities 4k, lifestyle 15k"),
        UserMessage("no EMIs, no loans"),
        UserMessage("we have 8L combined in savings + 6L in MFs"),
        UserMessage("term cover ₹75L each, health 10L family floater"),
        UserMessage("goal: own a flat by 2031, target ₹1.2 Cr"),
        UserMessage("retirement at 55 for both with ₹6 Cr corpus"),
        UserMessage("kids education future goal: ₹50L by 2042"),
        UserMessage("run the risk profile flow"),
    ],
    judges=[
        PlanFieldSet(path="personal_details.city_of_residence"),
        PlanFieldSet(path="income_details.spouse_salary_in_hand"),
        ToolCalled(tool_name="plan_add", arg_predicate=_goal_amount(12000000),
                   predicate_label="Flat goal at ₹1.2 Cr (12,000,000)"),
        ToolCalled(tool_name="plan_add", arg_predicate=_goal_amount(60000000),
                   predicate_label="Retirement at ₹6 Cr (60,000,000)"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C4 = Case(
    id="L3.conv.hyderabad_new_grad_low_income",
    name="Hyderabad new grad — low income, first SIP, no goals yet (11 turns)",
    layer=3,
    description=(
        "23yo new grad in Hyderabad on a starter salary. Tests the agent "
        "gracefully handling a household where the math will be tight, "
        "and starts the SIP discipline from scratch."
    ),
    tags=["conversation", "onboarding", "hyderabad", "starter"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("hi i just started working, want to plan my finances"),
        UserMessage("23, hyderabad, single, no dependents"),
        UserMessage("DOB is 02-06-2003"),
        UserMessage("monthly take-home is ₹45k"),
        UserMessage("rent 12k, groceries 8k, utilities 2k, internet 1k"),
        UserMessage("no loans yet"),
        UserMessage("savings is only 30k, no investments at all"),
        UserMessage("no insurance"),
        UserMessage("i want to retire by 55 with ₹3 Cr"),
        UserMessage("can you tell me what my freedom score looks like?"),
        UserMessage("what's the freedom age estimate from this?"),
    ],
    judges=[
        PlanFieldSet(path="freedom_score_inputs.age"),
        PlanFieldSet(path="freedom_score_inputs.monthly_income"),
        ToolCalled(tool_name="freedom_score"),
        ComputedPresent(field="freedom_score"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C5 = Case(
    id="L3.conv.delhi_midcareer_home_loan",
    name="Delhi mid-career — heavy EMI + retirement pressure (13 turns)",
    layer=3,
    description=(
        "42yo Delhi household with a heavy home loan and tight surplus. "
        "Exercises the EMI/income ratio impact on capacity, debt pillar in "
        "freedom score, and goal feasibility under a constrained budget."
    ),
    tags=["conversation", "onboarding", "delhi", "high-emi"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("hi need a financial plan, things are getting tight"),
        UserMessage("im 42, delhi, married, one kid (age 8)"),
        UserMessage("DOB 18-11-1983"),
        UserMessage("retirement target 60"),
        UserMessage("my take-home is 2.5L per month"),
        UserMessage("rent EMI is 95k (heavy home loan), groceries 25k, school 18k, utilities 7k"),
        UserMessage("home loan 1.2 Cr outstanding at 9%, 18 years left, EMI 95k"),
        UserMessage("savings 5L, MFs 12L, no equity, no FDs"),
        UserMessage("term cover ₹2 Cr, health 15L"),
        UserMessage("retirement at 60 with ₹6 Cr corpus"),
        UserMessage("kid's education ₹50L by 2035"),
        UserMessage("ready for risk quiz"),
        UserMessage("sell some on a 30% drop, option B, max loss 10%"),
    ],
    judges=[
        PlanFieldSet(path="loans_liabilities.home_loan"),
        PlanFieldSet(path="freedom_score_inputs.monthly_emi"),
        ToolCalled(tool_name="plan_add", arg_predicate=_goal_amount(60000000),
                   predicate_label="Retirement goal at ₹6 Cr"),
        ToolCalled(tool_name="risk_assess"),
        ComputedPresent(field="risk_profile"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


# ─────────────────────────────────────────────────────────────────────────
# Mid-funnel — pre-seeded household, run analytics + scenarios.
# ─────────────────────────────────────────────────────────────────────────


_C6 = Case(
    id="L3.conv.mumbai_risk_quiz_to_analysis",
    name="Pre-seeded Mumbai family — risk quiz to full analysis (11 turns)",
    layer=3,
    description=(
        "Household is already populated; conversation focuses on the risk "
        "quiz exchange and the orchestrator. Validates that the agent stays "
        "in advisor tone, surfaces the goal-risk-mismatch flag, and runs "
        "every analytics tool."
    ),
    tags=["conversation", "analytics", "mumbai"],
    fixture=as_fixture(mumbai_family_32yo),
    steps=[
        UserMessage("hi, where do we stand on the plan?"),
        UserMessage("can you walk me through what we need to lock in next"),
        UserMessage("ok lets do the risk profile"),
        UserMessage("if there's a 30% drop i'd hold steady, not panic"),
        UserMessage("for return preference, option C - decent growth, accept some swings"),
        UserMessage("max loss in a year i can handle is 20%"),
        UserMessage("ok lets run the full analysis"),
        UserMessage("what's the freedom score looking like?"),
        UserMessage("and what about the goal probabilities?"),
        UserMessage("any flags i should worry about?"),
        UserMessage("can you give me the PDF link?"),
    ],
    judges=[
        ToolCalled(tool_name="risk_assess"),
        ToolCalled(tool_name="run_full_analysis"),
        ComputedPresent(field="risk_profile"),
        ComputedPresent(field="allocation"),
        ComputedPresent(field="monte_carlo"),
        ComputedPresent(field="freedom_score"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C7 = Case(
    id="L3.conv.bengaluru_plan_a_vs_b_sip",
    name="Bengaluru — Plan A vs Plan B with SIP delta scenario (12 turns)",
    layer=3,
    description=(
        "Pre-seeded with risk profile. User compares baseline vs a Plan B "
        "with a ₹45k SIP added. Tests scenario_pin with explicit mutation "
        "(the Pydantic-coercion regression) and scenario_diff."
    ),
    tags=["conversation", "scenarios", "plan-b"],
    fixture=as_fixture(with_risk_set(bengaluru_single_21yo)),
    steps=[
        UserMessage("hi, where are we on the analysis?"),
        UserMessage("run the full analysis"),
        UserMessage("got it. now i want to model adding a SIP"),
        UserMessage("pin the current plan as Plan A"),
        UserMessage("now pin a Plan B with a ₹45k monthly SIP added"),
        UserMessage("how does plan B compare to plan A?"),
        UserMessage("what happens to the goa house probability under plan B?"),
        UserMessage("what if i bump it to ₹60k SIP instead?"),
        UserMessage("pin that as Plan C"),
        UserMessage("which plan looks most realistic for me?"),
        UserMessage("can i see the PDF with all three plans?"),
        UserMessage("download the plan please"),
    ],
    judges=[
        ToolCalled(tool_name="run_full_analysis"),
        ToolCalled(tool_name="scenario_pin"),
        ComputedPresent(field="risk_profile"),
        ComputedPresent(field="monte_carlo"),
        ToolCalled(tool_name="report_generate"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C8 = Case(
    id="L3.conv.pune_couple_retirement_age_delta",
    name="Pune couple — early retirement scenario at 50 vs 55 (12 turns)",
    layer=3,
    description=(
        "Pre-seeded couple wants to compare retiring at 50 instead of 55. "
        "Tests retirement_age_target mutation through plan_assumption + "
        "scenario_pin, and the agent's narration of the headline delta."
    ),
    tags=["conversation", "scenarios", "retirement"],
    fixture=as_fixture(bengaluru_pro_32yo_ready_for_analysis),
    steps=[
        UserMessage("hi, can you run the full analysis first?"),
        UserMessage("for willingness — hold steady, option C, max loss 20%"),
        UserMessage("ok now i want to see what early retirement at 50 looks like"),
        UserMessage("pin current as Plan A (retire at 60)"),
        UserMessage("now show me Plan B with retirement at 50"),
        UserMessage("what's the headline number difference?"),
        UserMessage("what about retirement at 55 - call that Plan C"),
        UserMessage("which retirement age is realistic for me?"),
        UserMessage("can i see all three plans on the same chart?"),
        UserMessage("ok lets go with the retire-at-55 path"),
        UserMessage("get me the PDF of the final plan"),
        UserMessage("thanks"),
    ],
    judges=[
        ToolCalled(tool_name="run_full_analysis"),
        ToolCalled(tool_name="scenario_pin"),
        ComputedPresent(field="risk_profile"),
        ComputedPresent(field="allocation"),
        ComputedPresent(field="monte_carlo"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C9 = Case(
    id="L3.conv.equity_drawdown_shock",
    name="Equity drawdown shock — model a 35% market crash scenario (11 turns)",
    layer=3,
    description=(
        "Tests the equity drawdown shock variant of scenario_pin. The user "
        "wants to see what a -35% equity shock does to the projection."
    ),
    tags=["conversation", "scenarios", "stress-test"],
    fixture=as_fixture(with_risk_set(mumbai_family_32yo)),
    steps=[
        UserMessage("hi, run the full analysis"),
        UserMessage("ok now i want to stress test this"),
        UserMessage("what if there's a 35% market crash in the next 5 years?"),
        UserMessage("how does that affect my retirement timeline?"),
        UserMessage("pin a Plan B with that drawdown shock"),
        UserMessage("compare to baseline"),
        UserMessage("what's the recovery time roughly?"),
        UserMessage("would my goals still be on track?"),
        UserMessage("should i increase my emergency fund as a buffer?"),
        UserMessage("ok lets keep the current plan but bump emergency fund target"),
        UserMessage("download the final PDF"),
    ],
    judges=[
        ToolCalled(tool_name="run_full_analysis"),
        ComputedPresent(field="risk_profile"),
        ComputedPresent(field="monte_carlo"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C10 = Case(
    id="L3.conv.goal_target_reduction",
    name="Goal stress — lower the house target to fit risk (12 turns)",
    layer=3,
    description=(
        "User starts with an aggressive house goal that surfaces "
        "goal_risk_mismatch. Walks through the options (extend horizon, "
        "increase SIP, reduce target) and finally lowers the target. "
        "Tests plan_set on financial_goals[0].target_amount."
    ),
    tags=["conversation", "goals", "mismatch-resolution"],
    fixture=as_fixture(mumbai_family_32yo),
    steps=[
        UserMessage("hi, run risk first"),
        UserMessage("hold steady, option C, max loss 20%"),
        UserMessage("now show me where the house goal stands"),
        UserMessage("what does 'goal risk mismatch' mean exactly?"),
        UserMessage("what are my options to fix it?"),
        UserMessage("ok lets try reducing the house target"),
        UserMessage("change house target to ₹60L instead of ₹80L"),
        UserMessage("does that close the gap?"),
        UserMessage("run the analysis again with the new target"),
        UserMessage("how does the probability look now?"),
        UserMessage("ok good, lets lock this in"),
        UserMessage("send the PDF"),
    ],
    judges=[
        ToolCalled(tool_name="risk_assess"),
        ToolCalled(tool_name="plan_set"),
        ComputedPresent(field="risk_profile"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


# ─────────────────────────────────────────────────────────────────────────
# Edge cases — number stress, tone, validator hygiene.
# ─────────────────────────────────────────────────────────────────────────


_C11 = Case(
    id="L3.conv.indian_numbers_stress",
    name="Indian numbers stress — 2.5 Cr, 80L, 5 Cr, 15 LPA in one session (12 turns)",
    layer=3,
    description=(
        "Bombards the agent with a variety of Indian number formats across "
        "one conversation to catch any 10× errors. Includes lakhs, crores, "
        "and LPA shorthand."
    ),
    tags=["conversation", "indian-numbers", "stress"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("hi setup my plan"),
        UserMessage("30, mumbai, single"),
        UserMessage("DOB 22-07-1995"),
        UserMessage("CTC is 25 LPA, take-home around ₹1.5L per month"),
        UserMessage("rent 35k, groceries 10k, lifestyle 15k"),
        UserMessage("no EMIs"),
        UserMessage("savings ₹8L, MFs ₹12L, equity ₹3L, ULIP ₹2L"),
        UserMessage("term cover ₹1.5 Cr, health ₹10L"),
        UserMessage("goal 1: buy a 2.5 Cr flat in mumbai by 2032"),
        UserMessage("goal 2: retirement at 60 with ₹5 Cr corpus"),
        UserMessage("goal 3: foreign trip every year ₹80k each"),
        UserMessage("kid's marriage in 2042 budget ₹50L"),
    ],
    judges=[
        ToolCalled(
            tool_name="plan_add",
            arg_predicate=_goal_amount(25000000),
            predicate_label="2.5 Cr flat → 25,000,000",
        ),
        ToolCalled(
            tool_name="plan_add",
            arg_predicate=_goal_amount(50000000),
            predicate_label="Retirement ₹5 Cr → 50,000,000",
        ),
        ToolCalled(
            tool_name="plan_add",
            arg_predicate=_goal_amount(5000000),
            predicate_label="Marriage ₹50L → 5,000,000",
        ),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C12 = Case(
    id="L3.conv.casual_tone_consistency",
    name="Casual user — agent stays professional, no slang/emoji (12 turns)",
    layer=3,
    description=(
        "User types casually ('yo', 'bro', 'lol'). The agent must reply in "
        "a consistent professional advisor tone — no mirrored slang or "
        "emoji — per the tone-consistency prompt rule."
    ),
    tags=["conversation", "tone", "regression-prone"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("yo lets do my plan"),
        UserMessage("im 27 bangalore, single"),
        UserMessage("dob 11-11-1998 bro"),
        UserMessage("salary is 1.8L per month lol decent"),
        UserMessage("rent 35k, groceries 12k, that's it"),
        UserMessage("no loans no insurance just chillin"),
        UserMessage("savings 4L in fd, no investments lol"),
        UserMessage("goal: chill retire at 50 with 4 cr"),
        UserMessage("yo can you score me out"),
        UserMessage("bro just run everything"),
        UserMessage("hold steady, C, 20%"),
        UserMessage("send the pdf"),
    ],
    judges=[
        ProseDoesNotContain(
            forbidden=["yo ", "bro ", "lol", "chillin", "😊", "👍", "🚀", "💰"],
            description_override="Agent must not mirror slang/emoji",
        ),
        ToolCalled(tool_name="risk_assess"),
        ComputedPresent(field="risk_profile"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C13 = Case(
    id="L3.conv.risk_gate_avoided_via_orchestrator",
    name="User asks for MC before risk — agent doesn't crash, uses orchestrator (11 turns)",
    layer=3,
    description=(
        "User jumps ahead and asks for Monte Carlo before any risk profile "
        "exists. The agent should either run the 3-question risk quiz first "
        "or use `run_full_analysis(willingness=...)`. Critically: must NOT "
        "emit risk_assess + montecarlo_run in the same turn (the race that "
        "caused the 'system blockage' bug)."
    ),
    tags=["conversation", "risk-gate", "regression-prone"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("hi i want monte carlo on my plan"),
        UserMessage("im 35, mumbai, married, 1 kid"),
        UserMessage("DOB 03-04-1990"),
        UserMessage("take-home 2L monthly"),
        UserMessage("expenses 80k total"),
        UserMessage("portfolio 15L in MFs"),
        UserMessage("term cover 1 Cr, health 10L"),
        UserMessage("retirement at 60 with 5 Cr"),
        UserMessage("now run monte carlo"),
        UserMessage("oh i guess i need risk first - hold steady, C, 20%"),
        UserMessage("now show me the MC outcome"),
    ],
    judges=[
        ToolCalled(tool_name="risk_assess"),
        ComputedPresent(field="risk_profile"),
        ComputedPresent(field="monte_carlo"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C14 = Case(
    id="L3.conv.goal_risk_mismatch_resolution",
    name="Goal-risk mismatch — agent surfaces 4 options + user picks one (13 turns)",
    layer=3,
    description=(
        "Aggressive house goal forces goal_risk_mismatch. Agent should "
        "surface the four canned options (raise SIP, extend horizon, "
        "lower target, split goal). User picks 'extend horizon' and the "
        "agent updates the target_year via plan_set."
    ),
    tags=["conversation", "goals", "mismatch-resolution"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("hi build my plan"),
        UserMessage("im 35, mumbai, married with 1 kid"),
        UserMessage("DOB 11-04-1990"),
        UserMessage("take-home 1.8L monthly, wife 60k"),
        UserMessage("rent 30k, groceries 15k, school 10k"),
        UserMessage("MFs 8L"),
        UserMessage("term cover 1 Cr, health 5L"),
        UserMessage("retirement at 60, ₹5 Cr"),
        UserMessage("AND i want a 3 Cr second home in coorg by 2030"),
        UserMessage("risk: hold steady, C, 20%"),
        UserMessage("run the analysis"),
        UserMessage("ok i see the mismatch. lets extend the coorg house to 2038"),
        UserMessage("now re-run"),
    ],
    judges=[
        ToolCalled(tool_name="plan_add", arg_predicate=_goal_amount(30000000),
                   predicate_label="Coorg house ₹3 Cr → 30,000,000"),
        ToolCalled(tool_name="risk_assess"),
        ComputedPresent(field="risk_profile"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C15 = Case(
    id="L3.conv.reengagement_update_expenses",
    name="Re-engagement — user updates expenses 6 months later (12 turns)",
    layer=3,
    description=(
        "Pre-seeded household. User comes back to update expenses after a "
        "life change (new rent, new EMI). Tests plan_set on existing fields "
        "without recreating goals, and the agent's recall of the running "
        "PlanState (state summary)."
    ),
    tags=["conversation", "reengagement"],
    fixture=as_fixture(bengaluru_pro_32yo_ready_for_analysis),
    steps=[
        UserMessage("hi im back, want to update some numbers"),
        UserMessage("what's on file currently?"),
        UserMessage("my rent went up - now 45k instead of 25k"),
        UserMessage("also started a 12k EMI on a personal loan, 5L outstanding at 12% for 5 years"),
        UserMessage("salary bumped up - now 2.2L take-home"),
        UserMessage("savings is now 15L"),
        UserMessage("rerun the freedom score"),
        UserMessage("how does this change the analysis?"),
        UserMessage("any new flags?"),
        UserMessage("should i still target same goals?"),
        UserMessage("run full analysis with the updates"),
        UserMessage("get me the new PDF"),
    ],
    judges=[
        ToolCalled(tool_name="plan_set"),
        ToolCalled(tool_name="freedom_score"),
        ComputedPresent(field="freedom_score"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


# ─────────────────────────────────────────────────────────────────────────
# Full advisor flows — onboarding → analysis → scenarios → PDF.
# ─────────────────────────────────────────────────────────────────────────


_C16 = Case(
    id="L3.conv.full_advisor_session_bengaluru",
    name="Full advisor session — Bengaluru 21yo, blank to downloaded PDF (15 turns)",
    layer=3,
    description=(
        "The longest case: from a blank plan all the way to a downloaded "
        "PDF with two scenarios pinned. Exercises every major agent flow "
        "in one conversation."
    ),
    tags=["conversation", "full-advisor", "bengaluru"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("hi setup my plan"),
        UserMessage("21, bengaluru, single"),
        UserMessage("DOB 14-04-2005"),
        UserMessage("monthly take-home 1.5L"),
        UserMessage("rent 40k, groceries 20k, no other expenses, 13k car EMI"),
        UserMessage("savings 3L FD, no investments"),
        UserMessage("no insurance"),
        UserMessage("goal: 2.5 Cr goa house by 2036"),
        UserMessage("retirement at 60 with ₹5 Cr corpus"),
        UserMessage("hold steady, C, 20% for risk"),
        UserMessage("run the full analysis"),
        UserMessage("pin current as Plan A"),
        UserMessage("pin Plan B with ₹40k monthly SIP added"),
        UserMessage("show me the comparison"),
        UserMessage("send the final PDF with both plans"),
    ],
    judges=[
        PlanFieldSet(path="freedom_score_inputs.age"),
        PlanFieldSet(path="personal_details.city_of_residence"),
        ToolCalled(tool_name="plan_add", arg_predicate=_goal_amount(25000000),
                   predicate_label="2.5 Cr Goa house"),
        ToolCalled(tool_name="run_full_analysis"),
        ToolCalled(tool_name="scenario_pin"),
        ToolCalled(tool_name="report_generate"),
        ComputedPresent(field="risk_profile"),
        ComputedPresent(field="allocation"),
        ComputedPresent(field="monte_carlo"),
        ComputedPresent(field="freedom_score"),
        ComputedPresent(field="cashflow"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C17 = Case(
    id="L3.conv.insurance_gap_session",
    name="Insurance gap deep dive — top-up sequence (11 turns)",
    layer=3,
    description=(
        "Pre-seeded Mumbai family with insufficient cover. Agent surfaces "
        "the city × dependent multiplier and the gap. User updates cover "
        "via plan_set and the gap narrows."
    ),
    tags=["conversation", "insurance"],
    fixture=as_fixture(mumbai_family_32yo),
    steps=[
        UserMessage("hi, what's my freedom score?"),
        UserMessage("why is the risk pillar low?"),
        UserMessage("what's the required cover for my profile?"),
        UserMessage("ok lets fix it. i'm bumping term to ₹2 Cr"),
        UserMessage("annual premium for that is ₹18k"),
        UserMessage("health insurance moving to ₹15L family floater"),
        UserMessage("premium for health is ₹22k annual"),
        UserMessage("now rerun freedom score"),
        UserMessage("better? what's the new risk pillar score?"),
        UserMessage("any other insurance gaps i should worry about?"),
        UserMessage("get me the updated PDF"),
    ],
    judges=[
        ToolCalled(tool_name="freedom_score"),
        ToolCalled(tool_name="plan_set"),
        ComputedPresent(field="freedom_score"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C18 = Case(
    id="L3.conv.multi_goal_prioritization",
    name="Multi-goal prioritization — essential vs important vs aspirational (13 turns)",
    layer=3,
    description=(
        "User has 4 goals across different priorities. Agent should help "
        "rank them, identify the binding constraint, and the orchestrator "
        "should drive analysis correctly. Tests priority + horizon interplay."
    ),
    tags=["conversation", "goals", "multi-goal"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("hi i have a lot of goals, lets prioritize"),
        UserMessage("im 38, hyderabad, married, 2 kids ages 8 and 5"),
        UserMessage("DOB 09-09-1987"),
        UserMessage("take-home 3L per month, wife 1L"),
        UserMessage("monthly expenses 80k total"),
        UserMessage("portfolio 25L MFs, savings 10L"),
        UserMessage("term 1.5 Cr, health 10L"),
        UserMessage("goal 1: retirement at 55 with ₹8 Cr (essential)"),
        UserMessage("goal 2: kid1 education ₹50L by 2035 (essential)"),
        UserMessage("goal 3: kid2 education ₹50L by 2038 (essential)"),
        UserMessage("goal 4: dream villa in goa ₹4 Cr by 2040 (aspirational)"),
        UserMessage("hold steady, C, 30%"),
        UserMessage("run full analysis"),
    ],
    judges=[
        ToolCalled(tool_name="plan_add", arg_predicate=_goal_amount(80000000),
                   predicate_label="Retirement ₹8 Cr → 80,000,000"),
        ToolCalled(tool_name="plan_add", arg_predicate=_goal_amount(40000000),
                   predicate_label="Goa villa ₹4 Cr → 40,000,000"),
        ToolCalled(tool_name="run_full_analysis"),
        ComputedPresent(field="risk_profile"),
        ComputedPresent(field="allocation"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C19 = Case(
    id="L3.conv.tax_harvest_with_holdings",
    name="Tax harvest deep dive — pre-seeded MF holdings (12 turns)",
    layer=3,
    description=(
        "Household has holdings already. Tests tax_harvest with real "
        "candidates (using the 30% unrealized gain proxy and round-trip "
        "cost gate). User explores LTCG headroom and the agent's "
        "recommendations."
    ),
    tags=["conversation", "tax", "holdings"],
    fixture=as_fixture(with_risk_set(mumbai_family_32yo)),
    steps=[
        UserMessage("hi i want to plan some tax harvesting this FY"),
        UserMessage("im holding 15L in MFs across 3 funds"),
        UserMessage("fund 1: HDFC top 100, current value ₹6L, bought ~3 years ago"),
        UserMessage("fund 2: Axis bluechip, current value ₹5L, also ~3 years ago"),
        UserMessage("fund 3: Mirae small cap, ₹4L, bought 2 years ago"),
        UserMessage("ok now run tax harvest analysis"),
        UserMessage("what's my LTCG headroom this FY?"),
        UserMessage("which fund should i harvest gains from?"),
        UserMessage("any loss harvesting opportunities?"),
        UserMessage("how much tax am i actually saving?"),
        UserMessage("ok lock in those recommendations"),
        UserMessage("get me the updated PDF"),
    ],
    judges=[
        ToolCalled(tool_name="plan_add"),
        ToolCalled(tool_name="tax_harvest"),
        ComputedPresent(field="tax"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


_C20 = Case(
    id="L3.conv.csp_pdf_full_pipeline",
    name="From-scratch to downloaded PDF — every section populated (15 turns)",
    layer=3,
    description=(
        "Comprehensive sign-off case. Tests the entire pipeline: every "
        "PlanState section gets touched, every computed.* field gets "
        "populated, the PDF is rendered. If THIS case fails, something "
        "fundamental about the agent flow is broken."
    ),
    tags=["conversation", "full-advisor", "smoke", "sign-off"],
    fixture=as_fixture(empty),
    steps=[
        UserMessage("hi setup my plan from scratch"),
        UserMessage("im 35, kolkata, married, 1 kid"),
        UserMessage("DOB 20-12-1990, partner 18-06-1992, kid 05-05-2018"),
        UserMessage("retirement target 60 for me"),
        UserMessage("take-home 2.2L monthly, wife 1L"),
        UserMessage("rent 28k, groceries 14k, school 8k, lifestyle 12k, utilities 4k"),
        UserMessage("no EMIs"),
        UserMessage("savings 8L FD, MFs 18L, equity stocks 5L"),
        UserMessage("term 1 Cr cover ₹14k annual premium, health 10L family floater ₹18k premium"),
        UserMessage("goal 1: retirement ₹6 Cr by 2050"),
        UserMessage("goal 2: kid education ₹60L by 2036"),
        UserMessage("goal 3: own a home ₹1.8 Cr by 2032"),
        UserMessage("hold steady, C, max loss 20%"),
        UserMessage("run the full analysis"),
        UserMessage("send the final PDF report"),
    ],
    judges=[
        PlanFieldSet(path="personal_details.city_of_residence"),
        PlanFieldSet(path="freedom_score_inputs.monthly_income"),
        PlanFieldSet(path="freedom_score_inputs.monthly_expenses"),
        ToolCalled(tool_name="plan_add", arg_predicate=_goal_amount(60000000),
                   predicate_label="Retirement ₹6 Cr"),
        ToolCalled(tool_name="plan_add", arg_predicate=_goal_amount(18000000),
                   predicate_label="Home ₹1.8 Cr → 18,000,000"),
        ToolCalled(tool_name="run_full_analysis"),
        ComputedPresent(field="risk_profile"),
        ComputedPresent(field="allocation"),
        ComputedPresent(field="monte_carlo"),
        ComputedPresent(field="freedom_score"),
        ComputedPresent(field="cashflow"),
        ToolCalled(tool_name="report_generate"),
        NoToolError(),
        _NO_UNVERIFIED,
    ],
)


CASES = [
    _C1, _C2, _C3, _C4, _C5,
    _C6, _C7, _C8, _C9, _C10,
    _C11, _C12, _C13, _C14, _C15,
    _C16, _C17, _C18, _C19, _C20,
]
