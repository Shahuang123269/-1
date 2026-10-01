import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


MODULE_PATH = Path(__file__).with_name("06_persistent_memory_agent.py")
SPEC = importlib.util.spec_from_file_location("day6", MODULE_PATH)
assert SPEC and SPEC.loader
day6 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = day6
SPEC.loader.exec_module(day6)


class CounterState(TypedDict):
    count: int


def counter_graph(connection: sqlite3.Connection):
    builder = StateGraph(CounterState)
    builder.add_node("increase", lambda state: {"count": state["count"] + 1})
    builder.add_edge(START, "increase")
    builder.add_edge("increase", END)
    saver = SqliteSaver(connection)
    saver.setup()
    return builder.compile(checkpointer=saver)


class PersistentMemoryTests(unittest.TestCase):
    def test_checkpoint_survives_reopening_sqlite_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "memory.sqlite"
            config = {"configurable": {"thread_id": "test-thread"}}
            first_connection = sqlite3.connect(database, check_same_thread=False)
            counter_graph(first_connection).invoke({"count": 1}, config=config)
            first_connection.close()
            second_connection = sqlite3.connect(database, check_same_thread=False)
            self.assertEqual(counter_graph(second_connection).get_state(config).values["count"], 2)
            second_connection.close()

    def test_note_search_tool_is_available(self) -> None:
        result = day6.execute_tool({"function": {"name": "search_notes", "arguments": '{"query": "LangGraph"}'}})
        self.assertIn("来源：langgraph.md", result)


if __name__ == "__main__":
    unittest.main()
