'use client';

import type { PlanState } from '@/types/plan-state';

export function AssumptionsCard({ plan }: { plan: PlanState }) {
  const a = plan.assumptions;
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <h3 className="text-sm font-medium text-zinc-700 mb-3">Assumptions</h3>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-6">
        {a.persons.length === 0 ? (
          <PersonBlock name="Add a person" />
        ) : (
          a.persons.map((p) => (
            <PersonBlock
              key={p.id}
              name={p.name}
              dob={p.date_of_birth ?? '—'}
              lifeExp={p.life_expectancy ?? '—'}
              retire={p.retirement_age ?? '—'}
            />
          ))
        )}

        <div>
          <h4 className="text-sm text-zinc-700 mb-2">Growth</h4>
          <Pair k="Cash" v={`${(a.growth.cash * 100).toFixed(1)}%`} />
          <Pair k="Investment" v={`${(a.growth.investment * 100).toFixed(1)}%`} />
          <Pair k="Real estate" v={`${(a.growth.real_estate * 100).toFixed(1)}%`} />
          <Pair k="Vehicle" v={`${(a.growth.vehicle * 100).toFixed(1)}%`} />
        </div>

        <div>
          <h4 className="text-sm text-zinc-700 mb-2">Taxes</h4>
          <Pair k="Federal" v={`${(a.taxes.federal * 100).toFixed(1)}%`} />
          <Pair k="State" v={`${(a.taxes.state * 100).toFixed(1)}%`} />
          <Pair k="Capital gains" v={`${(a.taxes.capital_gains * 100).toFixed(1)}%`} />
        </div>
      </div>
    </div>
  );
}

function PersonBlock({
  name,
  dob = '—',
  lifeExp,
  retire,
}: {
  name: string;
  dob?: string;
  lifeExp?: number | string;
  retire?: number | string;
}) {
  return (
    <div>
      <h4 className="text-sm text-zinc-700 mb-2">{name}</h4>
      <Pair k="Date of birth" v={dob ?? '—'} />
      <Pair k="Life expectancy" v={String(lifeExp ?? '—')} />
      <Pair k="Retirement age" v={String(retire ?? '—')} />
    </div>
  );
}

function Pair({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between text-sm py-1 border-b border-dashed border-zinc-100 last:border-0">
      <span className="text-zinc-600">{k}</span>
      <span className="text-zinc-800 tabular-nums">{v}</span>
    </div>
  );
}
