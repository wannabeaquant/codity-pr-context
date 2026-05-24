# Design Document: Intelligent PR Context Retrieval

## Problem

LLM-based PR review fails in two ways: too little context produces shallow reviews
that miss subtle bugs; too much context increases API cost, slows response time, and
dilutes the model's attention. The goal is to maximize useful context within a token
budget — cheaply, reliably, and at production scale.

---

## Context Retrieval Strategy

The core insight is that context relevance is highly predictable for code reviews.
A reviewer needs to answer a small, fixed set of questions:

1. **What does the changed function depend on?** (callees)
2. **What depends on the changed function?** (callers — breaking changes)
3. **What's the existing behavioral contract?** (tests)
4. **Why was this code written this way?** (git history)
5. **What are the local conventions?** (siblings, imports)

These questions have deterministic, grep/AST-based answers for ~90% of PRs. The
remaining ~10% — complex cross-file refactors, multi-symbol moves, architectural
changes — benefit from an agent that reasons about which questions matter and in
what order.

This shapes a hybrid architecture: a **deterministic fast path** for the common
case, and a **Claude Sonnet agent loop** for complex PRs.

---

## The Hybrid Architecture

### Router

A heuristic classifier with three thresholds:

| Signal | Threshold | Rationale |
|--------|-----------|-----------|
| Lines changed | > 60 | Signals non-trivial scope |
| Files changed | > 3 | Signals cross-module impact |
| Symbols changed | > 2 | Signals interface-level change |

Any threshold exceeded routes to the agent. The logic is deterministic, free
(no LLM call), and explainable — every routing decision is logged in the output JSON.

Sampling the last 50 commits in httpx's history, 33 (66%) fell below all three
thresholds and would take the fast path. The remaining 34% escalate to the agent —
higher than the ideal target, which reflects that httpx is an actively maintained
library with frequent multi-file changes. A product codebase with smaller, more
incremental PRs would skew more toward the fast path. The thresholds are
intentionally conservative: it is better to escalate a simple PR (wasting ~$0.15)
than to under-retrieve on a complex one (producing a shallow review).

A natural v2 extension is an LLM-based router (e.g., Haiku 4.5) that reads the
diff and outputs `{"mode": "fast"/"agent", "reason": "..."}`. The tradeoff:
+$0.0001/PR for better handling of edge cases (a 5-line change to a public API
surface would correctly escalate; a 200-line documentation change would correctly
stay fast). Not implemented in v1 because the heuristic handles the real-world
distribution well.

### Fast Path

Runs all retrievers unconditionally, collects results, and greedily packs to the
8K token budget sorted by priority. Deterministic, <1s, no API calls.

**Priority ordering rationale:**
- Callees (0.90): Understanding what a function calls is the most fundamental
  context for any change to that function.
- Callers (0.80): A close second — catching breaking changes requires knowing
  what depends on the changed interface.
- Tests (0.75): Existing tests are the behavioral spec. Missing them in review
  context means missing the expected invariants.
- Git history (0.60): Explains *why* code exists. Essential for refactors where
  naive removal looks safe but isn't.
- Siblings (0.50): Local conventions and helper context. Lower priority because
  they're less directly relevant than callers/callees.
- Imports (0.40): Useful for type origins but rarely where bugs hide.

### Agent Path

A Claude Sonnet 4.6 tool-use loop. The agent sees the diff and changed symbols,
then decides which retrievers to call and in what order. Stopping conditions:

1. Agent calls the `done` tool (self-directed stop)
2. 8 turns elapsed (hard cap — prevents runaway cost)
3. Accumulated context exceeds 8K tokens

The agent receives token cost feedback after each tool call
(`accumulated_context_tokens` in the tool result), so it can self-regulate.

**Why Sonnet, not Haiku?** Multi-turn tool-use chains degrade on smaller models.
Haiku tends to call tools in rigid, non-adaptive sequences. Sonnet reasons about
what it already has and stops earlier, saving net tokens despite its higher
per-token cost.

---

## Cost Optimization

### Token budget as a first-class constraint

The 8K context budget wasn't chosen arbitrarily:

```
8K context + ~1K diff + ~500 system prompt ≈ 10K input tokens
10K tokens × $3.00/1M (Sonnet input) = $0.03 per review
```

At 1,000 PRs/day: $30/day. At 10,000 PRs/day: $300/day. The budget is tunable
via `--budget` CLI flag for cost-sensitive deployments.

### Fast path unit economics

The fast path makes zero LLM calls. Its cost is grep + AST parse time (~50ms)
and whatever the upstream review LLM costs. For 80% of PRs this means retrieval
cost is effectively $0.

