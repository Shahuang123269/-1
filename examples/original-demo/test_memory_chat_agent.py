import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).with_name("05_memory_chat_agent.py")
SPEC = importlib.util.spec_from_file_location("day5", MODULE_PATH)
assert SPEC and SPEC.loader
day5 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = day5
SPEC.loader.exec_module(day5)


class MemoryChatAgentTests(unittest.TestCase):
    def test_builds_a_graph_with_a_checkpointer(self) -> None:
        self.assertIsNotNone(day5.build_graph(object(), "deepseek-v4-flash"))

    def test_routes_tool_call_to_tools_node(self) -> None:
        state = {"messages": [{"tool_calls": [{"id": "call_1"}]}]}
        self.assertEqual(day5.choose_next_step(state), "tools")

    def test_runs_local_note_search(self) -> None:
        result = day5.execute_tool(
            {"function": {"name": "search_notes", "arguments": '{"query": "LangGraph"}'}}
        )
        self.assertIn("来源：langgraph.md", result)


if __name__ == "__main__":
    unittest.main()
