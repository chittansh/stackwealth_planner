"""
Core eval abstractions.

A `Case` is a declarative test: fixture → steps → judges. The runner executes
the steps, collecting tool calls / tool results / final assistant text / final
PlanState into a `RunContext` that every judge inspects. Judges return
`JudgeResult` (ok/expected/actual/message). The runner aggregates everything
into a `RunResult` per case and an `EvalRun` for the whole batch.

Design notes:

- Cases are plain dataclasses, not subclasses. Keeps the test list scannable
  and discoverable — `grep -rn "Case(" backend_py/evals/cases/` lists every
  case in the suite.
- Steps are tagged unions (SkillCall, UserMessage, ToolCall). The runner
  dispatches each in `_execute_step`.
- Langfuse is silenced during evals so we don't pollute the prod trace tree.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal, Optional, Protocol

from ..db import get_plan, save_plan
from ..types import PlanState


# Per-turn wall-clock budget. The Anthropic SDK can silently hang on a
# dropped TCP read for ~10 minutes — without this guard a single bad
# connection wastes most of an eval run. 240s is generous for a multi-tool
# turn but kills a stuck call before it dominates the budget.
DEFAULT_TURN_TIMEOUT_SECONDS = float(os.environ.get("EVAL_TURN_TIMEOUT", "240"))


Layer = Literal[1, 2, 3, 4]


# ── Steps ──────────────────────────────────────────────────────────────────


@dataclass
class SkillCall:
    """Invoke a skill function directly (no LLM). Layer 1."""
    skill: Callable[..., Awaitable[Any]]
    args: dict[str, Any]
    label: str = ""


@dataclass
class UserMessage:
    """Send a chat message and run a planner turn. Captures every tool_call
    and tool_result event plus the final assistant text. Layer 2 / 3 / 4."""
    text: str
    label: str = ""


@dataclass
class ToolCall:
    """Invoke an agent tool wrapper directly (bypass LLM). Useful when the
    case wants to assert on persistence/coercion semantics without LLM
    flakiness."""
    tool_name: str
    kwargs: dict[str, Any]
    label: str = ""


Step = SkillCall | UserMessage | ToolCall


# ── Judges ─────────────────────────────────────────────────────────────────


@dataclass
class JudgeResult:
    ok: bool
    judge_name: str
    description: str
    expected: Any = None
    actual: Any = None
    message: str = ""


class Judge(Protocol):
    """A judge inspects a `RunContext` and emits one `JudgeResult`."""
    name: str

    def check(self, ctx: "RunContext") -> JudgeResult:  # pragma: no cover - protocol
        ...


# ── Run-time context ───────────────────────────────────────────────────────


@dataclass
class ToolCallEvent:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolResultEvent:
    id: str
    name: str
    result: Any


@dataclass
class StepRecord:
    """One row of the step log — what we did and what came back."""
    label: str
    kind: Literal["skill", "user", "tool"]
    duration_seconds: float
    tool_calls: list[ToolCallEvent] = field(default_factory=list)
    tool_results: list[ToolResultEvent] = field(default_factory=list)
    assistant_text: str = ""
    skill_output: Any = None
    error: Optional[str] = None


@dataclass
class RunContext:
    """Everything a judge needs to make a decision.

    `tool_calls` / `tool_results` / `assistant_texts` are flat aggregates
    across all steps; `step_records` preserves per-step ordering when a case
    has multiple turns. Judges should prefer the aggregates unless they
    explicitly care about ordering."""
    household_id: str
    plan_before: dict[str, Any]
    plan_after: dict[str, Any]
    step_records: list[StepRecord] = field(default_factory=list)
    tool_calls: list[ToolCallEvent] = field(default_factory=list)
    tool_results: list[ToolResultEvent] = field(default_factory=list)
    assistant_texts: list[str] = field(default_factory=list)
    skill_outputs: list[Any] = field(default_factory=list)


# ── Case ───────────────────────────────────────────────────────────────────


@dataclass
class Case:
    """A single eval case."""
    id: str
    name: str
    layer: Layer
    description: str
    fixture: Callable[[str], Awaitable[PlanState]]
    steps: list[Step]
    judges: list[Judge]
    tags: list[str] = field(default_factory=list)


# ── Result types ───────────────────────────────────────────────────────────


@dataclass
class RunResult:
    case: Case
    passed: bool
    duration_seconds: float
    judge_results: list[JudgeResult]
    ctx: Optional[RunContext]
    error: Optional[str] = None

    @property
    def failed_judges(self) -> list[JudgeResult]:
        return [j for j in self.judge_results if not j.ok]


@dataclass
class EvalRun:
    started_at: datetime
    finished_at: datetime
    model: str
    results: list[RunResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    def by_layer(self) -> dict[int, list[RunResult]]:
        out: dict[int, list[RunResult]] = {1: [], 2: [], 3: [], 4: []}
        for r in self.results:
            out[r.case.layer].append(r)
        return out


# ── Runner ─────────────────────────────────────────────────────────────────


class Runner:
    """Executes cases. Captures every tool_call / tool_result event by
    iterating the planner turn's async generator (the same shape `api/chat`
    consumes in prod)."""

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        turn_timeout: float = DEFAULT_TURN_TIMEOUT_SECONDS,
        on_progress: Optional[Callable[[RunResult, int, int], None]] = None,
    ) -> None:
        # Silence Langfuse during evals — no need to pollute the prod trace
        # tree with synthetic test traffic.
        os.environ.setdefault("LANGFUSE_DISABLED_FOR_EVALS", "1")
        os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
        os.environ.pop("LANGFUSE_SECRET_KEY", None)
        self.model = model or os.environ.get("PLANNER_MODEL") or "claude-sonnet-4-6"
        self.turn_timeout = turn_timeout
        self.on_progress = on_progress

    async def run_one(self, case: Case) -> RunResult:
        # Each case gets a fresh household so there's no cross-case contamination.
        household_id = f"eval_{case.id}_{uuid.uuid4().hex[:6]}"
        t0 = time.perf_counter()
        try:
            plan = await case.fixture(household_id)
            await save_plan(plan)
            plan_before = (await get_plan(household_id)).model_dump(mode="python")  # type: ignore[union-attr]

            ctx = RunContext(
                household_id=household_id,
                plan_before=plan_before,
                plan_after=plan_before,
            )

            for step in case.steps:
                record = await self._execute_step(step, household_id, ctx)
                ctx.step_records.append(record)
                ctx.tool_calls.extend(record.tool_calls)
                ctx.tool_results.extend(record.tool_results)
                if record.assistant_text:
                    ctx.assistant_texts.append(record.assistant_text)
                if record.skill_output is not None:
                    ctx.skill_outputs.append(record.skill_output)

            plan_after = await get_plan(household_id)
            ctx.plan_after = plan_after.model_dump(mode="python") if plan_after else plan_before

            judge_results = [j.check(ctx) for j in case.judges]
            passed = all(jr.ok for jr in judge_results)

            return RunResult(
                case=case,
                passed=passed,
                duration_seconds=time.perf_counter() - t0,
                judge_results=judge_results,
                ctx=ctx,
            )
        except Exception as e:
            return RunResult(
                case=case,
                passed=False,
                duration_seconds=time.perf_counter() - t0,
                judge_results=[],
                ctx=None,
                error=f"{type(e).__name__}: {e}",
            )

    async def run_many(self, cases: list[Case]) -> EvalRun:
        started = datetime.now(timezone.utc)
        results: list[RunResult] = []
        total = len(cases)
        for idx, case in enumerate(cases, 1):
            result = await self.run_one(case)
            results.append(result)
            if self.on_progress is not None:
                try:
                    self.on_progress(result, idx, total)
                except Exception:
                    # Progress callbacks are advisory — never let one fail
                    # the run.
                    pass
        finished = datetime.now(timezone.utc)
        return EvalRun(
            started_at=started, finished_at=finished, model=self.model, results=results
        )

    # ── Step dispatch ──────────────────────────────────────────────────────

    async def _execute_step(
        self, step: Step, household_id: str, ctx: RunContext
    ) -> StepRecord:
        t0 = time.perf_counter()
        if isinstance(step, SkillCall):
            return await self._run_skill(step, t0, household_id)
        if isinstance(step, UserMessage):
            return await self._run_chat(step, household_id, t0)
        if isinstance(step, ToolCall):
            return await self._run_tool(step, t0, household_id)
        raise TypeError(f"Unknown step type: {type(step)}")

    async def _run_skill(self, step: SkillCall, t0: float, household_id: str) -> StepRecord:
        # Inject household_id automatically so cases don't need to thread it
        # through every step's args.
        args = {**step.args, "household_id": household_id}
        try:
            output = await step.skill(args)
            return StepRecord(
                label=step.label or step.skill.__name__,
                kind="skill",
                duration_seconds=time.perf_counter() - t0,
                skill_output=output,
            )
        except Exception as e:
            return StepRecord(
                label=step.label or step.skill.__name__,
                kind="skill",
                duration_seconds=time.perf_counter() - t0,
                error=f"{type(e).__name__}: {e}",
            )

    async def _run_chat(
        self, step: UserMessage, household_id: str, t0: float
    ) -> StepRecord:
        from ..agent.planner import run_planner_turn

        record = StepRecord(
            label=step.label or step.text[:60],
            kind="user",
            duration_seconds=0,
        )

        async def _drain() -> None:
            async for ev in run_planner_turn(
                household_id=household_id, chat_id="eval", message=step.text
            ):
                kind = ev.get("event")
                data = ev.get("data")
                if kind == "tool_call":
                    record.tool_calls.append(
                        ToolCallEvent(
                            id=data.get("id", ""),
                            name=data.get("name", ""),
                            args=data.get("args") or {},
                        )
                    )
                elif kind == "tool_result":
                    record.tool_results.append(
                        ToolResultEvent(
                            id=data.get("id", ""),
                            name=data.get("name", ""),
                            result=data.get("result"),
                        )
                    )
                elif kind == "_final_text":
                    record.assistant_text = data or ""
                elif kind == "error":
                    record.error = (data or {}).get("message", "error")

        try:
            await asyncio.wait_for(_drain(), timeout=self.turn_timeout)
            record.duration_seconds = time.perf_counter() - t0
            return record
        except asyncio.TimeoutError:
            record.error = f"turn timed out after {self.turn_timeout:.0f}s"
            record.duration_seconds = time.perf_counter() - t0
            return record
        except Exception as e:
            record.error = f"{type(e).__name__}: {e}"
            record.duration_seconds = time.perf_counter() - t0
            return record

    async def _run_tool(self, step: ToolCall, t0: float, household_id: str) -> StepRecord:
        from ..agent.tools import make_tools

        tools = {t.name: t for t in make_tools()}
        tool = tools.get(step.tool_name)
        if tool is None:
            return StepRecord(
                label=step.label or step.tool_name,
                kind="tool",
                duration_seconds=time.perf_counter() - t0,
                error=f"tool not found: {step.tool_name}",
            )
        kwargs = {**step.kwargs, "household_id": household_id}
        try:
            result = await tool.coroutine(**kwargs)  # type: ignore[misc]
            return StepRecord(
                label=step.label or step.tool_name,
                kind="tool",
                duration_seconds=time.perf_counter() - t0,
                tool_results=[
                    ToolResultEvent(
                        id=f"direct-{uuid.uuid4().hex[:6]}",
                        name=step.tool_name,
                        result=result,
                    )
                ],
            )
        except Exception as e:
            return StepRecord(
                label=step.label or step.tool_name,
                kind="tool",
                duration_seconds=time.perf_counter() - t0,
                error=f"{type(e).__name__}: {e}",
            )
