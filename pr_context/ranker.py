from __future__ import annotations
from .retrievers.base import RetrievalResult

TOKEN_BUDGET = 8192


def rank_and_pack(
    results: list[RetrievalResult], budget: int = TOKEN_BUDGET
) -> list[RetrievalResult]:
    """Sort by priority desc, greedily pack into budget. Deduplicates by (file, start_line)."""
    seen: set[tuple[str, int]] = set()
    deduplicated: list[RetrievalResult] = []
    for r in results:
        key = (r.file, r.start_line)
        if key not in seen:
            seen.add(key)
            deduplicated.append(r)

    sorted_results = sorted(deduplicated, key=lambda r: r.priority, reverse=True)

    packed: list[RetrievalResult] = []
    remaining = budget
    for r in sorted_results:
        if r.estimated_tokens <= remaining:
            packed.append(r)
            remaining -= r.estimated_tokens
        if remaining <= 0:
            break

    return packed
