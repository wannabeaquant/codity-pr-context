# codity-pr-context — Errors & Failures Log

| Date | What didn't work | What worked instead | Note for next time |
|------|-----------------|--------------------|--------------------|
| 2026-05-24 | Batched all files into one giant initial commit despite files being written incrementally | N/A — already committed, can't undo | Commit after each independently runnable layer (diff parser alone, then fast path after retrievers exist, etc.). Interdependent files that only work together = one commit. Don't wait for the whole feature. |
