import unittest

from note_search import search_notes


class NoteSearchTests(unittest.TestCase):
    def test_finds_langgraph_note(self) -> None:
        result = search_notes("LangGraph 是什么")
        self.assertIn("来源：langgraph.md", result)
        self.assertIn("状态", result)

    def test_finds_agent_note_with_chinese_query(self) -> None:
        result = search_notes("智能体如何调用工具")
        self.assertIn("来源：agent.md", result)

    def test_rejects_empty_query(self) -> None:
        self.assertIn("不能为空", search_notes(""))


if __name__ == "__main__":
    unittest.main()
