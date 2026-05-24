from __future__ import annotations
import subprocess
from pathlib import Path

from ..tokenizer import count_tokens, truncate_to_tokens
from .base import RetrievalResult

PRIORITY = 0.6
MAX_COMMITS = 5
MAX_HISTORY_TOKENS = 800


def get_git_history(
    repo_path: Path, source_file: str, start_line: int, end_line: int
) -> list[RetrievalResult]:
    """Return recent git history for the given line range via git log -L."""
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"-L{start_line},{end_line}:{source_file}",
                f"-{MAX_COMMITS}",
                "--no-patch",
                "--format=%H %s",
            ],
            cwd=repo_path,
            capture_output=True, text=True, timeout=15,
        )
        log_output = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if not log_output:
        # fallback: plain git log for the file
        try:
            result = subprocess.run(
                ["git", "log", f"-{MAX_COMMITS}", "--oneline", "--", source_file],
                cwd=repo_path,
                capture_output=True, text=True, timeout=10,
            )
            log_output = result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    if not log_output:
        return []

    content = truncate_to_tokens(log_output, MAX_HISTORY_TOKENS)
    tokens = count_tokens(content)

    return [RetrievalResult(
        source="git_history",
        symbol="",
        file=source_file,
        start_line=start_line,
        end_line=end_line,
        content=content,
        reason=f"Recent commits touching lines {start_line}-{end_line} of {source_file} — explains intent behind existing code.",
        estimated_tokens=tokens,
        priority=PRIORITY,
    )]
