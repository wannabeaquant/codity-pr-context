# codity-pr-context

Hybrid context retrieval for LLM-powered PR review. Given a PR diff and a repo checkout,
determines what additional context (callees, callers, tests, git history, type definitions)
to send to an LLM — while staying within a token budget.

## Architecture

```
PR diff
   │
   ▼
┌─────────────┐   lines>60 OR files>3 OR symbols>2
│   Router    │─────────────────────────────────────► Agent Path
│ (heuristic) │                                       (Claude Sonnet tool-use loop)
└─────────────┘                                              │
   │ otherwise                                               │
   ▼                                                         │
Fast Path                                                    │
(all retrievers, rank + pack)                                │
   │                                                         │
   └─────────────────────────────────────────────────────────┘
                          │
                          ▼
              JSON retrieval plan + review prompt
```

**Fast path**: deterministic, runs all retrievers in parallel, greedily packs to 8K token budget.
~$0.001 in retrieval cost. Used for 80%+ of PRs.

**Agent path**: Claude Sonnet with 9 tools, iterates until it decides context is sufficient or
hits 8 turns / budget cap. Handles complex cross-file refactors where the right context isn't
obvious upfront. ~$0.10–0.30/PR.

## Retrievers

| Tool | What it returns | Priority |
|------|----------------|----------|
| `get_callees` | Definitions of functions called by changed code | 0.90 |
| `get_callers` | Call sites of changed symbols | 0.80 |
| `get_tests` | Test functions referencing changed symbols | 0.75 |
| `get_git_history` | Recent commits on changed line ranges | 0.60 |
| `get_siblings` | Other top-level defs in the same file | 0.50 |
| `get_imports` | Import block of the changed file | 0.40 |
| `grep_repo` | Regex search (agent only, ad-hoc) | 0.55 |
| `read_file` | Direct line-range read (agent only) | 0.70 |

## Quickstart

```bash
git clone https://github.com/wannabeaquant/codity-pr-context
cd codity-pr-context
python -m venv venv && source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# get a diff (or use your own)
git diff main..feature-branch > my_pr.diff

# run — fast path (no API key needed)
python -m pr_context /path/to/repo my_pr.diff

# run — agent path enabled
ANTHROPIC_API_KEY=sk-... python -m pr_context /path/to/repo my_pr.diff

# force a specific mode
python -m pr_context /path/to/repo my_pr.diff --mode fast
python -m pr_context /path/to/repo my_pr.diff --mode agent

# JSON output (pipe to jq, save to file, etc.)
python -m pr_context /path/to/repo my_pr.diff --json-out > plan.json
```

## Output

```json
{
  "mode": "fast",
  "router_reasoning": "Fast path: 7 lines, 1 file(s), 1 symbol(s) — within thresholds.",
  "diff_stats": { "files_changed": 1, "total_lines_changed": 7, "changed_symbols": ["create_ssl_context"] },
  "retrievals": [
    {
      "source": "callers",
      "symbol": "create_ssl_context",
      "file": "httpx/_transports/default.py",
      "lines": "136-215",
      "reason": "Call site of `create_ssl_context` — shows how callers depend on its contract.",
      "estimated_tokens": 662,
      "priority": 0.8
    }
  ],
  "summary": {
    "retrieved_count": 18,
    "total_context_tokens": 3284,
    "total_prompt_tokens": 4316,
    "estimated_review_cost_usd": 0.01295,
    "budget_used_pct": 40.1
  },
  "agent_trace": [],
  "final_prompt": "..."
}
```

## Running the eval

```bash
# clone httpx eval repo (done once)
git clone --depth 200 https://github.com/encode/httpx eval/repos/httpx

# run eval (fast path — no API key needed)
python eval/run_eval.py

# run eval with agent path
ANTHROPIC_API_KEY=sk-... python eval/run_eval.py
```

Outputs saved to `eval/outputs/`.

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

## Design

See [DESIGN.md](DESIGN.md) for the full design document.
