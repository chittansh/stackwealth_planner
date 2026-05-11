"""
Concrete judges. Each one is a dataclass with `name` and a `check(ctx)`
returning a `JudgeResult`. Compose freely on a case's `judges` list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .core import JudgeResult, RunContext


# ── Helpers ────────────────────────────────────────────────────────────────


def _get_path(obj: Any, path: str) -> Any:
    """Walk a dotted path through dicts / lists / pydantic-dumped trees.
    Returns None if any segment is missing."""
    cur = obj
    for seg in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(seg)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            cur = getattr(cur, seg, None)
    return cur


# ── Tool-call judges ───────────────────────────────────────────────────────


@dataclass
class ToolCalled:
    """At least one tool call matched `tool_name` (and optional arg predicate)."""
    tool_name: str
    arg_predicate: Optional[Callable[[dict[str, Any]], bool]] = None
    predicate_label: str = ""

    @property
    def name(self) -> str:
        return f"ToolCalled({self.tool_name})"

    def check(self, ctx: RunContext) -> JudgeResult:
        matching = [c for c in ctx.tool_calls if c.name == self.tool_name]
        if not matching:
            return JudgeResult(
                ok=False,
                judge_name=self.name,
                description=f"Tool `{self.tool_name}` must be called at least once",
                expected=self.tool_name,
                actual=[c.name for c in ctx.tool_calls] or "no tool calls",
                message="Tool was never called.",
            )
        if self.arg_predicate is None:
            return JudgeResult(
                ok=True,
                judge_name=self.name,
                description=f"Tool `{self.tool_name}` called",
                expected=self.tool_name,
                actual=[c.name for c in matching],
            )
        for c in matching:
            if self.arg_predicate(c.args):
                return JudgeResult(
                    ok=True,
                    judge_name=self.name,
                    description=f"Tool `{self.tool_name}` called with matching args: {self.predicate_label}",
                    expected=self.predicate_label or "predicate",
                    actual=c.args,
                )
        return JudgeResult(
            ok=False,
            judge_name=self.name,
            description=f"Tool `{self.tool_name}` called but no invocation matched the arg predicate ({self.predicate_label})",
            expected=self.predicate_label or "predicate",
            actual=[c.args for c in matching],
            message="No tool_call args satisfied the predicate.",
        )


@dataclass
class ToolNotCalled:
    """Asserts a specific tool was NEVER called."""
    tool_name: str

    @property
    def name(self) -> str:
        return f"ToolNotCalled({self.tool_name})"

    def check(self, ctx: RunContext) -> JudgeResult:
        hits = [c for c in ctx.tool_calls if c.name == self.tool_name]
        return JudgeResult(
            ok=len(hits) == 0,
            judge_name=self.name,
            description=f"Tool `{self.tool_name}` must NOT be called",
            expected="(no calls)",
            actual=[c.args for c in hits] if hits else "(no calls)",
            message=f"Forbidden tool was called {len(hits)} time(s)." if hits else "",
        )


@dataclass
class NoToolError:
    """Asserts no tool returned an `error` field."""

    @property
    def name(self) -> str:
        return "NoToolError"

    def check(self, ctx: RunContext) -> JudgeResult:
        errors = [
            (r.name, r.result)
            for r in ctx.tool_results
            if isinstance(r.result, dict) and r.result.get("error")
        ]
        return JudgeResult(
            ok=not errors,
            judge_name=self.name,
            description="No tool_result carried an `error` field",
            expected="(no tool errors)",
            actual=errors or "(no tool errors)",
            message=f"{len(errors)} tool error(s) surfaced." if errors else "",
        )


# ── PlanState judges ───────────────────────────────────────────────────────


@dataclass
class PlanFieldEquals:
    """The final PlanState's value at `path` equals `expected` exactly."""
    path: str
    expected: Any

    @property
    def name(self) -> str:
        return f"PlanFieldEquals({self.path})"

    def check(self, ctx: RunContext) -> JudgeResult:
        actual = _get_path(ctx.plan_after, self.path)
        return JudgeResult(
            ok=actual == self.expected,
            judge_name=self.name,
            description=f"`plan.{self.path}` must equal {self.expected!r}",
            expected=self.expected,
            actual=actual,
        )