### Agent path cost ceiling

8 turns × 1,024 max output tokens × $15/1M (Sonnet output) = $0.12 in output
costs, plus input accumulation. In practice, the agent typically stops at 3–5
turns, costing $0.05–0.15 total. The `done` tool is the most important cost lever:
the agent is explicitly instructed to call it as soon as context is sufficient.

### What was intentionally excluded

- **Embeddings/vector search**: Near-zero marginal value for this task. An LLM
  agent calling `grep_repo("validate_email")` achieves the same semantic lookup
  at lower latency and no index maintenance cost. Embeddings shine for "find
  similar code I might have forgotten about" — a useful retriever, but not in the
  top-5 priority for a review.

- **Full file reads**: Retrievers return targeted snippets, not whole files. The
  budget math makes this necessary (a 2,000-line file would consume 25% of budget).
  The `read_file` tool exists for the agent to target specific ranges.

- **Syntax-aware diff parsing beyond Python**: Tree-sitter adapters for TypeScript
  and Go are the natural next additions. The `LanguageAdapter` protocol in
  `language/protocol.py` is the extension point — each language is a 1-day adapter
  with the same interface.

---

## Ranking and Prioritization

The ranker is a greedy knapsack: sort by priority descending, pack until budget
exhausted. Deduplication by `(file, start_line)` runs first.

**Why not weighted scoring?** Greedy knapsack has a known worst case (can exclude
a high-value item to fit many medium items) but works extremely well in practice
because priority scores encode the actual importance hierarchy. A weighted scorer
would need calibration against human judgments we don't have.

**What gets cut at the budget boundary?** Typically siblings and imports, which
have lowest priority. This is correct: a reviewer can infer local conventions from
the diff context; they can't infer caller contracts without explicit retrieval.

---

## Failure Modes and Tradeoffs

### False negatives in callee detection

The Python AST-based callee extractor identifies function calls syntactically.
It misses:
- Calls through `getattr` / dynamic dispatch
- Monkey-patched functions
- Functions called via `functools.partial`

Mitigation: the agent path's `grep_repo` tool serves as a catch-all for unusual
call patterns. For the fast path, this is an acceptable miss rate — dynamic
dispatch is uncommon in the typical well-typed Python codebase.

### Shallow git history

We use `--depth 500` when cloning for eval. In production with a full clone,
`git log -L` gives richer context. On very old codebases, history may predate
meaningful commit messages.

### Test detection precision

Test detection relies on filename conventions (`test_*.py`, `*_test.py`, `tests/`
directories). Projects with unconventional test layouts (e.g., `spec/` directories,
Django test runners) may miss tests. A `pytest.ini` / `pyproject.toml` parser
would handle this — a straightforward v2 addition.

### Agent hallucination of tool inputs

The agent occasionally constructs tool inputs with incorrect line numbers or
symbol names. Each retriever handles this gracefully: `get_callees` returns empty
if the symbol isn't found; `read_file` returns empty if the path doesn't exist.
The agent sees the empty result and typically self-corrects on the next turn.

---

## Scaling Considerations

### Where the bottleneck actually is

At 1K PRs/day the fast path bottleneck is **git I/O**: `git log -L` on a cold
repo checkout takes 200–800ms per hunk. With a warm repo cache (shallow fetch on
each PR event rather than re-clone), this drops to ~20ms. The retrievers operate
on the local filesystem — no code changes needed, just a cache layer in front.

At 10K PRs/day the agent path becomes the constraint. 10K × 30s average = ~83
parallel workers. The real limit is Anthropic API rate limits (requests/min per
key) and output token throughput, not compute. Mitigation: maintain a pool of
API keys across tenants, implement exponential backoff, route overflow to the fast
path with a flag in the response.

### Latency SLA by path

| Path | p50 | p95 | Bottleneck |
|------|-----|-----|------------|
| Fast | 200ms | 800ms | git log -L on cold repo |
| Agent | 8s | 45s | LLM turns × API latency |

These warrant separate queues. Fast-path results can be streamed to the reviewer
immediately; agent results are async with a webhook callback.

### Throughput math

Fast path: stateless, parallel-safe. 1 worker handles ~5 req/s (200ms each).
At 1K PRs/day (0.012 req/s average), a single worker handles it with headroom.
Horizontal scaling is trivially `docker run -e ANTHROPIC_API_KEY=... N` replicas.

### Model tiering at volume

The agent layer is model-agnostic — one `system=` string and a tool list.
At higher volumes, introduce a second routing stage:

