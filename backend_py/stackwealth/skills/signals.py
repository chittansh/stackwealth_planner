"""
India market signal block — port of skills/signals/index.ts.

Reads a fixture snapshot for reproducibility (live fetchers stubbed; same
behaviour as TS).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_cached: dict | None = None


def get_signals() -> dict[str, Any]:
    global _cached
    if _cached is not None:
        return _cached
    here = Path(__file__).resolve().parent.parent / "seed" / "signals.fixture.json"
    try:
        _cached = json.loads(here.read_text(encoding="utf-8"))
    except Exception:
        from datetime import date

        _cached = {
            "as_of": date.today().isoformat(),
            "blocks": {
                "valuation": {"score": 0, "reason": "Neutral (no snapshot)"},
                "trend": {"score": 0, "reason": "Neutral"},
                "breadth": {"score": 0, "reason": "Neutral"},
                "flows": {"score": 0, "reason": "Neutral"},
                "macro": {"score": 0, "reason": "Neutral"},
                "external": {"score": 0, "reason": "Neutral"},
            },
            "source_versions": {},
        }
    return _cached  # type: ignore[return-value]


def regime_from_blocks(b: dict[str, dict[str, Any]]) -> dict[str, Any]:
    s = (
        b["valuation"]["score"]
        + b["trend"]["score"]
        + b["breadth"]["score"]
        + b["flows"]["score"]
        + b["macro"]["score"]
        + b["external"]["score"]
    )
    if s >= 4:
        label = "Risk-On"
    elif s >= 1:
        label = "Mild Risk-On"
    elif s >= -1:
        label = "Neutral"
    elif s >= -4:
        label = "Mild Defensive"
    else:
        label = "Defensive"
    return {"score": s, "label": label}
