# codity-pr-context

Hybrid context retrieval for LLM-powered PR review. Given a PR diff and a repo checkout,
determines what additional context (callees, callers, tests, git history, type definitions)
to send to an LLM — while staying within a token budget.

## Architecture

```
PR diff
   │
   ▼
┌──────────────────────┐   agent  ┌──────────────────────────────────────┐
│   Router             │─────────►│  Agent Path                          │
│ Haiku LLM (primary)  │          │  Claude Sonnet tool-use loop         │
│ heuristic (fallback) │          │  10 tools, up to 8 turns             │
└──────────────────────┘          └──────────────────────────────────────┘
   │ fast                                        │
   ▼                                             │
Fast Path                                        │
(all retrievers, diversity-aware pack)           │
   │                                             │
   └─────────────────────────────────────────────┘
                          │
                          ▼
              JSON retrieval plan + review prompt
```

**Fast path**: deterministic, runs all retrievers, packs to 8K budget with diversity-aware
knapsack. ~$0.0001 router call + zero retrieval cost. Used for ~66% of PRs.

**Agent path**: Claude Sonnet with 10 tools (including `note` scratchpad), iterates until
context is sufficient or hits 8 turns / budget cap. Handles complex cross-file refactors.
~$0.10–0.30/PR.

## Retrievers

| Tool | What it returns | Priority | Path |
|------|----------------|----------|------|
| `get_callees` | Definitions of functions called by changed code | 0.90 | both |
| `get_callers` | Call sites of changed symbols | 0.80 | both |
| `get_tests` | Test functions referencing changed symbols | 0.75 | both |
| `read_file` | Direct line-range read | 0.70 | agent only |
| `get_git_history` | Recent commits on changed line ranges | 0.60 | both |
| `grep_repo` | Regex search across repo | 0.55 | agent only |
| `get_siblings` | Other top-level defs in the same file | 0.50 | both |
| `get_imports` | Import block of the changed file | 0.40 | both |

## Requirements

- Python >= 3.9
- `ANTHROPIC_API_KEY` — used by the LLM router and agent path; fast path runs without it
  (router falls back to heuristics when key is absent)

## Quickstart

```bash
git clone https://github.com/wannabeaquant/codity-pr-context
cd codity-pr-context

# create venv
python -m venv venv
source venv/bin/activate        # bash/zsh
# venv\Scripts\Activate.ps1    # PowerShell
# venv\Scripts\activate.bat    # cmd

pip install -r requirements.txt

# get a diff (or use your own)
git diff main..feature-branch > my_pr.diff

# run — auto mode (fast path if small PR, agent if complex)
python -m pr_context /path/to/repo my_pr.diff

# run with agent path enabled
ANTHROPIC_API_KEY=sk-... python -m pr_context /path/to/repo my_pr.diff

# force a specific mode: auto (default) | fast | agent
python -m pr_context /path/to/repo my_pr.diff --mode fast
python -m pr_context /path/to/repo my_pr.diff --mode agent

# JSON output
python -m pr_context /path/to/repo my_pr.diff --json-out > plan.json

# custom token budget (default: 8192)
python -m pr_context /path/to/repo my_pr.diff --budget 4096
```

## Output

```json
{
  "mode": "fast",
  "router_reasoning": "[LLM router] Single-function bug fix with no interface changes — fast path is sufficient.",
  "diff_stats": {
    "files_changed": 1,
    "total_lines_changed": 7,
    "changed_symbols": ["create_ssl_context"],
    "diff_tokens": 194
  },
  "retrievals": [
    {
      "source": "callers",
      "symbol": "create_ssl_context",
      "file": "httpx/_transports/default.py",
      "lines": "136-215",
      "reason": "Call site of `create_ssl_context` — shows how callers depend on its contract.",
      "estimated_tokens": 662,
      "priority": 0.8,
      "content": "..."
    }
  ],
  "excluded": [
    {
      "source": "siblings",
      "symbol": "Proxy",
      "file": "httpx/_config.py",
      "lines": "202-244",
      "estimated_tokens": 357,
      "priority": 0.5,
      "reason_excluded": "Budget cutoff — needed 357 tokens, only 120 remaining."
    }
  ],
  "summary": {
    "retrieved_count": 16,
    "excluded_count": 2,
    "total_context_tokens": 2696,
    "total_prompt_tokens": 3644,
    "estimated_review_cost_usd": 0.01093,
    "budget_used_pct": 32.9
  },
  "agent_trace": [],
  "final_prompt": "..."
}
```

`excluded` lists items that were retrieved but cut at the budget boundary, with the
specific reason. This makes the retrieval auditable — you can see exactly what was
left out and why.

## Running the eval

```bash
# clone httpx eval repo (done once)
# --depth 500 ensures all 3 eval commits are reachable
git clone --depth 500 https://github.com/encode/httpx eval/repos/httpx

# run eval — fast path only, no API key needed
python eval/run_eval.py

# run eval with agent path (PR2 and PR3 will use Claude Sonnet)
ANTHROPIC_API_KEY=sk-... python eval/run_eval.py
```

Outputs saved to `eval/outputs/`. Each PR produces a JSON file with the full
retrieval plan, excluded items, agent trace (if agent path ran), and the final
review prompt.

## Running tests

```bash
pytest tests/ -v   # 26 tests, no API key needed
```

## Design

See [DESIGN.md](DESIGN.md) for: retrieval strategy, ranking rationale, cost math,
failure modes, scaling analysis, and per-PR eval breakdown.
