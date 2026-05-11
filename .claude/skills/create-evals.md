---
name: create-evals
description: Author a complete agent eval suite for a project from scratch — four-layer architecture (deterministic math, single-turn agent, multi-turn flows, regression cases), a Python runner with per-case streaming progress and per-turn timeouts, and a Playwright-rendered PDF report. Use when starting evals on an agent / RAG / LLM-driven pipeline that has none, or when migrating from ad-hoc tests. Adaptable across Python/TS/etc projects.
---

# create-evals — Agent eval suites with PDF reports

This is a procedure for authoring an end-to-end eval suite for an AI agent in any project, not just StackWealth Planner. Run it whenever a project needs evals and the existing test coverage is ad-hoc or absent.

The goal is the same every time:

- **Four layers** of cases — deterministic math, single-turn agent, multi-turn flows, regression
- **A runner** that captures every tool call and assertion, with **streaming progress** + **per-turn timeout**
- **A PDF report** with one detail page per case (judge breakdown, tool-call trace, assistant text)
- **A CLI** that exits 0 iff every case passes, so it works as a CI gate
- **At least 5 cases per layer** at first ship — quality over quantity

The shape of the runtime depends on the project (Python / TS / etc.) but the conceptual layers and the lessons-learned (below) are constant.

---

## Procedure

**Do not write code in Phase 1.** Confirm the proposed shape with the user before generating files.

### Phase 1 — Discovery

Read the project to understand what you're evaling.

1. **What is the agent?** Chat agent, RAG pipeline, code assistant, classifier, multi-step orchestrator? The shape of the eval differs.
2. **Map the surface area:**
   - Tools / functions the agent can call (LangChain `StructuredTool`, OpenAI function-calling, JSON-output, etc.)
   - State the agent mutates (in-memory dict, Postgres, vector store, file outputs)
   - Deterministic skills/helpers that tools dispatch to (where the pure math lives)
   - HTTP endpoints exposed, if any
3. **Read the existing tests:** what do they assert on? What gaps are obvious?
4. **Find the recent bug list.** `git log --oneline` for the last 50 commits, look for `fix:` and `revert:`. Each shipped fix becomes a candidate Layer 4 regression case.
5. **Trace one real conversation end-to-end** — read the agent's main loop and one chat handler. Identify where you can intercept tool-call events.
6. **Confirm runtime details:**
   - Python / TS / other
   - Async vs sync agent loop
   - Where secrets live (env vars / `.env`)
   - Whether the project has a PDF dependency already (Playwright? weasyprint? wkhtmltopdf?) — reuse it for the report

**Output of Phase 1** (a message to the user, no code yet):

- Proposed layer mapping with 2-3 candidate cases per layer, derived from THIS project's actual surface
- Directory layout
- "Minimum viable" case count (≈15) and "comprehensive" (≈30+)
- A list of recent bugs and which become Layer 4 regression cases

Wait for the user to confirm or redirect before scaffolding.

---

### Phase 2 — Scaffold

Generate the eval directory. Keep it small and self-contained; do not pull in heavy test frameworks (pytest works, but the suite needs to be runnable as a CLI too).

For a Python project, target:

```
<project>/<package>/evals/
├── README.md              How to run + how to add cases
├── __init__.py
├── core.py                Case, Step, Judge, RunContext, RunResult, EvalRun, Runner
├── judges.py              ToolCalled, NoToolError, FieldEquals, NumericEquals, ProseContains, …
├── fixtures.py            Starting-state builders (with composition helpers like `with_risk_set`)
├── cases/
│   ├── __init__.py        Re-exports every layer's CASES list into ALL_CASES
│   ├── skill_math.py      Layer 1 (no LLM)
│   ├── tool_selection.py  Layer 2 (single-turn agent)
│   ├── e2e.py             Layer 3 (multi-turn flows) — see also `conversations.py` once richer
│   └── regression.py      Layer 4 (one case per shipped bug)
├── report.py              HTML → PDF render (Playwright by default)
└── cli.py                 `python -m <package>.evals.cli run [--layer N] [--tag X] [--case ID]`
```

**Core data model** (use dataclasses; same shape in every project):

