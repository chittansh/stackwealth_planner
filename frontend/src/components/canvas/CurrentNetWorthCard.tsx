'use client';

import { Plus } from 'lucide-react';
import type { PlanState, NetWorth } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { firePrompt } from '@/lib/prompt';

/**
 * Net-worth card with full asset/loan breakdown.
 *
 * Shows every component the engine knows about — cash, investments,
 * real estate, gold — and pairs each secured loan with the asset it's
 * against. Replaces the earlier simplistic "Assets / Debts" two-column
 * view where real estate (often the household's biggest asset) was
 * invisible because the legacy net-worth math excluded it.
 *
 * Source of truth: `plan.computed.net_worth` (server-computed). Falls
 * back to local sums when the snapshot hasn't been computed yet.
 */
export function CurrentNetWorthCard({ plan }: { plan: PlanState }) {
  const fsi = plan.freedom_score_inputs ?? {};
  const lc = plan.liquid_capital ?? {};
  const l = plan.loans_liabilities ?? {};
  const nw: NetWorth | undefined = plan.computed.net_worth;

  // Prefer server-computed totals (canonical, identical to net_worth.total
  // and the report). Fall back to client-side sums on a fresh plan.
  const cashLocal =
    (lc.savings_account_balance ?? 0) +
    (lc.idle_cash_for_investment ?? 0) +
    (lc.fd_breakable_for_investment ?? 0) +
    (lc.bonus_expected_for_investment ?? 0) ||
    (fsi.liquid_assets_current_value ?? 0);
  const mfTotal = plan.mutual_funds.reduce((s, h) => s + (h.current_value ?? 0), 0);
  const eqTotal = plan.equity_stocks.reduce((s, h) => s + (h.current_value ?? 0), 0);
  const fiTotal = plan.fixed_income.reduce((s, h) => s + (h.current_value ?? 0), 0);
  const reLocal = (plan.real_estate ?? []).reduce((s, r) => s + (r.current_value ?? 0), 0);
  const goldLocal = (plan.gold ?? []).reduce((s, g) => s + (g.current_value ?? 0), 0);
  const investmentsLocal = mfTotal + eqTotal + fiTotal || (fsi.portfolio_current_value ?? 0);

  const cash = nw?.liquid ?? cashLocal;
  const investments = nw?.investments ?? investmentsLocal;
  const realEstateTotal = nw?.real_estate_total ?? reLocal;
  const goldTotal = nw?.gold_total ?? goldLocal;
  const homeLoan = nw?.home_loan_outstanding ?? (l.home_loan?.outstanding_amount ?? 0);
  const carLoan = nw?.car_loan_outstanding ?? (l.car_loan?.outstanding_amount ?? 0);
  const personalLoan = nw?.personal_loan_outstanding ?? (l.personal_loan?.outstanding_amount ?? 0);
  const ccDues = nw?.credit_card_outstanding ?? (l.credit_card_dues?.outstanding_amount ?? 0);
  const realEstateEquity = nw?.real_estate_equity ?? Math.max(0, realEstateTotal - homeLoan);
  const grossAssets = cash + investments + realEstateTotal + goldTotal;
  const totalDebt = homeLoan + carLoan + personalLoan + ccDues;
  const netWorth =
    nw?.total ?? (cash + investments + realEstateEquity + goldTotal - personalLoan - ccDues - carLoan);

  const hasAnything = grossAssets > 0 || totalDebt > 0;

  return (
    <Card title="Current net worth" addPrompt="Help me capture my current cash, investments, properties, and any loans.">
      {!hasAnything ? (
        <EmptyAdd
          prompt="Help me capture my current cash, investments, properties, and any loans."
          label="Tell me your current savings, properties, and any loans"
        />
      ) : (
        <>
          {/* ── Headline net-worth tile ─────────────────────────────── */}
          <div className="rounded-lg bg-[var(--color-accent-soft,#eef3eb)] border border-[color:var(--color-accent,#5f7d56)]/20 px-3 py-2 mb-3">
            <div className="text-[10px] uppercase tracking-wide text-zinc-500">Net worth</div>
            <div className="flex items-baseline justify-between gap-3 mt-0.5">
              <span className="text-xl font-semibold tabular-nums text-[color:var(--color-accent,#5f7d56)]">
                {formatINR(netWorth, { compact: true })}
              </span>
              <span className="text-[10px] text-zinc-500 tabular-nums">
                gross {formatINR(grossAssets, { compact: true })} − debt {formatINR(totalDebt, { compact: true })}
              </span>
            </div>
          </div>

          {/* ── Asset breakdown ─────────────────────────────────────── */}
          <Section label="Assets" subtotal={grossAssets}>
            {cash > 0 && <Row label="Cash & savings" value={cash} />}
            {investments > 0 && (
              <Row
                label="Investments"
                value={investments}
                hint={
                  mfTotal + eqTotal + fiTotal > 0
                    ? `${plan.mutual_funds.length + plan.equity_stocks.length + plan.fixed_income.length} holdings (MFs · stocks · FI)`
                    : undefined
                }
              />
            )}
            {realEstateTotal > 0 && (
              <Row
                label="Real estate"
                value={realEstateTotal}
                hint={
                  (plan.real_estate?.length ?? 0) > 0
                    ? `${plan.real_estate!.length} property${plan.real_estate!.length === 1 ? '' : 'ies'}`
                    : undefined
                }
              />
            )}
            {goldTotal > 0 && (
              <Row
                label="Gold"
                value={goldTotal}
                hint={(plan.gold?.length ?? 0) > 0 ? `${plan.gold!.length} holding${plan.gold!.length === 1 ? '' : 's'}` : undefined}
              />
            )}
          </Section>

          {/* ── Loans, paired to underlying asset where we have it ──── */}
          {totalDebt > 0 && (
            <Section label="Loans outstanding" subtotal={-totalDebt} className="mt-3">
              {homeLoan > 0 && (
                <PairedLoanRow
                  label="Home loan"
                  loan={homeLoan}
                  emi={l.home_loan?.emi}
                  pairedAssetLabel="against real estate"
                  pairedAssetValue={realEstateTotal}
                  equity={realEstateEquity}
                />
              )}
              {carLoan > 0 && (
                <Row label="Car loan" value={-carLoan} hint={l.car_loan?.emi ? `EMI ${formatINR(l.car_loan.emi, { compact: true })}/mo` : undefined} />
              )}
              {personalLoan > 0 && (
                <Row label="Personal loan" value={-personalLoan} hint={l.personal_loan?.emi ? `EMI ${formatINR(l.personal_loan.emi, { compact: true })}/mo` : undefined} />
              )}
              {ccDues > 0 && (
                <Row label="Credit card dues" value={-ccDues} hint={l.credit_card_dues?.emi ? `EMI ${formatINR(l.credit_card_dues.emi, { compact: true })}/mo` : undefined} />
              )}
            </Section>
          )}
        </>
      )}
    </Card>
  );
}

