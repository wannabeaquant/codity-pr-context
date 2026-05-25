from __future__ import annotations
from pathlib import Path

from ..py_search import search_files
from ..tokenizer import count_tokens
from .base import RetrievalResult

PRIORITY = 0.55
MAX_RESULTS = 8
CONTEXT_LINES = 3


def grep_repo(
    repo_path: Path, pattern: str, reason: str = "", symbol: str = ""
) -> list[RetrievalResult]:
    """Search repo for `pattern`, returning context around each match."""
    matches = search_files(repo_path, pattern, include_glob="*.py", max_results=MAX_RESULTS * 3)
    if not matches:
        return []

    results: list[RetrievalResult] = []
    seen_files: set[str] = set()

    for match in matches:
        if len(results) >= MAX_RESULTS:
            break
        rel_file = match.file  # already normalized by GrepResult.__init__
        if rel_file in seen_files:
            continue
        seen_files.add(rel_file)

        abs_path = repo_path / rel_file
        if not abs_path.exists():
            continue

        lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, match.lineno - 1 - CONTEXT_LINES)
        end = min(len(lines), match.lineno + CONTEXT_LINES)
        content = "\n".join(lines[start:end])

        results.append(RetrievalResult(
            source="grep_repo",
            symbol=symbol or pattern,
            file=rel_file,
            start_line=start + 1,
            end_line=end,
            content=content,
            reason=reason or f"grep match for `{pattern}`",
            estimated_tokens=count_tokens(content),
            priority=PRIORITY,
        ))

    return results
