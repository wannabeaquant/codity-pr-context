from __future__ import annotations
import subprocess
from pathlib import Path

from ..tokenizer import count_tokens
from .base import RetrievalResult

PRIORITY = 0.55
MAX_RESULTS = 8
CONTEXT_LINES = 3


def grep_repo(
    repo_path: Path, pattern: str, reason: str = "", symbol: str = ""
) -> list[RetrievalResult]:
    """Grep the repo for `pattern`, returning context around each match."""
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "-A", str(CONTEXT_LINES),
             "-B", str(CONTEXT_LINES), pattern, "."],
            cwd=repo_path,
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if not output:
        return []

    # split on the grep separator "--"
    blocks = output.split("\n--\n")
    results: list[RetrievalResult] = []

    for block in blocks[:MAX_RESULTS]:
        lines = block.strip().splitlines()
        if not lines:
            continue

        # first line has the file:lineno: content pattern
        first = lines[0]
        parts = first.split(":", 2)
        if len(parts) < 2:
            continue

        rel_file = parts[0]
        try:
            lineno = int(parts[1])
        except ValueError:
            continue

        content = "\n".join(lines)
        tokens = count_tokens(content)

        results.append(RetrievalResult(
            source="grep",
            symbol=symbol or pattern,
            file=rel_file,
            start_line=max(1, lineno - CONTEXT_LINES),
            end_line=lineno + CONTEXT_LINES,
            content=content,
            reason=reason or f"grep match for `{pattern}`",
            estimated_tokens=tokens,
            priority=PRIORITY,
        ))

    return results
