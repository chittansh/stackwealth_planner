/**
 * PlanState — the canonical spine of Stackwealth Planner.
 * Mirrors `canonical_fields.md` from the financial-plan-intake-extractor skill.
 */

export type PersonalDetails = {
  full_name?: string | null;
  date_of_birth?: string | null; // DD-MM-YYYY
  pan?: string | null;
  email?: string | null;
  mobile?: string | null;
  address?: string | null;
  marital_status?: string | null;
  spouse_name_and_age?: string | null;
  number_of_children?: number | null;
  dependents?: number | null;
  city_of_residence?: string | null;
  city_type?: 'Metro' | 'Non-metro' | null;
  occupation?: string | null;
  retirement_age_target?: number | null;
};

export type IncomeDetails = {
  client_salary_in_hand?: number | null;
  spouse_salary_in_hand?: number | null;
  client_business_income?: number | null;
  spouse_business_income?: number | null;
  client_rental_income?: number | null;
  spouse_rental_income?: number | null;
  client_other_income?: number | null;
  spouse_other_income?: number | null;
};

export type MonthlyExpenses = {
  household_expenses?: number | null;
  rent_or_emi?: number | null;
  groceries?: number | null;
  utilities?: number | null;
  school_fees?: number | null;
  insurance_premium?: number | null;
  medical?: number | null;
  travel_or_lifestyle?: number | null;
  sip_investments?: number | null;
  other_emis?: number | null;
};

export type MFHolding = {
  id: string;
  fund_name?: string | null;
  folio?: string | null;
  current_value?: number | null;
  closing_units?: number | null;
  isin?: string | null;
  nav?: number | null;
  nav_date?: string | null;
  registrar?: string | null;
  sip_amount?: number | null;
  source_file?: string | null;
};

export type StockHolding = {
  id: string;
  stock_name?: string | null;
  quantity?: number | null;
  current_value?: number | null;
  isin?: string | null;
  last_traded_price?: number | null;
  long_term_or_trading?: 'long_term' | 'trading' | null;
  source_file?: string | null;
};

export type FixedIncomeRow = {
  id: string;
  instrument: 'FD' | 'RD' | 'PPF' | 'EPF' | 'Bonds' | 'NPS';
  invested_amount?: number | null;
  current_value?: number | null;
  maturity_date?: string | null;
};

export type MonthlyInvestments = {
  mutual_fund_sip?: number | null;
  nps?: number | null;
  ppf?: number | null;
  rd?: number | null;
  direct_equity?: number | null;
  insurance_premium?: number | null;
  other?: number | null;
};

export type LiquidCapital = {
  savings_account_balance?: number | null;
  idle_cash_for_investment?: number | null;
  fd_breakable_for_investment?: number | null;
  bonus_expected_for_investment?: number | null;
};

export type EmergencyFund = {
  emergency_fund_available?: boolean | null;
  total_emergency_corpus?: number | null;
  where_is_it_parked?: string | null;
  monthly_household_expense_for_calculation?: number | null;
  months_of_cover_available?: number | null;
};

export type LoanBlock = {
  outstanding_amount?: number | null;
  emi?: number | null;
  interest_rate?: number | null; // percent
  tenure_left?: number | null;   // years
};

export type Liabilities = {
  home_loan?: LoanBlock;
  car_loan?: LoanBlock;
  personal_loan?: LoanBlock;
  credit_card_dues?: LoanBlock;
};

export type InsuranceBlock = {
  company?: string | null;
  cover_amount?: number | null;
  annual_premium?: number | null;
};

export type InsuranceDetails = {
  term_plan?: InsuranceBlock;
  health_insurance?: InsuranceBlock;
  family_floater?: InsuranceBlock;
  ulip_or_endowment?: InsuranceBlock;
};

export type Goal = {
  id: string;
  goal_name: string;
  kind: 'child_education' | 'child_marriage' | 'retirement' | 'house_purchase' | 'foreign_travel' | 'other';
  target_year?: number | null;
  today_cost?: number | null;
  target_amount?: number | null;
  current_allocated_amount?: number | null;
  periodic_contribution?: number | null;
  contribution_frequency?: 'monthly' | 'annual' | null;
  horizon_years?: number | null;
  priority?: 'essential' | 'important' | 'aspirational' | null;
  is_target_in_today_money?: boolean | null;
  inflation_assumed?: number | null;
  required_return_override?: number | null;
};

