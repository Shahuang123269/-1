"""Offline tests for Day 10's RAG benchmark and citation validator."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rag_evaluation import RetrievalCase, citations_are_grounded, evaluate_retrieval, hit_rate, load_cases
from rag_retrieval import RetrievedChunk


class RagEvaluationTests(unittest.TestCase):
    def test_evaluation_reports_hit_at_k(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            notes = Path(directory)
            (notes / "agent.md").write_text("Agent 会选择并调用工具完成任务。", encoding="utf-8")
            (notes / "other.md").write_text("Python 有列表。", encoding="utf-8")
            cases = [RetrievalCase("agent-tool", "Agent 如何调用工具？", ("agent.md",))]
            results = evaluate_retrieval(cases, notes_directory=notes)

        self.assertTrue(results[0].passed)
        self.assertEqual(hit_rate(results), 1.0)

    def test_load_cases_rejects_bad_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"not": "a list"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_cases(path)

    def test_grounding_validator_rejects_unretrieved_citation(self) -> None:
        chunks = [RetrievedChunk("rag.md", 1, "RAG 是检索增强生成。", 1.0)]
        self.assertTrue(citations_are_grounded("答案【rag.md#片段1】", chunks))
        self.assertFalse(citations_are_grounded("答案【mcp.md#片段1】", chunks))


if __name__ == "__main__":
    unittest.main()
