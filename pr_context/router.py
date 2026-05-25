from __future__ import annotations
import json
import os
from typing import Literal

from .diff_parser import ParsedDiff
from .tokenizer import truncate_to_tokens

# Heuristic thresholds — used as fallback when no API key is available
LINES_THRESHOLD = 60
FILES_THRESHOLD = 3
SYMBOLS_THRESHOLD = 2

# Haiku is cheap enough ($0.0001/PR) that we use it as the primary router
# when an API key is present. The heuristic can't distinguish a 5-line API
# change (should escalate) from a 200-line docstring rewrite (should not).
_ROUTER_MODEL = "claude-haiku-4-5"
_ROUTER_DIFF_TOKEN_LIMIT = 600  # enough to understand the nature of the change


def route(diff: ParsedDiff, diff_text: str = "") -> tuple[Literal["fast", "agent"], str]:
    """Decide whether to use the fast (deterministic) or agent path.

    Tries an LLM-based router (Haiku) if ANTHROPIC_API_KEY is set, because
    pure heuristics can't distinguish a 5-line API contract change (complex)
    from a 200-line docstring rewrite (trivial). Falls back to heuristics if
    the API is unavailable.

    Returns (mode, reasoning_string).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key and diff_text:
        try:
            return _llm_route(diff, diff_text, api_key)
        except Exception:
            pass  # any failure falls through to heuristic

    return _heuristic_route(diff)


def _llm_route(
    diff: ParsedDiff, diff_text: str, api_key: str
) -> tuple[Literal["fast", "agent"], str]:
    """Route using a cheap Haiku call. Raises on any error so caller can fallback."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    truncated = truncate_to_tokens(diff_text, _ROUTER_DIFF_TOKEN_LIMIT)

    stats_block = (
        f"Lines changed: {diff.total_lines_changed}\n"
        f"Files changed: {len(diff.changed_files)} ({', '.join(diff.changed_files[:5])})\n"
        f"Symbols changed: {len(diff.changed_symbols)} ({', '.join(diff.changed_symbols[:5])})\n"
    )

    prompt = f"""You are routing a PR diff to either a fast deterministic retrieval path or a
Claude agent retrieval loop for code review context gathering.

DIFF STATS:
{stats_block}
DIFF (may be truncated):
```diff
{truncated}
```

Respond with a JSON object only — no prose, no markdown fences:
{{"mode": "fast" or "agent", "reason": "one sentence explaining the decision"}}

Use "agent" when the change involves:
- Cross-file refactors where understanding caller impact requires reasoning
- Public API or interface changes where contract shifts matter
- Multi-symbol moves or renames across modules
- Non-obvious dependency chains

Use "fast" for:
- Bug fixes to a single function
- Documentation or comment changes
- Straightforward additions with no interface changes
- Simple config or constant changes"""

    response = client.messages.create(
        model=_ROUTER_MODEL,
        max_tokens=128,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown fences if the model wraps despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()

    parsed = json.loads(raw)
    mode = parsed["mode"]
    reason = parsed.get("reason", "LLM router decision.")

    if mode not in ("fast", "agent"):
        raise ValueError(f"Unexpected mode from LLM router: {mode!r}")

    return mode, f"[LLM router] {reason}"  # type: ignore[return-value]


def _heuristic_route(diff: ParsedDiff) -> tuple[Literal["fast", "agent"], str]:
    """Deterministic fallback router — three integer thresholds."""
    reasons: list[str] = []

    if diff.total_lines_changed > LINES_THRESHOLD:
        reasons.append(f"{diff.total_lines_changed} lines changed (>{LINES_THRESHOLD})")

    if len(diff.changed_files) > FILES_THRESHOLD:
        reasons.append(f"{len(diff.changed_files)} files changed (>{FILES_THRESHOLD})")

    if len(diff.changed_symbols) > SYMBOLS_THRESHOLD:
        reasons.append(f"{len(diff.changed_symbols)} symbols changed (>{SYMBOLS_THRESHOLD})")

    if reasons:
        return "agent", "[heuristic] Escalated to agent: " + "; ".join(reasons) + "."
    else:
        return "fast", (
            f"[heuristic] Fast path: {diff.total_lines_changed} lines, "
            f"{len(diff.changed_files)} file(s), "
            f"{len(diff.changed_symbols)} symbol(s) — within thresholds."
        )
