"""Offline, repeatable evaluation utilities for the local RAG retriever."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from rag_retrieval import NOTES_DIRECTORY, RetrievedChunk, retrieve


@dataclass(frozen=True)
class RetrievalCase:
    """One question and the source file that should be retrieved for it."""

    case_id: str
    question: str
    expected_sources: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalResult:
    case: RetrievalCase
    retrieved_sources: tuple[str, ...]
    passed: bool


def load_cases(path: Path) -> list[RetrievalCase]:
    """Load a human-editable JSON benchmark and reject malformed entries early."""
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list):
        raise ValueError("评测文件必须是 JSON 数组。")
    cases: list[RetrievalCase] = []
    for item in raw_cases:
        if not isinstance(item, dict):
            raise ValueError("每个评测样例必须是 JSON 对象。")
        case_id, question, sources = item.get("id"), item.get("question"), item.get("expected_sources")
        if not isinstance(case_id, str) or not isinstance(question, str) or not isinstance(sources, list):
            raise ValueError("每个样例都需要 id、question 和 expected_sources。")
        if not question.strip() or not sources or not all(isinstance(source, str) for source in sources):
            raise ValueError(f"样例 {case_id!r} 缺少有效问题或期望来源。")
        cases.append(RetrievalCase(case_id, question, tuple(sources)))
    return cases


def evaluate_retrieval(
    cases: list[RetrievalCase], *, notes_directory: Path = NOTES_DIRECTORY, limit: int = 3
) -> list[RetrievalResult]:
    """Measure source hit@k: one expected source must appear in the top-k results."""
    results: list[RetrievalResult] = []
    for case in cases:
        chunks = retrieve(case.question, notes_directory=notes_directory, limit=limit)
        sources = tuple(dict.fromkeys(chunk.source for chunk in chunks))
        passed = bool(set(sources).intersection(case.expected_sources))
        results.append(RetrievalResult(case, sources, passed))
    return results


def hit_rate(results: list[RetrievalResult]) -> float:
    return sum(result.passed for result in results) / len(results) if results else 0.0


def citations_are_grounded(answer: str, chunks: list[RetrievedChunk]) -> bool:
    """Check that every Chinese-style source tag in an answer was actually retrieved."""
    citations = re.findall(r"【([^】]+)】", answer)
    allowed = {chunk.citation for chunk in chunks}
    return bool(citations) and all(citation in allowed for citation in citations)
