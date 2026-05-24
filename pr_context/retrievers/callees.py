from __future__ import annotations
from pathlib import Path

from ..language.python_adapter import PythonAdapter
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
    callee_names = _adapter.extract_callees(source, symbol)
    if not callee_names:
        return []

    results: list[RetrievalResult] = []

    for callee in callee_names:
        # search the source file first, then the whole repo
        definition = _find_definition(callee, source, source_file)
        if definition:
            results.append(definition)
            continue
        definition = _search_repo(callee, repo_path)
        if definition:
            results.append(definition)

    return results


def _find_definition(
    name: str, source: str, rel_file: str
) -> RetrievalResult | None:
    body = _adapter.get_symbol_body(source, name)
    if body is None:
        return None
    start_line, end_line, content = body
    tokens = count_tokens(content)
    return RetrievalResult(
        source="callees",
        symbol=name,
        file=rel_file,
        start_line=start_line,
        end_line=end_line,
        content=content,
        reason=f"Definition of `{name}` which is called by the changed function.",
        estimated_tokens=tokens,
        priority=PRIORITY,
    )


def _search_repo(name: str, repo_path: Path) -> RetrievalResult | None:
    """Grep-based fallback: find the definition of `name` across all .py files."""
    import subprocess
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", f"^def {name}\\|^    def {name}\\|^class {name}", "."],
            cwd=repo_path,
            capture_output=True, text=True, timeout=10,
        )
        lines = [l for l in result.stdout.splitlines() if l]
        if not lines:
            return None

        # take the first match
        first = lines[0]
        parts = first.split(":", 2)
        if len(parts) < 2:
            return None

        rel_file, lineno_str = parts[0], parts[1]
        try:
            lineno = int(lineno_str)
        except ValueError:
            return None

        abs_path = repo_path / rel_file
        if not abs_path.exists():
            return None

        source = abs_path.read_text(encoding="utf-8", errors="replace")
        body = _adapter.get_symbol_body(source, name)
        if body is None:
            # fallback: grab 20 lines from lineno
            file_lines = source.splitlines()
            snippet_lines = file_lines[lineno - 1: lineno + 19]
            content = "\n".join(snippet_lines)
            return RetrievalResult(
                source="callees",
                symbol=name,
                file=rel_file,
                start_line=lineno,
                end_line=lineno + 19,
                content=content,
                reason=f"Definition of `{name}` which is called by the changed function.",
                estimated_tokens=count_tokens(content),
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
            reason=f"Definition of `{name}` which is called by the changed function.",
            estimated_tokens=count_tokens(content),
            priority=PRIORITY,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