export type Person = {
  id: string;
  name: string;
  date_of_birth?: string | null;
  life_expectancy?: number | null;
  retirement_age?: number | null;
};

export type LumpsumEvent = {
  id: string;
  /** Calendar year, e.g. 2031. */
  year: number;
  /** Positive = deposit into FA, negative = withdrawal. INR. */
  amount: number;
  /** Free-text label rendered in the Excel cashflow's "Remarks" column. */
  label?: string | null;
};

export type Assumptions = {
  persons: Person[];
  growth: { cash: number; investment: number; real_estate: number; vehicle: number };
  /** Per-source annual income growth — see Excel `YoY Cash Flow` row 5. */
  income_growth?: { employment: number; business: number; rental: number; other: number };
  taxes: { federal: number; state: number; capital_gains: number };
  inflation: number;
  /** Annual SIP step-up over and above inflation. */
  sip_annual_step_up_pct?: number;
  /** One-off cashflow events — bonuses, surgeries, asset sales, etc. */
  lumpsum_events?: LumpsumEvent[];
};

export type RealEstateHolding = {
  id: string;
  label?: string | null;
  kind: 'residential' | 'commercial' | 'land' | 'other';
  current_value: number;
  earmarked_for_sale: boolean;
  expected_appreciation_pa?: number | null;
};

export type GoldHolding = {
  id: string;
  label?: string | null;
  kind: 'physical' | 'sgb' | 'digital' | 'jewellery';
  current_value: number;
  held_for_investment: boolean;
};

export type FreedomScoreInputs = {
  portfolio_current_value?: number | null;
  liquid_assets_current_value?: number | null;
  monthly_income?: number | null;
  monthly_expenses?: number | null;
  monthly_emi?: number | null;
  age?: number | null;
  risk_tolerance?: string | null;
  equity_allocation_percent?: number | null;
  number_of_holdings?: number | null;
};

export type EvidenceRow = {
  field: string;            // canonical path e.g. "personal_details.date_of_birth"
  value: unknown;
  source_file?: string | null;
  source_type: 'user' | 'transcript' | 'pdf_aa' | 'pdf_generic' | 'xlsx' | 'csv' | 'docx' | 'md' | 'image' | 'audio' | 'inferred' | 'derived';
  parser_tier: 'deterministic' | 'llm' | 'manual';
  confidence: number;       // 0..1
  evidence_quote?: string | null;
  page_or_sheet?: string | null;
  timestamp: string;        // ISO
};

export type RiskOutput = {
  capacity_score: number;
  capacity_profile: string;
  capacity_binding_cap: string;
  need_score: number;
  need_profile: string;
  need_primary_goal?: string;
  need_driver_goals: string[];
  willingness_score: number;
  willingness_raw_score: number;
  willingness_profile: string;
  prudent_ceiling: number;
  recommended_score: number;
  recommended_profile: string;
  alignment_status: 'aligned' | 'need_below_ceiling' | 'goal_risk_mismatch' | 'need_unavailable' | 'incomplete';
  key_warnings: string[];
  goal_actions: string[];
};

export type AllocationOutput = {
  investor_risk_band: string;
  strategic_allocation: { equity: number; debt: number; gold: number; cash: number };
  strategic_equity_split: { large: number; mid: number; small: number };
  tactical_regime_score: number;
  tactical_regime_label: string;
  signal_breakdown: Record<string, { score: number; reason: string }>;
  recommended_allocation: { equity: number; debt: number; gold: number; cash: number };
  recommended_equity_split: { large: number; mid: number; small: number };
  debt_duration_stance: 'shorten' | 'neutral' | 'extend';
  sector_theme_views: { overweight: string[]; underweight: string[] };
  rebalancing_actions: string[];
  warnings: string[];
};

export type FreedomOutput = {
  raw_weighted_score: number;
  profile_strength_multiplier: number;
  final_score: number; // 0..100
  pillars: {
    liquidity: number;
    debt: number;
    investment: number;
    discipline: number;
    risk: number;
  };
  estimated_freedom_age: number;
  freedom_age_gap: number;
  city_cover_multiplier: number;
  required_life_cover: number;
  required_medical_cover: number;
};

