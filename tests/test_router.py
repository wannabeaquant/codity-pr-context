from pr_context.diff_parser import ParsedDiff, ChangedHunk
from pr_context.router import route


def _make_diff(lines: int, files: int, symbols: int) -> ParsedDiff:
    hunks = [
        ChangedHunk(
            file=f"file_{i}.py",
            old_start=1, old_count=lines // files,
            new_start=1, new_count=lines // files,
            added_lines=["+ x"] * (lines // files // 2),
            removed_lines=["- x"] * (lines // files // 2),
            context_lines=[],
        )
        for i in range(files)
    ]
    return ParsedDiff(
        hunks=hunks,
        changed_files=[f"file_{i}.py" for i in range(files)],
        changed_symbols=[f"sym_{i}" for i in range(symbols)],
        total_lines_changed=lines,
    )


def test_fast_path_small_pr():
    diff = _make_diff(lines=10, files=1, symbols=1)
    mode, reasoning = route(diff)
    assert mode == "fast"
    assert "Fast path" in reasoning


def test_agent_path_many_lines():
    diff = _make_diff(lines=100, files=1, symbols=1)
    mode, reasoning = route(diff)
    assert mode == "agent"
    assert "lines changed" in reasoning


def test_agent_path_many_files():
    diff = _make_diff(lines=20, files=4, symbols=1)
    mode, reasoning = route(diff)
    assert mode == "agent"
    assert "files changed" in reasoning


def test_agent_path_many_symbols():
    diff = _make_diff(lines=10, files=1, symbols=5)
    mode, reasoning = route(diff)
    assert mode == "agent"
    assert "symbols changed" in reasoning


def test_threshold_boundary():
    # exactly at threshold — should be fast
    diff = _make_diff(lines=60, files=3, symbols=2)
    mode, _ = route(diff)
    assert mode == "fast"
