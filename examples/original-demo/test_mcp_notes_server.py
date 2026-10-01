import unittest

from mcp import Client

from mcp_notes_server import mcp


class McpNotesServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_lists_the_learning_tools(self) -> None:
        async with Client(mcp) as client:
            result = await client.list_tools()
            names = {tool.name for tool in result.tools}
        self.assertEqual(
            names,
            {"search_learning_notes", "list_learning_notes", "retrieve_note_chunks", "calculate_expression"},
        )

    async def test_server_searches_notes(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("search_learning_notes", {"query": "LangGraph"})
        text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
        self.assertIn("来源：langgraph.md", text)

    async def test_server_retrieves_cited_chunks(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("retrieve_note_chunks", {"query": "MCP"})
        text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
        self.assertIn("mcp.md#片段", text)


if __name__ == "__main__":
    unittest.main()
