from __future__ import annotations
import ast
from typing import Optional


class PythonAdapter:
    def is_supported(self, file_path: str) -> bool:
        return file_path.endswith(".py")

    def extract_top_level_symbols(self, source: str) -> list[dict]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        symbols = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # only top-level and class-level methods (not nested)
                symbols.append({
                    "name": node.name,
                    "type": "class" if isinstance(node, ast.ClassDef) else "function",
                    "start_line": node.lineno,
                    "end_line": node.end_lineno or node.lineno,
                })
        return symbols

    def extract_callees(self, source: str, symbol: str) -> list[str]:
        """Return names of all functions/methods called within `symbol`'s body."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        target_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
                target_node = node
                break

        if target_node is None:
            return []

        callees: list[str] = []
        for node in ast.walk(target_node):
            if isinstance(node, ast.Call):
                name = _extract_call_name(node)
                if name:
                    callees.append(name)

        return list(dict.fromkeys(callees))

    def get_symbol_body(self, source: str, symbol: str) -> tuple[int, int, str] | None:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None

        lines = source.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == symbol:
                    start = node.lineno - 1  # 0-indexed
                    end = (node.end_lineno or node.lineno)  # 1-indexed exclusive
                    body = "\n".join(lines[start:end])
                    return node.lineno, end, body
        return None

    def get_imports(self, source: str) -> str:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return ""

        lines = source.splitlines()
        import_lines: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                end = node.end_lineno or node.lineno
                import_lines.extend(lines[node.lineno - 1:end])

        return "\n".join(import_lines)


def _extract_call_name(node: ast.Call) -> Optional[str]:
    """Extract a readable name from a Call node."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None
