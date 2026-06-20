"""
PlanState — Pydantic v2 mirror of shared/types/plan-state.ts.

The frontend serializes/deserializes by JSON shape, NOT by class — so the
field names + nullability MUST match the TypeScript types exactly. Use
`model_dump(mode='json', exclude_none=False)` when sending to the client so
nulls survive the round-trip.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

# ── Inputs / building blocks ───────────────────────────────────────────────

CityType = Literal["Metro", "Non-metro"]
ContribFreq = Literal["monthly", "annual"]
GoalKind = Literal[
    "child_education",
    "child_marriage",
    "retirement",
    "house_purchase",
    "foreign_travel",
    "other",
]
Priority = Literal["essential", "important", "aspirational"]
Instrument = Literal["FD", "RD", "PPF", "EPF", "Bonds", "NPS", "NSC", "PostOffice", "SukanyaSamriddhi", "Other"]
LongOrTrade = Literal["long_term", "trading"]
SourceType = Literal[
    "user",
    "transcript",
    "pdf_aa",
    "pdf_generic",
    "xlsx",
    "csv",
    "docx",
    "md",
    "image",
    "audio",
    "inferred",
    "derived",
]
ParserTier = Literal["deterministic", "llm", "manual"]
AlignmentStatus = Literal[
    "aligned",
    "need_below_ceiling",
    "goal_risk_mismatch",
    "need_unavailable",
    "incomplete",
]
DurationStance = Literal["shorten", "neutral", "extend"]
MilestoneType = Literal[
    "home_purchase", "education", "retirement", "travel", "marriage", "other"
]


class StrictModel(BaseModel):
    """Default model: allow extra (Pydantic discards unknown fields by default
    in v2 with extra='ignore'); we permit them so the Python side is forward-
    compatible with future TS field additions without crashing."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class PersonalDetails(StrictModel):
    full_name: Optional[str] = None
    date_of_birth: Optional[str] = None  # DD-MM-YYYY
    pan: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    marital_status: Optional[str] = None
    spouse_name_and_age: Optional[str] = None
    number_of_children: Optional[int] = None
    # `dependents` is loosely typed because intake sheets often capture freeform
    # descriptions ("Mother (78)", "Father 60 + Mother 56") that are more
    # informative than a count. Accept both int (count) and str (description).
    dependents: Optional[Union[int, str]] = None
    city_of_residence: Optional[str] = None
    city_type: Optional[CityType] = None
    occupation: Optional[str] = None
    retirement_age_target: Optional[int] = None


class IncomeDetails(StrictModel):
    client_salary_in_hand: Optional[float] = None
    spouse_salary_in_hand: Optional[float] = None
    client_business_income: Optional[float] = None
    spouse_business_income: Optional[float] = None
    client_rental_income: Optional[float] = None
    spouse_rental_income: Optional[float] = None
    client_other_income: Optional[float] = None
    spouse_other_income: Optional[float] = None


class MonthlyExpenses(StrictModel):
    household_expenses: Optional[float] = None
    rent_or_emi: Optional[float] = None
    groceries: Optional[float] = None
    utilities: Optional[float] = None
    school_fees: Optional[float] = None
    insurance_premium: Optional[float] = None
    medical: Optional[float] = None
    travel_or_lifestyle: Optional[float] = None
    sip_investments: Optional[float] = None
    other_emis: Optional[float] = None


class MFHolding(StrictModel):
    id: str
    fund_name: Optional[str] = None
    folio: Optional[str] = None
    current_value: Optional[float] = None
    closing_units: Optional[float] = None
    isin: Optional[str] = None
    nav: Optional[float] = None
    nav_date: Optional[str] = None
    registrar: Optional[str] = None
    sip_amount: Optional[float] = None
    source_file: Optional[str] = None


class StockHolding(StrictModel):
    id: str
    stock_name: Optional[str] = None
    quantity: Optional[float] = None
    current_value: Optional[float] = None
    isin: Optional[str] = None
    last_traded_price: Optional[float] = None
    long_term_or_trading: Optional[LongOrTrade] = None
    source_file: Optional[str] = None


