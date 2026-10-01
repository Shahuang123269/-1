import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import Settings
from .domain import DomainError

READ_TOOLS = {"get_issue", "list_issue_comments", "list_issues"}


class MCPTools:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stack = AsyncExitStack()

    async def __aenter__(self):
        env = {
            k: os.environ[k]
            for k in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP")
            if k in os.environ
        }
        env.update(
            IA_TOOL_MODE=self.settings.tool_mode,
            IA_REPOSITORY=self.settings.repository,
            IA_DATA_DIR=str(self.settings.data_dir.resolve()),
            IA_GITHUB_TOKEN=self.settings.github_token.get_secret_value(),
            IA_TIMEOUT_SECONDS=str(self.settings.timeout_seconds),
            PYTHONIOENCODING="utf-8",
        )
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "issue_agent.mcp_server"], env=env
        )
        try:
            read, write = await self.stack.enter_async_context(stdio_client(params))
            self.session = await self.stack.enter_async_context(
                ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=self.settings.timeout_seconds),
                )
            )
            await self.session.initialize()
            discovered = (await self.session.list_tools()).tools
            self.schemas = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.inputSchema,
                    },
                }
                for t in discovered
                if t.name in READ_TOOLS
            ]
            if {t["function"]["name"] for t in self.schemas} != READ_TOOLS:
                raise DomainError("tool_contract_mismatch")
        except BaseException:
            await self.stack.aclose()
            raise
        return self

    async def __aexit__(self, *args):
        await self.stack.aclose()

    async def call(self, name: str, arguments: dict):
        if name not in READ_TOOLS:
            raise DomainError("tool_not_allowed")
        try:
            result = await asyncio.wait_for(
                self.session.call_tool(name, arguments), timeout=self.settings.timeout_seconds
            )
        except TimeoutError:
            raise DomainError("tool_timeout") from None
        if result.isError:
            import re

            text = "\n".join(c.text for c in result.content if c.type == "text")
            known = re.search(
                r"\b(issue_not_found|read_unavailable|comment_scan_limit|github_http_\d{3}|pull_request_out_of_scope)\b",
                text,
            )
            raise DomainError(known.group(1) if known else "tool_failed")
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured
        texts = [c.text for c in result.content if c.type == "text"]
        try:
            return json.loads("\n".join(texts))
        except ValueError:
            raise DomainError("invalid_tool_result") from None
