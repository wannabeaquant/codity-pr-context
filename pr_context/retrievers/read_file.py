from __future__ import annotations
from pathlib import Path

from ..tokenizer import count_tokens, truncate_to_tokens
from .base import RetrievalResult

PRIORITY = 0.7
MAX_TOKENS_PER_READ = 1500


def read_file_range(
    repo_path: Path,
    rel_file: str,
    start_line: int,
    end_line: int,
    reason: str = "",
    symbol: str = "",
) -> list[RetrievalResult]:
    """Read a specific line range from a file."""
    abs_path = repo_path / rel_file
    if not abs_path.exists():
        return []

    lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
    start_idx = max(0, start_line - 1)
    end_idx = min(len(lines), end_line)
    content = "\n".join(lines[start_idx:end_idx])
    content = truncate_to_tokens(content, MAX_TOKENS_PER_READ)

    tokens = count_tokens(content)
    return [RetrievalResult(
        source="read_file",
        symbol=symbol,
        file=rel_file,
        start_line=start_line,
        end_line=end_line,
        content=content,
        reason=reason or f"Direct read of {rel_file}:{start_line}-{end_line}",
        estimated_tokens=tokens,
        priority=PRIORITY,
    )]