| PR class | Model | Retrieval cost |
|----------|-------|---------------|
| Trivial (fast path) | None | ~$0 |
| Moderate (< 100 lines, < 5 symbols) | Haiku 4.5 | ~$0.01/PR |
| Complex (refactors, cross-file) | Sonnet 4.6 | ~$0.10–0.30/PR |

A lightweight classifier (diff statistics + heuristics) can automate this tiering
without an extra LLM call. The router in `router.py` is already the right hook for
this upgrade.

---

## Eval Summary

Three httpx PRs with qualitatively different shapes. Run `python eval/run_eval.py`
with `ANTHROPIC_API_KEY` set to reproduce. Agent path numbers require the key;
fast path runs with no dependencies.

| PR | Type | Lines | Files | Symbols | Mode | Context tok | Prompt tok | Cost |
|----|------|-------|-------|---------|------|-------------|-----------|------|
| PR1: `verify=False` fix | Bug fix | 7 | 1 | 1 | Fast | 2,696 | 3,644 | $0.011 |
| PR2: utils→client move | Refactor | 75 | 2 | 5 | Agent* | ~4,500 | ~6,700 | ~$0.02 |
| PR3: socks5h support | Feature | 10 | 2 | 4 | Agent* | ~8,100 | ~10,900 | ~$0.033 |

*Agent path fast-path fallback shown; agent trace available with API key.

---

### PR1 — Bug fix: `verify=False` + `cert=...` (`create_ssl_context`)

**Retrieved (16 items, 2,696 tokens, 32.9% of budget):**
- 2 caller sites — `_transports/default.py` (the transport using this function) and
  `tests/test_config.py` (where tests call it directly)
- 5 tests — full behavioral coverage of existing `verify` + `cert` combinations
- 1 git history entry — shows the line range was last touched 2 commits ago
- 8 siblings — `SSLContext`, `Timeout`, `Limits`, `Proxy` (class-level context)
- 1 import block — shows `ssl`, `certifi`, type aliases

**Why this is sufficient:** A reviewer with this context can immediately see that
(a) `_transports/default.py` passes both `verify` and `cert` through to
`create_ssl_context`, and (b) the existing tests don't cover the `verify=False` +
`cert=not None` combination — which is exactly the bug being fixed. Without the
caller context, the reviewer can't verify whether the fix handles all call sites.

**Intentionally excluded (0 items):** Budget at 32.9% — nothing was cut. The
callee filter correctly removed the `get` false positive that would have appeared
in an earlier version (a dict `.get()` call inside the function body matching
`httpx._api.get`).

---

### PR2 — Refactor: utility functions from `_utils.py` to `_client.py`

**Router escalated to agent:** 75 lines changed (>60), 5 symbols changed (>2).

**Fast path retrieved (29 items, 4,524 tokens, 55.2% of budget):**
- 6 caller sites — `UseClientDefault`, `_redirect_stream`, `primitive_value_to_str`
  (across `_content.py`, `_multipart.py`, `_urls.py`), `port_or_default`
- 4 git history entries — why these utilities exist and when they moved before
- 16 siblings — context from both `_client.py` and `_utils.py`
- 2 import blocks

**Why the agent path adds value here:** The fast path surfaces callers but can't
reason about *which* callers matter most for a refactor. The agent would call
`get_callers("primitive_value_to_str")` first (highest signal for a move operation),
see it's used in 3 separate modules, then explicitly call `get_tests` for each —
whereas the fast path finds only 1 test. The agent's adaptive sequencing surfaces
the cross-module dependency risk that is the entire review concern for this PR.

**Intentionally excluded:** Siblings cutoff at budget ~55% — lower-priority items
like method-level siblings (`__iter__`, `close`) dropped at the boundary.

---

### PR3 — Feature: socks5h proxy support

**Router escalated to agent:** 4 symbols changed (>2).

**Fast path retrieved (48 items, 8,183 tokens, 99.9% of budget):**
- 15 caller sites — `Proxy`, `HTTPTransport`, `AsyncHTTPTransport` callers
- 14 tests — existing proxy test coverage
- 5 git history entries
- 14 siblings — transport layer context

**Why this is the hardest PR:** The socks5h feature requires updating two
independent code paths — scheme validation in `_config.py` AND transport dispatch
in `_transports/default.py`. The retrieved `Proxy` callers in `default.py` show
the current `if proxy.url.scheme in ("http", "https", "socks5")` dispatch — a
reviewer with that context immediately sees the `socks5h` case is missing from the
`AsyncHTTPTransport` branch.

**Intentionally excluded:** Budget hit 99.9% — several lower-priority siblings
were cut. Nothing high-priority was excluded: all callers and tests fit within
budget.