class FixedIncomeRow(StrictModel):
    id: str
    instrument: Instrument
    invested_amount: Optional[float] = None
    current_value: Optional[float] = None
    maturity_date: Optional[str] = None


class RealEstateHolding(StrictModel):
    """Non-financial asset that appreciates separately from the FA pool.
    Matches the Excel `YoY Cash Flow` tab columns X..AA (real estate +
    gold + other non-financial) which roll forward at their own rate."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    label: Optional[str] = None
    kind: Literal["residential", "commercial", "land", "other"] = "residential"
    current_value: float = 0
    earmarked_for_sale: bool = False
    expected_appreciation_pa: Optional[float] = None  # override; default uses growth.real_estate


class GoldHolding(StrictModel):
    """Physical gold / SGB / digital gold / jewellery."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    label: Optional[str] = None
    kind: Literal["physical", "sgb", "digital", "jewellery"] = "physical"
    current_value: float = 0
    held_for_investment: bool = True  # vs sentimental — affects allocation eligibility


class MonthlyInvestments(StrictModel):
    mutual_fund_sip: Optional[float] = None
    nps: Optional[float] = None
    ppf: Optional[float] = None
    rd: Optional[float] = None
    direct_equity: Optional[float] = None
    insurance_premium: Optional[float] = None
    other: Optional[float] = None


class RecurringInvestment(StrictModel):
    """One line of the firm's `5_Recurring_Investments` sheet, WITH its
    purpose. The flat `MonthlyInvestments` aggregate loses the per-line
    "For Retirement" / "For House Purchase" intent from the Remarks column;
    this list preserves it so the CFP can net retirement-directed SIPs
    against the retirement corpus (Excel E43) without sweeping in SIPs that
    are earmarked for other goals."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    investment_type: Optional[str] = None       # "Mutual Fund SIP", "NPS", "VPF", ...
    monthly_amount: Optional[float] = None
    # What the SIP is FOR. "retirement" → netted against the retirement
    # corpus; "goal" → credited to financial goals; "general"/"emergency"
    # → neither (treated as flexible savings).
    purpose: Literal["retirement", "goal", "emergency", "general"] = "general"
    linked_goal: Optional[str] = None            # free-text goal name when purpose="goal"
    remarks: Optional[str] = None


class LiquidCapital(StrictModel):
    savings_account_balance: Optional[float] = None
    idle_cash_for_investment: Optional[float] = None
    fd_breakable_for_investment: Optional[float] = None
    bonus_expected_for_investment: Optional[float] = None


class EmergencyFund(StrictModel):
    emergency_fund_available: Optional[bool] = None
    total_emergency_corpus: Optional[float] = None
    where_is_it_parked: Optional[str] = None
    monthly_household_expense_for_calculation: Optional[float] = None
    months_of_cover_available: Optional[float] = None


class LoanBlock(StrictModel):
    outstanding_amount: Optional[float] = None
    emi: Optional[float] = None
    interest_rate: Optional[float] = None  # percent
    tenure_left: Optional[float] = None  # years


class Liabilities(StrictModel):
    home_loan: Optional[LoanBlock] = None
    car_loan: Optional[LoanBlock] = None
    personal_loan: Optional[LoanBlock] = None
    credit_card_dues: Optional[LoanBlock] = None


class InsuranceBlock(StrictModel):
    company: Optional[str] = None
    cover_amount: Optional[float] = None
    annual_premium: Optional[float] = None


class InsuranceDetails(StrictModel):
    term_plan: Optional[InsuranceBlock] = None
    health_insurance: Optional[InsuranceBlock] = None
    family_floater: Optional[InsuranceBlock] = None
    ulip_or_endowment: Optional[InsuranceBlock] = None


class Goal(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    goal_name: str
    kind: GoalKind
    target_year: Optional[int] = None
    today_cost: Optional[float] = None
    target_amount: Optional[float] = None
    current_allocated_amount: Optional[float] = None
    periodic_contribution: Optional[float] = None
    contribution_frequency: Optional[ContribFreq] = None
    horizon_years: Optional[int] = None
    priority: Optional[Priority] = None
    is_target_in_today_money: Optional[bool] = None
    inflation_assumed: Optional[float] = None
    required_return_override: Optional[float] = None


class Person(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    date_of_birth: Optional[str] = None
    life_expectancy: Optional[int] = None
    retirement_age: Optional[int] = None


class Growth(StrictModel):
    cash: float = 0.04
    investment: float = 0.10
    real_estate: float = 0.06
    vehicle: float = -0.10


class IncomeGrowth(StrictModel):
    """Per-source annual growth rates. Defaults match the firm's
    `YoY Cash Flow` row 5: employment 5.6%, business 7%, rental 3.5%,
    other 3.5%. These are post-tax growth rates applied year-over-year
    to each income line in the projection."""
    employment: float = 0.056
    business: float = 0.070
    rental: float = 0.035
    other: float = 0.035


class Taxes(StrictModel):
    federal: float = 0.30
    state: float = 0.0
    capital_gains: float = 0.125


class LumpsumEvent(StrictModel):
    """One-off deposit or withdrawal in a specific calendar year.

    Mirrors the Excel YoY Cash Flow tab's "Lumpsum Further deposit /
    (Withdrawal)" column with the adjacent "Remarks" text. Positive
    `amount` adds to financial assets that year (bonus expected, sale
    proceeds, reverse mortgage payout); negative withdraws (knee
    surgery, dependent expense, anything unmodelled in regular
    expenses)."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    year: int                  # Calendar year, e.g. 2031
    amount: float              # Positive = deposit, negative = withdrawal (INR)
    label: Optional[str] = None  # "Bonus expected", "Knee surgery", "Reverse mortgage"


