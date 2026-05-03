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
      </div>
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
