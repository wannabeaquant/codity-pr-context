from __future__ import annotations
from typing import Literal

from .diff_parser import ParsedDiff

# Thresholds — deliberately conservative: fast path handles 80%+ of real PRs
LINES_THRESHOLD = 60
FILES_THRESHOLD = 3
SYMBOLS_THRESHOLD = 2


def route(diff: ParsedDiff) -> tuple[Literal["fast", "agent"], str]:
    """Decide whether to use the fast (deterministic) or agent path.

    Returns (mode, reasoning_string).
    Reasoning is included in the output JSON for transparency.
    """
    reasons: list[str] = []

    if diff.total_lines_changed > LINES_THRESHOLD:
        reasons.append(f"{diff.total_lines_changed} lines changed (>{LINES_THRESHOLD})")

    if len(diff.changed_files) > FILES_THRESHOLD:
        reasons.append(f"{len(diff.changed_files)} files changed (>{FILES_THRESHOLD})")

    if len(diff.changed_symbols) > SYMBOLS_THRESHOLD:
        reasons.append(f"{len(diff.changed_symbols)} symbols changed (>{SYMBOLS_THRESHOLD})")

    if reasons:
        return "agent", "Escalated to agent: " + "; ".join(reasons) + "."
    else:
        return "fast", (
            f"Fast path: {diff.total_lines_changed} lines, "
            f"{len(diff.changed_files)} file(s), "
            f"{len(diff.changed_symbols)} symbol(s) — within thresholds."
        )
