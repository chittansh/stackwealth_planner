"""
PDF report generator for eval runs. Uses the same Playwright Chromium →
HTML-to-PDF stack as the main household report; the styling is tailored
for eval data — pass/fail bars, per-layer rollup, per-case detail pages
with tool-call traces and judge breakdowns.

Layout (one page per section unless content overflows):

    1. Cover         run metadata + headline pass rate + per-layer bars
    2. Summary       failure breakdown, slowest cases, judge hit/miss rollup
    3..N. Per-case   one page per case with input / expected / actual / trace
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from .core import EvalRun, JudgeResult, RunResult


# ── HTML helpers ───────────────────────────────────────────────────────────


def _h(s: Any) -> str:
    return html.escape(str(s)) if s is not None else "—"


def _trunc(s: Any, n: int = 220) -> str:
    text = str(s)
    return _h(text if len(text) <= n else text[:n] + "…")


def _json_block(value: Any, *, indent: int = 2, limit: int = 1200) -> str:
    try:
        s = json.dumps(value, default=str, indent=indent)
    except (TypeError, ValueError):
        s = str(value)
    if len(s) > limit:
        s = s[:limit] + f"\n… ({len(s) - limit} more chars)"
    return f'<pre class="code">{_h(s)}</pre>'


def _bar(numerator: int, denominator: int, *, kind: str = "pass") -> str:
    pct = (numerator / denominator * 100) if denominator else 0
    return (
        f'<div class="bar"><div class="bar-fill bar-{kind}" '
        f'style="width:{pct:.0f}%"></div></div>'
        f'<div class="bar-label">{numerator}/{denominator} · {pct:.0f}%</div>'
    )


# ── CSS ────────────────────────────────────────────────────────────────────


CSS = """
@page { size: A4; margin: 14mm 14mm 18mm 14mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: 'Helvetica Neue', Arial, sans-serif;
  color: #18181b;
  font-size: 10pt;
  line-height: 1.45;
}
.page { page-break-after: always; padding-bottom: 16mm; position: relative; }
.page:last-child { page-break-after: auto; }
h1 { font-size: 22pt; margin: 0 0 4mm; font-weight: 700; letter-spacing: -0.01em; }
h2 { font-size: 15pt; margin: 8mm 0 3mm; font-weight: 600; border-bottom: 1px solid #e4e4e7; padding-bottom: 1.5mm; }
h3 { font-size: 11pt; margin: 4mm 0 1.5mm; font-weight: 600; color: #27272a; text-transform: uppercase; letter-spacing: 0.04em; }
h4 { font-size: 10pt; margin: 3mm 0 1mm; font-weight: 600; color: #3f3f46; }
p { margin: 0 0 2mm; }
ul, ol { margin: 0 0 2mm 5mm; padding: 0; }
li { margin: 0 0 1mm; }
table { width: 100%; border-collapse: collapse; margin: 2mm 0 4mm; font-size: 9.5pt; }
th, td { padding: 1.5mm 2.5mm; border: 1px solid #e4e4e7; text-align: left; vertical-align: top; }
th { background: #fafafa; font-weight: 600; color: #3f3f46; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.muted { color: #71717a; font-size: 9pt; }
.code {
  background: #fafafa; border: 1px solid #e4e4e7; border-radius: 1.5mm;
  padding: 2mm 3mm; font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 8.5pt; line-height: 1.45; white-space: pre-wrap; word-break: break-word;
  margin: 1mm 0 2.5mm;
}
.pill { display: inline-block; padding: 0.4mm 2mm; border-radius: 1.5mm; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.02em; }
.pill-pass { background: #dcfce7; color: #166534; }
.pill-fail { background: #fee2e2; color: #991b1b; }
.pill-layer { background: #e0e7ff; color: #3730a3; margin-right: 1.5mm; }
.pill-tag { background: #f4f4f5; color: #52525b; margin-right: 1mm; }
.pill-skill { background: #f1f5f9; color: #334155; }
.pill-user { background: #fef3c7; color: #92400e; }
.pill-tool { background: #f0fdf4; color: #166534; }
.headline {
  background: #18181b; color: #fff; padding: 4mm 5mm; margin: 0 0 5mm;
  border-radius: 1.5mm;
}
.headline .brand { font-size: 9.5pt; color: #a1a1aa; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 1.5mm; }
.headline h1 { color: #fff; font-size: 20pt; }
.headline .sub { font-size: 11pt; color: #d4d4d8; }
.kbox { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 3mm; margin: 2mm 0 4mm; }
.kcell { background: #fafafa; padding: 3mm 4mm; border: 1px solid #e4e4e7; border-radius: 1.5mm; }
.kcell .label { font-size: 8.5pt; color: #71717a; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 1mm; }
.kcell .val { font-size: 14pt; font-weight: 700; color: #18181b; }
.kcell .note { font-size: 8.5pt; color: #52525b; margin-top: 1mm; }
.bar { width: 100%; height: 4mm; background: #f4f4f5; border-radius: 1mm; overflow: hidden; }
.bar-fill { height: 100%; }
.bar-pass { background: #16a34a; }
.bar-fail { background: #dc2626; }
.bar-label { font-size: 8.5pt; color: #52525b; margin-top: 1mm; }
.layer-row { display: grid; grid-template-columns: 80mm 1fr; gap: 5mm; align-items: center; margin: 2mm 0; }
.layer-row .lbl { font-size: 10pt; }
.case-header { display: flex; align-items: center; gap: 2mm; margin-bottom: 3mm; }
.case-header h2 { margin: 0; border: none; padding: 0; font-size: 13pt; flex: 1; }
.judge-row td { vertical-align: top; }
.judge-row .ok-cell { width: 18mm; }
.cover-meta { font-size: 9.5pt; color: #52525b; }
.cover-meta strong { color: #18181b; }
"""


# ── Cover ──────────────────────────────────────────────────────────────────


def _cover(run: EvalRun) -> str:
    by_layer = run.by_layer()
    layer_rows = []
    for layer in (1, 2, 3, 4):
        results = by_layer.get(layer, [])
        if not results:
            continue
        passed = sum(1 for r in results if r.passed)
        layer_rows.append(
            f'<div class="layer-row">'
            f'<div class="lbl"><span class="pill pill-layer">L{layer}</span>'
            f'{_layer_label(layer)}</div>'
            f'<div>{_bar(passed, len(results), kind="pass" if passed == len(results) else "fail")}</div>'
            f'</div>'
        )
    overall_kind = "pass" if run.failed == 0 else "fail"
    return f"""<section class="page">
  <div class="headline">
    <div class="brand">StackWealth Planner · Agent Eval</div>
    <h1>Run Report</h1>
    <div class="sub">{run.passed} passed · {run.failed} failed · {run.pass_rate * 100:.0f}% pass rate</div>
  </div>
  <p class="cover-meta">
    <strong>Started:</strong> {run.started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}
    &nbsp;·&nbsp; <strong>Duration:</strong> {run.duration_seconds:.1f}s
    &nbsp;·&nbsp; <strong>Model:</strong> {_h(run.model)}
    &nbsp;·&nbsp; <strong>Cases:</strong> {run.total}
  </p>

  <h2>Headline</h2>
  <div class="kbox">
    <div class="kcell"><div class="label">Overall</div><div class="val">{run.pass_rate * 100:.0f}%</div><div class="note">{run.passed} / {run.total} cases passed</div></div>
    <div class="kcell"><div class="label">Failures</div><div class="val">{run.failed}</div><div class="note">{('All clear.' if run.failed == 0 else 'See per-case detail.')}</div></div>
    <div class="kcell"><div class="label">Avg duration</div><div class="val">{(sum(r.duration_seconds for r in run.results) / run.total if run.total else 0):.1f}s</div><div class="note">per case end-to-end</div></div>
  </div>

  <h2>Pass Rate by Layer</h2>
  {''.join(layer_rows)}

  <p class="muted">L1 = deterministic skill math (no LLM). L2 = single-turn tool selection. L3 = multi-turn end-to-end. L4 = regression cases anchored to shipped fixes.</p>
</section>"""


def _layer_label(layer: int) -> str:
    return {
        1: "Skill math (deterministic)",
        2: "Tool selection (single-turn)",
        3: "End-to-end (multi-turn)",
        4: "Regression (shipped fixes)",
    }.get(layer, f"Layer {layer}")


# ── Summary ────────────────────────────────────────────────────────────────


def _summary(run: EvalRun) -> str:
    failed_rows = []
    for r in run.results:
        if r.passed:
            continue
        reasons = ", ".join(jr.judge_name for jr in r.failed_judges) or (r.error or "—")
        failed_rows.append(
            f'<tr><td><span class="pill pill-layer">L{r.case.layer}</span>{_h(r.case.id)}</td>'
            f'<td>{_h(r.case.name)}</td>'
            f'<td>{_h(reasons)}</td></tr>'
        )
    failures_html = (
        f'<table><tr><th>Case</th><th>Name</th><th>Failed judges</th></tr>{"".join(failed_rows)}</table>'
        if failed_rows
        else '<p class="muted">No failures.</p>'
    )

    slowest = sorted(run.results, key=lambda r: -r.duration_seconds)[:5]
    slow_rows = "".join(
        f'<tr><td>{_h(r.case.id)}</td><td>{_h(r.case.name)}</td>'
        f'<td class="num">{r.duration_seconds:.2f}s</td>'
        f'<td><span class="pill pill-{"pass" if r.passed else "fail"}">{("pass" if r.passed else "fail")}</span></td></tr>'
        for r in slowest
    )

    return f"""<section class="page">
  <h2>Failures</h2>
  {failures_html}

  <h2>Slowest cases</h2>
  <table>
    <tr><th>Case</th><th>Name</th><th class="num">Duration</th><th>Status</th></tr>
    {slow_rows}
  </table>

  <h2>Reading guide</h2>
  <p>Each subsequent page is one case. The headline pill on the left is the
  outcome. The <em>steps</em> section lists what the runner did. The
  <em>judges</em> table is the verdict each assertion returned with
  expected/actual values. <em>Tool-call trace</em> is the exact sequence of
  agent tool emissions captured during the run — the same shape Langfuse
  records in prod.</p>
</section>"""


# ── Per-case page ──────────────────────────────────────────────────────────


def _judge_table(judge_results: list[JudgeResult]) -> str:
    if not judge_results:
        return '<p class="muted">No judges ran (case errored out before assertions).</p>'
    rows = []
    for j in judge_results:
        pill = '<span class="pill pill-pass">pass</span>' if j.ok else '<span class="pill pill-fail">fail</span>'
        rows.append(
            f'<tr class="judge-row">'
            f'<td class="ok-cell">{pill}</td>'
            f'<td>'
            f'<strong>{_h(j.judge_name)}</strong><br/>'
            f'<span class="muted">{_h(j.description)}</span>'
            f'{(f"<br/><span class=\"muted\">{_h(j.message)}</span>" if j.message else "")}'
            f'</td>'
            f'<td><strong>expected</strong>{_json_block(j.expected, limit=600)}</td>'
            f'<td><strong>actual</strong>{_json_block(j.actual, limit=600)}</td>'
            f'</tr>'
        )
    return f"""<table>
      <tr><th>Status</th><th>Judge</th><th>Expected</th><th>Actual</th></tr>
      {''.join(rows)}
    </table>"""


def _steps_table(result: RunResult) -> str:
    if not result.ctx or not result.ctx.step_records:
        return '<p class="muted">No steps recorded.</p>'
    rows = []
    for i, s in enumerate(result.ctx.step_records, 1):
        kind_pill = f'<span class="pill pill-{s.kind}">{s.kind}</span>'
        rows.append(
            f'<tr>'
            f'<td class="num">{i}</td>'
            f'<td>{kind_pill}</td>'
            f'<td>{_h(s.label)}</td>'
            f'<td class="num">{s.duration_seconds:.2f}s</td>'
            f'<td>{_h(s.error) if s.error else "—"}</td>'
            f'</tr>'
        )
    return f"""<table>
      <tr><th class="num">#</th><th>Kind</th><th>Label</th><th class="num">Duration</th><th>Error</th></tr>
      {''.join(rows)}
    </table>"""


def _trace_section(result: RunResult) -> str:
    if not result.ctx:
        return ""
    tool_calls = result.ctx.tool_calls
    if not tool_calls:
        return '<h3>Tool-call trace</h3><p class="muted">No tool calls captured.</p>'
    # Build a paired view: each call alongside its matching result.
    results_by_id = {r.id: r for r in result.ctx.tool_results}
    rows = []
    for c in tool_calls:
        res = results_by_id.get(c.id)
        rows.append(
            f'<tr>'
            f'<td><code>{_h(c.name)}</code></td>'
            f'<td>{_json_block(c.args, limit=500)}</td>'
            f'<td>{_json_block(res.result if res else None, limit=500)}</td>'
            f'</tr>'
        )
    return f"""<h3>Tool-call trace</h3>
    <table>
      <tr><th>Tool</th><th>Args</th><th>Result</th></tr>
      {''.join(rows)}
    </table>"""


def _assistant_section(result: RunResult) -> str:
    if not result.ctx or not result.ctx.assistant_texts:
        return ""
    blobs = "".join(
        f'<div class="code">{_h(t)}</div>'
        for t in result.ctx.assistant_texts
        if t and t.strip()
    )
    if not blobs:
        return ""
    return f"<h3>Assistant text</h3>{blobs}"


def _case_page(result: RunResult) -> str:
    case = result.case
    tags_html = "".join(f'<span class="pill pill-tag">{_h(t)}</span>' for t in case.tags)
    outcome = '<span class="pill pill-pass">pass</span>' if result.passed else '<span class="pill pill-fail">fail</span>'
    error_html = (
        f'<div class="code"><strong>Runtime error:</strong> {_h(result.error)}</div>'
        if result.error
        else ""
    )
    return f"""<section class="page">
  <div class="case-header">
    <span class="pill pill-layer">L{case.layer}</span>
    <h2>{_h(case.id)} — {_h(case.name)}</h2>
    {outcome}
  </div>
  <p>{_h(case.description)}</p>
  <p class="muted">Tags: {tags_html or '<span class="muted">none</span>'} &nbsp;·&nbsp; Duration: {result.duration_seconds:.2f}s</p>

  {error_html}

  <h3>Steps</h3>
  {_steps_table(result)}

  <h3>Judges</h3>
  {_judge_table(result.judge_results)}

  {_trace_section(result)}

  {_assistant_section(result)}
</section>"""


# ── Build + render ─────────────────────────────────────────────────────────


def _build_html(run: EvalRun) -> str:
    sections = [_cover(run), _summary(run)]
    for r in run.results:
        sections.append(_case_page(r))
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>StackWealth Planner — Agent Eval Report</title>
<style>{CSS}</style>
</head><body>
{''.join(sections)}
</body></html>"""


async def render_run_pdf(run: EvalRun) -> dict[str, Any]:
    """Render the eval run as a PDF (Playwright Chromium). On failure,
    returns the raw HTML so callers can fall back to browser print."""
    return await _render_html_to_pdf(_build_html(run), run.started_at)


# ── Summary report ─────────────────────────────────────────────────────────


def _summary_cover(run: EvalRun) -> str:
    """Compact cover — same scoreboard, no reading guide."""
    by_layer = run.by_layer()
    layer_rows = []
    for layer in (1, 2, 3, 4):
        results = by_layer.get(layer, [])
        if not results:
            continue
        passed = sum(1 for r in results if r.passed)
        layer_rows.append(
            f'<div class="layer-row">'
            f'<div class="lbl"><span class="pill pill-layer">L{layer}</span>'
            f'{_layer_label(layer)}</div>'
            f'<div>{_bar(passed, len(results), kind="pass" if passed == len(results) else "fail")}</div>'
            f'</div>'
        )
    return f"""<section class="page">
  <div class="headline">
    <div class="brand">StackWealth Planner · Agent Eval · Summary</div>
    <h1>Run Report</h1>
    <div class="sub">{run.passed} passed · {run.failed} failed · {run.pass_rate * 100:.0f}% pass rate</div>
  </div>
  <p class="cover-meta">
    <strong>Started:</strong> {run.started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}
    &nbsp;·&nbsp; <strong>Duration:</strong> {run.duration_seconds:.1f}s
    &nbsp;·&nbsp; <strong>Model:</strong> {_h(run.model)}
    &nbsp;·&nbsp; <strong>Cases:</strong> {run.total}
  </p>

  <h2>Pass Rate by Layer</h2>
  {''.join(layer_rows)}

  <p class="muted">This summary shows every case on one table (next page) and short failure notes (if any). For full per-case detail with tool-call traces, run with <code>--style detailed</code>.</p>
</section>"""


def _summary_all_cases_table(run: EvalRun) -> str:
    """Every case on one page — one row per case, no per-case detail pages."""
    rows = []
    for r in run.results:
        case = r.case
        pill = (
            '<span class="pill pill-pass">pass</span>'
            if r.passed
            else '<span class="pill pill-fail">fail</span>'
        )
        notes = ""
        if not r.passed:
            failed = ", ".join(jr.judge_name for jr in r.failed_judges)
            notes = _h(failed[:80]) if failed else _h(r.error or "—")
        rows.append(
            f'<tr>'
            f'<td>{pill}</td>'
            f'<td><span class="pill pill-layer">L{case.layer}</span></td>'
            f'<td><code>{_h(case.id)}</code></td>'
            f'<td>{_h(case.name)}</td>'
            f'<td class="num">{r.duration_seconds:.1f}s</td>'
            f'<td>{notes}</td>'
            f'</tr>'
        )
    return f"""<section class="page">
  <h2>All cases</h2>
  <table class="dense">
    <tr><th>Status</th><th>Layer</th><th>Case ID</th><th>Name</th><th class="num">Time</th><th>Notes</th></tr>
    {''.join(rows)}
  </table>
</section>"""


def _summary_failure_deepdive(run: EvalRun) -> str:
    """One short block per failure — no tool traces, no assistant text. Just
    name + description + which judges failed + the human-readable reason."""
    failures = [r for r in run.results if not r.passed]
    if not failures:
        return f"""<section class="page">
  <h2>Failures</h2>
  <p class="muted">No failures — all {run.total} cases passed.</p>
</section>"""
    blocks = []
    for r in failures:
        case = r.case
        judge_lines = []
        for jr in r.failed_judges:
            judge_lines.append(
                f'<li><strong>{_h(jr.judge_name)}</strong>'
                f' — {_h(jr.message or jr.description)}</li>'
            )
        error_line = (
            f'<p class="muted"><strong>Runtime error:</strong> {_h(r.error)}</p>'
            if r.error
            else ""
        )
        blocks.append(
            f'<div class="failure-block">'
            f'  <h3><span class="pill pill-layer">L{case.layer}</span> '
            f'<span class="pill pill-fail">fail</span> '
            f'<code>{_h(case.id)}</code> — {_h(case.name)}</h3>'
            f'  <p class="muted">{_h(case.description)}</p>'
            f'  {error_line}'
            f'  <p><strong>Failed judges:</strong></p>'
            f'  <ul>{"".join(judge_lines) if judge_lines else "<li>(none — runtime error)</li>"}</ul>'
            f'</div>'
        )
    return f"""<section class="page">
  <h2>Failure deep-dive</h2>
  {''.join(blocks)}
</section>"""


def _build_summary_html(run: EvalRun) -> str:
    sections = [
        _summary_cover(run),
        _summary_all_cases_table(run),
        _summary_failure_deepdive(run),
    ]
    extra_css = """
.dense th, .dense td { padding: 1mm 2mm; font-size: 9pt; }
.dense code { font-size: 8.5pt; }
.failure-block { margin-bottom: 5mm; padding: 3mm 4mm; background: #fafafa; border-left: 3px solid #dc2626; border-radius: 1.5mm; }
.failure-block h3 { margin-top: 0; text-transform: none; letter-spacing: 0; }
.failure-block ul { margin: 1mm 0 0 4mm; }
"""
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>StackWealth Planner — Agent Eval Report (Summary)</title>
<style>{CSS}{extra_css}</style>
</head><body>
{''.join(sections)}
</body></html>"""


async def render_run_summary_pdf(run: EvalRun) -> dict[str, Any]:
    """Render a compact 3-page summary PDF (cover · all cases on one table ·
    failure deep-dive). For full per-case detail including tool-call traces
    and assistant text, use render_run_pdf instead."""
    return await _render_html_to_pdf(_build_summary_html(run), run.started_at)


# ── Shared PDF render ──────────────────────────────────────────────────────


async def _render_html_to_pdf(report_html: str, started_at) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception:
        return {"ok": False, "html": report_html, "reason": "playwright_not_installed"}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
            try:
                page = await browser.new_page()
                await page.set_content(report_html, wait_until="domcontentloaded")
                footer_template = (
                    '<div style="font-size:8pt;color:#71717a;width:100%;'
                    'padding:0 14mm;display:flex;justify-content:space-between;'
                    'border-top:1px solid #e4e4e7;padding-top:2mm;">'
                    f'<span>StackWealth Eval — {started_at.strftime("%Y-%m-%d %H:%M")}</span>'
                    '<span>Page <span class="pageNumber"></span>'
                    ' / <span class="totalPages"></span></span>'
                    '</div>'
                )
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "14mm", "right": "14mm", "bottom": "20mm", "left": "14mm"},
                    display_header_footer=True,
                    header_template='<div></div>',
                    footer_template=footer_template,
                )
                return {"ok": True, "bytes": pdf_bytes, "html": report_html}
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
    except Exception as e:
        return {"ok": False, "html": report_html, "reason": str(e)}
