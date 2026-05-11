"""Aggregate every layer's CASES list into ALL_CASES."""
from __future__ import annotations

from . import conversations, e2e, regression, skill_math, tool_selection

ALL_CASES = [
    *skill_math.CASES,
    *tool_selection.CASES,
    *e2e.CASES,
    *conversations.CASES,
    *regression.CASES,
]
