from __future__ import annotations
import subprocess
from pathlib import Path

from ..language.python_adapter import PythonAdapter
from ..tokenizer import count_tokens
from .base import RetrievalResult

_adapter = PythonAdapter()

PRIORITY = 0.8
MAX_CALLERS = 5  # cap to avoid drowning the budget


def get_callers(repo_path: Path, symbol: str) -> list[RetrievalResult]:
    """Find call sites of `symbol` across the repo."""
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", f"{symbol}(", "."],
            cwd=repo_path,
            capture_output=True, text=True, timeout=15,
        )
        lines = [l for l in result.stdout.splitlines() if l]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    # filter out lines that are the definition itself
    call_lines = [l for l in lines if not _is_definition_line(l, symbol)]
    if not call_lines:
        return []

    # dedupe by file, take up to MAX_CALLERS
    seen_files: set[str] = set()
    results: list[RetrievalResult] = []

    for line in call_lines:
        if len(results) >= MAX_CALLERS:
            break
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        rel_file, lineno_str, _ = parts
        if rel_file in seen_files:
            continue
        seen_files.add(rel_file)

        try:
            lineno = int(lineno_str)
        except ValueError:
            continue

        abs_path = repo_path / rel_file
        if not abs_path.exists():
            continue

        source = abs_path.read_text(encoding="utf-8", errors="replace")
        snippet = _extract_calling_function(source, lineno)
        if snippet is None:
            file_lines = source.splitlines()
            start = max(0, lineno - 3)
            end = min(len(file_lines), lineno + 5)
            snippet = "\n".join(file_lines[start:end])
            start_line, end_line = start + 1, end
        else:
            start_line, end_line, snippet = snippet

        tokens = count_tokens(snippet)
        results.append(RetrievalResult(
            source="callers",
            symbol=symbol,
            file=rel_file,
            start_line=start_line,
            end_line=end_line,
            content=snippet,
            reason=f"Call site of `{symbol}` — shows how callers depend on its contract.",
            estimated_tokens=tokens,
            priority=PRIORITY,
        ))

    return results


def _is_definition_line(line: str, symbol: str) -> bool:
    content = line.split(":", 2)[-1].strip() if ":" in line else line.strip()
    return content.startswith(f"def {symbol}") or content.startswith(f"async def {symbol}")


def _extract_calling_function(
    source: str, lineno: int
) -> tuple[int, int, str] | None:
    """Return the enclosing function/method body that contains lineno."""
    try:
        import ast
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines()
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = node.end_lineno or node.lineno
            if start <= lineno <= end:
                # prefer the innermost match
                if best is None or (end - start) < (best[1] - best[0]):
                    best = (start, end, node.name)

    if best is None:
        return None

    start, end, _ = best
    content = "\n".join(lines[start - 1:end])
    return start, end, content
