from __future__ import annotations
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class LanguageAdapter(Protocol):
    """Interface for language-specific AST operations.

    Python is the only implemented adapter. Others should subclass this protocol
    and implement the methods for their language's AST tooling.
    """

    def is_supported(self, file_path: str) -> bool:
        """Return True if this adapter handles the given file extension."""
        ...

    def extract_top_level_symbols(self, source: str) -> list[dict]:
        """Return list of {name, type, start_line, end_line} for top-level defs."""
        ...

    def extract_callees(self, source: str, symbol: str) -> list[str]:
        """Return names of functions/methods called within the given symbol's body."""
        ...

    def get_symbol_body(self, source: str, symbol: str) -> tuple[int, int, str] | None:
        """Return (start_line, end_line, body_text) for the given symbol, or None."""
        ...

    def get_imports(self, source: str) -> str:
        """Return the import block at the top of the file."""
        ...
