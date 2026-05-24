from __future__ import annotations
import os
from pathlib import Path
from typing import Any

import anthropic

from ..diff_parser import ParsedDiff
from ..ranker import rank_and_pack, TOKEN_BUDGET
from ..retrievers.base import RetrievalResult
from .tools import TOOL_DEFINITIONS, dispatch_tool

MAX_TURNS = 8
MODEL = "claude-sonnet-4-6"


def run_agent_path(
    repo_path: Path, diff: ParsedDiff, diff_text: str
) -> tuple[list[RetrievalResult], list[dict]]:
    """Run the agent-based retrieval loop.

    Returns (packed_results, agent_trace).
    agent_trace is a list of {turn, tool, inputs, results_count, tokens_added}
    for inclusion in the output JSON.
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    system_prompt = _build_system_prompt(diff, diff_text)
    messages: list[dict] = [{"role": "user", "content": system_prompt}]

    all_results: list[RetrievalResult] = []
    agent_trace: list[dict] = []
    accumulated_tokens = 0

    for turn in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        # collect assistant message
        messages.append({"role": "assistant", "content": response.content})

        # check stop conditions
        if response.stop_reason == "end_turn":
            break

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if not tool_calls:
            break

        tool_results_content: list[dict] = []

        for tool_use in tool_calls:
            tool_name = tool_use.name
            tool_inputs = tool_use.input

            if tool_name == "done":
                agent_trace.append({
                    "turn": turn + 1,
                    "tool": "done",
                    "inputs": tool_inputs,
                    "results_count": 0,
                    "tokens_added": 0,
                })
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": "Context collection complete.",
                })
                # append the tool result and break out of the loop
                messages.append({"role": "user", "content": tool_results_content})
                packed = rank_and_pack(all_results)
                return packed, agent_trace

            # dispatch to retriever
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

            # build tool result summary for the agent
            summary = _format_results_summary(new_results)
            tool_results_content.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": summary,
            })

        messages.append({"role": "user", "content": tool_results_content})

        # stop if already over budget — no point collecting more
        if accumulated_tokens >= TOKEN_BUDGET:
            agent_trace.append({
                "turn": turn + 1,
                "tool": "_budget_exceeded",
                "inputs": {},
                "results_count": 0,
                "tokens_added": 0,
                "note": f"Stopped: accumulated {accumulated_tokens} tokens >= budget {TOKEN_BUDGET}",
            })
            break

    packed = rank_and_pack(all_results)
    return packed, agent_trace


def _build_system_prompt(diff: ParsedDiff, diff_text: str) -> str:
    changed_files = ", ".join(diff.changed_files) if diff.changed_files else "unknown"
    changed_symbols = ", ".join(diff.changed_symbols) if diff.changed_symbols else "none detected"

    return f"""You are a code review context retrieval agent. Your job is to collect the right context \
from a repository so that a senior engineer can do a high-quality review of a pull request.

PR DIFF:
```diff
{diff_text[:3000]}{"... [diff truncated]" if len(diff_text) > 3000 else ""}
```

CHANGED FILES: {changed_files}
CHANGED SYMBOLS: {changed_symbols}
LINES CHANGED: {diff.total_lines_changed}

You have access to tools that retrieve context from the repository. Use them strategically:
- Prioritize callees (what changed functions depend on) and callers (what depends on the changed functions)
- Fetch tests to understand existing behavioral contracts
- Use git history to understand *why* code was written a certain way
- Use grep and read_file for anything not covered by specific tools
- Stop as soon as you have sufficient context — token cost matters

Token budget: 8192 tokens across all retrieved context.
When you have enough context for a thorough review, call the `done` tool.
Do NOT call the same tool twice with the same inputs.
"""


def _format_results_summary(results: list[RetrievalResult]) -> str:
    if not results:
        return "No results found."
    lines = []
    for r in results:
        lines.append(f"[{r.source}] {r.file}:{r.start_line}-{r.end_line} | {r.estimated_tokens} tokens | {r.reason}")
    return "\n".join(lines)
