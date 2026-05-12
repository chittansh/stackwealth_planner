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
# Optional Indian magnitude suffix (Cr / crore / L / lakh / K / thousand)
# is captured so we can resolve "₹2.07 Cr" into 20,700,000 rupees and
# validate the rupee value — otherwise "2.07" rounds to 2 which is in
# PERMISSIBLE_SMALL and silently passes a 10× fabrication.
NUMBER_RE = re.compile(
    r"(?<![\w.])(-?\d(?:[\d,]*\d)?(?:\.\d+)?)\s*(cr|crore|crores|l|lakh|lakhs|k|thousand)?\b",
    re.IGNORECASE,
)

_SUFFIX_MULTIPLIER = {
    "": 1,
    "cr": 10_000_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "l": 100_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "k": 1_000,
    "thousand": 1_000,
}


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
        digits = match.group(1)
        suffix = (match.group(2) or "").lower()
        multiplier = _SUFFIX_MULTIPLIER.get(suffix, 1)

        # Normalize digit grouping commas + trailing .0.
        digits_norm = re.sub(r"\.0+$", "", digits.replace(",", ""))

        # When there's an Indian magnitude suffix (Cr / L / K), the user-
        # facing value is `digits × multiplier` rupees. Validate the resolved
        # rupee value against known — do NOT fall back to PERMISSIBLE_SMALL
        # (5 alone is fine; "5 Cr" is a 5-crore claim that must come from a
        # tool).
        try:
            n_raw = float(digits_norm)
        except ValueError:
            return token

        if multiplier != 1:
            resolved = n_raw * multiplier
            r = round(resolved)
            # Exact match against any known rupee value.
            if str(r) in known or str(r - 1) in known or str(r + 1) in known:
                return token
            # 2% drift tolerance for projections (e.g. agent rounds ₹19,997 to ₹20k).
            abs_n = abs(resolved)
            for k in known:
                try:
                    kn = float(k)
                except ValueError:
                    continue
                if kn == 0:
                    continue
                if abs(kn - resolved) / max(abs_n, abs(kn)) <= 0.02:
                    return token
            return f"«unverified:{token}»"

        # No suffix — fall back to the legacy small-number / year / drift logic.
        if digits_norm in known:
            return token

        # Year whitelist: 1900–2200
        try:
            as_int = int(digits_norm)
            if 1900 <= as_int <= 2200:
                return token
        except ValueError:
            pass

        # ±1 rounding tolerance against any known integer
        r = round(n_raw)
        if str(r) in known or str(r - 1) in known or str(r + 1) in known:
            return token

        # 2% drift tolerance for compounding/projection
        abs_n = abs(n_raw)
        for k in known:
            try:
                kn = float(k)
            except ValueError:
                continue
            if kn == 0:
                continue
            if abs(kn - n_raw) / max(abs_n, abs(kn)) <= 0.02:
                return token

        return f"«unverified:{token}»"

    return NUMBER_RE.sub(replace, text)
