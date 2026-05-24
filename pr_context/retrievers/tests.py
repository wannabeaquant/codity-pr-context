from __future__ import annotations
import subprocess
from pathlib import Path

from ..language.python_adapter import PythonAdapter
from ..tokenizer import count_tokens
from .base import RetrievalResult

_adapter = PythonAdapter()

PRIORITY = 0.75
MAX_TESTS = 6


def get_tests(repo_path: Path, symbol: str, source_file: str) -> list[RetrievalResult]:
    """Find test functions that reference `symbol` or its module."""
    results: list[RetrievalResult] = []

    # search test files for references to the symbol
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py",
             "--include=test_*.py",
             symbol, "."],
            cwd=repo_path,
            capture_output=True, text=True, timeout=15,
        )
        lines = result.stdout.splitlines()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    # filter to files in test dirs or with test prefix/suffix
    test_lines = [l for l in lines if _is_test_file(l)]
    if not test_lines:
        return []

    seen_functions: set[str] = set()

    for line in test_lines:
        if len(results) >= MAX_TESTS:
            break
        parts = line.split(":", 2)
        if len(parts) < 2:
            continue
        rel_file = parts[0]
        try:
            lineno = int(parts[1])
        except (ValueError, IndexError):
            continue

        abs_path = repo_path / rel_file
        if not abs_path.exists():
            continue

        source = abs_path.read_text(encoding="utf-8", errors="replace")
        func = _extract_test_function(source, lineno)
        if func is None:
            continue

        start_line, end_line, func_name, content = func
        key = f"{rel_file}:{func_name}"
        if key in seen_functions:
            continue
        seen_functions.add(key)

        tokens = count_tokens(content)
        results.append(RetrievalResult(
            source="tests",
            symbol=symbol,
            file=rel_file,
            start_line=start_line,
            end_line=end_line,
            content=content,
            reason=f"Test covering `{symbol}` — existing behavioral spec for the changed code.",
            estimated_tokens=tokens,
            priority=PRIORITY,
        ))

    return results


def _is_test_file(grep_line: str) -> bool:
    file_part = grep_line.split(":")[0]
    name = Path(file_part).name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "tests/" in file_part.replace("\\", "/")
        or "test/" in file_part.replace("\\", "/")
    )


def _extract_test_function(
    source: str, lineno: int
) -> tuple[int, int, str, str] | None:
    try:
        import ast
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
