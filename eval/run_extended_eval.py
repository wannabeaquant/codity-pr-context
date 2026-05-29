"""
Extended eval: runs the system on 10 additional httpx commits covering
a wider range of PR types — API changes, bug fixes, refactors, features.

Usage:
    python eval/run_extended_eval.py
    ANTHROPIC_API_KEY=sk-... python eval/run_extended_eval.py
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HTTPX_REPO = REPO_ROOT / "eval" / "repos" / "httpx"
OUTPUTS_DIR = REPO_ROOT / "eval" / "outputs" / "extended"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# (commit, label, type)
EVAL_CASES = [
    ("ae1b9f6", "expose_functionauth",      "api-change",  "Expose FunctionAuth in __all__"),
    ("336204f", "proxy_scheme_error",        "bug-fix",     "Display proxy protocol scheme on error"),
    ("ce7e14d", "verify_str_error",          "validation",  "Error on verify=str instead of silent fail"),
    ("47f4a96", "empty_zstd_response",       "edge-case",   "Handle empty zstd responses"),
    ("2ea2286", "ssl_import_on_demand",      "refactor",    "Import ssl on demand (lazy import)"),
    ("41597ad", "utils_to_models",           "refactor",    "Move utility functions to _models.py"),
    ("6212e8f", "utils_to_multipart",        "refactor",    "Move utility functions to _multipart.py"),
    ("83a8518", "header_funcs_to_models",    "refactor",    "Move normalize header functions to _models.py"),
    ("a33c878", "extensions_type_fix",       "type-fix",    "Fix extensions type annotation"),
    ("ba2e512", "urlescape_percent_set",     "algorithm",   "Review urlescape percent-safe set"),
]


def get_current_branch(repo: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo, capture_output=True, text=True,
    )
    branch = r.stdout.strip()
    return branch if branch != "HEAD" else "master"


def run_case(commit: str, label: str, pr_type: str, description: str) -> dict:
    print(f"\n{'='*64}")
    print(f"  [{pr_type.upper()}] {description}")
    print(f"  commit: {commit}")
    print(f"{'='*64}", flush=True)

    original_branch = get_current_branch(HTTPX_REPO)

    # generate diff from this commit
    diff_result = subprocess.run(
        ["git", "show", commit, "--format="],
        cwd=HTTPX_REPO, capture_output=True, text=True,
    )
    if diff_result.returncode != 0 or not diff_result.stdout.strip():
        print(f"  [SKIP] could not generate diff for {commit}")
        return {}

    diff_text = diff_result.stdout

    # checkout parent so retrievers see pre-PR state
    subprocess.run(["git", "checkout", f"{commit}^", "-q"],
                   cwd=HTTPX_REPO, capture_output=True)

    python = REPO_ROOT / "venv" / "Scripts" / "python"
    if not python.exists():
        python = Path(sys.executable)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".diff",
                                     delete=False, encoding="utf-8") as f:
        f.write(diff_text)
        diff_path = f.name

    try:
        result = subprocess.run(
            [str(python), "-m", "pr_context",
             str(HTTPX_REPO), diff_path, "--json-out"],
            cwd=REPO_ROOT,
            capture_output=True, text=True,
            env={**os.environ},
        )
    finally:
        os.unlink(diff_path)
        subprocess.run(["git", "checkout", original_branch, "-q"],
                       cwd=HTTPX_REPO, capture_output=True)

    if result.returncode != 0 and not result.stdout:
        print(f"  [ERROR] {result.stderr[:400]}")
        return {}

    stdout = result.stdout
    start = stdout.find("{")
    if start == -1:
        print(f"  [ERROR] no JSON in output")
        return {}

    try:
        data = json.loads(stdout[start:])
    except json.JSONDecodeError as e:
        print(f"  [ERROR] JSON parse: {e}")
        return {}

    data["_meta"] = {"commit": commit, "label": label,
                     "type": pr_type, "description": description}

    out_path = OUTPUTS_DIR / f"{label}.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    _print_summary(data)
    return data


def _print_summary(data: dict) -> None:
    meta = data.get("_meta", {})
    mode = data.get("mode", "?")
    routing = data.get("router_reasoning", "")
    stats = data.get("diff_stats", {})
    summary = data.get("summary", {})
    retrievals = data.get("retrievals", [])
    excluded = data.get("excluded", [])

    print(f"\n  Mode:     {mode.upper()}")
    print(f"  Router:   {routing}")
    print(f"  Diff:     {stats.get('files_changed','?')} file(s), "
          f"{stats.get('total_lines_changed','?')} lines, "
          f"{len(stats.get('changed_symbols',[]))} symbol(s)  "
          f"[{stats.get('diff_tokens','?')} tokens]")
    print(f"  Budget:   {summary.get('total_context_tokens','?')} / "
          f"{summary.get('budget_used_pct','?')}%")
    print(f"  Items:    {len(retrievals)} retrieved, {len(excluded)} excluded")
    print(f"  Cost:     ${summary.get('estimated_review_cost_usd','?')}")

    sources: dict[str, int] = {}
    for r in retrievals:
        src = r["source"]
        sources[src] = sources.get(src, 0) + 1
    if sources:
        print(f"  Sources:  {', '.join(f'{k}×{v}' for k, v in sources.items())}")

    print(f"\n  Top retrievals:")
    for i, r in enumerate(retrievals[:5], 1):
        print(f"    {i}. [{r['source']:12}] {r['file']}:{r['lines']} "
              f"({r['estimated_tokens']} tok) — {r['reason'][:55]}")
    if excluded:
        print(f"\n  Excluded (first 3):")
        for r in excluded[:3]:
            print(f"    - [{r['source']:12}] {r['file']}:{r['lines']} "
                  f"— {r['reason_excluded'][:55]}")


def print_comparison_table(results: list[dict]) -> None:
    print(f"\n\n{'='*90}")
    print("  EXTENDED EVAL — COMPARISON TABLE")
    print(f"{'='*90}")

    headers = ["Label", "Type", "Mode", "Lines", "Symbols", "Items", "Tok", "Budget%", "Cost$"]
    rows = []
    for data in results:
        if not data:
            rows.append(["ERROR"] + ["-"] * (len(headers) - 1))
            continue
        meta = data.get("_meta", {})
        stats = data.get("diff_stats", {})
        summary = data.get("summary", {})
        rows.append([
            meta.get("label", "?")[:22],
            meta.get("type", "?"),
            data.get("mode", "?").upper(),
            str(stats.get("total_lines_changed", "?")),
            str(len(stats.get("changed_symbols", []))),
            str(len(data.get("retrievals", []))),
            str(summary.get("total_context_tokens", "?")),
            f"{summary.get('budget_used_pct','?')}%",
            f"${summary.get('estimated_review_cost_usd','?')}",
        ])

    col_w = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in col_w)
    print(fmt.format(*headers))
    print("  " + "-" * (sum(col_w) + 2 * len(col_w)))
    for row in rows:
        print(fmt.format(*row))
    print()


def main() -> None:
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"\nExtended eval — 10 additional httpx PRs")
    print(f"API key: {'SET' if has_key else 'NOT SET (agent path falls back to fast)'}")
    print(f"Outputs: {OUTPUTS_DIR}")

    if not HTTPX_REPO.exists():
        print(f"\nERROR: httpx repo not found at {HTTPX_REPO}")
        print("Run: git clone --depth 500 https://github.com/encode/httpx eval/repos/httpx")
        sys.exit(1)

    results = []
    for case in EVAL_CASES:
        data = run_case(*case)
        results.append(data)

    # final safety restore
    branch = get_current_branch(HTTPX_REPO)
    if branch == "HEAD":
        subprocess.run(["git", "checkout", "master", "-q"],
                       cwd=HTTPX_REPO, capture_output=True)

    print_comparison_table(results)
    print(f"Done. JSON outputs saved to {OUTPUTS_DIR}")


if __name__ == "__main__":
    main()
