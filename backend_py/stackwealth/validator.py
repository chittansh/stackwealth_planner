"""
Numbers-from-tools validator — Python port of agent/validator.ts.

Hard rule: any number named in an assistant message must be present in a
recent tool result (or be a small ordinal). On violation, rewrite the token
to «unverified:N» so the chat surfaces the issue without dropping the message.
"""
from __future__ import annotations

import re
from typing import Any

PERMISSIBLE_SMALL = {
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
    "12", "15", "20", "25", "30", "45", "50", "60", "75", "80", "100",
}

# Western 1,234,567 AND Indian 1,25,000 grouping; optional decimal.
# Excludes leading word/dot chars so identifiers like v1.2 aren't mangled.
NUMBER_RE = re.compile(r"(?<![\w.])(-?\d(?:[\d,]*\d)?(?:\.\d+)?)")


def collect_numbers(value: Any, out: set[str] | None = None) -> set[str]:
    if out is None:
        out = set()
    if value is None:
        return out
    if isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        if value == value and value not in (float("inf"), float("-inf")):  # finite check
            out.add(str(round(value)))
        return out
    if isinstance(value, str):
        return out
    if isinstance(value, (list, tuple)):
        for v in value:
            collect_numbers(v, out)
        return out
    if isinstance(value, dict):
        for v in value.values():
            collect_numbers(v, out)
        return out
    # Fallback: try .__dict__ for pydantic objects, etc.
    if hasattr(value, "model_dump"):
        try:
            return collect_numbers(value.model_dump(), out)  # type: ignore[attr-defined]
        except Exception:
            pass
    return out


def validate_assistant_text(text: str, known_numbers: set[str]) -> str:
    known = set(known_numbers) | PERMISSIBLE_SMALL

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        stripped = token.replace(",", "").rstrip("0").rstrip(".") if "." in token else token.replace(",", "")
        # Reapply the original strip rule from TS exactly:
        stripped = re.sub(r"\.0+$", "", token.replace(",", ""))
        if stripped in known:
            return token

        # Year whitelist: 1900–2200
        try:
            as_int = int(stripped)
            if 1900 <= as_int <= 2200:
                return token
        except ValueError:
            pass

        try:
            n = float(stripped)
        except ValueError:
            return token

        # ±1 rounding tolerance against any known integer
        r = round(n)
        if str(r) in known or str(r - 1) in known or str(r + 1) in known:
            return token

        # 2% drift tolerance for compounding/projection
        abs_n = abs(n)
        for k in known:
            try:
                kn = float(k)
            except ValueError:
                continue
            if kn == 0:
                continue
            if abs(kn - n) / max(abs_n, abs(kn)) <= 0.02:
                return token

        return f"«unverified:{token}»"

    return NUMBER_RE.sub(replace, text)
