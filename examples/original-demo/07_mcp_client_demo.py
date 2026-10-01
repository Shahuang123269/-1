"""Day 7 offline demo: a MCP client lists and calls tools from the local server."""

from __future__ import annotations

import asyncio

from mcp import Client

from mcp_notes_server import mcp


def result_to_text(result: object) -> str:
    """Turn an MCP tool result into the text a language model would receive."""
    content = getattr(result, "content", [])
    texts = [item.text for item in content if hasattr(item, "text")]
    return "\n".join(texts) or str(content)


async def main() -> None:
    # This in-process transport still uses the MCP protocol, but needs no port.
    async with Client(mcp) as client:
        listed = await client.list_tools()
        print("[MCP Server 提供的工具]")
        for tool in listed.tools:
            print(f"- {tool.name}: {tool.description}")

        result = await client.call_tool("search_learning_notes", {"query": "LangGraph"})
        print("\n[MCP 工具返回]")
        print(result_to_text(result))


if __name__ == "__main__":
    asyncio.run(main())
