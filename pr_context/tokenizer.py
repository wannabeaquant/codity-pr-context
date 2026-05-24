from __future__ import annotations
import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Estimate token count. Uses cl100k_base (~5% off Claude actual)."""
    return len(_enc.encode(text))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Hard-truncate text to at most max_tokens tokens, preserving whole lines where possible."""
    tokens = _enc.encode(text)
    if len(tokens) <= max_tokens:
        return text
    truncated = _enc.decode(tokens[:max_tokens])
    # walk back to last newline to avoid mid-line truncation
    last_nl = truncated.rfind("\n")
    if last_nl > 0:
        return truncated[:last_nl] + "\n... [truncated]"
    return truncated + "\n... [truncated]"