```python
@dataclass
class Case:
    id: str          # e.g. "L3.conv.bengaluru_21yo_onboarding"
    name: str        # human-readable
    layer: int       # 1..4
    description: str # appears on the PDF detail page
    fixture: Callable[[str], Awaitable[State]]   # produces starting state from session id
    steps: list[Step]                            # SkillCall | UserMessage | ToolCall
    judges: list[Judge]                          # assertions
    tags: list[str]                              # for filtering

@dataclass
class JudgeResult:
    ok: bool
    judge_name: str
    description: str
    expected: Any
    actual: Any
    message: str
```

**Three step types** are enough for most agents:

| Step | When to use |
|---|---|
| `SkillCall(func, args)` | Layer 1 — invoke a deterministic function directly, no LLM |
| `UserMessage(text)`     | Layers 2 / 3 / 4 — run a full agent turn, capture all tool-call events |
| `ToolCall(name, kwargs)`| Bypass the LLM and exercise the tool wrapper directly (good for testing persistence / arg coercion / regression of wrappers) |

The runner injects the session id (`household_id` / `thread_id` / whatever) into every step automatically so cases don't thread it through.

---

### Phase 3 — Author judges that are stable, not brittle

The single most common failure mode of a hand-rolled eval suite is **judges that are too strict** — they fail on agent behavior that's actually correct. From the StackWealth run:

- `ToolCalled("risk_assess")` failed in 5 cases because the agent called `run_full_analysis` (the orchestrator) which subsumed `risk_assess` internally. The user got the right outcome; the judge demanded the wrong proof.
- `NoToolError()` failed in 2 cases because the agent fired `scenario_diff` early with an unknown id, got `{"error": "scenario_not_found"}`, then immediately retried with the right id. Recoverable error → eval false positive.

**Default judges to ship** (concrete classes in `judges.py`):

| Judge | What it checks | Notes / pitfalls |
|---|---|---|
| `ToolCalled(name, arg_predicate?)` | At least one tool_call event matched | If the agent has an orchestrator tool that subsumes this one, accept either via `ToolCalledOrSubsumed(name, subsumers=["run_full_analysis"])` |
| `ToolNotCalled(name)` | Forbidden tool stayed silent | |
| `NoToolError()` | No tool_result carried `.error` | **Make this lenient by default** — accept errors that were followed by a successful retry of the same tool. Provide a strict `NoFatalToolError` variant for cases that explicitly forbid any error. |
| `FieldEquals(path, expected)` | Exact equality at dotted path | |
| `FieldSet(path)` | Not None at dotted path | Most stable assertion; prefer over FieldEquals when LLM may format the value |
| `ComputedPresent(field)` | `state.computed.<field>` populated | For agents that run analytics & cache results |
| `NumericEquals(path, expected, tolerance)` | Within ±tolerance at path | Pin to *current code behavior*, not docs (so divergence is caught) |
| `ProseContains(needles)` | Final assistant text contains all needles (case-insensitive) | Use sparingly; LLM phrasing drifts |
| `ProseDoesNotContain(forbidden)` | Final text avoids each token | Best for validator/tone regression (no «unverified», no slang/emoji) |

**Anti-patterns to avoid:**

- ❌ Exact-match prose assertions for LLM output
- ❌ Asserting that a *specific* tool was called when an *equivalent* orchestrator path exists (use the subsumes variant)
- ❌ `NoToolError` without recovery awareness
- ❌ One huge case with 20 judges — favor 5 small judges per case across more cases
- ❌ Pinning expected values to documentation. Pin to actual code output (`.venv/bin/python -c "..."` to capture) and write a comment explaining the math

**Pro tip:** every time an eval fails as a *false positive* during early development, the fix is *almost always to widen the judge*, not to relax the agent. Don't make the agent pass the eval — make the eval pass the agent correctly.

---

### Phase 4 — Author cases by layer

#### Layer 1 — Skill math (cheap, no LLM)

Pick the deterministic functions (scoring, ranking, math, tax/risk/allocation logic) the project exposes. For each:

1. Seed a known state via fixture
2. `SkillCall(fn, args)` the deterministic function
3. Assert with `NumericEquals` / `FieldEquals` on output

Pin reference numbers to *current* code output, not docs. Run the function once locally, copy the numbers, write a comment explaining the math. If the math drifts, the test catches it.

**Aim for 4-6 cases.** Goal is coverage of every formula in the spec.

#### Layer 2 — Single-turn tool selection (one LLM call per case)

For each *prompt rule* the project depends on, write a single-turn case:

- User sends ONE message
- Assert on the emitted tool calls (`ToolCalled(name, arg_predicate=lambda a: ...)`)
- Bonus: `ProseDoesNotContain(["«unverified", emojis, slang])` for validator/tone rules

**Aim for 5-10 cases.** Each one pins a specific prompt rule:
- "₹2.5 Cr → 25,000,000" (Indian number conversion)
- "When user gives only age, agent asks for full DOB"
- "When user asks for X, agent picks orchestrator over manual chain"
- "Casual user → agent stays professional"

#### Layer 3 — Multi-turn flows (10-15 turns per case)

This is where you exercise *state evolution*, recall, the canonical-order tool sequence. Split into flow families:

- **Onboarding** (5 cases) — empty plan → risk-quizzed plan, different personas
- **Mid-funnel analytics** (5 cases) — pre-seeded plan, risk quiz, scenario_pin, scenario_diff
- **Edge cases** (5 cases) — number-format stress, tone, validator hygiene, gate avoidance, mismatch resolution
- **Full advisor flows** (5 cases) — onboarding → analysis → scenarios → PDF link

Judges should lean on stable signals:
- `FieldSet(path)` for top-level data captured
- `ComputedPresent(field)` for analytics run
- `ToolCalled(name)` for canonical tools
- `ToolCalledOrSubsumed(name, subsumers=[...])` for tools that may be reached via orchestrator
- `NoToolError()` with recovery awareness
- `ProseDoesNotContain(["«unverified"])` for validator hygiene

Anti-pattern: writing 20 conversations in one batch. Write 5, run them, see what flakes, iterate.

#### Layer 4 — Regression cases (one per shipped bug)

Walk `git log` and find every `fix:` commit. For each:

- One case that exercises the bug's trigger
- Should have failed against the *old* code, passes against the *new* code
- Description includes a pointer to the commit / PR
- Tag with `regression-prone`

Once the regression suite covers your past bug list, future refactors that reopen those wounds get caught immediately.

---

### Phase 5 — Runtime hardening

Lessons that bit us in production runs and should be baked into every eval suite by default:

#### 1. Per-turn timeout

The Anthropic SDK (and most LLM SDKs) can silently hang on a dropped TCP connection for ~10 minutes per call. One bad network event mid-run kills the whole budget. Wrap every agent turn:

```python
DEFAULT_TURN_TIMEOUT_SECONDS = float(os.environ.get("EVAL_TURN_TIMEOUT", "240"))

async def _run_chat(self, step, household_id, t0):
    ...
    try:
        await asyncio.wait_for(_drain(), timeout=self.turn_timeout)
    except asyncio.TimeoutError:
        record.error = f"turn timed out after {self.turn_timeout:.0f}s"
```

Default 240s is generous for a multi-tool turn but kills a stuck call before it dominates the run.

#### 2. Streaming per-case progress

A 40-minute run with zero output is unusable — you can't tell if it's progressing or stuck. The CLI must print one line per case as it lands:

```python
def _on_progress(result, idx, total):
    mark = "✓" if result.passed else "✗"
    line = f"  [{idx:>2}/{total}] L{result.case.layer} [{mark}] {result.case.id:<46} {result.duration_seconds:>6.2f}s"
    if not result.passed:
        failed = ", ".join(jr.judge_name for jr in result.failed_judges)
        line += f"  ↳ {failed[:80]}"
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
```

Pass it to `Runner(on_progress=...)`. Run the CLI with `python -u` for unbuffered output.

#### 3. Dotenv autoload in the CLI

If the project's server normally loads `.env` via uvicorn `--env-file`, the eval CLI runs as a separate process and won't see it. Add a `_load_dotenv()` helper at the top of `cli.py` that loads `<project>/.env` before any module that reads `config.X` is imported.

#### 4. Silence prod telemetry during evals

Pop any Langfuse / LangSmith / Sentry keys before running so synthetic traffic doesn't pollute prod traces:

```python
def __init__(self, ...):
    os.environ.setdefault("LANGFUSE_DISABLED_FOR_EVALS", "1")
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
```

#### 5. Auto-inject session id

Cases should never have to thread `household_id` (or `thread_id` / `user_id` / whatever) through every step's args. The runner generates a fresh one per case and injects it into every `SkillCall.args`, `ToolCall.kwargs`, and `UserMessage` execution. Cases stay terse.

#### 6. Each case gets a fresh session

No cross-case contamination. Generate `f"eval_{case.id}_{uuid4().hex[:6]}"` per case and use that as the session/household id. The in-memory store (or test database) is keyed by it.

