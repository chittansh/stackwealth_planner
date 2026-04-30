/**
 * Household merge skill.
 * Combines N households into one. Sums monetary fields, unions repeatable
 * lists, max-takes insurance covers, and unions goals.
 */
import { randomUUID } from 'node:crypto';
import { emptyPlanState, type PlanState } from '../../types/plan-state.js';
import { getPlan, savePlan } from '../../db/client.js';

export async function preview(args: { household_ids: string[] }) {
  const plans = await loadAll(args.household_ids);
  return summary(plans);
}

export async function merge(args: { household_ids: string[] }): Promise<{ parent_household_id: string }> {
  const plans = await loadAll(args.household_ids);
  const parent = mergeMany(plans);
  await savePlan(parent);
  return { parent_household_id: parent.household_id };
}

async function loadAll(ids: string[]): Promise<PlanState[]> {
  const out: PlanState[] = [];
  for (const id of ids) {
    const p = await getPlan(id);
    if (p) out.push(p);
  }
  return out;
}

function summary(plans: PlanState[]) {
  let combined_assets = 0;
  let combined_income_monthly = 0;
  let combined_expenses_monthly = 0;
  let combined_goals_count = 0;
  for (const p of plans) {
    combined_assets += p.computed.net_worth.assets_total ?? 0;
    combined_income_monthly +=
      (p.income_details.client_salary_in_hand ?? 0) +
      (p.income_details.spouse_salary_in_hand ?? 0) +
      (p.income_details.client_business_income ?? 0) +
      (p.income_details.client_rental_income ?? 0);
    combined_expenses_monthly += sumNumbers(p.monthly_expenses);
    combined_goals_count += p.financial_goals.length;
  }
  return {
    parent_household_id: 'preview',
    combined_assets,
    combined_income_monthly,
    combined_expenses_monthly,
    combined_goals_count,
  };
}

function sumNumbers(o: Record<string, number | null | undefined>): number {
  return Object.values(o).reduce<number>((a, v) => a + (typeof v === 'number' ? v : 0), 0);
}

function mergeMany(plans: PlanState[]): PlanState {
  const parent = emptyPlanState(`hh-${randomUUID().slice(0, 8)}`);
  parent.personal_details.full_name = plans.map((p) => p.personal_details.full_name ?? 'Member').join(' + ');
  parent.personal_details.city_of_residence = plans[0]?.personal_details.city_of_residence ?? null;
  parent.personal_details.city_type = plans[0]?.personal_details.city_type ?? 'Non-metro';

  // Income: sum all
  for (const p of plans) {
    parent.income_details.client_salary_in_hand =
      (parent.income_details.client_salary_in_hand ?? 0) + (p.income_details.client_salary_in_hand ?? 0);
    parent.income_details.spouse_salary_in_hand =
      (parent.income_details.spouse_salary_in_hand ?? 0) + (p.income_details.spouse_salary_in_hand ?? 0);
    parent.income_details.client_business_income =
      (parent.income_details.client_business_income ?? 0) + (p.income_details.client_business_income ?? 0);
    parent.income_details.client_rental_income =
      (parent.income_details.client_rental_income ?? 0) + (p.income_details.client_rental_income ?? 0);
    parent.income_details.client_other_income =
      (parent.income_details.client_other_income ?? 0) + (p.income_details.client_other_income ?? 0);
  }

  // Expenses: sum
  const expenseKeys = Object.keys(plans[0]?.monthly_expenses ?? {}) as (keyof typeof parent.monthly_expenses)[];
  for (const k of expenseKeys) {
    let total = 0;
    for (const p of plans) total += (p.monthly_expenses[k] ?? 0) as number;
    parent.monthly_expenses[k] = total as never;
  }

  // Holdings: union (each row tagged with its source plan via source_file)
  for (const p of plans) {
    parent.mutual_funds.push(...p.mutual_funds);
    parent.equity_stocks.push(...p.equity_stocks);
    parent.fixed_income.push(...p.fixed_income);
    parent.financial_goals.push(...p.financial_goals);
    parent.evidence.push(...p.evidence);
  }

  // Liquid + emergency: sum
  parent.liquid_capital.savings_account_balance = plans.reduce(
    (a, p) => a + (p.liquid_capital.savings_account_balance ?? 0),
    0,
  );
  parent.emergency_fund.total_emergency_corpus = plans.reduce(
    (a, p) => a + (p.emergency_fund.total_emergency_corpus ?? 0),
    0,
  );

  // Loans: sum each block
  for (const k of ['home_loan', 'car_loan', 'personal_loan', 'credit_card_dues'] as const) {
    let outstanding = 0,
      emi = 0;
    let rate = 0,
      tenure = 0,
      n = 0;
    for (const p of plans) {
      const b = p.loans_liabilities[k];
      if (!b) continue;
      outstanding += b.outstanding_amount ?? 0;
      emi += b.emi ?? 0;
      if (typeof b.interest_rate === 'number') {
        rate += b.interest_rate;
        n++;
      }
      if (typeof b.tenure_left === 'number' && b.tenure_left > tenure) tenure = b.tenure_left;
    }
    if (outstanding > 0 || emi > 0) {
      parent.loans_liabilities[k] = {
        outstanding_amount: outstanding,
        emi,
        interest_rate: n ? rate / n : null,
        tenure_left: tenure || null,
      };
    }
  }

  // Insurance: max cover, sum premium
  for (const k of ['term_plan', 'health_insurance', 'family_floater', 'ulip_or_endowment'] as const) {
    let cover = 0,
      premium = 0,
      company: string | null = null;
    for (const p of plans) {
      const b = p.insurance_details[k];
      if (!b) continue;
      cover = Math.max(cover, b.cover_amount ?? 0);
      premium += b.annual_premium ?? 0;
      company = company ?? b.company ?? null;
    }
    if (cover > 0 || premium > 0) {
      parent.insurance_details[k] = { company, cover_amount: cover || null, annual_premium: premium || null };
    }
  }

  // Persons: union
  for (const p of plans) {
    parent.assumptions.persons.push(...p.assumptions.persons);
  }

  // FreedomScoreInputs roll-up
  parent.freedom_score_inputs.monthly_income = plans.reduce(
    (a, p) => a + (p.freedom_score_inputs.monthly_income ?? 0),
    0,
  );
  parent.freedom_score_inputs.monthly_expenses = plans.reduce(
    (a, p) => a + (p.freedom_score_inputs.monthly_expenses ?? 0),
    0,
  );
  parent.freedom_score_inputs.portfolio_current_value = plans.reduce(
    (a, p) => a + (p.freedom_score_inputs.portfolio_current_value ?? 0),
    0,
  );
  parent.freedom_score_inputs.liquid_assets_current_value = plans.reduce(
    (a, p) => a + (p.freedom_score_inputs.liquid_assets_current_value ?? 0),
    0,
  );
  parent.freedom_score_inputs.age = Math.max(...plans.map((p) => p.freedom_score_inputs.age ?? 0));
  parent.freedom_score_inputs.equity_allocation_percent =
    plans.reduce((a, p) => a + (p.freedom_score_inputs.equity_allocation_percent ?? 0), 0) / Math.max(1, plans.length);

  parent.last_updated_at = new Date().toISOString();
  return parent;
}
