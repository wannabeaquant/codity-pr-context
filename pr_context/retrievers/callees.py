from __future__ import annotations
from pathlib import Path

from ..language.python_adapter import PythonAdapter
from ..py_search import search_files, CALLEE_BLOCKLIST
from ..tokenizer import count_tokens
from .base import RetrievalResult

_adapter = PythonAdapter()

PRIORITY = 0.9


def get_callees(repo_path: Path, symbol: str, source_file: str) -> list[RetrievalResult]:
    """Find definitions of functions called within `symbol` in `source_file`."""
    abs_path = repo_path / source_file
    if not abs_path.exists():
        return []

    source = abs_path.read_text(encoding="utf-8", errors="replace")
    raw_callees = _adapter.extract_callees(source, symbol)

    # Filter out builtins, common method names, and single-char names that
    # produce near-100% false positives (e.g. dict.get → httpx.get).
    callee_names = [
        name for name in raw_callees
        if name not in CALLEE_BLOCKLIST
        and len(name) >= 3
        and not name.startswith("_")  # skip private helpers — too noisy
    ]
    if not callee_names:
        return []

    results: list[RetrievalResult] = []
    for callee in callee_names:
        # search same file first
        definition = _find_definition(callee, source, source_file)
        if definition:
            results.append(definition)
            continue
        # search repo-wide
        definition = _search_repo(callee, repo_path, source_file)
        if definition:
            results.append(definition)

    return results


def _find_definition(name: str, source: str, rel_file: str) -> RetrievalResult | None:
    body = _adapter.get_symbol_body(source, name)
    if body is None:
        return None
    start_line, end_line, content = body
    return RetrievalResult(
        source="callees",
        symbol=name,
        file=rel_file,
        start_line=start_line,
        end_line=end_line,
        content=content,
        reason=f"Definition of `{name}` — called by the changed function.",
        estimated_tokens=count_tokens(content),
        priority=PRIORITY,
    )


def _search_repo(name: str, repo_path: Path, source_file: str) -> RetrievalResult | None:
    """Find definition of `name` across repo using cross-platform search."""
    # Match top-level def or class at any indentation
    pattern = rf"^(def|async def|class)\s+{re.escape(name)}\b"
    matches = search_files(repo_path, pattern, include_glob="*.py", max_results=5)
    if not matches:
        return None

    # Prefer matches in the same package/directory as the source file
    source_pkg = str(Path(source_file).parent)
    matches.sort(key=lambda m: (0 if source_pkg in m.file else 1, m.file))

    first = matches[0]
    rel_file = first.file  # already normalized by GrepResult.__init__
    lineno = first.lineno

    abs_path = repo_path / rel_file
    if not abs_path.exists():
        return None

    source = abs_path.read_text(encoding="utf-8", errors="replace")
    body = _adapter.get_symbol_body(source, name)
    if body is None:
        # fallback: grab 25 lines from lineno
        file_lines = source.splitlines()
        snippet = "\n".join(file_lines[lineno - 1: lineno + 24])
        return RetrievalResult(
            source="callees",
            symbol=name,
            file=rel_file,
            start_line=lineno,
            end_line=lineno + 24,
            content=snippet,
            reason=f"Definition of `{name}` — called by the changed function.",
            estimated_tokens=count_tokens(snippet),
            priority=PRIORITY - 0.05,
        )

    start_line, end_line, content = body
    return RetrievalResult(
        source="callees",
        symbol=name,
        file=rel_file,
        start_line=start_line,
        end_line=end_line,
        content=content,
        reason=f"Definition of `{name}` — called by the changed function.",
        estimated_tokens=count_tokens(content),
        priority=PRIORITY,
    )


import re  # noqa: E402 — intentionally at bottom to keep imports clean
