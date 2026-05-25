# Design Document: Intelligent PR Context Retrieval

## Problem

Naive PR review sends either only the diff (misses caller contracts, tests, intent) or
whole files (dilutes model focus, inflates cost). The goal is to maximize useful context
within a token budget — deterministically for simple PRs, adaptively for complex ones.

---

## Architecture

```
                        ┌─► Fast Path   (deterministic, <1s,        ~$0.0001)
PR diff ──► Router ─────┤
                        └─► Agent Path  (Sonnet tool-use loop, ~$0.10–0.30)
                                │
                    JSON retrieval plan + review prompt
```

**Router** — primary: Haiku 4.5 reads the diff and returns `{"mode", "reason"}` (~$0.0001).
Fallback when no API key: three integer thresholds (lines > 60, files > 3, symbols > 2).
Tagged `[LLM router]` or `[heuristic]` in output. Haiku handles edge cases the heuristic
misses: a 5-line API contract change escalates; a 200-line docstring rewrite stays fast.

**Fast path** — runs all retrievers unconditionally, packs results into the 8K token budget
with a diversity-aware greedy knapsack. No LLM calls. Handles ~66% of PRs (sampled from
httpx history). Result: deterministic, auditable, effectively free.

**Agent path** — Claude Sonnet 4.6 with 10 tools decides which retrievers to call and in
what order. Stops when it calls `done`, hits 8 turns, or exceeds the budget. A `note`
scratchpad tool lets the agent record reasoning threads explicitly — these are prepended
to every subsequent tool result so open threads stay visible across turns.

---

## Retrievers and Prioritization

| Tool | What it returns | Priority | Path |
|------|----------------|----------|------|
| `get_callees` | Definitions called by changed code | 0.90 | both |
| `get_callers` | Call sites of changed symbols | 0.80 | both |
| `get_tests` | Tests covering changed symbols | 0.75 | both |
| `read_file` | Targeted line-range read | 0.70 | agent only |
| `get_git_history` | Recent commits on changed lines | 0.60 | both |
| `grep_repo` | Regex search across repo | 0.55 | agent only |
| `get_siblings` | Other top-level defs in same file | 0.50 | both |
| `get_imports` | Import block of changed file | 0.40 | both |

Priority ordering rationale: callees and callers are the primary review questions (what
does the change depend on, and what depends on it). Tests encode the existing behavioral
contract. Git history explains *why* code exists — critical for refactors. Siblings and
imports are low-signal convention context.

**Diversity correction:** the knapsack applies a `−0.05 × same_file_count` penalty at
each step so budget doesn't saturate on one file. A second result from
`_transports/default.py` loses priority to a fresh result from `_config.py` if base
priorities are close.

**Git history** tries `git log -L :symbol:file` first (name-based, survives line shifts),
falls back to line-range log, then `git log --follow -- file`.

---

## Cost Optimization

```
8K context + ~1K diff + ~500 system prompt ≈ 10K input tokens
10K × $3.00/1M (Sonnet input) = $0.03/review
```

| Path | Retrieval cost | Bottleneck |
|------|---------------|------------|
| Fast | ~$0.0001 (router only) | git I/O on cold repo (~200ms) |
| Agent | ~$0.10–0.30 | LLM turns × API latency (~8–45s) |

The fast path makes zero retrieval LLM calls. The 8K budget is tunable via `--budget`.
At 1,000 PRs/day: ~$30/day review cost. The `done` tool is the primary agent cost lever —
the system prompt instructs the agent to call it as soon as context is sufficient.

**Intentionally excluded:** embeddings/vector search (no index maintenance, agent `grep_repo`
achieves the same lookup), whole-file reads (a 2,000-line file consumes 25% of budget).

---

## Failure Modes and Tradeoffs

- **Callee false negatives:** AST misses `getattr` and variable dispatch. `partial(fn, ...)`
  and `wraps(fn)` are now handled via first-arg extraction. The agent's `grep_repo` serves
  as a catch-all for unusual patterns.
- **Test detection:** relies on filename conventions (`test_*.py`, `*_test.py`, `tests/`).
  Unconventional layouts (Django, `spec/`) will miss tests. A `pyproject.toml` parser is the
  v2 fix.
- **Agent hallucination:** incorrect line numbers or symbol names in tool inputs. Each
  retriever returns empty on failure; the agent sees the empty result and self-corrects.
- **Shallow git history:** eval uses `--depth 500`. Full clones give richer context; very
  old codebases may predate meaningful commit messages.

---

## Scaling

| Path | p50 | p95 | Bottleneck |
|------|-----|-----|------------|
| Fast | 200ms | 800ms | `git log -L` on cold repo |
| Agent | 8s | 45s | LLM turns × API latency |

Fast path is stateless and parallel-safe — 1 worker handles ~5 req/s. A warm repo cache
(shallow fetch per PR event) drops git I/O from ~500ms to ~20ms. At 10K PRs/day the agent
path constraint is API rate limits, not compute: pool keys across tenants, exponential
backoff, route overflow to fast path. These warrant separate queues — fast path results
stream immediately, agent results are async with a webhook callback.

Current model stack: Haiku for routing (~$0.0001), Sonnet for agent retrieval
(~$0.10–0.30). At volume, a third tier (Haiku-based agent for moderate PRs) reduces
cost further. `router.py` is already the right hook.

---

*Eval: see [EVAL.md](EVAL.md) for per-PR retrieval breakdown, token counts, and excluded items.*
