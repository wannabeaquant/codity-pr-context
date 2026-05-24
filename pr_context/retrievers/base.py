from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class RetrievalResult:
    source: str        # "callees" | "callers" | "tests" | "siblings" | "imports" | "git_history" | "grep" | "read_file"
    symbol: str        # primary symbol this context is about (empty string if N/A)
    file: str          # path relative to repo root
    start_line: int
    end_line: int
    content: str
    reason: str        # why this context was selected — goes into the retrieval plan
    estimated_tokens: int
    priority: float    # 0.0–1.0; used by ranker

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "symbol": self.symbol,
            "file": self.file,
            "lines": f"{self.start_line}-{self.end_line}",
            "reason": self.reason,
            "estimated_tokens": self.estimated_tokens,
            "priority": self.priority,
            "content": self.content,
        }
