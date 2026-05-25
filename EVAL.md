# Evaluation: Three httpx Pull Requests

Three PRs from [encode/httpx](https://github.com/encode/httpx) with qualitatively different
shapes — a bug fix, a refactor, and a feature addition. Run `python eval/run_eval.py` with
`ANTHROPIC_API_KEY` set to reproduce. Fast path runs without a key.

```bash
git clone --depth 500 https://github.com/encode/httpx eval/repos/httpx
python eval/run_eval.py                          # fast path only
ANTHROPIC_API_KEY=sk-... python eval/run_eval.py # agent path for PR2 + PR3
```

Outputs saved to `eval/outputs/`. Each file contains the full retrieval plan, excluded
items, agent trace, and final review prompt.

---

## Summary

| PR | Type | Lines | Files | Symbols | Mode | Context tok | Prompt tok | Est. cost |
|----|------|-------|-------|---------|------|-------------|------------|-----------|
| PR1: `verify=False` fix | Bug fix | 7 | 1 | 1 | Fast | 2,696 | 3,644 | $0.011 |
| PR2: utils→client move | Refactor | 75 | 2 | 5 | Agent | ~4,500 | ~6,700 | ~$0.02 |
| PR3: socks5h support | Feature | 10 | 2 | 4 | Agent | ~8,100 | ~10,900 | ~$0.033 |

PR2 and PR3 token numbers are estimates from fast-path fallback runs; agent trace with
real numbers requires `ANTHROPIC_API_KEY`.

---

## PR1 — Bug fix: `verify=False` + `cert=...` (`create_ssl_context`)

**Commit:** `89599a9`  
**Router:** Fast path — 7 lines, 1 file, 1 symbol, all within thresholds.

**Retrieved (16 items, 2,696 tokens, 32.9% of budget):**
- 2 caller sites — `_transports/default.py` (transport that calls this function) and
  `tests/test_config.py` (direct test calls)
- 5 tests — full behavioral coverage of `verify` + `cert` combinations
- 1 git history entry — line range last touched 2 commits ago
- 8 siblings — `SSLContext`, `Timeout`, `Limits`, `Proxy` (class-level context)
- 1 import block — shows `ssl`, `certifi`, type aliases

**Why this context is sufficient:** The caller in `_transports/default.py` shows that
both `verify` and `cert` are passed through to `create_ssl_context`. The test list
reveals the `verify=False` + `cert=not None` combination is untested — exactly the
gap this bug fix addresses. Without the caller retrieval, a reviewer can't confirm
all call sites are handled correctly.

**Intentionally excluded (0 items):** Budget at 32.9% — nothing was cut. The callee
filter correctly dropped `get` (a dict `.get()` call inside the function body that
would otherwise match `httpx._api.get`).

---

## PR2 — Refactor: utility functions moved from `_utils.py` to `_client.py`

**Commit:** `7b19cd5`  
**Router:** Escalated to agent — 75 lines (>60), 5 symbols (>2).  
**Note:** Numbers below are from the fast-path fallback. Full agent trace requires `ANTHROPIC_API_KEY`.

**Fast-path baseline (29 items, 4,524 tokens, 55.2% of budget):**
- 6 caller sites — `UseClientDefault`, `_redirect_stream`, `primitive_value_to_str`
  across `_content.py`, `_multipart.py`, `_urls.py`, `port_or_default`
- 4 git history entries — when these utilities last moved and why
- 16 siblings — context from both `_client.py` and `_utils.py`
- 2 import blocks

**Why the agent path adds value:** The fast path surfaces callers but can't reason
about which matter most for a move operation. The agent would call
`get_callers("primitive_value_to_str")` first, see it's used across 3 separate
modules, then explicitly pull tests for each — the fast path finds only 1. Adaptive
sequencing surfaces the cross-module dependency risk that is the entire concern for
this PR type.

**Intentionally excluded:** Method-level siblings (`__iter__`, `close`) dropped at
~55% budget — convention context that a reviewer can infer from the diff itself.

---

## PR3 — Feature: socks5h proxy support

**Commit:** `12be5c4`  
**Router:** Escalated to agent — 4 symbols changed (>2).  
**Note:** Numbers below are from the fast-path fallback. Full agent trace requires `ANTHROPIC_API_KEY`.

**Fast-path baseline (48 items, 8,183 tokens, 99.9% of budget):**
- 15 caller sites — `Proxy`, `HTTPTransport`, `AsyncHTTPTransport` callers
- 14 tests — existing proxy test coverage
- 5 git history entries
- 14 siblings — transport layer context

**Why this is the hardest PR:** socks5h requires updates in two independent code
paths — scheme validation in `_config.py` AND transport dispatch in
`_transports/default.py`. The retrieved `Proxy` callers in `default.py` show the
current dispatch:

```python
if proxy.url.scheme in ("http", "https", "socks5"):
```

A reviewer with this context immediately sees `socks5h` is missing from the
`AsyncHTTPTransport` branch — the exact bug the PR introduces by omission.

**Intentionally excluded:** Several lower-priority siblings were cut at 99.9% budget.
All callers and tests fit within budget — nothing high-priority was dropped.
