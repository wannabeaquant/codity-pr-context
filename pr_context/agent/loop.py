from __future__ import annotations
import os
from pathlib import Path
from typing import Any

import anthropic

from ..diff_parser import ParsedDiff
from ..ranker import rank_and_pack, PackResult, TOKEN_BUDGET
from ..tokenizer import count_tokens, truncate_to_tokens
from ..retrievers.base import RetrievalResult
from .tools import TOOL_DEFINITIONS, dispatch_tool

MAX_TURNS = 8
MODEL = "claude-sonnet-4-6"
# Truncate diff to this many tokens in the system prompt — agent needs to see
# the full shape of the change, not just the first 750 tokens (3000 chars).
DIFF_TOKEN_LIMIT = 2000


def run_agent_path(
    repo_path: Path, diff: ParsedDiff, diff_text: str
) -> tuple[PackResult, list[dict]]:
    """Run the agent-based retrieval loop.

    Returns (PackResult, agent_trace).
    agent_trace is a list of {turn, tool, inputs, results_count, tokens_added}
    for inclusion in the output JSON.
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    truncated_diff = truncate_to_tokens(diff_text, DIFF_TOKEN_LIMIT)
    system_prompt = _build_system_prompt(diff, truncated_diff)

    messages: list[dict] = [
        {"role": "user", "content": "Begin context retrieval for this PR."}
    ]

    all_results: list[RetrievalResult] = []
    agent_trace: list[dict] = []
    accumulated_tokens = 0
    # Track (tool_name, canonical_inputs) to prevent duplicate calls
    seen_calls: set[tuple[str, str]] = set()
    # Scratchpad: notes the agent writes to itself, prepended to every tool result
    agent_notes: list[str] = []

    for turn in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,  # enough for multi-tool reasoning turns
            system=system_prompt,  # system param, not user message — saves tokens + enables caching
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            agent_trace.append({
                "turn": turn + 1, "tool": "_end_turn",
                "note": "Agent stopped without calling done — treating as complete.",
            })
            break

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if not tool_calls:
            break

        # Check for `done` AFTER processing all tools in this turn
        done_call = next((t for t in tool_calls if t.name == "done"), None)
        # `note` is also handled separately — no retrieval, just scratchpad storage
        note_calls = [t for t in tool_calls if t.name == "note"]
        work_calls = [t for t in tool_calls if t.name not in ("done", "note")]

        tool_results_content: list[dict] = []

        # Process notes first — they're acknowledged immediately with no retrieval
        for note_call in note_calls:
            note_text = note_call.input.get("text", "")
            agent_notes.append(note_text)
            tool_results_content.append({
                "type": "tool_result",
                "tool_use_id": note_call.id,
                "content": f"Note recorded: {note_text!r}",
            })
            agent_trace.append({
                "turn": turn + 1, "tool": "note",
                "inputs": {"text": note_text},
                "note": "scratchpad entry recorded",
            })

        for tool_use in work_calls:
            tool_name = tool_use.name
            tool_inputs = tool_use.input
            call_key = (tool_name, str(sorted(tool_inputs.items())))

            if call_key in seen_calls:
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": "Duplicate call — this exact tool+inputs was already called. Skip and try something different.",
                })
                agent_trace.append({
                    "turn": turn + 1, "tool": tool_name,
                    "inputs": tool_inputs, "note": "duplicate — skipped",
                })
                continue

            seen_calls.add(call_key)
            new_results = dispatch_tool(tool_name, tool_inputs, repo_path)
            tokens_added = sum(r.estimated_tokens for r in new_results)
            accumulated_tokens += tokens_added

            agent_trace.append({
                "turn": turn + 1,
                "tool": tool_name,
                "inputs": tool_inputs,
                "results_count": len(new_results),
                "tokens_added": tokens_added,
                "accumulated_context_tokens": accumulated_tokens,
            })

            all_results.extend(new_results)
            tool_results_content.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": _format_results_summary(new_results, accumulated_tokens, agent_notes),
            })

        # Handle `done` after all work tools in this turn
        if done_call:
            tool_results_content.append({
                "type": "tool_result",
                "tool_use_id": done_call.id,
                "content": "Context collection complete.",
            })
            agent_trace.append({
                "turn": turn + 1, "tool": "done",
                "inputs": done_call.input,
                "results_count": 0, "tokens_added": 0,
            })
            messages.append({"role": "user", "content": tool_results_content})
            return rank_and_pack(all_results), agent_trace

        messages.append({"role": "user", "content": tool_results_content})

        if accumulated_tokens >= TOKEN_BUDGET:
            agent_trace.append({
                "turn": turn + 1, "tool": "_budget_cap",
                "note": f"Stopped: {accumulated_tokens} tokens >= budget {TOKEN_BUDGET}",
            })
            break

    return rank_and_pack(all_results), agent_trace


def _build_system_prompt(diff: ParsedDiff, truncated_diff: str) -> str:
    changed_files = ", ".join(diff.changed_files) if diff.changed_files else "unknown"
    changed_symbols = ", ".join(diff.changed_symbols) if diff.changed_symbols else "none detected"
    was_truncated = count_tokens(truncated_diff) >= DIFF_TOKEN_LIMIT - 50

    return f"""You are a code review context retrieval agent. Your job is to collect exactly the right \
context from a repository so that a senior engineer can do a high-quality review of this pull request.

PR DIFF{' (truncated — fetch specific ranges with read_file if you need more)' if was_truncated else ''}:
```diff
{truncated_diff}
```

CHANGED FILES: {changed_files}
CHANGED SYMBOLS: {changed_symbols}
LINES CHANGED: {diff.total_lines_changed}

STRATEGY:
1. Callees first — understand what the changed code depends on
2. Callers second — understand what depends on the changed interface (breaking changes)
3. Tests — existing behavioral contracts
4. Use git_history, grep, read_file only when the above leave gaps
5. Call `done` as soon as you have sufficient context — token cost is real

Token budget: {TOKEN_BUDGET} tokens. Current usage is reported after each tool call.
Do NOT call the same tool with the same inputs twice.
"""


def _format_results_summary(
    results: list[RetrievalResult],
    accumulated: int,
    notes: list[str] | None = None,
) -> str:
    lines = []
    # Prepend scratchpad so the agent always sees its open threads
    if notes:
        lines.append("SCRATCHPAD (your notes so far):")
        for i, note in enumerate(notes, 1):
            lines.append(f"  [{i}] {note}")
        lines.append("")

    if not results:
        lines.append(f"No results found. Accumulated context: {accumulated} tokens.")
        return "\n".join(lines)

    lines.append(f"Retrieved {len(results)} item(s). Accumulated context: {accumulated} tokens.\n")
    for r in results:
        lines.append(
            f"  [{r.source}] {r.file}:{r.start_line}-{r.end_line} "
            f"({r.estimated_tokens} tok) — {r.reason}"
        )
    return "\n".join(lines)
