# StackWealth Planner — Agent Evals

Pytest-style eval suite for the planner agent. Cases are organised into four layers; results are aggregated into a single PDF report after every run.

## Layers

| Layer | What it catches | LLM? |
|---|---|---|
| **1 — skill_math** | Risk / allocation / freedom / tax / MC math drift. Assertions are exact-number-with-tolerance on skill outputs. | No |
| **2 — tool_selection** | Prompt regressions: does the agent pick the right tool with the right args, given a single user message? | Yes (1 turn per case) |
| **3 — e2e** | Multi-turn flow: state evolves correctly across an onboarding session; orchestrator persists every section. | Yes (3–6 turns) |
| **4 — regression** | One case per shipped bug. Failing here means a refactor reopened a wound. | Mixed |

## Run it

```bash
cd backend_py
.venv/bin/python -m stackwealth.evals.cli run
```

Subset to one layer / tag / case:

```bash
# Layer 1 only — pure math, no LLM calls
.venv/bin/python -m stackwealth.evals.cli run --layer 1

# Only the Indian-numbers regression-prone cases
.venv/bin/python -m stackwealth.evals.cli run --tag regression-prone

# A specific case by id substring
.venv/bin/python -m stackwealth.evals.cli run --case crore_conversion
```

Skip the PDF when iterating quickly:

```bash
.venv/bin/python -m stackwealth.evals.cli run --no-pdf
```

The PDF lands at `/tmp/sw_evals_<ISO-timestamp>.pdf` by default; override with `--output-pdf`. CLI exits 0 only when every case passes, so it works as a CI gate.

## File layout

```
backend_py/evals/
├── core.py              EvalCase, Step, Judge, RunContext, RunResult, Runner
├── judges.py            ToolCalled, PlanFieldEquals, NumericEquals, ProseContains, …
├── fixtures.py          household builders (empty, Bengaluru 21yo, Mumbai 32yo, …)
├── cases/
│   ├── __init__.py      collects every CASES list into ALL_CASES
│   ├── skill_math.py    Layer 1
│   ├── tool_selection.py Layer 2
│   ├── e2e.py           Layer 3
│   └── regression.py    Layer 4
├── report.py            PDF + HTML report generator (Playwright)
├── cli.py               argparse entry point
└── README.md            ← you are here
```

## Authoring a case

Cases are plain `Case` dataclasses. The runner injects `household_id` into every step's args / kwargs automatically — don't thread it through.

```python
from ..core import Case, UserMessage
from ..fixtures import as_fixture, empty
from ..judges import ToolCalled

CASES = [
    Case(
        id="L2.my_case.short_handle",
        name="Human-readable one-line summary",
        layer=2,
        description=(
            "Long-form explanation. Goes into the per-case page of the PDF."
        ),
        tags=["my-feature", "regression-prone"],
        fixture=as_fixture(empty),
        steps=[
            UserMessage(text="hi", label="opening"),
        ],
        judges=[
            ToolCalled(tool_name="plan_set"),
        ],
    ),
]
```

Then add the module to `cases/__init__.py`'s star-import.

### Step types

- `SkillCall(skill, args, label?)` — call a skill function directly. Layer 1.
- `UserMessage(text, label?)` — run a full planner turn through the LangGraph agent. Layers 2 / 3 / 4.
- `ToolCall(tool_name, kwargs, label?)` — invoke an agent tool wrapper directly (bypasses the LLM, exercises the wrapper / persistence / coercion).

### Judges

- `ToolCalled(tool_name, arg_predicate?, predicate_label?)` — at least one matching call happened.
- `ToolNotCalled(tool_name)` — the forbidden tool stayed silent.
- `NoToolError()` — no tool_result carried `{"error": ...}`.
- `PlanFieldEquals(path, expected)` — `plan.X.Y.Z == expected` after the run.
- `PlanFieldSet(path)` — `plan.X.Y.Z` is not None.
- `ComputedPresent(field)` — `plan.computed.<field>` is populated (use after analytics tools).
- `NumericEquals(path, expected, tolerance, source)` — number at path within tolerance. `source="skill"` reads the last skill output; `source="plan"` reads the final PlanState.
- `ProseContains(needles)` / `ProseDoesNotContain(forbidden)` — case-insensitive substring assertions on the assistant's final text.

Custom judges are dataclasses with `name: str` and `check(ctx) -> JudgeResult`. Drop them in `judges.py` once they earn their keep.

## When a case fails

The PDF's per-case page shows the steps, the judge breakdown with expected/actual values, the full tool-call trace (args + result paired by tool_call_id), and the assistant's final text. That's almost always enough to diagnose without re-running the chat.

The terminal output points at the failing judges with one-line summaries — useful for CI logs.

## Not (yet) implemented

- **Layer 4 prod-trace replay via Langfuse Datasets**. Not enough prod volume to make it meaningful yet. When we have it, the runner gets a `--from-langfuse-dataset DATASET_ID` flag and pulls real turns from Langfuse to replay.
- **LLM-as-judge for prose quality**. The `ProseContains` / `ProseDoesNotContain` substring judges are a stepping stone. Add a `ProseLLMJudge` (Claude with a graded rubric) once the simpler judges stop catching everything we care about.
- **Cost / latency reporting per layer**. Today the PDF shows duration; a future iteration tracks Anthropic token usage per case so we can spot prompt bloat.