class Assumptions(StrictModel):
    persons: list[Person] = Field(default_factory=list)
    growth: Growth = Field(default_factory=Growth)
    income_growth: IncomeGrowth = Field(default_factory=IncomeGrowth)
    taxes: Taxes = Field(default_factory=Taxes)
    # 7% matches the firm's reference Excel `YoY Cash Flow` row 5 J$5 — the
    # expense growth rate used across all firm-issued client plans. The
    # previous default (6%) silently under-projected expenses by ~1pp/yr
    # compounding to ~20% lower expenses by retirement vs the firm's
    # workbook. Per-client overrides via `Inflation Assumed` columns in
    # the goals sheet still take precedence.
    inflation: float = 0.07
    # Annual SIP step-up *over and above* inflation. 0.0 means SIP scales
    # with inflation only (real SIP rupees flat). 0.10 means SIP grows by
    # inflation + 10 percentage points each year — i.e. the household
    # commits to raising their SIP faster than inflation as income grows.
    # Used by `compute_cashflow` to scale `monthly_investments.* SIPs`
    # forward. Scenarios card / agent mutations target this field to model
    # "Plan B with 10%/yr step-up".
    sip_annual_step_up_pct: float = 0.0
    # One-off events that hit the YoY Cash Flow's lumpsum column —
    # bonuses, surgeries, asset sales, reverse mortgage payouts, etc.
    lumpsum_events: list[LumpsumEvent] = Field(default_factory=list)


class FreedomScoreInputs(StrictModel):
    portfolio_current_value: Optional[float] = None
    liquid_assets_current_value: Optional[float] = None
    monthly_income: Optional[float] = None
    monthly_expenses: Optional[float] = None
    monthly_emi: Optional[float] = None
    age: Optional[int] = None
    risk_tolerance: Optional[str] = None
    equity_allocation_percent: Optional[float] = None
    number_of_holdings: Optional[int] = None


