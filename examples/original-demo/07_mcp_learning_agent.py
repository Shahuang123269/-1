r"""Day 7: DeepSeek chooses and calls tools supplied by a local MCP server.

Run:
    .\.venv\Scripts\python.exe 07_mcp_learning_agent.py "根据我的笔记解释 MCP 是什么？"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any

from dotenv import load_dotenv
from mcp import Client
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError

from mcp_notes_server import mcp


SYSTEM_PROMPT = """你是一名简洁、友好的中文 AI 学习助手。
你获得的全部工具都来自一个本地 MCP Server。
当用户询问 LLM、Agent、Tool、LangGraph、MCP 或笔记内容时，必须先调用 search_learning_notes。
需要算术计算时必须调用 calculate_expression，不能心算。
只能依据工具返回内容回答。如果工具返回“本地笔记中没有找到相关内容”，必须原样说明没有本地资料，不能使用自己的通用知识补充。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask DeepSeek using tools supplied by a local MCP server.")
    parser.add_argument("prompt", help="要交给学习助手的问题。")
    return parser.parse_args()


def as_openai_tools(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    """Adapt MCP's tool descriptions into DeepSeek's function-tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "MCP tool.",
                "parameters": tool.input_schema,
            },
        }
        for tool in mcp_tools
    ]


def result_to_text(result: object) -> str:
    content = getattr(result, "content", [])
    texts = [item.text for item in content if hasattr(item, "text")]
    return "\n".join(texts) or str(content)


async def run_agent(prompt: str) -> str:
    """Let the model use tools discovered at runtime from the MCP server."""
    client = OpenAI()
    model = os.getenv("OPENAI_MODEL", "deepseek-v4-flash")
    async with Client(mcp) as mcp_client:
        listed = await mcp_client.list_tools()
        tools = as_openai_tools(listed.tools)
        print("[MCP 发现工具] " + ", ".join(tool.name for tool in listed.tools))
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        for _round in range(4):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                extra_body={"thinking": {"type": "disabled"}},
            )
            message = response.choices[0].message
            if not message.tool_calls:
                return message.content or "模型没有返回文字。"

            messages.append(message.model_dump(exclude_none=True))
            for call in message.tool_calls:
                try:
                    arguments = json.loads(call.function.arguments)
                except json.JSONDecodeError:
                    tool_output = "工具参数不是有效 JSON。"
                else:
                    print(f"[MCP 工具调用] {call.function.name}({arguments})")
                    tool_output = result_to_text(await mcp_client.call_tool(call.function.name, arguments))
                    print(f"[MCP 工具结果] 已返回 {len(tool_output)} 个字符。")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": tool_output})

    return "工具调用次数超过上限，程序已安全停止。"


def main() -> int:
    logging.getLogger().setLevel(logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    load_dotenv()
    args = parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 缺失。请先完成第一步的 .env 配置。", file=sys.stderr)
        return 2
    try:
        print("[最终回答]")
        print(asyncio.run(run_agent(args.prompt)))
        return 0
    except AuthenticationError:
        print("鉴权失败：请检查 .env 中的 DeepSeek API Key。", file=sys.stderr)
        return 3
    except RateLimitError:
        print("请求过于频繁或余额不足，请稍后再试。", file=sys.stderr)
        return 4
    except APIConnectionError:
        print("无法连接 DeepSeek，请检查网络和 OPENAI_BASE_URL。", file=sys.stderr)
        return 5
    except APIStatusError as error:
        print(f"API 返回错误 {error.status_code}: {error.message}", file=sys.stderr)
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
