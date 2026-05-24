# codity-pr-context — Session Memory

## Decisions
| Date | Decision | Why | What was rejected |
|------|----------|-----|-------------------|
| 2026-05-24 | Python-only AST retrievers behind LanguageAdapter protocol | 2-3 day budget; polyglot = half-implemented in 3 langs vs fully-implemented in 1 | Polyglot from day one |
| 2026-05-24 | No embeddings/vector DB | AST+grep+git covers 90% of signal at near-zero cost; agent handles the rest semantically via tool calls | RAG pipeline with pgvector |
| 2026-05-24 | Hybrid agent + fast path, not agent-only | Cost: fast path ~$0.001/PR, agent ~$0.10-0.30/PR; trivial PRs don't need agent | Agent-only (expensive, slow for trivial PRs) |
| 2026-05-24 | Heuristic router (lines/files/symbols count) | Free, deterministic, explainable; LLM router adds latency + failure mode | LLM-based router (Haiku) |
| 2026-05-24 | Raw Anthropic SDK, no framework | Clean loop in ~60 lines; frameworks add abstraction on top of tool-use we control directly | LangChain, LlamaIndex |
| 2026-05-24 | Eval on httpx (encode/httpx) | Well-known Python repo, manageable size, real bugs, pure Python | Own repos (Chaitanya can't sanity-check), FastAPI (too large) |
| 2026-05-24 | Stop before the review LLM call | Deliverable is the retrieval/context, not the review itself; avoids extra cost during evals | Running full review end-to-end |

## Session Logs

## Next Session Priorities
