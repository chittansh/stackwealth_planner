'use client';

import type { PlanState } from '@/types/plan-state';
import { firePrompt } from '@/lib/prompt';
import { Plus } from 'lucide-react';

const ADD_PERSON_PROMPT =
  'Add a household member (name, date of birth in DD-MM-YYYY, life expectancy, retirement age).';

export function AssumptionsCard({ plan }: { plan: PlanState }) {
  const a = plan.assumptions;
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-zinc-700">Assumptions</h3>
        <button
          onClick={() => firePrompt(ADD_PERSON_PROMPT)}
          className="w-6 h-6 grid place-items-center rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-50"
          title="Add a person via chat"
        >
          <Plus size={14} />
        </button>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-6">
        {a.persons.length === 0 ? (
          <button
            onClick={() => firePrompt(ADD_PERSON_PROMPT)}
            className="text-left rounded-md border border-dashed border-zinc-200 p-3 hover:border-zinc-400 hover:bg-zinc-50 text-zinc-500 text-[13px]"
          >
            Add a household member →
            <div className="text-[10px] text-zinc-400 mt-1">
              I&apos;ll ask for date of birth, life expectancy, and retirement age in chat.
            </div>
          </button>
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

        <div>
          <h4 className="text-sm text-zinc-700 mb-2">
            Income growth (per source)
            <span className="ml-1 text-[10px] text-zinc-400 font-normal">post-tax / yr</span>
          </h4>
          <Pair k="Employment" v={`${((a.income_growth?.employment ?? 0.056) * 100).toFixed(1)}%`} />
          <Pair k="Business" v={`${((a.income_growth?.business ?? 0.070) * 100).toFixed(1)}%`} />
          <Pair k="Rental" v={`${((a.income_growth?.rental ?? 0.035) * 100).toFixed(1)}%`} />
          <Pair k="Other" v={`${((a.income_growth?.other ?? 0.035) * 100).toFixed(1)}%`} />
        </div>

        <div>
          <h4 className="text-sm text-zinc-700 mb-2">
            Goal inflation (per type)
            <span className="ml-1 text-[10px] text-zinc-400 font-normal">CFP table</span>
          </h4>
          <Pair k="General" v="7.0%" />
          <Pair k="Education" v="10.0%" />
          <Pair k="Wedding" v="9.0%" />
          <Pair k="Medical" v="12.0%" />
          <Pair k="Real estate / vacation" v="9.0%" />
          <Pair k="Lifestyle" v="25.0%" />
        </div>

        <div>
          <h4 className="text-sm text-zinc-700 mb-2">
            Post-tax returns
            <span className="ml-1 text-[10px] text-zinc-400 font-normal">used by projection</span>
          </h4>
          <Pair k="Equity hybrid" v="10.5%" />
          <Pair k="Equity conservative" v="8.75%" />
          <Pair k="PPF" v="7.10%" />
          <Pair k="EPF" v="8.10%" />
          <Pair k="Bank FD" v="4.55%" />
          <Pair k="Liquid fund" v="3.85%" />
          <Pair k="Real estate" v="7.00%" />
          <Pair k="Gold" v="7.00%" />
        </div>
      </div>

      <p className="text-[11px] text-zinc-400 mt-4 pt-3 border-t border-zinc-100">
        All values match the firm&apos;s CFP Excel (Assumptions &amp; Computation tab). Per-goal
        return overrides take precedence when set on the goal row itself. Income growth applies
        per source — employment vs business vs rental — instead of a single blended rate.
      </p>
    </div>
  );
}

function PersonBlock({
  name,
  dob,
  lifeExp,
  retire,
}: {
  name: string;
  dob: string;
  lifeExp: number | string;
  retire: number | string;
}) {
  return (
    <div>
      <h4 className="text-sm text-zinc-700 mb-2">{name}</h4>
      <Pair k="Date of birth" v={dob} />
      <Pair k="Life expectancy" v={String(lifeExp)} />
      <Pair k="Retirement age" v={String(retire)} />
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
