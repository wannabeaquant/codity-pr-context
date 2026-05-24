from pr_context.ranker import rank_and_pack
from pr_context.retrievers.base import RetrievalResult


def _make_result(source: str, priority: float, tokens: int, file: str = "a.py", line: int = 1) -> RetrievalResult:
    return RetrievalResult(
        source=source, symbol="sym", file=file,
        start_line=line, end_line=line + 5,
        content="x" * tokens,  # approximate
        reason="test", estimated_tokens=tokens, priority=priority,
    )


def test_pack_respects_budget():
    results = [_make_result("callees", 0.9, 5000, line=1), _make_result("callers", 0.8, 5000, line=50)]
    pack = rank_and_pack(results, budget=8192)
    # Only one fits; should be the higher-priority one
    assert len(pack.packed) == 1
    assert pack.packed[0].source == "callees"
    assert len(pack.excluded) == 1
    assert pack.excluded[0]["source"] == "callers"


def test_pack_priority_order():
    results = [
        _make_result("imports", 0.4, 100, line=1),
        _make_result("callees", 0.9, 100, line=2),
        _make_result("callers", 0.8, 100, line=3),
    ]
    pack = rank_and_pack(results, budget=8192)
    assert [r.source for r in pack.packed] == ["callees", "callers", "imports"]


def test_pack_deduplication():
    r1 = _make_result("callees", 0.9, 100, file="a.py", line=10)
    r2 = _make_result("callers", 0.8, 100, file="a.py", line=10)  # same (file, line)
    pack = rank_and_pack([r1, r2], budget=8192)
    assert len(pack.packed) == 1  # duplicate dropped


def test_pack_empty_input():
    pack = rank_and_pack([], budget=8192)
    assert pack.packed == []
    assert pack.excluded == []


def test_excluded_has_reason():
    big = _make_result("callees", 0.9, 9000)  # over budget
    pack = rank_and_pack([big], budget=8192)
    assert len(pack.excluded) == 1
    assert "Budget cutoff" in pack.excluded[0]["reason_excluded"]
