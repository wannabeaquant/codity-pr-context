from __future__ import annotations
import json
import sys
from pathlib import Path

import click

from .diff_parser import parse_diff
from .router import route
from .fast_path import run_fast_path
from .ranker import PackResult
from .prompt_builder import build_review_prompt, estimate_prompt_tokens
from .tokenizer import count_tokens

SONNET_INPUT_COST_PER_1M = 3.00


@click.command()
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("diff_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json-out", is_flag=True, default=False, help="Emit JSON retrieval plan")
@click.option("--budget", default=8192, help="Token budget for retrieved context (default: 8192)")
@click.option("--mode", type=click.Choice(["auto", "fast", "agent"]), default="auto")
def main(repo_path: Path, diff_path: Path, json_out: bool, budget: int, mode: str) -> None:
    """Retrieve context from REPO_PATH for the PR described by DIFF_PATH."""
    diff_text = diff_path.read_text(encoding="utf-8", errors="replace")
    diff = parse_diff(diff_text, repo_path)

    if not diff.hunks:
        click.echo("No hunks found in diff.", err=True)
        sys.exit(1)

    if mode == "auto":
        selected_mode, router_reasoning = route(diff, diff_text)
    else:
        selected_mode = mode  # type: ignore[assignment]
        router_reasoning = f"Mode forced to '{mode}' by --mode flag."

    agent_trace: list[dict] = []
    pack_result: PackResult

    if selected_mode == "agent":
        try:
            from .agent.loop import run_agent_path
            pack_result, agent_trace = run_agent_path(repo_path, diff, diff_text)
        except Exception as e:
            err_msg = str(e)
            if "api_key" in err_msg.lower() or "auth" in err_msg.lower():
                click.echo("ANTHROPIC_API_KEY not set — falling back to fast path.", err=True)
            else:
                click.echo(f"Agent path failed ({type(e).__name__}: {e}) — falling back.", err=True)
            pack_result = run_fast_path(repo_path, diff, budget=budget)
            selected_mode = "fast"
            router_reasoning += " [fell back to fast path]"
    else:
        pack_result = run_fast_path(repo_path, diff, budget=budget)

    packed = pack_result.packed
    excluded = pack_result.excluded

    review_prompt = build_review_prompt(diff_text, packed)
    total_context_tokens = sum(r.estimated_tokens for r in packed)
    total_prompt_tokens = estimate_prompt_tokens(diff_text, packed)
    diff_tokens = count_tokens(diff_text)
    cost_usd = (total_prompt_tokens / 1_000_000) * SONNET_INPUT_COST_PER_1M

    output = {
        "mode": selected_mode,
        "router_reasoning": router_reasoning,
        "diff_stats": {
            "files_changed": len(diff.changed_files),
            "total_lines_changed": diff.total_lines_changed,
            "changed_symbols": diff.changed_symbols,
            "diff_tokens": diff_tokens,
        },
        "retrievals": [r.to_dict() for r in packed],
        "excluded": excluded,  # items computed but not packed — satisfies assignment requirement
        "summary": {
            "retrieved_count": len(packed),
            "excluded_count": len(excluded),
            "total_context_tokens": total_context_tokens,
            "total_prompt_tokens": total_prompt_tokens,
            "estimated_review_cost_usd": round(cost_usd, 5),
            "budget_used_pct": round(total_context_tokens / budget * 100, 1),
        },
        "agent_trace": agent_trace,
        "final_prompt": review_prompt,
    }

    if json_out:
        click.echo(json.dumps(output, indent=2))
    else:
        _print_human(output)


def _print_human(output: dict) -> None:
    mode = output["mode"]
    stats = output["diff_stats"]
    summary = output["summary"]

    click.echo(f"\n{'='*64}")
    click.echo(f"  PR Context Retrieval  [mode: {mode.upper()}]")
    click.echo(f"{'='*64}")
    click.echo(f"  Router  : {output['router_reasoning']}")
    click.echo(f"  Diff    : {stats['files_changed']} file(s), "
               f"{stats['total_lines_changed']} lines, "
               f"{len(stats['changed_symbols'])} symbol(s)  [{stats['diff_tokens']} tokens]")
    click.echo(f"  Symbols : {', '.join(stats['changed_symbols']) or 'none'}")
    click.echo(f"  Budget  : {summary['total_context_tokens']}/{summary['budget_used_pct']}% "
               f"({summary['retrieved_count']} retrieved, {summary['excluded_count']} excluded)")
    click.echo(f"  Prompt  : ~{summary['total_prompt_tokens']} tokens  "
               f"est. cost: ${summary['estimated_review_cost_usd']}")

    # Agent trace — printed explicitly so the reasoning is visible without opening JSON
    if output.get("agent_trace"):
        click.echo(f"\n  Agent Trace ({len(output['agent_trace'])} turns):")
        for step in output["agent_trace"]:
            tool = step["tool"]
            if tool.startswith("_"):
                click.echo(f"    [{step['turn']}] {tool}: {step.get('note', '')}")
                continue
            inputs_str = _fmt_inputs(step.get("inputs", {}))
            results = step.get("results_count", 0)
            tokens = step.get("tokens_added", 0)
            accum = step.get("accumulated_context_tokens", "")
            note = step.get("note", "")
            click.echo(
                f"    [{step['turn']}] {tool}({inputs_str}) "
                f"-> {results} results, +{tokens} tok"
                + (f"  [total: {accum}]" if accum else "")
                + (f"  [{note}]" if note else "")
            )

    click.echo(f"\n  Retrieved ({summary['retrieved_count']}):")
    for i, r in enumerate(output["retrievals"], 1):
        click.echo(f"    {i:2}. [{r['source']:12}] {r['file']}:{r['lines']}  "
                   f"({r['estimated_tokens']} tok, pri={r['priority']:.2f})")
        click.echo(f"          {r['reason']}")

    if output["excluded"]:
        click.echo(f"\n  Intentionally Excluded ({summary['excluded_count']}) — hit budget cutoff:")
        for r in output["excluded"][:8]:  # cap display at 8
            click.echo(f"    - [{r['source']:12}] {r['file']}:{r['lines']}  "
                       f"({r['estimated_tokens']} tok, pri={r['priority']:.2f})")
            click.echo(f"          {r['reason_excluded']}")
        if len(output["excluded"]) > 8:
            click.echo(f"    ... and {len(output['excluded']) - 8} more (see --json-out)")

    click.echo(f"\n{'='*64}\n")


def _fmt_inputs(inputs: dict) -> str:
    parts = []
    for k, v in inputs.items():
        if isinstance(v, list):
            parts.append(f"{k}=[{len(v)}]")
        else:
            parts.append(f"{k}={str(v)[:25]!r}")
    return ", ".join(parts)
