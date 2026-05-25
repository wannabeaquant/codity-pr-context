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

    # Diversity-aware greedy knapsack.
    # At each step, pick the item with the highest *adjusted* priority, where
    # adjusted = base_priority - 0.05 * (number of items already packed from same file).
    # This prevents budget saturation by a single file when equally-good results
    # exist across multiple files.
    candidates = list(deduplicated)
    packed: list[RetrievalResult] = []
    excluded: list[dict] = []
    remaining = budget
    file_packed_counts: dict[str, int] = {}

    while candidates:
        # Score each candidate with the current diversity penalty
        best = max(
            candidates,
            key=lambda r: (
                r.priority - 0.05 * file_packed_counts.get(r.file, 0),
                r.priority,           # tiebreak: prefer higher base priority
                -file_packed_counts.get(r.file, 0),  # tiebreak: prefer fresh files
            ),
        )
        candidates.remove(best)

        if best.estimated_tokens <= remaining:
            packed.append(best)
            remaining -= best.estimated_tokens
            file_packed_counts[best.file] = file_packed_counts.get(best.file, 0) + 1
        else:
            excluded.append({
                "source": best.source,
                "symbol": best.symbol,
                "file": best.file,
                "lines": f"{best.start_line}-{best.end_line}",
                "estimated_tokens": best.estimated_tokens,
                "priority": best.priority,
                "reason_excluded": (
                    f"Budget cutoff — needed {best.estimated_tokens} tokens, "
                    f"only {remaining} remaining."
                ),
            })

    return PackResult(packed=packed, excluded=excluded)
