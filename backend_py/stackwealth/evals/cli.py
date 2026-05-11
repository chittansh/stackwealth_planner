"""
Eval CLI.

Usage:

    cd backend_py
    .venv/bin/python -m stackwealth.evals.cli run [options]

Options:
    --layer N           Only run cases with this layer (1-4). Repeatable.
    --tag TAG           Only run cases tagged TAG. Repeatable.
    --case ID           Only run cases whose id matches ID (substring). Repeatable.
    --output-pdf PATH   Where to write the PDF report. Defaults to
                        /tmp/sw_evals_<utc-timestamp>.pdf
    --output-html PATH  Also write the raw HTML (handy when iterating on layout).
    --no-pdf            Skip PDF render — just print the pass/fail table.

Exit code is 0 iff every case passed, so the CLI works as a CI gate.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_dotenv() -> None:
    """Pull `backend_py/.env` into the process env before importing anything
    that reads `config.ANTHROPIC_API_KEY`. The main app relies on uvicorn's
    `--env-file` flag to do this; when running the eval CLI we have to do it
    ourselves or every Layer-2/3 case silently errors with
    `ANTHROPIC_API_KEY not set` and the suite finishes in milliseconds."""
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    # backend_py/.env, three levels up from this file (stackwealth/evals/cli.py).
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


_load_dotenv()


from .cases import ALL_CASES  # noqa: E402 — dotenv must load before config import
from .core import Case, EvalRun, Runner  # noqa: E402
from .report import render_run_pdf  # noqa: E402


def _filter_cases(args: argparse.Namespace) -> list[Case]:
    out = list(ALL_CASES)
    if args.layer:
        wanted = set(args.layer)
        out = [c for c in out if c.layer in wanted]
    if args.tag:
        wanted_tags = set(args.tag)
        out = [c for c in out if wanted_tags.intersection(c.tags)]
    if args.case:
        out = [c for c in out if any(needle in c.id for needle in args.case)]
    return out


def _print_table(run: EvalRun) -> None:
    """Compact terminal output — one line per case + a summary."""
    sys.stdout.write("\n")
    sys.stdout.write(
        f"StackWealth eval · {run.total} cases · {run.passed} passed · {run.failed} failed "
        f"· {run.duration_seconds:.1f}s · model={run.model}\n"
    )
    sys.stdout.write("─" * 80 + "\n")
    for r in run.results:
        mark = "✓" if r.passed else "✗"
        line = f"  L{r.case.layer} [{mark}] {r.case.id:<46} {r.duration_seconds:>6.2f}s"
        sys.stdout.write(line + "\n")
        if not r.passed:
            if r.error:
                sys.stdout.write(f"        ↳ runtime error: {r.error}\n")
            for jr in r.failed_judges:
                sys.stdout.write(f"        ↳ {jr.judge_name}: {jr.message or jr.description}\n")
    sys.stdout.write("─" * 80 + "\n")
    sys.stdout.write(
        f"Pass rate: {run.pass_rate * 100:.0f}% ({run.passed}/{run.total})\n"
    )


async def _run(args: argparse.Namespace) -> int:
    cases = _filter_cases(args)
    if not cases:
        sys.stderr.write("No cases matched the filters.\n")
        return 2

    sys.stdout.write(f"Running {len(cases)} case(s)...\n")
    runner = Runner(model=args.model)
    run = await runner.run_many(cases)

    _print_table(run)

    if not args.no_pdf:
        out_pdf = args.output_pdf or f"/tmp/sw_evals_{run.started_at.strftime('%Y%m%dT%H%M%SZ')}.pdf"
        rendered = await render_run_pdf(run)
        if rendered.get("ok"):
            Path(out_pdf).write_bytes(rendered["bytes"])
            sys.stdout.write(f"\nPDF: {out_pdf}\n")
        else:
            reason = rendered.get("reason", "unknown")
            sys.stdout.write(f"\nPDF render failed ({reason}); writing HTML fallback.\n")
            html_path = out_pdf.replace(".pdf", ".html")
            Path(html_path).write_text(rendered.get("html", ""), encoding="utf-8")
            sys.stdout.write(f"HTML: {html_path}\n")
        if args.output_html:
            Path(args.output_html).write_text(rendered.get("html", ""), encoding="utf-8")

    return 0 if run.failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="stackwealth.evals.cli")
    sub = parser.add_subparsers(dest="cmd")

    run_parser = sub.add_parser("run", help="Run eval cases and emit a PDF report.")
    run_parser.add_argument("--layer", type=int, action="append", choices=[1, 2, 3, 4])
    run_parser.add_argument("--tag", action="append", default=[])
    run_parser.add_argument("--case", action="append", default=[])
    run_parser.add_argument("--output-pdf", default=None)
    run_parser.add_argument("--output-html", default=None)
    run_parser.add_argument("--no-pdf", action="store_true")
    run_parser.add_argument(
        "--model",
        default=os.environ.get("PLANNER_MODEL", "claude-sonnet-4-6"),
        help="Override the Claude model id (defaults to env PLANNER_MODEL).",
    )

    list_parser = sub.add_parser("list", help="List discovered cases.")
    list_parser.add_argument("--layer", type=int, action="append", choices=[1, 2, 3, 4])

    args = parser.parse_args()
    if args.cmd == "run":
        return asyncio.run(_run(args))
    if args.cmd == "list":
        cases = _filter_cases(args) if hasattr(args, "case") else list(ALL_CASES)
        for c in cases:
            sys.stdout.write(f"  L{c.layer}  {c.id:<46}  {c.name}\n")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
