"""
Layer 1 — Deterministic skill math.

These cases bypass the LLM entirely. They seed a household, call a skill
directly via `SkillCall`, and assert on numerical outputs with a tolerance.
Catches table edits / formula drift / weight regressions.

Reference numbers anchored to PLANNER_GUIDE.md so any divergence between
docs and code is caught here.
"""
from __future__ import annotations

from ...skills.allocate import recommend as allocate_recommend
from ...skills.freedom import score as freedom_score
from ...skills.risk import assess as risk_assess
from ...skills.tax import harvest as tax_harvest
from ..core import Case, SkillCall
from ..fixtures import as_fixture, bengaluru_single_21yo, mumbai_family_32yo, with_risk_set
from ..judges import NumericEquals


CASES = [
    Case(
        id="L1.risk.mumbai_family",
        name="Risk profile — Mumbai family scores Moderately Aggressive",
        layer=1,
        description=(
            "32yo Mumbai metro family (₹1.5L income, ₹60k expenses, ₹25k EMI, "
            "5-mo emergency fund, 7-yr house horizon). hold_steady / C / 20 willingness. "
            "Expected per PLANNER_GUIDE: capacity 75 (horizon/ef/exp tied), "
            "willingness 60.5 → reconciled 60.5 → Moderately Aggressive. "
            "Need is dominated by the House goal (~13.5%/yr required) → goal_risk_mismatch."
        ),
        tags=["risk", "reference-persona"],
        fixture=as_fixture(mumbai_family_32yo),
        steps=[
            SkillCall(
                skill=risk_assess,
                args={
                    "willingness": {
                        "volatility_reaction": "hold_steady",
                        "risk_return_tradeoff": "C",
                        "max_tolerable_loss": "20",
                    },
                },
                label="risk_assess",
            )
        ],
        judges=[
            NumericEquals(path="capacity_score", expected=75, tolerance=1),
            NumericEquals(path="willingness_score", expected=60, tolerance=1),
            NumericEquals(path="recommended_score", expected=60, tolerance=1),
            # Retirement goal at 29y dominates by priority·need: needs ~34%/yr
            # to grow ₹5L into ₹27Cr (inflation-adjusted), so lands in the
            # top need band (95).
            NumericEquals(path="need_score", expected=95, tolerance=2),
        ],
    ),
    Case(
        id="L1.allocate.moderately_aggressive_band",
        name="Allocation — Moderately Aggressive strategic anchor",
        layer=1,
        description=(
            "With risk profile pre-set to Moderately Aggressive, the strategic "
            "anchor (per PLANNER_GUIDE allocation table) is 65/25/7/3. The signals "
            "fixture's composite is +2 (Mild Risk-On), so equity_shift = +5pp at the "
            "Moderately Aggressive cap of 10. Recommended equity should land near 70%."
        ),
        tags=["allocation", "tactical"],
        fixture=as_fixture(with_risk_set(mumbai_family_32yo)),
        steps=[SkillCall(skill=allocate_recommend, args={})],
        judges=[
            NumericEquals(path="strategic_allocation.equity", expected=65, tolerance=0.5),
            NumericEquals(path="strategic_allocation.debt", expected=25, tolerance=0.5),
            NumericEquals(path="recommended_allocation.equity", expected=70, tolerance=5),
            NumericEquals(path="tactical_regime_score", expected=2, tolerance=2),
        ],
    ),
    Case(
        id="L1.freedom.bengaluru_no_investment",
        name="Freedom Score — investment pillar zero kills the score",
        layer=1,
        description=(
            "21yo Bengaluru engineer with zero portfolio (but equity_alloc_pct=60). "
            "Per the freedom formula: portfolio_vs_income = 0 but equity_fit = 60, "
            "so investment pillar = 0.4·60 = 24. Risk pillar = 0 (no term cover). "
            "Liquidity ≈ 68 (5+ months), debt ≈ 90 (low EMI, no debts), "
            "discipline ≈ 92. Final weighted ≈ 50."
        ),
        tags=["freedom-score", "reference-persona"],
        fixture=as_fixture(bengaluru_single_21yo),
        steps=[SkillCall(skill=freedom_score, args={})],
        judges=[
            NumericEquals(path="pillars.investment", expected=24, tolerance=2),
            NumericEquals(path="pillars.risk", expected=0, tolerance=1),
            NumericEquals(path="final_score", expected=50, tolerance=5),
        ],
    ),
    Case(
        id="L1.tax.no_holdings_empty_harvest",
        name="Tax harvest — empty holdings yield no suggestions",
        layer=1,
        description=(
            "Bengaluru household with no MF / equity holdings. Expected: "
            "ltcg_headroom_remaining = ₹1,25,000 (full FY allowance), zero gain or "
            "loss suggestions, and a 'no opportunities cleared the round-trip gate' warning."
        ),
        tags=["tax"],
        fixture=as_fixture(with_risk_set(bengaluru_single_21yo)),
        steps=[SkillCall(skill=tax_harvest, args={})],
        judges=[
            NumericEquals(path="ltcg_headroom_remaining", expected=125000, tolerance=1),
            NumericEquals(path="realized_ltcg_fy", expected=0, tolerance=0.5),
            NumericEquals(path="net_post_tax_delta", expected=0, tolerance=0.5),
        ],
    ),
]


