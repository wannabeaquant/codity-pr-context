from __future__ import annotations
from pathlib import Path
from typing import Any

from ..retrievers.base import RetrievalResult
from ..retrievers.callees import get_callees
from ..retrievers.callers import get_callers
from ..retrievers.tests import get_tests
from ..retrievers.siblings import get_siblings
from ..retrievers.imports import get_imports
from ..retrievers.git_history import get_git_history
from ..retrievers.grep_repo import grep_repo
from ..retrievers.read_file import read_file_range

# Anthropic tool definitions — used verbatim in the API call
TOOL_DEFINITIONS = [
    {
        "name": "get_callees",
        "description": "Find the definitions of functions/methods called by a given symbol. Use when you need to understand what a changed function depends on.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Function name to inspect"},
                "source_file": {"type": "string", "description": "Repo-relative path to the file containing the symbol"},
            },
            "required": ["symbol", "source_file"],
        },
    },
    {
        "name": "get_callers",
        "description": "Find call sites of a symbol across the repo. Use when a changed function's contract may have shifted and you need to check what depends on it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Function name to find callers of"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_tests",
        "description": "Find test functions that cover a symbol. Use to understand existing behavioral expectations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Symbol to find tests for"},
                "source_file": {"type": "string", "description": "Repo-relative file path"},
            },
            "required": ["symbol", "source_file"],
        },
    },
    {
        "name": "get_siblings",
        "description": "Get other top-level functions/classes in the same file. Use to understand local conventions and helpers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_file": {"type": "string", "description": "Repo-relative file path"},
                "changed_symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Symbols already in context — siblings will exclude these",
                },
            },
            "required": ["source_file", "changed_symbols"],
        },
    },
    {
        "name": "get_imports",
        "description": "Get the import block of a file. Use to understand the file's dependencies and type origins.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_file": {"type": "string", "description": "Repo-relative file path"},
            },
            "required": ["source_file"],
        },
    },
    {
        "name": "get_git_history",
        "description": "Get recent git commit history for a line range in a file. Use to understand the intent behind existing code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_file": {"type": "string", "description": "Repo-relative file path"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            "required": ["source_file", "start_line", "end_line"],
        },
    },
    {
        "name": "grep_repo",
        "description": "Grep the repo for a pattern. Use when you need to find references, usages, or definitions not covered by other tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "reason": {"type": "string", "description": "Why this pattern is relevant"},
            },
            "required": ["pattern", "reason"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a specific line range from a file. Use when you know exactly what you need.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_file": {"type": "string", "description": "Repo-relative file path"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "reason": {"type": "string", "description": "Why this range is needed"},
            },
            "required": ["source_file", "start_line", "end_line", "reason"],
        },
    },
    {
        "name": "done",
        "description": "Signal that you have collected sufficient context. Call this when you have everything needed for a high-quality review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Brief summary of what context was collected and why it is sufficient"},
            },
            "required": ["summary"],
        },
    },
]


def dispatch_tool(
    name: str, inputs: dict[str, Any], repo_path: Path
) -> list[RetrievalResult]:
    """Route a tool call from the agent to the appropriate retriever."""
    if name == "get_callees":
        return get_callees(repo_path, inputs["symbol"], inputs["source_file"])
    elif name == "get_callers":
        return get_callers(repo_path, inputs["symbol"])
    elif name == "get_tests":
        return get_tests(repo_path, inputs["symbol"], inputs["source_file"])
    elif name == "get_siblings":
        return get_siblings(repo_path, inputs["source_file"], inputs.get("changed_symbols", []))
    elif name == "get_imports":
        return get_imports(repo_path, inputs["source_file"])
    elif name == "get_git_history":
        return get_git_history(
            repo_path, inputs["source_file"], inputs["start_line"], inputs["end_line"]
        )
    elif name == "grep_repo":
        return grep_repo(repo_path, inputs["pattern"], inputs.get("reason", ""))
    elif name == "read_file":
        return read_file_range(
            repo_path,
            inputs["source_file"],
            inputs["start_line"],
            inputs["end_line"],
            reason=inputs.get("reason", ""),
        )
    return []
