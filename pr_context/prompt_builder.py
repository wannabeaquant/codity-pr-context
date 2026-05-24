from __future__ import annotations
from .retrievers.base import RetrievalResult
from .tokenizer import count_tokens

SYSTEM_PREAMBLE = """You are a senior software engineer performing a pull request review.
You will be given the PR diff followed by relevant context retrieved from the repository.
Focus on: correctness, breaking changes, edge cases, missing error handling, and test coverage gaps.
Be specific — cite file:line numbers when pointing out issues.
"""


def build_review_prompt(diff_text: str, context: list[RetrievalResult]) -> str:
    sections: list[str] = [SYSTEM_PREAMBLE, "## PR Diff\n```diff", diff_text, "```\n"]

    if context:
        sections.append("## Retrieved Context\n")
        for r in context:
            header = f"### [{r.source}] `{r.symbol or r.file}` — {r.file}:{r.start_line}-{r.end_line}"
            sections.append(header)
            sections.append(f"*{r.reason}*\n")
            sections.append(f"```python\n{r.content}\n```\n")

    sections.append("## Review\n")
    return "\n".join(sections)


def estimate_prompt_tokens(diff_text: str, context: list[RetrievalResult]) -> int:
    prompt = build_review_prompt(diff_text, context)
    return count_tokens(prompt)