export type CashFlowGoalOutflow = {
  goal_id: string;
  goal_name: string;
  amount: number;
};

export type CashFlowRow = {
  year: number;
  age: number;
  assets: number;
  income: number;
  expenses: number;
  taxes: number;
  retirement_contributions: number;
  other: number;
  total_net_worth: number;
  goal_outflow?: number;
  goal_outflow_breakdown?: CashFlowGoalOutflow[];
  /** Asset-class breakdown — populated from compute_cashflow's per-year
   * end-state. `assets` (above) is liquid + portfolio. total_net_worth
   * also includes real_estate + gold. */
  liquid?: number;
  portfolio?: number;
  real_estate?: number;
  gold?: number;
};

export type CashFlowProjection = {
  rows: CashFlowRow[];
  monthly_strip_next_12mo: { month: string; inflow: number; outflow: number }[];
  retirement_glide: { year: number; balance: number }[];
};

export type TaxView = {
  ltcg_headroom_remaining: number;
  realized_ltcg_fy: number;
  realized_stcg_fy: number;
  gain_harvest_suggestions: { holding_id: string; units: number; expected_gain: number; tax_saved: number }[];
  loss_harvest_suggestions: { holding_id: string; units: number; expected_loss: number; tax_offset: number }[];
  fee_vs_value_warnings: string[];
  net_post_tax_delta: number;
};

export type MCResult = {
  paths_count: number;
  p10_freedom_age: number;
  p50_freedom_age: number;
  p90_freedom_age: number;
  goal_success_probabilities: { goal_id: string; probability: number }[];
};

export type NetWorth = {
  total: number;
  liquid: number;
  non_liquid: number;
  assets_total: number;      // GROSS (includes real_estate + gold at face value)
  debts_total: number;       // UNSECURED only (personal_loan + credit_card_dues)
  secured_debts?: number;    // home_loan + car_loan — back-compat / informational

  // Asset breakdown
  investments?: number;
  real_estate_total?: number;
  gold_total?: number;
  real_estate_equity?: number;  // max(0, real_estate_total − home_loan_outstanding)

  // Liability breakdown (per-loan)
  home_loan_outstanding?: number;
  car_loan_outstanding?: number;
  personal_loan_outstanding?: number;
  credit_card_outstanding?: number;
};

export type DebtAmortRow = {
  year: number;
  opening_balance: number;
  annual_emi: number;
  annual_interest: number;
  annual_principal: number;
  closing_balance: number;
};

export type DebtSchedule = {
  loan_type: 'home_loan' | 'car_loan' | 'personal_loan' | 'credit_card_dues';
  outstanding_amount: number;
  emi: number;
  interest_rate: number;
  tenure_left_years: number;
  rows: DebtAmortRow[];
  total_interest_paid: number;
  total_principal_paid: number;
  final_year: number;
};

export type DebtPaydownOutput = {
  schedules: DebtSchedule[];
  total_outstanding_today: number;
  total_emi_monthly: number;
  total_interest_over_term: number;
  aggregate_yearly: DebtAmortRow[];
  last_emi_year: number;
  note?: string;
};

export type MilestonePin = {
  year: number;
  label: string;
  type: 'home_purchase' | 'education' | 'retirement' | 'travel' | 'marriage' | 'other';
  goal_id?: string;
};

export type CFPDebtRatios = {
  dscr: number | null;
  dscr_status: 'healthy' | 'watch' | 'reduce debt' | 'high' | 'n/a';
  dti: number | null;
  dti_status: 'healthy' | 'watch' | 'reduce debt' | 'high' | 'n/a';
  dni: number | null;
  dni_status: 'healthy' | 'watch' | 'reduce debt' | 'high' | 'n/a';
  total_debt_outstanding: number;
  annual_income: number;
  annual_emi: number;
  income_available_for_debt_service: number;
};

export type CFPRepaymentStrategies = {
  avalanche_order: string[];
  snowball_order: string[];
  blizzard_order: string[];
  loans: { kind: string; label: string; outstanding: number; emi: number; rate_pct: number }[];
  default_strategy: 'avalanche' | 'snowball' | 'blizzard';
  rationale: string;
};

