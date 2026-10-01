import json
import os

import httpx
import pytest
from openai import AsyncOpenAI

from issue_agent.config import Settings
from issue_agent.connectors import GitHubConnector
from issue_agent.domain import DomainError
from issue_agent.mcp_client import READ_TOOLS, MCPTools
from issue_agent.models import DeepSeekModel


async def test_mcp_is_independent_process_with_real_discovery(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    async with MCPTools(settings) as tools:
        info = await tools.session.call_tool("server_info", {})
        identity = info.structuredContent or json.loads(info.content[0].text)
        assert identity["pid"] != os.getpid()
        assert {t["function"]["name"] for t in tools.schemas} == READ_TOOLS
        issue = await tools.call("get_issue", {"issue_number": 2})
        assert issue["number"] == 2
        with pytest.raises(DomainError, match="tool_not_allowed"):
            await tools.call("create_comment", {})


async def test_github_paginates_comments_without_following_external_urls(tmp_path):
    pages = []

    def handle(request):
        assert request.url.host == "api.github.com"
        page = int(request.url.params["page"])
        pages.append(page)
        count = 100 if page == 1 else 1
        return httpx.Response(
            200,
            json=[{"id": page * 100 + i, "body": "text", "html_url": "url"} for i in range(count)],
        )

    remote = GitHubConnector(
        Settings(_env_file=None, data_dir=tmp_path), httpx.MockTransport(handle)
    )
    try:
        assert len(await remote.list_comments(2)) == 101
        assert pages == [1, 2]
    finally:
        await remote.close()


async def test_github_read_retry_but_never_retry_write(tmp_path):
    calls = []

    def handle(request):
        calls.append(request.method)
        if request.method == "GET" and calls.count("GET") == 2:
            return httpx.Response(
                200, json={"number": 2, "title": "x", "body": "", "labels": [], "html_url": "url"}
            )
        raise httpx.ReadTimeout("ambiguous", request=request)

    remote = GitHubConnector(
        Settings(_env_file=None, data_dir=tmp_path, allow_remote_writes=True),
        httpx.MockTransport(handle),
    )
    try:
        assert (await remote.get_issue(2))["number"] == 2
        with pytest.raises(DomainError, match="write_uncertain"):
            await remote.write(2, {"kind": "comment", "body": "x"}, "marker")
        assert calls == ["GET", "GET", "POST"]
    finally:
        await remote.close()


async def test_remote_writes_disabled_by_default(tmp_path):
    def never(request):
        raise AssertionError("must not contact GitHub")

    remote = GitHubConnector(
        Settings(_env_file=None, data_dir=tmp_path), httpx.MockTransport(never)
    )
    try:
        with pytest.raises(DomainError, match="remote_writes_disabled"):
            await remote.write(2, {"kind": "comment", "body": "x"}, "marker")
    finally:
        await remote.close()


async def test_deepseek_adapter_uses_correct_endpoint_and_records_usage(tmp_path):
    def handle(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-flash"
        assert body["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "id": "completion",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_issue",
                                        "arguments": '{"issue_number":2}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    settings = Settings(_env_file=None, data_dir=tmp_path, deepseek_api_key="test-only-placeholder")
    model = DeepSeekModel(settings)
    await model.client.close()
    model.client = AsyncOpenAI(
        api_key="test-only-placeholder",
        base_url=settings.deepseek_base_url,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        max_retries=0,
    )
    try:
        message, usage = await model.complete([{"role": "user", "content": "test"}], [])
        assert message["tool_calls"][0]["function"]["name"] == "get_issue"
        assert usage["total_tokens"] == 15
    finally:
        await model.close()
