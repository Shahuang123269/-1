import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).with_name("04_langgraph_learning_assistant.py")
SPEC = importlib.util.spec_from_file_location("day4", MODULE_PATH)
assert SPEC and SPEC.loader
day4 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = day4
SPEC.loader.exec_module(day4)


class LangGraphFlowTests(unittest.TestCase):
    def test_routes_to_tools_when_model_requests_a_tool(self) -> None:
        state = {"messages": [{"tool_calls": [{"id": "call_1"}]}], "rounds": 1, "answer": ""}
        self.assertEqual(day4.choose_next_step(state), "tools")

    def test_routes_to_finish_when_model_returns_text(self) -> None:
        state = {"messages": [{"content": "完成"}], "rounds": 1, "answer": ""}
        self.assertEqual(day4.choose_next_step(state), "finish")

    def test_builds_a_compiled_graph(self) -> None:
        graph = day4.build_graph(object(), "deepseek-v4-flash")
        self.assertIsNotNone(graph)


if __name__ == "__main__":
    unittest.main()
