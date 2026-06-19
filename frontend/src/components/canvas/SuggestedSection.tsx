'use client';

import { useEffect, useState } from 'react';

import type { PlanState, SuggestionLever, SuggestionsSnapshot } from '@/types/plan-state';
import { fetchSuggestions } from '@/lib/api';
import { formatINR } from '@/lib/utils';

/**
 * The AI "Suggested ___" section — rendered BELOW the as-is content in the
 * Cashflow, Goals, and Retirement tabs. Shows the recommended combined plan,
 * the itemized levers, and the lumpsum nudge. Reads
 * `plan.computed.suggestions`; if absent, fetches once (the endpoint persists
 * it, so a subsequent plan refresh hydrates it everywhere).
 */
export function SuggestedSection({
  plan,
  domain,
}: {
  plan: PlanState | null;
  domain: 'cashflow' | 'goals' | 'retirement';
}) {
  const persisted = (plan?.computed?.suggestions ?? null) as SuggestionsSnapshot | null;
  const [local, setLocal] = useState<SuggestionsSnapshot | null>(null);
  const [loading, setLoading] = useState(false);

  const id = plan?.household_id;
  const hasCfp = !!plan?.computed?.cfp;

  useEffect(() => {
    if (persisted || local || !id || !hasCfp || loading) return;
    setLoading(true);
    fetchSuggestions(id)
      .then((s) => setLocal(s as SuggestionsSnapshot))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id, hasCfp, persisted, local, loading]);

  const snap = persisted ?? local;

  if (!hasCfp) return null;
  if (loading && !snap) {
    return (
      <div className="rounded-xl border border-dashed border-[color:var(--color-accent,#5f7d56)]/40 p-6 text-sm text-zinc-500 text-center">
        Generating suggestions…
      </div>
    );
  }
  if (!snap) return null;

  if (!snap.has_gaps) {
    return (
      <SuggestedShell title={titleFor(domain)}>
        <p className="text-sm text-zinc-600">
          On the current trajectory this is adequately funded by existing SIPs and assets — no corrective
          levers needed. Keep current SIPs running and step them up with annual income growth.
        </p>
      </SuggestedShell>
    );
  }

  return (
    <SuggestedShell title={titleFor(domain)}>
      <RecommendedCard snap={snap} />
      {domain === 'cashflow' && <CashflowBody snap={snap} />}
      {domain === 'goals' && <GoalsBody snap={snap} />}
      {domain === 'retirement' && <RetirementBody snap={snap} />}
      <LumpsumNudge snap={snap} />
    </SuggestedShell>
  );
}

function titleFor(d: string) {
  return d === 'cashflow' ? 'Suggested Cashflow' : d === 'goals' ? 'Suggested Goals' : 'Suggested Retirement Glide';
}

function SuggestedShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-[color:var(--color-accent,#5f7d56)]/30 bg-[color:var(--color-accent,#5f7d56)]/[0.04] p-5">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[10px] uppercase tracking-wide font-semibold text-[color:var(--color-accent,#5f7d56)]">
          AI Suggested
        </span>
      </div>
      <h3 className="text-sm font-medium text-zinc-700 mb-3">{title}</h3>
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  );
}

function RecommendedCard({ snap }: { snap: SuggestionsSnapshot }) {
  const rec = snap.recommended;
  const imp = rec?.impact ?? {};
  const retDelta = imp.net_worth_at_retirement_delta ?? 0;
  return (
    <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 px-4 py-3 text-sm">
      <div className="text-[10px] uppercase tracking-wide text-emerald-700 mb-0.5">Recommended combined plan</div>
      <div className="text-zinc-800">{rec?.summary || 'On track — keep current SIPs running.'}</div>
      {retDelta !== 0 && imp.retirement_year && (
        <div className="text-xs text-emerald-800 mt-1 tabular-nums">
          Projected net worth at retirement ({imp.retirement_year}):{' '}
          {formatINR(imp.net_worth_at_retirement ?? 0, { compact: true })} vs{' '}
          {formatINR(imp.baseline_net_worth_at_retirement ?? 0, { compact: true })} today&apos;s plan
          {retDelta > 0 ? ` (+${formatINR(retDelta, { compact: true })})` : ''}
        </div>
      )}
      {rec?.residual_note && (
        <div className="text-[11px] text-amber-800 bg-amber-50 border border-amber-100 rounded px-2 py-1.5 mt-2">
          {rec.residual_note}
        </div>
      )}
    </div>
  );
}