export type CFPTaxRegime = {
  fy: string;
  annual_gross_income: number;
  old_regime: {
    standard_deduction: number;
    deductions: { '80C': number; '80CCD_1B': number; '80D': number; '24b': number; HRA: number; total: number };
    taxable_income: number;
    tax_before_cess: number;
    cess: number;
    total_tax: number;
    effective_rate: number;
  };
  new_regime: {
    standard_deduction: number;
    taxable_income: number;
    tax_before_cess: number;
    cess: number;
    total_tax: number;
    effective_rate: number;
  };
  recommended_regime: 'old' | 'new';
  annual_savings_with_recommended: number;
  rationale: string;
};

export type CFPSnapshot = {
  summary: Record<string, unknown>;
  goal_blocks: Record<string, unknown>[];
  retirement: Record<string, unknown>;
  insurance: Record<string, unknown>;
  yoy_cashflow: Record<string, unknown>[];
  debt: { ratios: CFPDebtRatios; strategies: CFPRepaymentStrategies };
  tax_regime: CFPTaxRegime;
  constants_used: Record<string, unknown>;
};

export type ComputedSnapshot = {
  headline_amount_at_horizon: number;
  horizon_years: number;
  net_worth_series: { year: number; value: number }[];
  cash_flow_table: CashFlowRow[];
  net_worth: NetWorth;
  risk_profile?: RiskOutput;
  freedom_score?: FreedomOutput;
  allocation?: AllocationOutput;
  cashflow?: CashFlowProjection;
  tax?: TaxView;
  monte_carlo?: MCResult;
  debt_paydown?: DebtPaydownOutput;
  milestone_pins: MilestonePin[];
  cfp?: CFPSnapshot | null;
  suggestions?: SuggestionsSnapshot | null;
  scenarios_v2?: ScenariosSnapshot | null;
};

export type ScenarioPath = {
  key: 'baseline' | 'easy' | 'aggressive';
  name: string;
  headline: string;
  levers: string[];
  monthly_sip: number;
  total_sip_needed?: number;
  retirement_age: number;
  retirement_corpus: number;
  corpus_required: number;
  goals_met_pct: number;
  achieved?: boolean;
  outcomes?: { goal: string; target_year?: number; status: string }[];
  net_worth_series?: { year: number; value: number }[];
  trade_off: string;
};

export type ScenariosSnapshot = {
  generated_at: string;
  surplus: {
    monthly_income: number;
    gross_surplus: number;
    bare_minimum_expense: number;
    emergency_target: number;
    emergency_current: number;
    emergency_build_sip: number;
    investable_surplus: number;
  };
  total_sip_needed: number;
  goal_sip_needed: number;
  retirement_sip_needed: number;
  verdict: { confidence: string; achievable: boolean; text: string };
  top_actions: string[];
  achievable: boolean;
  single_plan?: { headline: string; monthly_sip: number; cushion_monthly: number; step_up_pct: number };
  baseline: ScenarioPath;
  scenarios: ScenarioPath[];
  comparison?: { metric: string; kind: string; baseline: unknown; easy: unknown; aggressive: unknown }[];
  which_path?: { path: string; suits: string }[];
};

export type SuggestionLever = {
  lever: 'increase_sip' | 'delay_goal' | 'reduce_value' | 'increase_income' | 'liquidate_assets' | 'lumpsum';
  title: string;
  change: string;
  rationale: string;
  feasible: boolean;
  impact: Record<string, unknown>;
};

export type SuggestedGoalRow = {
  goal_name: string;
  target_year: number;
  is_retirement?: boolean;
  required_sip_monthly: number;
  existing_sip_monthly: number;
  shortfall_monthly: number;
  funded_pct: number | null;
  levers: SuggestionLever[];
};

