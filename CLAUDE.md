# codity-pr-context

## Project
Intern assignment for Codity.ai. Hybrid PR context retrieval system for LLM code review.
Given a PR diff and a repo checkout, determines what additional context (callees, callers,
tests, type defs, git history) to send to an LLM for high-quality review — while minimizing
token cost. Hybrid: deterministic fast path for trivial PRs, agent loop for complex ones.

## Stack
Python 3.11+, Anthropic SDK (Claude Sonnet 4.6 for agent, Haiku 4.5 for nothing currently),
tiktoken, unidiff, gitpython, click.

## Commands
- Install: `pip install -r requirements.txt`
- Run: `python -m pr_context <repo_path> <diff_path>`
- Run (JSON out): `python -m pr_context <repo_path> <diff_path> --json`
- Eval: `python eval/run_eval.py`
- Tests: `pytest tests/`

## Architecture
```
PR diff -> diff_parser -> router -> fast path OR agent path -> JSON plan + prompt
                                         |                          |
                               ranker + greedy pack        tool-use loop (Claude Sonnet)
                                         |                          |
                               retrieval results          retrieval results + agent trace
```

Retrievers are pure functions: (repo_path, symbol, ...) -> RetrievalResult.
They are also exposed as tools to the Claude agent.
Token budget: 8192 tokens for packed context, hard cap.
Router: heuristic (lines > 60 OR files > 3 OR symbols > 2 -> agent).

## Conventions
- All retrievers return `RetrievalResult` (see retrievers/base.py)
- Token estimation via tiktoken cl100k_base (~5% off Claude actual — acceptable)
- Retrievers never call the LLM. Only agent/loop.py does.
- Language support via LanguageAdapter protocol. Python is implemented. Others stubbed.
- All file paths in results are relative to repo root

## GitHub
https://github.com/wannabeaquant/codity-pr-context — push after every commit.

## Git & Commits
- Format: `<type>(<scope>): <short imperative description>`
- Every self-contained working change = one commit. Push after every commit.

## Session Memory
- Read MEMORY.md at session start.
- On session end: write summary to MEMORY.md.

## Error Log
- Read ERRORS.md before suggesting approaches.
- Log failures after 2+ attempts to ERRORS.md.
