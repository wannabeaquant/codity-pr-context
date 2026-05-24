from __future__ import annotations
from pathlib import Path

from .diff_parser import ParsedDiff
from .ranker import rank_and_pack
from .retrievers.base import RetrievalResult
from .retrievers.callees import get_callees
from .retrievers.callers import get_callers
from .retrievers.tests import get_tests
from .retrievers.siblings import get_siblings
from .retrievers.imports import get_imports
from .retrievers.git_history import get_git_history


def run_fast_path(repo_path: Path, diff: ParsedDiff) -> list[RetrievalResult]:
    """Run all retrievers deterministically, then rank and pack to budget."""
    all_results: list[RetrievalResult] = []

    for hunk in diff.hunks:
        if not hunk.file.endswith(".py"):
            continue

        # imports for every changed file (cheap, high signal)
        all_results.extend(get_imports(repo_path, hunk.file))

        # git history for the changed line range
        all_results.extend(get_git_history(
            repo_path, hunk.file, hunk.new_start, hunk.new_start + hunk.new_count
        ))

    for symbol in diff.changed_symbols:
        # find which file the symbol lives in
        source_file = _find_symbol_file(diff, symbol)
        if source_file is None:
            continue

        all_results.extend(get_callees(repo_path, symbol, source_file))
        all_results.extend(get_callers(repo_path, symbol))
        all_results.extend(get_tests(repo_path, symbol, source_file))

    # siblings for each changed file
    for rel_file in diff.changed_files:
        if rel_file.endswith(".py"):
            all_results.extend(get_siblings(repo_path, rel_file, diff.changed_symbols))

    return rank_and_pack(all_results)


def _find_symbol_file(diff: ParsedDiff, symbol: str) -> str | None:
    """Return the first changed file that likely contains `symbol`."""
    for hunk in diff.hunks:
        if hunk.file.endswith(".py"):
            # the symbol is assumed to be in one of the changed files
            return hunk.file
    return None
