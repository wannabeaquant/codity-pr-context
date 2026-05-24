from __future__ import annotations
from dataclasses import dataclass
from .retrievers.base import RetrievalResult

TOKEN_BUDGET = 8192


@dataclass
class PackResult:
    packed: list[RetrievalResult]
    excluded: list[dict]  # items computed but not packed, with reason


def rank_and_pack(
    results: list[RetrievalResult], budget: int = TOKEN_BUDGET
) -> PackResult:
    """Sort by priority desc, greedily pack into budget.

    Deduplicates by (file, start_line). Tracks excluded items so the caller
    can report what was intentionally left out — a stated assignment requirement.
    """
    seen: set[tuple[str, int]] = set()
    deduplicated: list[RetrievalResult] = []
    for r in results:
        key = (r.file, r.start_line)
        if key not in seen:
            seen.add(key)
            deduplicated.append(r)

    sorted_results = sorted(deduplicated, key=lambda r: r.priority, reverse=True)

    packed: list[RetrievalResult] = []
    excluded: list[dict] = []
    remaining = budget

    for r in sorted_results:
        if r.estimated_tokens <= remaining:
            packed.append(r)
            remaining -= r.estimated_tokens
        else:
            excluded.append({
                "source": r.source,
                "symbol": r.symbol,
                "file": r.file,
                "lines": f"{r.start_line}-{r.end_line}",
                "estimated_tokens": r.estimated_tokens,
                "priority": r.priority,
                "reason_excluded": (
                    f"Budget cutoff — needed {r.estimated_tokens} tokens, "
                    f"only {remaining} remaining."
                ),
            })

    return PackResult(packed=packed, excluded=excluded)
