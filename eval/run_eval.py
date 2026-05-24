"""
Eval runner: runs both fast-path and agent-path on all 3 httpx PRs,
saves JSON outputs, and prints a comparison table.

Usage:
    python eval/run_eval.py                        # fast path only (no API key needed)
    ANTHROPIC_API_KEY=sk-... python eval/run_eval.py   # both paths
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HTTPX_REPO = REPO_ROOT / "eval" / "repos" / "httpx"
DIFFS_DIR = REPO_ROOT / "eval" / "diffs"
OUTPUTS_DIR = REPO_ROOT / "eval" / "outputs"

OUTPUTS_DIR.mkdir(exist_ok=True)

# (pr_name, diff_file, base_commit, description)
EVAL_CASES = [
    (
        "pr1_bugfix",
        "pr1_bugfix_verify_cert.diff",
        "89599a9^",  # commit before the fix
        "Bug fix: verify=False + cert=... combination in create_ssl_context",
    ),
    (
        "pr2_refactor",
        "pr2_refactor_utils_to_client.diff",
        "7b19cd5^",
        "Refactor: move utility functions from _utils.py to _client.py",
    ),
    (
        "pr3_feature",
        "pr3_feature_socks5h.diff",
        "12be5c4^",
        "Feature: add socks5h proxy support",
    ),
]


def run_case(name: str, diff_file: str, base_commit: str, description: str) -> dict:
    diff_path = DIFFS_DIR / diff_file
    if not diff_path.exists():
        print(f"  [SKIP] diff not found: {diff_path}", flush=True)
        return {}

    print(f"\n{'='*60}")
    print(f"  {name}: {description}")
    print(f"{'='*60}", flush=True)

    # checkout base commit so retrievers see the pre-PR state
    subprocess.run(
        ["git", "checkout", base_commit, "-q"],
        cwd=HTTPX_REPO, capture_output=True
    )

    python = REPO_ROOT / "venv" / "Scripts" / "python"
    if not python.exists():
        python = Path(sys.executable)

    result = subprocess.run(
        [str(python), "-m", "pr_context",
         str(HTTPX_REPO), str(diff_path), "--json-out"],
        cwd=REPO_ROOT,
        capture_output=True, text=True,
        env={**os.environ},
    )

    # restore HEAD
    subprocess.run(
        ["git", "checkout", "HEAD", "-q"],
        cwd=HTTPX_REPO, capture_output=True
    )

    if result.returncode != 0 and not result.stdout:
        print(f"  [ERROR] {result.stderr[:500]}", flush=True)
        return {}

    try:
        # stdout may have warnings before JSON; find the JSON blob
        stdout = result.stdout
        start = stdout.find("{")
        if start == -1:
            print(f"  [ERROR] no JSON in output. stderr: {result.stderr[:300]}")
            return {}
        data = json.loads(stdout[start:])
    except json.JSONDecodeError as e:
        print(f"  [ERROR] JSON parse failed: {e}")
        return {}

    output_path = OUTPUTS_DIR / f"{name}.json"
    output_path.write_text(json.dumps(data, indent=2))
    print(f"  Saved: {output_path.name}", flush=True)

    _print_case_summary(name, data)
    return data


def _print_case_summary(name: str, data: dict) -> None:
    mode = data.get("mode", "?")
    routing = data.get("router_reasoning", "")
    stats = data.get("diff_stats", {})
    summary = data.get("summary", {})
    retrievals = data.get("retrievals", [])

    print(f"\n  Mode:   {mode.upper()}")
    print(f"  Router: {routing}")
    print(f"  Diff:   {stats.get('files_changed','?')} file(s), "
          f"{stats.get('total_lines_changed','?')} lines, "
          f"{len(stats.get('changed_symbols',[]))} symbol(s)")
    print(f"  Budget: {summary.get('total_context_tokens','?')} tokens "
          f"({summary.get('budget_used_pct','?')}% of 8192)")
    print(f"  Prompt: ~{summary.get('total_prompt_tokens','?')} tokens | "
          f"cost: ${summary.get('estimated_review_cost_usd','?')}")
    print(f"  Items:  {len(retrievals)} retrieved")

    sources: dict[str, int] = {}
    for r in retrievals:
        src = r["source"]
        sources[src] = sources.get(src, 0) + 1
    print(f"  Sources: {', '.join(f'{k}×{v}' for k, v in sources.items())}")

    if data.get("agent_trace"):
        print(f"  Agent turns: {len(data['agent_trace'])}")

    print()
    print("  Top retrievals:")
    for i, r in enumerate(retrievals[:6], 1):
        print(f"    {i}. [{r['source']:12}] {r['file']}:{r['lines']} "
              f"({r['estimated_tokens']} tok) — {r['reason'][:60]}")


def print_comparison_table(results: list[dict]) -> None:
    print(f"\n{'='*80}")
    print("  COMPARISON TABLE")
    print(f"{'='*80}")
    names = ["pr1_bugfix", "pr2_refactor", "pr3_feature"]
    headers = ["PR", "Mode", "Items", "Context tok", "Prompt tok", "Cost $", "Budget %"]
    rows = []
    for name, data in zip(names, results):
        if not data:
            rows.append([name, "ERROR", "-", "-", "-", "-", "-"])
            continue
        s = data.get("summary", {})
        rows.append([
            name,
            data.get("mode", "?").upper(),
            str(len(data.get("retrievals", []))),
            str(s.get("total_context_tokens", "?")),
            str(s.get("total_prompt_tokens", "?")),
            str(s.get("estimated_review_cost_usd", "?")),
            f"{s.get('budget_used_pct','?')}%",
        ])

    col_widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("  " + "-" * (sum(col_widths) + 2 * len(col_widths)))
    for row in rows:
        print(fmt.format(*row))
    print()


def main() -> None:
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"\nEval runner — API key: {'SET' if has_api_key else 'NOT SET (agent path will fall back to fast)'}")
    print(f"httpx repo: {HTTPX_REPO}")

    results = []
    for case in EVAL_CASES:
        data = run_case(*case)
        results.append(data)

    print_comparison_table(results)

    # restore httpx to HEAD
    subprocess.run(["git", "checkout", "HEAD", "-q"], cwd=HTTPX_REPO, capture_output=True)
    print("Done. Outputs saved to eval/outputs/")


if __name__ == "__main__":
    main()