export type SuggestionsSnapshot = {
  generated_at: string;
  has_gaps: boolean;
  recommended: {
    summary: string;
    levers_used: string[];
    mutation: ScenarioMutation;
    residual_note?: string | null;
    income_bump_monthly?: number;
    surplus_redirected?: number;
    impact: {
      retirement_year?: number;
      net_worth_at_retirement?: number;
      baseline_net_worth_at_retirement?: number;
      net_worth_at_retirement_delta?: number;
      headline_at_horizon?: number;
      headline_delta?: number;
      baseline_headline?: number;
    };
  };
  domains: {
    cashflow: {
      title: string;
      monthly_surplus: number;
      monthly_existing_sip: number;
      affordable_new_sip: number;
      total_required_incremental_sip: number;
      sip_shortfall_monthly: number;
      is_affordable: boolean;
      levers: SuggestionLever[];
    };
    goals: { title: string; goals: SuggestedGoalRow[] };
    retirement: {
      title: string;
      corpus_required: number;
      provisioned: number;
      shortfall: number;
      required_sip_monthly: number;
      funded_pct: number;
      on_track: boolean;
      stepup_reaches_goal?: boolean;
      stepup_required_start_sip_monthly?: number;
      stepup_additional_start_sip_monthly?: number;
      ongoing_sip_monthly?: number;
      levers: SuggestionLever[];
    };
  };
  nudges: { lever: string; title: string; question: string }[];
  suggested: {
    net_worth_series?: { year: number; value: number }[];
    headline_at_horizon?: number;
    retirement_required_sip?: number;
    retirement_funded_pct?: number;
  };
};

export type ScenarioMutation = {
  ops: { path: string; op: 'set' | 'add' | 'remove'; value?: unknown; row?: unknown; id?: string }[];
};

export type Scenario = {
  id: string;
  label: string;
  mutation: ScenarioMutation;
  computed: ComputedSnapshot;
};

export type PlanState = {
  household_id: string;
  personal_details: PersonalDetails;
  income_details: IncomeDetails;
  monthly_expenses: MonthlyExpenses;
  mutual_funds: MFHolding[];
  equity_stocks: StockHolding[];
  fixed_income: FixedIncomeRow[];
  real_estate?: RealEstateHolding[];
  gold?: GoldHolding[];
  monthly_investments: MonthlyInvestments;
  liquid_capital: LiquidCapital;
  emergency_fund: EmergencyFund;
  loans_liabilities: Liabilities;
  insurance_details: InsuranceDetails;
  financial_goals: Goal[];
  freedom_score_inputs: FreedomScoreInputs;
  assumptions: Assumptions;
  scenarios: Scenario[];
  active_scenario_ids: string[];
  computed: ComputedSnapshot;
  evidence: EvidenceRow[];
  missing_fields: string[];
  last_updated_at: string;
};

export type PlanStateDelta = Partial<Omit<PlanState, 'household_id' | 'computed' | 'last_updated_at'>>;

export const SOURCE_PRIORITY: EvidenceRow['source_type'][] = [
  'user',
  'transcript',
  'pdf_aa',
  'xlsx',
  'docx',
  'md',
  'csv',
  'image',
  'audio',
  'pdf_generic',
  'inferred',
  'derived',
];

export function sourceRank(t: EvidenceRow['source_type']): number {
  const idx = SOURCE_PRIORITY.indexOf(t);
  return idx === -1 ? SOURCE_PRIORITY.length : idx;
}

export function emptyPlanState(household_id: string): PlanState {
  return {
    household_id,
    personal_details: {},
    income_details: {},
    monthly_expenses: {},
    mutual_funds: [],
    equity_stocks: [],
    fixed_income: [],
    monthly_investments: {},
    liquid_capital: {},
    emergency_fund: {},
    loans_liabilities: {},
    insurance_details: {},
    financial_goals: [],
    freedom_score_inputs: {},
    assumptions: {
      persons: [],
      growth: { cash: 0.04, investment: 0.10, real_estate: 0.06, vehicle: -0.10 },
      taxes: { federal: 0.30, state: 0.0, capital_gains: 0.125 },
      inflation: 0.06,
    },
    scenarios: [],
    active_scenario_ids: [],
    computed: {
      headline_amount_at_horizon: 0,
      horizon_years: 45,
      net_worth_series: [],
      cash_flow_table: [],
      net_worth: { total: 0, liquid: 0, non_liquid: 0, assets_total: 0, debts_total: 0 },
      milestone_pins: [],
    },
    evidence: [],
    missing_fields: [],
    last_updated_at: new Date().toISOString(),
  };
}