---

### Phase 6 — PDF report

The PDF is what makes evals usable for non-engineers (reviewers, PMs, leadership). It should have:

- **Cover** — run metadata, headline pass-rate scoreboard with bars per layer
- **Summary page** — failures table (case id, name, failed judges), slowest cases, reading guide
- **One detail page per case** with:
  - Header pill (pass/fail) + layer pill + tags
  - Description + duration
  - Steps table (what the runner did)
  - Judges table (status, judge name, description, expected, actual)
  - Tool-call trace (one row per emitted tool call with args + paired result)
  - Assistant text blocks (final reply per turn, in `<pre>` boxes)

Render with the same PDF stack the project already uses. For most LLM apps that's **Playwright Chromium**: HTML → `page.set_content(html)` → `page.pdf(format='A4')`. Fallback to returning HTML if Playwright isn't installed.

The CLI accepts `--output-pdf PATH` and `--output-html PATH`. Default location: `/tmp/<project>_evals_<ISO-timestamp>.pdf`.

---

### Phase 7 — Iterate

Run the suite. Categorize failures:

1. **Expected number off** — pin to actual computed value, update expected. Comment with the math.
2. **Brittle judge** (most common in first 3 runs) — widen the judge. Common cases:
   - `ToolCalled(X)` failing because agent used orchestrator → use `ToolCalledOrSubsumed`
   - `NoToolError` failing on recovered errors → use recovery-aware variant
   - `ProseContains` failing on phrasing drift → switch to tool-call assertion
3. **Real agent regression** — fix the prompt or code, then add a Layer 4 regression case so the fix is permanent.

After every "real regression" fix, **add a regression case before pushing.** Living documentation of "things that broke."

---

## CLI surface

Once the suite exists, the CLI shape is the same across projects:

```bash
# Full suite + PDF
python -u -m <package>.evals.cli run

# Subset for fast iteration
python -m <package>.evals.cli run --layer 1 --no-pdf        # math only, no LLM
python -m <package>.evals.cli run --tag regression-prone     # only flagged cases
python -m <package>.evals.cli run --case crore_conversion    # one case by id substring

# Discovery
python -m <package>.evals.cli list
```

`--output-pdf` and `--output-html` for custom paths. Exit code 0 iff every case passed.

---

## Common project adaptations

- **TS/Node agent (LangGraph.js, Mastra, Vercel AI SDK):** mirror the same dataclass model in TypeScript. Use `tsx` to run the CLI. Use Puppeteer or Playwright for PDF.
- **RAG pipeline (retrieve + answer):** Layer 1 = retrieval recall/MRR on a frozen golden set; Layer 2 = single-question accuracy with citation assertions; Layer 3 = multi-turn with follow-up questions exercising context retention.
- **Classifier / structured output:** Layer 1 dominates — golden set with confusion matrix. Layer 2/3 may be small or absent.
- **Code assistant:** Layer 1 = static analysis on generated code (parses? typechecks?). Layer 2 = single-prompt → diff matches expected pattern. Layer 3 = multi-turn debugging session.

In all cases, **the four-layer structure and the runtime hardening (timeout, streaming, dotenv, fresh session) are constant.**

---

## Quick-start for a new project

Once Phase 1 is confirmed:

1. Generate `<project>/<package>/evals/` with all 8 files
2. Author 4 Layer 1 cases (run them — should pass instantly, ~0.1s each)
3. Author 3 Layer 2 cases (each takes ~10s)
4. Author 2 Layer 3 cases of 4-6 turns each (each ~60s)
5. Author 1 Layer 4 case for the most recent shipped bug
6. Run full suite, fix flaky judges
7. Author 15 more conversations gradually (10-15 turns each, mix personas + flows)
8. Run again, iterate, ship

First Layer-1 + Layer-2 pass takes ~half a day. The Layer-3 conversation set is where most of the time goes — budget a day for 20 cases authored + iterated.

---

## What to tell the user at the end

After the suite is shipped and the first run is green-ish, summarize:

- Total cases by layer
- Pass rate
- Wall-time + estimated API cost per run
- Top 3 false-positive patterns surfaced (and how the judges were widened)
- Top 3 real bugs surfaced (and their fixes / open issues)
- A pointer to the PDF and how to run again

That summary becomes the project's eval-suite README onboarding paragraph.
