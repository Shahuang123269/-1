"""Offline tests for Day 9's chunking, ranking, and source labels."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from rag_retrieval import format_context, retrieve, split_into_chunks


class RagRetrievalTests(unittest.TestCase):
    def test_split_keeps_short_paragraphs_together(self) -> None:
        chunks = split_into_chunks("第一段。\n\n第二段。", max_characters=30)
        self.assertEqual(chunks, ["第一段。\n第二段。"])

    def test_retrieval_ranks_the_matching_note_and_returns_a_citation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            notes = Path(directory)
            (notes / "mcp.md").write_text("MCP 让 AI 应用通过标准协议发现工具。", encoding="utf-8")
            (notes / "python.txt").write_text("Python 可以处理列表和字典。", encoding="utf-8")
            results = retrieve("MCP 协议和工具", notes_directory=notes)

        self.assertEqual(results[0].source, "mcp.md")
        self.assertEqual(results[0].citation, "mcp.md#片段1")
        self.assertIn("MCP", format_context(results))

    def test_unknown_or_empty_query_returns_no_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            notes = Path(directory)
            (notes / "only.md").write_text("LangGraph 管理状态。", encoding="utf-8")
            self.assertEqual(retrieve("不存在的主题", notes_directory=notes), [])
            self.assertEqual(retrieve("", notes_directory=notes), [])


if __name__ == "__main__":
    unittest.main()
