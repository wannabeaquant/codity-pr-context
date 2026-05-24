"""
Cross-platform file search utilities.
Tries subprocess (grep/rg) first for speed; falls back to pure Python on Windows
or when the binary is unavailable.
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path

# Names so common in Python (builtins, dunder, dict methods) that treating them
# as "user-defined callees to retrieve" produces only false positives.
CALLEE_BLOCKLIST: frozenset[str] = frozenset({
    # builtins
    "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "type", "print", "range", "enumerate", "zip", "map", "filter", "sorted",
    "reversed", "sum", "min", "max", "abs", "round", "repr", "hash",
    "isinstance", "issubclass", "hasattr", "getattr", "setattr", "delattr",
    "callable", "iter", "next", "open", "super", "vars", "dir", "id",
    "format", "input", "object", "property", "staticmethod", "classmethod",
    # extremely common dict / object method names
    "get", "set", "update", "clear", "copy", "pop", "items", "keys",
    "values", "append", "extend", "insert", "remove", "index", "count",
    "join", "split", "strip", "encode", "decode", "read", "write",
    "close", "flush", "seek", "tell", "lower", "upper", "replace",
    # dunder patterns — short enough to cause noise
    "new", "init", "call", "repr", "str", "eq", "hash",
    # async patterns
    "run", "send", "throw", "aclose",
})


class GrepResult:
    def __init__(self, file: str, lineno: int, line: str):
        self.file = file
        self.lineno = lineno
        self.line = line


def search_files(
    repo_path: Path,
    pattern: str,
    include_glob: str = "*.py",
    context_lines: int = 0,
    max_results: int = 50,
    word_boundary: bool = False,
) -> list[GrepResult]:
    """Search repo for pattern. Tries rg/grep first, falls back to Python."""
    if word_boundary:
        pattern = rf"\b{re.escape(pattern)}\b" if not pattern.startswith(r"\b") else pattern

    results = _try_rg(repo_path, pattern, include_glob, max_results)
    if results is None:
        results = _try_grep(repo_path, pattern, include_glob, max_results)
    if results is None:
        results = _py_search(repo_path, pattern, include_glob, max_results)
    return results or []


def _try_rg(
    repo_path: Path, pattern: str, include_glob: str, max_results: int
) -> list[GrepResult] | None:
    try:
        result = subprocess.run(
            ["rg", "--no-heading", "-n", f"--glob={include_glob}", pattern, "."],
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
        if result.returncode not in (0, 1):
            return None
        return _parse_grep_output(result.stdout, max_results)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _try_grep(
    repo_path: Path, pattern: str, include_glob: str, max_results: int
) -> list[GrepResult] | None:
    try:
        result = subprocess.run(
            ["grep", "-rn", f"--include={include_glob}", "-E", pattern, "."],
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
        if result.returncode not in (0, 1):
            return None
        return _parse_grep_output(result.stdout, max_results)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _py_search(
    repo_path: Path, pattern: str, include_glob: str, max_results: int
) -> list[GrepResult]:
    """Pure Python fallback — works on all platforms."""
    try:
        regex = re.compile(pattern)
    except re.error:
        regex = re.compile(re.escape(pattern))

    # convert glob to suffix filter (handles *.py, test_*.py)
    suffix = include_glob.lstrip("*") if "*" in include_glob else None

    results: list[GrepResult] = []
    for path in repo_path.rglob(include_glob):
        if len(results) >= max_results:
            break
        if suffix and not path.name.endswith(suffix.lstrip(".")):
            continue
        try:
            for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    rel = str(path.relative_to(repo_path)).replace("\\", "/")
                    results.append(GrepResult(f"./{rel}", i, line))
                    if len(results) >= max_results:
                        break
        except (OSError, PermissionError):
            continue
    return results


def _parse_grep_output(output: str, max_results: int) -> list[GrepResult]:
    results = []
    for line in output.splitlines():
        if len(results) >= max_results:
            break
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        try:
            results.append(GrepResult(parts[0], int(parts[1]), parts[2]))
        except ValueError:
            continue
    return results
