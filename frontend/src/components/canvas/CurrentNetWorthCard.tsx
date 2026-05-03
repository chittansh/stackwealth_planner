'use client';

import { Plus } from 'lucide-react';
import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { firePrompt } from '@/lib/prompt';

export function CurrentNetWorthCard({ plan }: { plan: PlanState }) {
  const fsi = plan.freedom_score_inputs ?? {};
  const lc = plan.liquid_capital ?? {};
  const l = plan.loans_liabilities ?? {};

  const cash =
    (lc.savings_account_balance ?? 0) +
    (lc.idle_cash_for_investment ?? 0) +
    (lc.fd_breakable_for_investment ?? 0) +
    (lc.bonus_expected_for_investment ?? 0) ||
    (fsi.liquid_assets_current_value ?? 0);

  const mfTotal = plan.mutual_funds.reduce((s, h) => s + (h.current_value ?? 0), 0);
  const eqTotal = plan.equity_stocks.reduce((s, h) => s + (h.current_value ?? 0), 0);
  const fiTotal = plan.fixed_income.reduce((s, h) => s + (h.current_value ?? 0), 0);
  const portfolioFromHoldings = mfTotal + eqTotal + fiTotal;
  const investments = portfolioFromHoldings > 0 ? portfolioFromHoldings : fsi.portfolio_current_value ?? 0;

  const debtRows: { label: string; amount: number }[] = [];
  if (l.home_loan?.outstanding_amount) debtRows.push({ label: 'Home loan', amount: l.home_loan.outstanding_amount });
  if (l.car_loan?.outstanding_amount) debtRows.push({ label: 'Car loan', amount: l.car_loan.outstanding_amount });
  if (l.personal_loan?.outstanding_amount) debtRows.push({ label: 'Personal loan', amount: l.personal_loan.outstanding_amount });
  if (l.credit_card_dues?.outstanding_amount) debtRows.push({ label: 'Credit card', amount: l.credit_card_dues.outstanding_amount });

  const hasAssets = cash > 0 || investments > 0;
  const hasDebts = debtRows.length > 0;

  return (
    <Card title="Current net worth" addPrompt="Help me capture my current cash, investments, and any loans.">
      {!hasAssets && !hasDebts ? (
        <EmptyAdd
          prompt="Help me capture my current cash, investments, and any loans."
          label="Tell me your current savings and any loans"
        />
      ) : (
        <>
          <Section label="Assets">
            {cash > 0 && <Row label="Cash" value={cash} />}
            {investments > 0 && (
              <Row
                label="Investments"
                value={investments}
                hint={portfolioFromHoldings > 0 ? `${plan.mutual_funds.length + plan.equity_stocks.length + plan.fixed_income.length} holdings` : undefined}
              />
            )}
            {!hasAssets && <Empty />}
          </Section>
          <Section label="Debts" className="mt-3">
            {debtRows.map((d) => (
              <Row key={d.label} label={d.label} value={-d.amount} />
            ))}
            {!hasDebts && <Empty />}
          </Section>
        </>
      )}
    </Card>
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
  children,
  className = '',
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="text-[10px] uppercase tracking-wide text-zinc-400 mb-1">{label}</div>
      <div className="flex flex-col gap-0.5">{children}</div>
    </div>
  );
}

function Row({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-zinc-700 truncate">{label}</span>
      <div className="text-right shrink-0">
        <div className="text-zinc-900 tabular-nums whitespace-nowrap">
          {formatINR(value, { compact: true })}
        </div>
        {hint && <div className="text-[10px] text-zinc-400">{hint}</div>}
      </div>
    </div>
  );
}

function Empty() {
  return <p className="text-[11px] text-zinc-400">—</p>;
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