class EvidenceRow(StrictModel):
    field: str
    value: Any = None
    source_file: Optional[str] = None
    source_type: SourceType
    parser_tier: ParserTier
    confidence: float = 1.0
    evidence_quote: Optional[str] = None
    page_or_sheet: Optional[str] = None
    timestamp: str


# ── Outputs ───────────────────────────────────────────────────────────────


class FreedomPillars(StrictModel):
    liquidity: float
    debt: float
    investment: float
    discipline: float
    risk: float


class FreedomOutput(StrictModel):
    raw_weighted_score: float
    profile_strength_multiplier: float
    final_score: float
    pillars: FreedomPillars
    estimated_freedom_age: float
    freedom_age_gap: float
    city_cover_multiplier: float
    required_life_cover: float
    required_medical_cover: float


class RiskOutput(StrictModel):
    capacity_score: float
    capacity_profile: str
    capacity_binding_cap: str
    need_score: float
    need_profile: str
    need_primary_goal: Optional[str] = None
    need_driver_goals: list[str] = Field(default_factory=list)
    willingness_score: float
    willingness_raw_score: float
    willingness_profile: str
    prudent_ceiling: float
    recommended_score: float
    recommended_profile: str
    alignment_status: AlignmentStatus
    key_warnings: list[str] = Field(default_factory=list)
    goal_actions: list[str] = Field(default_factory=list)


class AllocationBuckets(StrictModel):
    equity: float
    debt: float
    gold: float
    cash: float


class EquitySplit(StrictModel):
    large: float
    mid: float
    small: float


class SignalEntry(StrictModel):
    score: float
    reason: str


class SectorThemeViews(StrictModel):
    overweight: list[str] = Field(default_factory=list)
    underweight: list[str] = Field(default_factory=list)


class AllocationOutput(StrictModel):
    investor_risk_band: str
    strategic_allocation: AllocationBuckets
    strategic_equity_split: EquitySplit
    tactical_regime_score: float
    tactical_regime_label: str
    signal_breakdown: dict[str, SignalEntry]
    recommended_allocation: AllocationBuckets
    recommended_equity_split: EquitySplit
    debt_duration_stance: DurationStance
    sector_theme_views: SectorThemeViews
    rebalancing_actions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CashFlowGoalOutflow(StrictModel):
    """A single goal expense paid out of `assets` during the cashflow year."""
    goal_id: str
    goal_name: str
    amount: float


class CashFlowRow(StrictModel):
    year: int
    age: int
    assets: float
    income: float
    expenses: float
    taxes: float
    retirement_contributions: float
    other: float
    total_net_worth: float
    # Total goal-driven outflow this year (inflation-adjusted target amounts
    # for goals whose target_year == this row's year).
    goal_outflow: float = 0
    # Per-goal breakdown for the canvas/PDF — empty when no goal hits this year.
    goal_outflow_breakdown: list[CashFlowGoalOutflow] = Field(default_factory=list)
    # Asset-class breakdown for this year. `assets` field above is the
    # sum of financial pools only (liquid + portfolio). `total_net_worth`
    # adds real_estate + gold. These fields let the canvas show what
    # each asset class is doing across the projection horizon.
    liquid: float = 0
    portfolio: float = 0
    real_estate: float = 0
    gold: float = 0


class MonthlyStrip(StrictModel):
    month: str
    inflow: float
    outflow: float


class GlidePoint(StrictModel):
    year: int
    balance: float


class CashFlowProjection(StrictModel):
    rows: list[CashFlowRow]
    monthly_strip_next_12mo: list[MonthlyStrip]
    retirement_glide: list[GlidePoint]


class GainHarvest(StrictModel):
    holding_id: str
    units: float
    expected_gain: float
    tax_saved: float


class LossHarvest(StrictModel):
    holding_id: str
    units: float
    expected_loss: float
    tax_offset: float


class DebtAmortRow(StrictModel):
    """One year of amortization on a single loan."""
    year: int
    opening_balance: float
    annual_emi: float
    annual_interest: float
    annual_principal: float
    closing_balance: float