@dataclass
class PlanFieldSet:
    """The final PlanState's value at `path` is not None."""
    path: str

    @property
    def name(self) -> str:
        return f"PlanFieldSet({self.path})"

    def check(self, ctx: RunContext) -> JudgeResult:
        actual = _get_path(ctx.plan_after, self.path)
        return JudgeResult(
            ok=actual is not None,
            judge_name=self.name,
            description=f"`plan.{self.path}` must be set",
            expected="(not None)",
            actual=actual,
        )


@dataclass
class ComputedPresent:
    """`plan.computed.<field>` is populated. Used to verify persistence."""
    field: str

    @property
    def name(self) -> str:
        return f"ComputedPresent({self.field})"

    def check(self, ctx: RunContext) -> JudgeResult:
        value = (ctx.plan_after.get("computed") or {}).get(self.field)
        return JudgeResult(
            ok=value is not None,
            judge_name=self.name,
            description=f"`plan.computed.{self.field}` must be populated after the run",
            expected="(populated)",
            actual="(populated)" if value is not None else None,
        )


# ── Numeric judges ─────────────────────────────────────────────────────────


@dataclass
class NumericEquals:
    """Value at `path` (in last skill output OR plan_after) is within tolerance."""
    path: str
    expected: float
    tolerance: float = 0.5
    source: str = "skill"  # "skill" or "plan"

    @property
    def name(self) -> str:
        return f"NumericEquals({self.path}, ±{self.tolerance})"

    def check(self, ctx: RunContext) -> JudgeResult:
        if self.source == "skill":
            obj = ctx.skill_outputs[-1] if ctx.skill_outputs else None
            if hasattr(obj, "model_dump"):
                obj = obj.model_dump()
        else:
            obj = ctx.plan_after
        actual = _get_path(obj, self.path)
        try:
            ok = actual is not None and abs(float(actual) - self.expected) <= self.tolerance
        except (TypeError, ValueError):
            ok = False
        return JudgeResult(
            ok=ok,
            judge_name=self.name,
            description=f"`{self.source}.{self.path}` must be within ±{self.tolerance} of {self.expected}",
            expected=self.expected,
            actual=actual,
        )


# ── Prose judges ───────────────────────────────────────────────────────────


@dataclass
class ProseContains:
    """The concatenated assistant text contains every needle (case-insensitive)."""
    needles: list[str]
    description_override: str = ""

    @property
    def name(self) -> str:
        return f"ProseContains({', '.join(self.needles)})"

    def check(self, ctx: RunContext) -> JudgeResult:
        text = "\n".join(ctx.assistant_texts).lower()
        missing = [n for n in self.needles if n.lower() not in text]
        return JudgeResult(
            ok=not missing,
            judge_name=self.name,
            description=self.description_override or f"Assistant prose must mention: {self.needles}",
            expected=self.needles,
            actual=text[:300] + ("…" if len(text) > 300 else ""),
            message=f"Missing: {missing}" if missing else "",
        )


@dataclass
class ProseDoesNotContain:
    """The assistant text avoids every forbidden token (case-insensitive).
    Useful for the `«unverified:N»` validator regression and tone checks."""
    forbidden: list[str]
    description_override: str = ""

    @property
    def name(self) -> str:
        return f"ProseDoesNotContain({', '.join(self.forbidden)})"

    def check(self, ctx: RunContext) -> JudgeResult:
        text = "\n".join(ctx.assistant_texts).lower()
        hits = [f for f in self.forbidden if f.lower() in text]
        return JudgeResult(
            ok=not hits,
            judge_name=self.name,
            description=self.description_override or f"Assistant prose must NOT mention: {self.forbidden}",
            expected="(absent)",
            actual=hits or "(absent)",
            message=f"Forbidden tokens found: {hits}" if hits else "",
        )
