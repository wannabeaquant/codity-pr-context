from __future__ import annotations
import json
import sys
from pathlib import Path

import click

from .diff_parser import parse_diff
from .router import route
from .fast_path import run_fast_path
from .prompt_builder import build_review_prompt, estimate_prompt_tokens
from .tokenizer import count_tokens

# Cost constants (USD per million tokens) — Sonnet input pricing
SONNET_INPUT_COST_PER_1M = 3.00


@click.command()
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("diff_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json-out", is_flag=True, default=False, help="Emit JSON retrieval plan instead of human-readable output")
@click.option("--budget", default=8192, help="Token budget for retrieved context (default: 8192)")
@click.option("--mode", type=click.Choice(["auto", "fast", "agent"]), default="auto", help="Force a specific retrieval mode")
def main(repo_path: Path, diff_path: Path, json_out: bool, budget: int, mode: str) -> None:
    """Retrieve context from REPO_PATH for the PR described by DIFF_PATH."""
    diff_text = diff_path.read_text(encoding="utf-8", errors="replace")
    diff = parse_diff(diff_text, repo_path)

    if not diff.hunks:
        click.echo("No hunks found in diff.", err=True)
        sys.exit(1)

    # routing
    if mode == "auto":
        selected_mode, router_reasoning = route(diff)
    else:
        selected_mode = mode  # type: ignore[assignment]
        router_reasoning = f"Mode forced to '{mode}' by --mode flag."

    agent_trace: list[dict] = []

    if selected_mode == "agent":
        try:
            from .agent.loop import run_agent_path
            packed, agent_trace = run_agent_path(repo_path, diff, diff_text)
        except (ImportError, TypeError, Exception) as e:
            err_msg = str(e)
            if "api_key" in err_msg.lower() or "auth" in err_msg.lower() or "ANTHROPIC_API_KEY" in err_msg:
                click.echo("ANTHROPIC_API_KEY not set — falling back to fast path.", err=True)
            else:
                click.echo(f"Agent path failed ({type(e).__name__}: {e}) — falling back to fast path.", err=True)
            packed = run_fast_path(repo_path, diff)
            selected_mode = "fast"
            router_reasoning += " [fell back to fast path]"
    else:
        packed = run_fast_path(repo_path, diff)

    # build the review prompt
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
        "summary": {
            "retrieved_count": len(packed),
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

    click.echo(f"\n{'='*60}")
    click.echo(f"  PR Context Retrieval — mode: {mode.upper()}")
    click.echo(f"{'='*60}")
    click.echo(f"  Router: {output['router_reasoning']}")
    click.echo(f"  Diff:   {stats['files_changed']} file(s), {stats['total_lines_changed']} lines, "
               f"{len(stats['changed_symbols'])} symbol(s) [{stats['diff_tokens']} tokens]")
    click.echo(f"  Budget: {summary['total_context_tokens']}/{summary.get('budget_used_pct', '?')}% used")
    click.echo(f"  Prompt: ~{summary['total_prompt_tokens']} tokens | est. cost: ${summary['estimated_review_cost_usd']}")
    click.echo()

    click.echo("  Retrieval Plan:")
    for i, r in enumerate(output["retrievals"], 1):
        click.echo(f"    {i:2}. [{r['source']:12}] {r['file']}:{r['lines']}  "
                   f"({r['estimated_tokens']} tok, priority={r['priority']:.2f})")
        click.echo(f"         {r['reason']}")
    click.echo()

    if output.get("agent_trace"):
        click.echo("  Agent Trace:")
        for step in output["agent_trace"]:
            click.echo(f"    Turn {step['turn']}: {step['tool']}({_fmt_inputs(step['inputs'])}) "
                       f"-> {step.get('results_count', 0)} results, +{step.get('tokens_added', 0)} tok")
        click.echo()

    click.echo(f"  Symbols in context: {', '.join(stats['changed_symbols']) or 'none'}")
    click.echo(f"{'='*60}\n")


def _fmt_inputs(inputs: dict) -> str:
    parts = []
    for k, v in inputs.items():
        if isinstance(v, list):
            parts.append(f"{k}=[{len(v)} items]")
        else:
            parts.append(f"{k}={str(v)[:30]!r}")
    return ", ".join(parts)