class DebtSchedule(StrictModel):
    """Amortization output for a single loan from `loans_liabilities.*`."""
    loan_type: str               # home_loan | car_loan | personal_loan | credit_card_dues
    outstanding_amount: float
    emi: float
    interest_rate: float          # percent
    tenure_left_years: float
    rows: list[DebtAmortRow] = Field(default_factory=list)
    total_interest_paid: float = 0
    total_principal_paid: float = 0
    final_year: int = 0           # the year the loan ends


class DebtPaydownOutput(StrictModel):
    """Aggregate paydown view across every loan in `loans_liabilities`."""
    schedules: list[DebtSchedule] = Field(default_factory=list)
    total_outstanding_today: float = 0
    total_emi_monthly: float = 0
    total_interest_over_term: float = 0
    aggregate_yearly: list["DebtAmortRow"] = Field(default_factory=list)
    last_emi_year: int = 0
    note: Optional[str] = None    # e.g. warnings when interest_rate is missing


class TaxView(StrictModel):
    ltcg_headroom_remaining: float
    realized_ltcg_fy: float
    realized_stcg_fy: float
    gain_harvest_suggestions: list[GainHarvest] = Field(default_factory=list)
    loss_harvest_suggestions: list[LossHarvest] = Field(default_factory=list)
    fee_vs_value_warnings: list[str] = Field(default_factory=list)
    net_post_tax_delta: float


class GoalSuccessProb(StrictModel):
    goal_id: str
    probability: float


class MCResult(StrictModel):
    paths_count: int
    p10_freedom_age: float
    p50_freedom_age: float
    p90_freedom_age: float
    goal_success_probabilities: list[GoalSuccessProb] = Field(default_factory=list)


class NetWorth(StrictModel):
    """Full net-worth snapshot with asset/loan breakdown.

    Earlier the math excluded real_estate + gold from assets AND excluded
    home_loan from debts — both halves cancelled out. That worked when
    the schema didn't track real_estate / gold rows, but now that they
    do, the user's primary residence (often the largest asset) was
    invisible in net worth. This shape exposes every component so the
    canvas can render the full breakdown and pair each secured loan with
    its underlying asset.

    Math:
        gross_assets = liquid + investments + real_estate_total + gold_total
        real_estate_equity = real_estate_total − home_loan_outstanding
                             (clamped ≥ 0)
        total = liquid + investments + real_estate_equity + gold_total
                − unsecured_debts − car_loan_outstanding
                (car_loan is subtracted as an unmatched secured debt
                 since we don't yet schema-track the vehicle itself —
                 once we add a vehicles[] list this becomes a paired
                 equity calc just like real_estate)
    """
    total: float = 0
    liquid: float = 0
    non_liquid: float = 0
    assets_total: float = 0     # GROSS — includes real_estate + gold at face value

    # Asset breakdown (new)
    investments: float = 0      # MFs + stocks + fixed income (or fsi.portfolio fallback)
    real_estate_total: float = 0  # Σ real_estate.current_value
    gold_total: float = 0       # Σ gold.current_value
    real_estate_equity: float = 0  # max(0, real_estate_total − home_loan_outstanding)

    # Liability breakdown
    debts_total: float = 0          # UNSECURED only (personal loan + credit-card dues)
    secured_debts: float = 0        # home_loan + car_loan (back-compat / informational)
    home_loan_outstanding: float = 0
    car_loan_outstanding: float = 0
    personal_loan_outstanding: float = 0
    credit_card_outstanding: float = 0


class NetWorthSeriesPoint(StrictModel):
    year: int
    value: float


class MilestonePin(StrictModel):
    year: int
    label: str
    type: MilestoneType
    goal_id: Optional[str] = None


