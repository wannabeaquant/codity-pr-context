from pr_context.language.python_adapter import PythonAdapter

adapter = PythonAdapter()

SAMPLE = """\
import os

def top_level_func():
    def nested():
        pass
    return nested

class MyClass:
    def method_one(self):
        pass
    def method_two(self):
        def inner():
            pass
"""


def test_extract_top_level_no_nested():
    symbols = adapter.extract_top_level_symbols(SAMPLE)
    names = [s["name"] for s in symbols]
    # top-level function and class should appear
    assert "top_level_func" in names
    assert "MyClass" in names
    # nested function should NOT appear as top-level
    assert "nested" not in names
    # inner function inside a method should NOT appear
    assert "inner" not in names


def test_extract_class_methods_included():
    symbols = adapter.extract_top_level_symbols(SAMPLE)
    names = [s["name"] for s in symbols]
    assert "method_one" in names
    assert "method_two" in names


def test_extract_callees_basic():
    source = """\
def helper(): pass
def foo():
    helper()
    x = len([])
"""
    callees = adapter.extract_callees(source, "foo")
    assert "helper" in callees
    # builtins filtered at retriever level, not here — adapter returns everything
    assert "len" in callees


def test_get_symbol_body():
    source = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
    result = adapter.get_symbol_body(source, "foo")
    assert result is not None
    start, end, body = result
    assert "return 1" in body
    assert "return 2" not in body


def test_get_imports():
    source = "import os\nfrom pathlib import Path\n\ndef foo(): pass\n"
    imports = adapter.get_imports(source)
    assert "import os" in imports
    assert "from pathlib import Path" in imports
    assert "def foo" not in imports


def test_syntax_error_returns_empty():
    symbols = adapter.extract_top_level_symbols("def (broken:")
    assert symbols == []
