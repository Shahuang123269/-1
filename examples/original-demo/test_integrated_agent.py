"""Offline tests for Day 8's MCP-schema adapter and SQLite checkpointing."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import tempfile
import unittest

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, StateGraph
from typing_extensions import TypedDict


MODULE_PATH = Path(__file__).with_name("08_integrated_learning_agent.py")
SPEC = importlib.util.spec_from_file_location("integrated_learning_agent", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CounterState(TypedDict):
    number: int


def build_counter_graph(checkpointer: AsyncSqliteSaver):
    builder = StateGraph(CounterState)
    builder.add_node("increase", lambda state: {"number": state["number"] + 1})
    builder.add_edge(START, "increase")
    return builder.compile(checkpointer=checkpointer)


class IntegratedAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_mcp_tool_schema_keeps_name_description_and_parameters(self) -> None:
        class FakeTool:
            name = "search_learning_notes"
            description = "Search notes."
            input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

        schemas = MODULE.as_openai_tools([FakeTool()])
        self.assertEqual(schemas[0]["function"]["name"], "search_learning_notes")
        self.assertEqual(schemas[0]["function"]["description"], "Search notes.")
        self.assertIn("query", schemas[0]["function"]["parameters"]["properties"])

    async def test_async_sqlite_checkpoint_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "memory.sqlite")
            config = {"configurable": {"thread_id": "test-thread"}}
            async with AsyncSqliteSaver.from_conn_string(database) as saver:
                await saver.setup()
                graph = build_counter_graph(saver)
                result = await graph.ainvoke({"number": 1}, config=config)
                self.assertEqual(result["number"], 2)

            async with AsyncSqliteSaver.from_conn_string(database) as reopened_saver:
                await reopened_saver.setup()
                graph = build_counter_graph(reopened_saver)
                state = await graph.aget_state(config)
                self.assertEqual(state.values["number"], 2)


if __name__ == "__main__":
    unittest.main()