class ComputedSnapshot(StrictModel):
    headline_amount_at_horizon: float = 0
    horizon_years: int = 45
    net_worth_series: list[NetWorthSeriesPoint] = Field(default_factory=list)
    cash_flow_table: list[CashFlowRow] = Field(default_factory=list)
    net_worth: NetWorth = Field(default_factory=NetWorth)
    risk_profile: Optional[RiskOutput] = None
    freedom_score: Optional[FreedomOutput] = None
    allocation: Optional[AllocationOutput] = None
    cashflow: Optional[CashFlowProjection] = None
    tax: Optional[TaxView] = None
    monte_carlo: Optional[MCResult] = None
    debt_paydown: Optional[DebtPaydownOutput] = None
    milestone_pins: list[MilestonePin] = Field(default_factory=list)
    # Excel-faithful CFP snapshot — populated on every recompute so the
    # canvas, the PDF report, and the agent all see the same numbers the
    # firm's `CFP_ng_080626.xlsx` model would produce.
    cfp: Optional[dict] = None
    # AI "suggested" optimisation layer (six-lever engine) — see
    # skills/suggestions.py. Loose dict (like `cfp`) so the canvas/report/
    # agent read the same shape without a strict round-trip.
    suggestions: Optional[dict] = None
    # Scenario engine (brief §6) — verdict + Baseline/Easy/Aggressive paths.
    # See skills/scenarios.py. Loose dict, same rationale as `cfp`.
    scenarios_v2: Optional[dict] = None


class ScenarioOp(StrictModel):
    path: str
    op: Literal["set", "add", "remove"]
    value: Any = None
    row: Any = None
    id: Optional[str] = None


class ScenarioMutation(StrictModel):
    ops: list[ScenarioOp] = Field(default_factory=list)


class Scenario(StrictModel):
    id: str
    label: str
    mutation: ScenarioMutation
    computed: ComputedSnapshot


class PlanState(StrictModel):
    household_id: str
    personal_details: PersonalDetails = Field(default_factory=PersonalDetails)
    income_details: IncomeDetails = Field(default_factory=IncomeDetails)
    monthly_expenses: MonthlyExpenses = Field(default_factory=MonthlyExpenses)
    mutual_funds: list[MFHolding] = Field(default_factory=list)
    equity_stocks: list[StockHolding] = Field(default_factory=list)
    fixed_income: list[FixedIncomeRow] = Field(default_factory=list)
    real_estate: list[RealEstateHolding] = Field(default_factory=list)
    gold: list[GoldHolding] = Field(default_factory=list)
    monthly_investments: MonthlyInvestments = Field(default_factory=MonthlyInvestments)
    recurring_investments: list[RecurringInvestment] = Field(default_factory=list)
    liquid_capital: LiquidCapital = Field(default_factory=LiquidCapital)
    emergency_fund: EmergencyFund = Field(default_factory=EmergencyFund)
    loans_liabilities: Liabilities = Field(default_factory=Liabilities)
    insurance_details: InsuranceDetails = Field(default_factory=InsuranceDetails)
    financial_goals: list[Goal] = Field(default_factory=list)
    freedom_score_inputs: FreedomScoreInputs = Field(default_factory=FreedomScoreInputs)
    assumptions: Assumptions = Field(default_factory=Assumptions)
    scenarios: list[Scenario] = Field(default_factory=list)
    active_scenario_ids: list[str] = Field(default_factory=list)
    computed: ComputedSnapshot = Field(default_factory=ComputedSnapshot)
    evidence: list[EvidenceRow] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    last_updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def empty_plan_state(household_id: str) -> PlanState:
    return PlanState(household_id=household_id)


# Source priority (lower index = higher trust) — mirrors TS SOURCE_PRIORITY.
SOURCE_PRIORITY: list[SourceType] = [
    "user",
    "transcript",
    "pdf_aa",
    "xlsx",
    "docx",
    "md",
    "csv",
    "image",
    "audio",
    "pdf_generic",
    "inferred",
    "derived",
]


def source_rank(t: SourceType) -> int:
    try:
        return SOURCE_PRIORITY.index(t)
    except ValueError:
        return len(SOURCE_PRIORITY)
