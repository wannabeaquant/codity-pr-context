from pathlib import Path
from pr_context.diff_parser import parse_diff

SAMPLE_DIFF = """\
diff --git a/httpx/_config.py b/httpx/_config.py
index abc1234..def5678 100644
--- a/httpx/_config.py
+++ b/httpx/_config.py
@@ -1,5 +1,4 @@
 import ssl
-import old_module
 import typing

 def create_ssl_context():
"""


def test_parse_basic_diff():
    diff = parse_diff(SAMPLE_DIFF)
    assert len(diff.hunks) == 1
    assert diff.changed_files == ["httpx/_config.py"]
    assert diff.total_lines_changed > 0


def test_parse_changed_files():
    diff = parse_diff(SAMPLE_DIFF)
    assert "httpx/_config.py" in diff.changed_files


def test_parse_no_symbols_without_repo():
    # without repo_path, symbol extraction is skipped
    diff = parse_diff(SAMPLE_DIFF, repo_path=None)
    assert diff.changed_symbols == []


def test_parse_symbols_with_repo():
    repo = Path(__file__).parent.parent / "eval" / "repos" / "httpx"
    if not repo.exists():
        import pytest
        pytest.skip("httpx repo not cloned")
    diff_path = Path(__file__).parent.parent / "eval" / "diffs" / "pr1_bugfix_verify_cert.diff"
    if not diff_path.exists():
        import pytest
        pytest.skip("diff file not present")
    diff = parse_diff(diff_path.read_text(), repo_path=repo)
    assert "create_ssl_context" in diff.changed_symbols


def test_empty_diff():
    diff = parse_diff("")
    assert diff.hunks == []
    assert diff.changed_files == []