function LeverList({ levers }: { levers: SuggestionLever[] }) {
  if (!levers?.length) return null;
  return (
    <ul className="flex flex-col gap-1.5">
      {levers.map((lv, i) => (
        <li
          key={i}
          className={`text-xs rounded-md border px-3 py-2 ${
            lv.feasible ? 'border-zinc-200 bg-white' : 'border-zinc-100 bg-zinc-50 text-zinc-400'
          }`}
        >
          <span className="font-medium text-zinc-700">
            {lv.feasible ? '' : '✗ '}
            {lv.title}:
          </span>{' '}
          <span className={lv.feasible ? 'text-zinc-800' : ''}>{lv.change}</span>
          {lv.rationale && <div className="text-[11px] text-zinc-400 mt-0.5">{lv.rationale}</div>}
        </li>
      ))}
    </ul>
  );
}

function CashflowBody({ snap }: { snap: SuggestionsSnapshot }) {
  const cf = snap.domains.cashflow;
  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <Mini label="Surplus (pre-SIP)" value={formatINR(cf.monthly_surplus, { compact: true })} />
        <Mini label="Existing SIPs" value={formatINR(cf.monthly_existing_sip, { compact: true })} />
        <Mini label="Room for new SIP" value={formatINR(cf.affordable_new_sip, { compact: true })} />
        <Mini
          label={cf.is_affordable ? 'Affordable as-is' : 'Monthly shortfall'}
          value={formatINR(cf.sip_shortfall_monthly, { compact: true })}
          accent={cf.is_affordable ? 'good' : 'bad'}
        />
      </div>
      <LeverList levers={cf.levers} />
    </>
  );
}

function GoalsBody({ snap }: { snap: SuggestionsSnapshot }) {
  const goals = snap.domains.goals.goals;
  if (!goals.length) return <p className="text-sm text-zinc-600">All goals are on track at current SIPs.</p>;
  return (
    <div className="flex flex-col gap-3">
      {goals.map((g) => (
        <div key={g.goal_name} className="rounded-lg border border-zinc-200 bg-white p-3">
          <div className="flex items-baseline justify-between mb-1.5">
            <span className="text-sm font-medium text-zinc-800">
              {g.goal_name}
              {g.is_retirement && (
                <span className="ml-1.5 text-[9px] uppercase tracking-wide text-[color:var(--color-accent,#5f7d56)] border border-[color:var(--color-accent,#5f7d56)]/40 rounded px-1 py-0.5">
                  retirement
                </span>
              )}
            </span>
            <span className="text-[11px] text-zinc-500 tabular-nums">
              {g.target_year} · need {formatINR(g.required_sip_monthly)}/mo · already{' '}
              {formatINR(g.existing_sip_monthly)}/mo · add {formatINR(g.shortfall_monthly)}/mo
              {g.funded_pct != null ? ` · ${g.funded_pct}% funded` : ''}
            </span>
          </div>
          <LeverList levers={g.levers} />
        </div>
      ))}
    </div>
  );
}

function RetirementBody({ snap }: { snap: SuggestionsSnapshot }) {
  const r = snap.domains.retirement;
  if (r.on_track) return <p className="text-sm text-zinc-600">Retirement is on track at the current contribution level.</p>;
  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <Mini label="Corpus required" value={formatINR(r.corpus_required, { compact: true })} />
        <Mini label="Provisioned" value={formatINR(r.provisioned, { compact: true })} />
        <Mini label="Funded" value={`${r.funded_pct}%`} />
        <Mini label="Additional SIP" value={`${formatINR(r.required_sip_monthly)}/mo`} accent="bad" />
      </div>
      <LeverList levers={r.levers} />
    </>
  );
}

function LumpsumNudge({ snap }: { snap: SuggestionsSnapshot }) {
  const n = snap.nudges?.[0];
  if (!n) return null;
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/70 px-4 py-3 text-xs">
      <span className="font-medium text-amber-900">{n.title}</span>{' '}
      <span className="text-amber-800">{n.question}</span>
    </div>
  );
}

function Mini({ label, value, accent }: { label: string; value: string; accent?: 'good' | 'bad' }) {
  const cls = accent === 'bad' ? 'text-rose-700' : accent === 'good' ? 'text-emerald-700' : 'text-zinc-800';
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</span>
      <span className={`tabular-nums font-medium ${cls}`}>{value}</span>
    </div>
  );
}
