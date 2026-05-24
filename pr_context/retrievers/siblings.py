from __future__ import annotations
from pathlib import Path

from ..language.python_adapter import PythonAdapter
from ..tokenizer import count_tokens, truncate_to_tokens
from .base import RetrievalResult

_adapter = PythonAdapter()

PRIORITY = 0.5
MAX_SIBLING_TOKENS = 600  # cap per sibling to avoid crowding the budget
MAX_SIBLINGS = 8


def get_siblings(
    repo_path: Path, source_file: str, changed_symbols: list[str]
) -> list[RetrievalResult]:
    """Return other top-level functions/classes in the same file (not the changed ones)."""
    abs_path = repo_path / source_file
    if not abs_path.exists():
        return []
    if not source_file.endswith(".py"):
        return []

    source = abs_path.read_text(encoding="utf-8", errors="replace")
    all_symbols = _adapter.extract_top_level_symbols(source)

    results: list[RetrievalResult] = []
    changed_set = set(changed_symbols)

    for sym in all_symbols:
        if len(results) >= MAX_SIBLINGS:
            break
        if sym["name"] in changed_set:
            continue

        body = _adapter.get_symbol_body(source, sym["name"])
        if body is None:
            continue

        start_line, end_line, content = body
        content = truncate_to_tokens(content, MAX_SIBLING_TOKENS)
        tokens = count_tokens(content)

        results.append(RetrievalResult(
            source="siblings",
            symbol=sym["name"],
            file=source_file,
            start_line=start_line,
            end_line=end_line,
            content=content,
            reason=f"Sibling `{sym['name']}` in same file — local conventions and helper context.",
            estimated_tokens=tokens,
            priority=PRIORITY,
        ))

    return results
