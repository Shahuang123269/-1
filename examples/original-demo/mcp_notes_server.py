"""A real local MCP server that exposes the Mini Agent's learning tools."""

from __future__ import annotations

from mcp.server import MCPServer

from calculator import CalculationError, calculate
from note_search import NOTES_DIRECTORY, search_notes
from rag_retrieval import format_context, retrieve


mcp = MCPServer(
    "Local Learning Notes",
    instructions="Use these tools only for the local Mini Agent learning notes and safe arithmetic.",
)


@mcp.tool()
def search_learning_notes(query: str) -> str:
    """Search the project's local Markdown learning notes for a topic."""
    return search_notes(query)


@mcp.tool()
def list_learning_notes() -> list[str]:
    """List the Markdown note files that are available to search."""
    return sorted(path.name for path in NOTES_DIRECTORY.glob("*.md"))


@mcp.tool()
def retrieve_note_chunks(query: str, limit: int = 3) -> str:
    """Retrieve the most relevant local note chunks with visible source citations for RAG."""
    safe_limit = min(max(limit, 1), 5)
    return format_context(retrieve(query, limit=safe_limit))


@mcp.tool()
def calculate_expression(expression: str) -> str:
    """Safely calculate one basic arithmetic expression."""
    try:
        return calculate(expression)
    except CalculationError as error:
        return f"计算失败：{error}"


if __name__ == "__main__":
    # A stdio server speaks MCP through stdin/stdout for a real external host.
    mcp.run()