/** A loan row that's paired with the asset it's secured against. Shows
 * the asset value, the loan remaining, and the equity you actually own. */
function PairedLoanRow({
  label,
  loan,
  emi,
  pairedAssetLabel,
  pairedAssetValue,
  equity,
}: {
  label: string;
  loan: number;
  emi?: number | null;
  pairedAssetLabel: string;
  pairedAssetValue: number;
  equity: number;
}) {
  return (
    <div className="rounded-md border border-zinc-200 bg-zinc-50/50 p-2.5 my-1">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-zinc-700">{label}</span>
        <span className="text-zinc-900 tabular-nums">−{formatINR(loan, { compact: true })}</span>
      </div>
      <div className="text-[10px] text-zinc-500 mt-0.5">
        {emi ? `EMI ${formatINR(emi, { compact: true })}/mo · ` : ''}
        {pairedAssetLabel} {formatINR(pairedAssetValue, { compact: true })}
      </div>
      {pairedAssetValue > 0 && (
        <div className="mt-2 pt-2 border-t border-dashed border-zinc-200 flex items-baseline justify-between text-xs">
          <span className="text-zinc-500">Your equity</span>
          <span className="text-[color:var(--color-accent,#5f7d56)] font-medium tabular-nums">
            {formatINR(equity, { compact: true })}
          </span>
        </div>
      )}
    </div>
  );
}

function Card({
  title,
  addPrompt,
  children,
}: {
  title: string;
  addPrompt: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-zinc-700">{title}</h3>
        <button
          onClick={() => firePrompt(addPrompt)}
          className="w-6 h-6 grid place-items-center rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50"
          title="Add via chat"
        >
          <Plus size={14} />
        </button>
      </header>
      {children}
    </div>
  );
}

function Section({
  label,
  subtotal,
  children,
  className = '',
}: {
  label: string;
  subtotal?: number;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[10px] uppercase tracking-wide text-zinc-400">{label}</span>
        {subtotal !== undefined && (
          <span className="text-[10px] tabular-nums text-zinc-500">
            {subtotal < 0 ? '−' : ''}
            {formatINR(Math.abs(subtotal), { compact: true })}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  );
}

function Row({ label, value, hint }: { label: string; value: number; hint?: string }) {
  const neg = value < 0;
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm py-0.5">
      <span className="text-zinc-700 truncate">{label}</span>
      <div className="text-right shrink-0">
        <div className={`tabular-nums whitespace-nowrap ${neg ? 'text-zinc-700' : 'text-zinc-900'}`}>
          {neg ? '−' : ''}
          {formatINR(Math.abs(value), { compact: true })}
        </div>
        {hint && <div className="text-[10px] text-zinc-400">{hint}</div>}
      </div>
    </div>
  );
}

function EmptyAdd({ prompt, label }: { prompt: string; label: string }) {
  return (
    <button
      onClick={() => firePrompt(prompt)}
      className="text-left text-[11px] text-zinc-400 hover:text-zinc-700"
    >
      {label} →
    </button>
  );
}
