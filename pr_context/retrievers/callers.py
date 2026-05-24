from __future__ import annotations
import ast
from pathlib import Path

from ..py_search import search_files
from ..tokenizer import count_tokens
from .base import RetrievalResult

PRIORITY = 0.8
MAX_CALLERS = 5


def get_callers(repo_path: Path, symbol: str) -> list[RetrievalResult]:
    """Find call sites of `symbol` across the repo."""
    # Word-boundary pattern prevents `process(` matching `subprocess(`
    pattern = rf"\b{symbol}\s*\("
    matches = search_files(repo_path, pattern, include_glob="*.py", max_results=50)
    if not matches:
        return []

    # filter out definition lines
    call_matches = [m for m in matches if not _is_definition_line(m.line, symbol)]
    if not call_matches:
        return []

    seen_files: set[str] = set()
    results: list[RetrievalResult] = []

    for match in call_matches:
        if len(results) >= MAX_CALLERS:
            break
        rel_file = match.file.lstrip("./").replace("\\", "/")
        if rel_file in seen_files:
            continue
        seen_files.add(rel_file)

        abs_path = repo_path / rel_file
        if not abs_path.exists():
            continue

        source = abs_path.read_text(encoding="utf-8", errors="replace")
        enclosing = _extract_calling_function(source, match.lineno)
        if enclosing is None:
            file_lines = source.splitlines()
            start = max(0, match.lineno - 3)
            end = min(len(file_lines), match.lineno + 5)
            snippet = "\n".join(file_lines[start:end])
            start_line, end_line = start + 1, end
        else:
            start_line, end_line, snippet = enclosing

        results.append(RetrievalResult(
            source="callers",
            symbol=symbol,
            file=rel_file,
            start_line=start_line,
            end_line=end_line,
            content=snippet,
            reason=f"Call site of `{symbol}` — shows how callers depend on its contract.",
            estimated_tokens=count_tokens(snippet),
            priority=PRIORITY,
        ))

    return results


def _is_definition_line(line: str, symbol: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith(f"def {symbol}")
        or stripped.startswith(f"async def {symbol}")
        or stripped.startswith(f"class {symbol}")
    )


def _extract_calling_function(source: str, lineno: int) -> tuple[int, int, str] | None:
    """Return (start, end, body) of the innermost function containing lineno."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines()
    best: tuple[int, int, str] | None = None
    best_size = float("inf")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = node.end_lineno or node.lineno
            if start <= lineno <= end:
                size = end - start
                if size < best_size:
                    best_size = size
                    content = "\n".join(lines[start - 1:end])
                    best = (start, end, content)

    return best
