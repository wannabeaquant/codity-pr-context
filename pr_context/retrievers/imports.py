from __future__ import annotations
from pathlib import Path

from ..language.python_adapter import PythonAdapter
from ..tokenizer import count_tokens
from .base import RetrievalResult

_adapter = PythonAdapter()

PRIORITY = 0.4


def get_imports(repo_path: Path, source_file: str) -> list[RetrievalResult]:
    """Return the import block at the top of the changed file."""
    abs_path = repo_path / source_file
    if not abs_path.exists():
        return []
    if not source_file.endswith(".py"):
        return []

    source = abs_path.read_text(encoding="utf-8", errors="replace")
    import_block = _adapter.get_imports(source)
    if not import_block.strip():
        return []

    tokens = count_tokens(import_block)
    return [RetrievalResult(
        source="imports",
        symbol="",
        file=source_file,
        start_line=1,
        end_line=import_block.count("\n") + 1,
        content=import_block,
        reason=f"Import block of {source_file} — shows runtime dependencies and type origins.",
        estimated_tokens=tokens,
        priority=PRIORITY,
    )]
