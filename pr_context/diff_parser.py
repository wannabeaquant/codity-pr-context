from __future__ import annotations
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import unidiff


@dataclass
class ChangedHunk:
    file: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    added_lines: list[str]
    removed_lines: list[str]
    context_lines: list[str]


@dataclass
class ParsedDiff:
    hunks: list[ChangedHunk]
    changed_files: list[str]          # unique, relative paths
    changed_symbols: list[str]        # function/class names overlapping changed lines
    total_lines_changed: int


def parse_diff(diff_text: str, repo_path: Optional[Path] = None) -> ParsedDiff:
    patch = unidiff.PatchSet(diff_text)
    hunks: list[ChangedHunk] = []
    changed_files: list[str] = []

    for patched_file in patch:
        if patched_file.is_binary_file:
            continue

        source_file = patched_file.path
        # unidiff prefixes with a/ b/ in some formats
        source_file = source_file.removeprefix("a/").removeprefix("b/")
        changed_files.append(source_file)

        for hunk in patched_file:
            added = [line.value for line in hunk if line.is_added]
            removed = [line.value for line in hunk if line.is_removed]
            context = [line.value for line in hunk if line.is_context]
            hunks.append(ChangedHunk(
                file=source_file,
                old_start=hunk.source_start,
                old_count=hunk.source_length,
                new_start=hunk.target_start,
                new_count=hunk.target_length,
                added_lines=added,
                removed_lines=removed,
                context_lines=context,
            ))

    changed_symbols = _extract_changed_symbols(hunks, repo_path)
    total_lines = sum(len(h.added_lines) + len(h.removed_lines) for h in hunks)

    return ParsedDiff(
        hunks=hunks,
        changed_files=list(dict.fromkeys(changed_files)),  # dedupe, preserve order
        changed_symbols=changed_symbols,
        total_lines_changed=total_lines,
    )


def _extract_changed_symbols(hunks: list[ChangedHunk], repo_path: Optional[Path]) -> list[str]:
    """Extract function/class names that overlap with changed line ranges."""
    if repo_path is None:
        return []

    symbols: list[str] = []
    files_seen: dict[str, list[ChangedHunk]] = {}
    for hunk in hunks:
        files_seen.setdefault(hunk.file, []).append(hunk)

    for rel_path, file_hunks in files_seen.items():
        if not rel_path.endswith(".py"):
            continue
        abs_path = repo_path / rel_path
        if not abs_path.exists():
            continue
        try:
            source = abs_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except SyntaxError:
            continue

        lines = source.splitlines()
        changed_line_set: set[int] = set()
        for h in file_hunks:
            # new_start is 1-indexed
            for i in range(h.new_start, h.new_start + h.new_count):
                changed_line_set.add(i)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                node_lines = set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
                if node_lines & changed_line_set:
                    symbols.append(node.name)

    return list(dict.fromkeys(symbols))
