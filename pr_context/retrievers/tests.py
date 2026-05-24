from __future__ import annotations
import ast
from pathlib import Path

from ..py_search import search_files
from ..tokenizer import count_tokens
from .base import RetrievalResult

PRIORITY = 0.75
MAX_TESTS = 6


def get_tests(repo_path: Path, symbol: str, source_file: str) -> list[RetrievalResult]:
    """Find test functions that reference `symbol`."""
    pattern = rf"\b{symbol}\b"
    # search only test files by restricting to test directories post-filter
    matches = search_files(repo_path, pattern, include_glob="*.py", max_results=100)
    test_matches = [m for m in matches if _is_test_file(m.file)]
    if not test_matches:
        return []

    seen_functions: set[str] = set()
    results: list[RetrievalResult] = []

    for match in test_matches:
        if len(results) >= MAX_TESTS:
            break
        rel_file = match.file.lstrip("./").replace("\\", "/")
        abs_path = repo_path / rel_file
        if not abs_path.exists():
            continue

        source = abs_path.read_text(encoding="utf-8", errors="replace")
        func = _extract_test_function(source, match.lineno)
        if func is None:
            continue

        start_line, end_line, func_name, content = func
        key = f"{rel_file}:{func_name}"
        if key in seen_functions:
            continue
        seen_functions.add(key)

        results.append(RetrievalResult(
            source="tests",
            symbol=symbol,
            file=rel_file,
            start_line=start_line,
            end_line=end_line,
            content=content,
            reason=f"Test covering `{symbol}` — existing behavioral spec for the changed code.",
            estimated_tokens=count_tokens(content),
            priority=PRIORITY,
        ))

    return results


def _is_test_file(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/")
    name = Path(normalized).name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "/tests/" in normalized
        or "/test/" in normalized
    )


def _extract_test_function(
    source: str, lineno: int
) -> tuple[int, int, str, str] | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = node.end_lineno or node.lineno
            if start <= lineno <= end and node.name.startswith("test"):
                content = "\n".join(lines[start - 1:end])
                return start, end, node.name, content
    return None
