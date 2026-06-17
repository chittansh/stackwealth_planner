'use client';

import type { PlanState } from '@/types/plan-state';
import { formatINR } from '@/lib/utils';
import { firePrompt } from '@/lib/prompt';
import { Plus } from 'lucide-react';

/**
 * Investments view — mirrors Excel sheets 4A-4E + 5 + 6 + 7.
 *
 * One consolidated page that surfaces every holding the engine tracks,
 * grouped by asset class, with class totals, asset-mix breakdown,
 * monthly SIP destinations, liquid capital, emergency fund coverage,
 * and the post-tax returns reference table used by the projection.
 *
 * Each section corresponds 1:1 to a tab in the CFP Excel workbook so
 * the canvas now has parity with what the firm uses in spreadsheet
 * form — every line in the input template has a home on the canvas.
 */
export function InvestmentsView({ plan }: { plan: PlanState }) {
  const mfs = plan.mutual_funds ?? [];
  const stocks = plan.equity_stocks ?? [];
  const fi = plan.fixed_income ?? [];
  const re = plan.real_estate ?? [];
  const gold = plan.gold ?? [];
  const mi = plan.monthly_investments ?? {};
  const lc = plan.liquid_capital ?? {};
  const ef = plan.emergency_fund ?? {};

  const mfTotal = mfs.reduce((s, h) => s + (h.current_value ?? 0), 0);
  const stockTotal = stocks.reduce((s, h) => s + (h.current_value ?? 0), 0);
  const fiTotal = fi.reduce((s, h) => s + (h.current_value ?? 0), 0);
  const reTotal = re.reduce((s, h) => s + (h.current_value ?? 0), 0);
  const goldTotal = gold.reduce((s, h) => s + (h.current_value ?? 0), 0);
  const liquidTotal =
    (lc.savings_account_balance ?? 0) +
    (lc.idle_cash_for_investment ?? 0) +
    (lc.fd_breakable_for_investment ?? 0) +
    (lc.bonus_expected_for_investment ?? 0);

  const investableTotal = mfTotal + stockTotal + fiTotal + reTotal + goldTotal + liquidTotal;

  const totalMonthlySip =
    (mi.mutual_fund_sip ?? 0) +
    (mi.nps ?? 0) +
    (mi.ppf ?? 0) +
    (mi.rd ?? 0) +
    (mi.direct_equity ?? 0) +
    (mi.insurance_premium ?? 0) +
    (mi.other ?? 0);

  if (investableTotal === 0 && totalMonthlySip === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-200 p-10 text-sm text-zinc-500 text-center">
        No investments captured yet. Upload your portfolio statements or tell me about your holdings in the chat.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Asset class mix headline */}
      <div className="rounded-xl border border-zinc-200 bg-white p-5">
        <div className="flex items-baseline justify-between mb-3">
          <h3 className="text-sm font-medium text-zinc-700">Investment portfolio</h3>
          <span className="text-[10px] text-zinc-400 tabular-nums">
            total {formatINR(investableTotal, { compact: true })}
          </span>
        </div>
        <AssetMixBar
          segments={[
            { key: 'mf', label: 'Mutual funds', value: mfTotal, color: 'var(--color-accent,#5f7d56)' },
            { key: 'stocks', label: 'Stocks', value: stockTotal, color: '#84a87a' },
            { key: 'fi', label: 'Fixed income', value: fiTotal, color: '#a8c1a0' },
            { key: 're', label: 'Real estate', value: reTotal, color: '#c4a878' },
            { key: 'gold', label: 'Gold', value: goldTotal, color: '#d4b878' },
            { key: 'liquid', label: 'Cash & liquid', value: liquidTotal, color: '#a1a1aa' },
          ]}
        />
      </div>

      {/* Mutual Funds — Excel 4A */}
      <SectionCard
        title="Mutual funds"
        subtitle="Excel 4A_Mutual_Funds"
        total={mfTotal}
        addPrompt="Add a mutual fund — fund name, current value, monthly SIP if any."
        empty={mfs.length === 0}
      >
        {mfs.length > 0 && (
          <table className="w-full text-xs">
            <thead className="text-zinc-500 border-b border-zinc-100">
              <tr className="text-left">
                <th className="py-1.5 font-medium">Fund name</th>
                <th className="py-1.5 font-medium">Folio</th>
                <th className="py-1.5 font-medium text-right">Current value</th>
                <th className="py-1.5 font-medium text-right">SIP / mo</th>
              </tr>
            </thead>
            <tbody>
              {mfs.map((m) => (
                <tr key={m.id} className="border-b border-zinc-100 last:border-0">
                  <td className="py-1.5 text-zinc-800">{m.fund_name || '—'}</td>
                  <td className="py-1.5 text-[11px] text-zinc-500">{m.folio || '—'}</td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-800">
                    {formatINR(m.current_value ?? 0, { compact: true })}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-800">
                    {m.sip_amount ? `${formatINR(m.sip_amount, { compact: true })}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      {/* Equity Stocks — Excel 4B */}
      <SectionCard
        title="Equity stocks"
        subtitle="Excel 4B_Equity_Stocks"
        total={stockTotal}
        addPrompt="Add a direct-equity stock holding — name, quantity, current value, long-term or trading."
        empty={stocks.length === 0}
      >
        {stocks.length > 0 && (
          <table className="w-full text-xs">
            <thead className="text-zinc-500 border-b border-zinc-100">
              <tr className="text-left">
                <th className="py-1.5 font-medium">Stock</th>
                <th className="py-1.5 font-medium text-right">Qty</th>
                <th className="py-1.5 font-medium text-right">Current value</th>
                <th className="py-1.5 font-medium text-right">Held as</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((s) => (
                <tr key={s.id} className="border-b border-zinc-100 last:border-0">
                  <td className="py-1.5 text-zinc-800">{s.stock_name || '—'}</td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-800">{s.quantity ?? '—'}</td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-800">
                    {formatINR(s.current_value ?? 0, { compact: true })}
                  </td>
                  <td className="py-1.5 text-right text-[11px] text-zinc-500">
                    {s.long_term_or_trading === 'trading' ? 'Trading' : 'Long term'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      {/* Fixed Income — Excel 4C */}
      <SectionCard
        title="Fixed income"
        subtitle="Excel 4C_Fixed_Income — FD · RD · PPF · EPF · Bonds · NPS"
        total={fiTotal}
        addPrompt="Add a fixed-income holding (FD, RD, PPF, EPF, Bonds, NPS) with invested amount, current value, maturity date."
        empty={fi.length === 0}
      >
        {fi.length > 0 && (
          <table className="w-full text-xs">
            <thead className="text-zinc-500 border-b border-zinc-100">
              <tr className="text-left">
                <th className="py-1.5 font-medium">Instrument</th>
                <th className="py-1.5 font-medium text-right">Invested</th>
                <th className="py-1.5 font-medium text-right">Current value</th>
                <th className="py-1.5 font-medium text-right">Maturity</th>
              </tr>
            </thead>
            <tbody>
              {fi.map((f) => (
                <tr key={f.id} className="border-b border-zinc-100 last:border-0">
                  <td className="py-1.5 text-zinc-800">{f.instrument || '—'}</td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-700">
                    {f.invested_amount ? formatINR(f.invested_amount, { compact: true }) : '—'}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-800">
                    {formatINR(f.current_value ?? 0, { compact: true })}
                  </td>
                  <td className="py-1.5 text-right text-[11px] text-zinc-500">{f.maturity_date || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      {/* Real Estate — Excel 4D */}
      <SectionCard
        title="Real estate"
        subtitle="Excel 4D_Real_Estate"
        total={reTotal}
        addPrompt="Add a real-estate holding (residential / commercial / land) with current market value and any attached loan."
        empty={re.length === 0}
      >
        {re.length > 0 && (
          <table className="w-full text-xs">
            <thead className="text-zinc-500 border-b border-zinc-100">
              <tr className="text-left">
                <th className="py-1.5 font-medium">Property</th>
                <th className="py-1.5 font-medium">Kind</th>
                <th className="py-1.5 font-medium text-right">Current value</th>
                <th className="py-1.5 font-medium text-right">For sale</th>
              </tr>
            </thead>
            <tbody>
              {re.map((r) => (
                <tr key={r.id} className="border-b border-zinc-100 last:border-0">
                  <td className="py-1.5 text-zinc-800">{r.label || '—'}</td>
                  <td className="py-1.5 text-[11px] text-zinc-500 capitalize">{r.kind}</td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-800">
                    {formatINR(r.current_value ?? 0, { compact: true })}
                  </td>
                  <td className="py-1.5 text-right text-[11px] text-zinc-500">
                    {r.earmarked_for_sale ? 'Yes' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      {/* Gold — Excel 4E */}
      <SectionCard
        title="Gold & others"
        subtitle="Excel 4E_Gold & Others"
        total={goldTotal}
        addPrompt="Add a gold holding (physical / SGB / digital / jewellery) with current value."
        empty={gold.length === 0}
      >
        {gold.length > 0 && (
          <table className="w-full text-xs">
            <thead className="text-zinc-500 border-b border-zinc-100">
              <tr className="text-left">
                <th className="py-1.5 font-medium">Holding</th>
                <th className="py-1.5 font-medium">Kind</th>
                <th className="py-1.5 font-medium text-right">Current value</th>
                <th className="py-1.5 font-medium text-right">For investment</th>
              </tr>
            </thead>
            <tbody>
              {gold.map((g) => (
                <tr key={g.id} className="border-b border-zinc-100 last:border-0">
                  <td className="py-1.5 text-zinc-800">{g.label || '—'}</td>
                  <td className="py-1.5 text-[11px] text-zinc-500 capitalize">{g.kind}</td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-800">
                    {formatINR(g.current_value ?? 0, { compact: true })}
                  </td>
                  <td className="py-1.5 text-right text-[11px] text-zinc-500">
                    {g.held_for_investment ? 'Yes' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      {/* Monthly recurring investments — Excel 5 */}
      <SectionCard
        title="Monthly investments (SIPs)"
        subtitle="Excel 5_Recurring_Investments"
        total={totalMonthlySip}
        totalSuffix="/mo"
        addPrompt="Tell me your monthly recurring investments — MF SIP, NPS, PPF, RD, direct equity, insurance premium."
        empty={totalMonthlySip === 0}
      >
        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
          {[
            { label: 'Mutual Fund SIP', value: mi.mutual_fund_sip },
            { label: 'NPS', value: mi.nps },
            { label: 'PPF', value: mi.ppf },
            { label: 'RD', value: mi.rd },
            { label: 'Direct Equity', value: mi.direct_equity },
            { label: 'Insurance Premium', value: mi.insurance_premium },
            { label: 'Other', value: mi.other },
          ]
            .filter((r) => (r.value ?? 0) > 0)
            .map((r) => (
              <div key={r.label} className="flex items-baseline justify-between border-b border-dashed border-zinc-100 last:border-0 py-1">
                <span className="text-zinc-700">{r.label}</span>
                <span className="text-zinc-900 tabular-nums">{formatINR(r.value ?? 0, { compact: true })}/mo</span>
              </div>
            ))}
        </div>
      </SectionCard>

      {/* Liquid capital — Excel 6 */}
      <SectionCard
        title="Liquid capital"
        subtitle="Excel 6_Liquid_Capital — savings, idle cash, breakable FD, expected bonus"
        total={liquidTotal}
        addPrompt="Tell me your savings balance, idle cash, breakable FDs, and any expected bonus."
        empty={liquidTotal === 0}
      >
        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
          {[
            { label: 'Savings account', value: lc.savings_account_balance },
            { label: 'Idle cash for investment', value: lc.idle_cash_for_investment },
            { label: 'FD breakable for investment', value: lc.fd_breakable_for_investment },
            { label: 'Bonus expected for investment', value: lc.bonus_expected_for_investment },
          ]
            .filter((r) => (r.value ?? 0) > 0)
            .map((r) => (
              <div key={r.label} className="flex items-baseline justify-between border-b border-dashed border-zinc-100 last:border-0 py-1">
                <span className="text-zinc-700">{r.label}</span>
                <span className="text-zinc-900 tabular-nums">{formatINR(r.value ?? 0, { compact: true })}</span>
              </div>
            ))}
        </div>
      </SectionCard>

      {/* Emergency fund — Excel 7 */}
      <SectionCard
        title="Emergency fund"
        subtitle="Excel 7_Emergency_Fund — months of cover relative to monthly expenses"
        total={ef.total_emergency_corpus ?? 0}
        addPrompt="Tell me about your emergency fund — total corpus, where it's parked, and monthly expenses for cover calc."
        empty={!ef.emergency_fund_available && !(ef.total_emergency_corpus ?? 0)}
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          <KV k="Fund available?" v={ef.emergency_fund_available ? 'Yes' : 'No'} />
          <KV k="Total corpus" v={ef.total_emergency_corpus ? formatINR(ef.total_emergency_corpus, { compact: true }) : '—'} />
          <KV k="Where parked" v={ef.where_is_it_parked || '—'} />
          <KV k="Monthly expense reference" v={ef.monthly_household_expense_for_calculation ? formatINR(ef.monthly_household_expense_for_calculation, { compact: true }) : '—'} />
          <KV
            k="Months of cover"
            v={
              ef.months_of_cover_available != null
                ? `${ef.months_of_cover_available.toFixed(1)} mo`
                : '—'
            }
            tone={
              (ef.months_of_cover_available ?? 0) >= 6
                ? 'good'
                : (ef.months_of_cover_available ?? 0) >= 3
                ? 'warn'
                : 'bad'
            }
          />
          <KV
            k="Recommended"
            v="6 months of expenses"
          />
        </div>
      </SectionCard>

      {/* Post-tax returns reference — Excel Asset Returns */}
      <div className="rounded-xl border border-zinc-200 bg-white p-5">
        <div className="flex items-baseline justify-between mb-1">
          <h3 className="text-sm font-medium text-zinc-700">Post-tax return assumptions</h3>
          <span className="text-[10px] text-zinc-400">Excel Asset Returns</span>
        </div>
        <p className="text-[11px] text-zinc-400 mb-3">
          Per-class post-tax returns the projection uses. The holdings-weighted blend across your actual portfolio
          is shown on the Net Worth chart.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-1.5 text-xs">
          {[
            ['Equity hybrid', '10.50%'],
            ['Equity conservative', '8.75%'],
            ['PPF', '7.10%'],
            ['EPF', '8.10%'],
            ['Bank FD', '4.55%'],
            ['Liquid fund', '3.85%'],
            ['Real estate', '7.00%'],
            ['Gold', '7.00%'],
          ].map(([label, rate]) => (
            <div key={label} className="flex items-baseline justify-between border-b border-dashed border-zinc-100 py-1">
              <span className="text-zinc-700">{label}</span>
              <span className="text-zinc-800 tabular-nums">{rate}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Helpers ─────────────────────────────────────────────────────────── */

function SectionCard({
  title,
  subtitle,
  total,
  totalSuffix,
  addPrompt,
  empty,
  children,
}: {
  title: string;
  subtitle?: string;
  total: number;
  totalSuffix?: string;
  addPrompt: string;
  empty: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <header className="flex items-baseline justify-between mb-3">
        <div>
          <h3 className="text-sm font-medium text-zinc-800">{title}</h3>
          {subtitle && <p className="text-[10px] text-zinc-400 mt-0.5">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium tabular-nums text-zinc-900">
            {formatINR(total, { compact: true })}
            {totalSuffix && <span className="text-[10px] text-zinc-500"> {totalSuffix}</span>}
          </span>
          <button
            onClick={() => firePrompt(addPrompt)}
            className="w-6 h-6 grid place-items-center rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50"
            title="Add via chat"
          >
            <Plus size={14} />
          </button>
        </div>
      </header>
      {empty ? (
        <button
          onClick={() => firePrompt(addPrompt)}
          className="text-left text-[11px] text-zinc-400 hover:text-zinc-700"
        >
          Nothing here yet — tell me about this in chat →
        </button>
      ) : (
        children
      )}
    </div>
  );
}

function AssetMixBar({
  segments,
}: {
  segments: { key: string; label: string; value: number; color: string }[];
}) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (total === 0) return <p className="text-[11px] text-zinc-400">No holdings to display yet.</p>;
  const live = segments.filter((s) => s.value > 0);
  return (
    <>
      <div className="flex h-3 rounded-full overflow-hidden border border-zinc-100">
        {live.map((s) => (
          <div
            key={s.key}
            style={{ width: `${(s.value / total) * 100}%`, backgroundColor: s.color }}
            title={`${s.label} · ${formatINR(s.value, { compact: true })}`}
          />
        ))}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1.5 mt-3 text-[11px]">
        {live.map((s) => (
          <div key={s.key} className="flex items-baseline justify-between">
            <span className="flex items-center gap-1.5 text-zinc-700">
              <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: s.color }} />
              {s.label}
            </span>
            <span className="tabular-nums text-zinc-800">
              {formatINR(s.value, { compact: true })}
              <span className="text-zinc-400 ml-1">{((s.value / total) * 100).toFixed(0)}%</span>
            </span>
          </div>
        ))}
      </div>
    </>
  );
}

function KV({ k, v, tone }: { k: string; v: string; tone?: 'good' | 'warn' | 'bad' }) {
  const cls =
    tone === 'good'
      ? 'text-[color:var(--color-accent,#5f7d56)]'
      : tone === 'warn'
      ? 'text-amber-700'
      : tone === 'bad'
      ? 'text-rose-700'
      : 'text-zinc-800';
  return (
    <div className="flex items-baseline justify-between border-b border-dashed border-zinc-100 py-1">
      <span className="text-zinc-600">{k}</span>
      <span className={`tabular-nums ${cls}`}>{v}</span>
    </div>
  );
}
