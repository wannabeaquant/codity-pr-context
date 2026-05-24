from __future__ import annotations
from pathlib import Path

from .diff_parser import ParsedDiff
from .ranker import rank_and_pack, PackResult
from .retrievers.base import RetrievalResult
from .retrievers.callees import get_callees
from .retrievers.callers import get_callers
from .retrievers.tests import get_tests
from .retrievers.siblings import get_siblings
from .retrievers.imports import get_imports
from .retrievers.git_history import get_git_history


def run_fast_path(repo_path: Path, diff: ParsedDiff) -> PackResult:
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
        source_file = _find_symbol_file(repo_path, diff, symbol)
        if source_file is None:
            continue

        all_results.extend(get_callees(repo_path, symbol, source_file))
        all_results.extend(get_callers(repo_path, symbol))
        all_results.extend(get_tests(repo_path, symbol, source_file))

    # siblings for each changed file
    for rel_file in diff.changed_files:
        if rel_file.endswith(".py"):
            all_results.extend(get_siblings(repo_path, rel_file, diff.changed_symbols))

    return rank_and_pack(all_results)  # returns PackResult


def _find_symbol_file(repo_path: Path, diff: ParsedDiff, symbol: str) -> str | None:
    """Return the changed file that actually defines `symbol`.

    Parses each changed .py file with AST to find the one that contains the
    symbol definition. Falls back to the first .py file if not found — handles
    cases where the file hasn't been written to disk at parse time.
    """
    import ast as _ast
    first_py: str | None = None

    for rel_file in dict.fromkeys(h.file for h in diff.hunks):
        if not rel_file.endswith(".py"):
            continue
        if first_py is None:
            first_py = rel_file

        abs_path = repo_path / rel_file
        if not abs_path.exists():
            continue
        try:
            source = abs_path.read_text(encoding="utf-8", errors="replace")
            tree = _ast.parse(source)
        except (SyntaxError, OSError):
            continue

        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                if node.name == symbol:
                    return rel_file

    return first_py
