from __future__ import annotations
import subprocess
from pathlib import Path

from ..tokenizer import count_tokens, truncate_to_tokens
from .base import RetrievalResult

PRIORITY = 0.6
MAX_COMMITS = 5
MAX_HISTORY_TOKENS = 800


def get_git_history(
    repo_path: Path,
    source_file: str,
    start_line: int,
    end_line: int,
    symbol: str = "",
) -> list[RetrievalResult]:
    """Return recent git history for a line range via git log -L.

    Tries three strategies in order:
    1. Name-based: ``git log -L :symbol:file`` — survives line number shifts
       caused by earlier edits; works even if the function moved within the file.
    2. Line-range: ``git log -L start,end:file`` — original behaviour.
    3. File-level fallback: plain ``git log -- file``.
    """
    log_output = ""
    strategy_used = "unknown"

    # Strategy 1 — name-based (preferred; robust to intra-file moves)
    if symbol:
        log_output = _run_git_log(
            repo_path,
            [f"-L:{symbol}:{source_file}", f"-{MAX_COMMITS}", "--no-patch", "--format=%H %s"],
        )
        if log_output:
            strategy_used = f"name-based (-L:{symbol}:)"

    # Strategy 2 — line-range
    if not log_output:
        log_output = _run_git_log(
            repo_path,
            [f"-L{start_line},{end_line}:{source_file}", f"-{MAX_COMMITS}", "--no-patch", "--format=%H %s"],
        )
        if log_output:
            strategy_used = f"line-range (-L{start_line},{end_line}:)"

    # Strategy 3 — file-level fallback
    if not log_output:
        log_output = _run_git_log(
            repo_path,
            [f"-{MAX_COMMITS}", "--oneline", "--follow", "--", source_file],
        )
        if log_output:
            strategy_used = "file-level (--follow)"

    if not log_output:
        return []

    content = truncate_to_tokens(log_output, MAX_HISTORY_TOKENS)
    tokens = count_tokens(content)
    desc = f"lines {start_line}-{end_line}" if not symbol else f"`{symbol}`"

    return [RetrievalResult(
        source="git_history",
        symbol=symbol,
        file=source_file,
        start_line=start_line,
        end_line=end_line,
        content=content,
        reason=(
            f"Recent commits touching {desc} of {source_file} "
            f"[{strategy_used}] — explains intent behind existing code."
        ),
        estimated_tokens=tokens,
        priority=PRIORITY,
    )]


def _run_git_log(repo_path: Path, args: list[str]) -> str:
    """Run ``git log <args>`` and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "log"] + args,
            cwd=repo_path,
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
