r"""Day 8: one complete learning Agent built from the previous exercises.

Run:
    .\.venv\Scripts\python.exe 08_integrated_learning_agent.py --thread xiaowang
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import operator
import os
from pathlib import Path
import sys
import uuid
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from mcp import Client
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError
from typing_extensions import TypedDict

from mcp_notes_server import mcp


DATABASE_PATH = Path(__file__).with_name("integrated_agent_memory.sqlite")
SYSTEM_PROMPT = """你是一名简洁、友好的中文 AI 学习助手。
你可以调用的工具全部由本地 MCP Server 提供。
当用户询问 LLM、Agent、Tool、LangGraph、MCP 或本地笔记时，必须先调用 search_learning_notes。
需要算术计算时，必须调用 calculate_expression，不能心算。
笔记相关回答只能依据 MCP 工具返回的本地笔记；没有找到时必须明确说“本地笔记中没有相关内容”，不能自行补充。
可以利用同一段对话中已经保存的上下文回答“我刚才说了什么”一类的问题。"""


class AgentState(TypedDict):
    """Every message is appended and persisted under one thread ID."""

    messages: Annotated[list[dict[str, Any]], operator.add]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LangGraph + SQLite + MCP learning assistant.")
    parser.add_argument("--thread", default="my-integrated-session", help="要继续的会话编号，例如 xiaowang。")
    return parser.parse_args()


def as_openai_tools(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    """Convert MCP tool descriptions into DeepSeek function-tool schemas."""
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
    """Keep only the text blocks returned by an MCP tool."""
    content = getattr(result, "content", [])
    texts = [item.text for item in content if hasattr(item, "text")]
    return "\n".join(texts) or str(content)


def call_model(
    state: AgentState, *, client: OpenAI, model: str, tools: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Ask DeepSeek to either answer or request one of the discovered MCP tools."""
    print("[节点：model] DeepSeek 根据已保存对话决定下一步")
    response = client.chat.completions.create(
        model=model,
        messages=state["messages"],
        tools=tools,
        tool_choice="auto",
        extra_body={"thinking": {"type": "disabled"}},
    )
    return {"messages": [response.choices[0].message.model_dump(exclude_none=True)]}


async def run_mcp_tools(
    state: AgentState, *, mcp_client: Client, allowed_names: set[str]
) -> dict[str, list[dict[str, str]]]:
    """Execute only tools the MCP server exposed when this program started."""
    print("[节点：tools] 通过 MCP 调用本地工具")
    outputs: list[dict[str, str]] = []
    for call in state["messages"][-1].get("tool_calls", []):
        name = call.get("function", {}).get("name", "")
        try:
            arguments = json.loads(call.get("function", {}).get("arguments", "{}"))
        except json.JSONDecodeError:
            output = "工具参数不是有效 JSON。"
        else:
            if name not in allowed_names:
                output = "该工具不在本次 MCP Server 发现的允许列表中。"
            elif not isinstance(arguments, dict):
                output = "工具参数必须是一个 JSON 对象。"
            else:
                print(f"  [MCP 工具调用] {name}({arguments})")
                output = result_to_text(await mcp_client.call_tool(name, arguments))
                print(f"  [MCP 工具结果] 已返回 {len(output)} 个字符。")
        outputs.append({"role": "tool", "tool_call_id": call["id"], "content": output})
    return {"messages": outputs}


def choose_next_step(state: AgentState) -> Literal["tools", "finish"]:
    if state["messages"][-1].get("tool_calls"):
        print("[条件边] model → tools")
        return "tools"
    print("[条件边] model → finish")
    return "finish"


def finish(_: AgentState) -> dict[str, str]:
    print("[节点：finish] 本轮消息已由 SQLite 保存")
    return {}


def build_graph(
    client: OpenAI,
    model: str,
    mcp_client: Client,
    mcp_tools: list[Any],
    checkpointer: AsyncSqliteSaver,
):
    """Build the visible agent loop: model → MCP tools → model → finish."""
    tool_schemas = as_openai_tools(mcp_tools)
    allowed_names = {tool.name for tool in mcp_tools}

    async def tools_node(state: AgentState) -> dict[str, list[dict[str, str]]]:
        """A named async node lets LangGraph await MCP network-style calls."""
        return await run_mcp_tools(state, mcp_client=mcp_client, allowed_names=allowed_names)

    builder = StateGraph(AgentState)
    builder.add_node("model", lambda state: call_model(state, client=client, model=model, tools=tool_schemas))
    builder.add_node("tools", tools_node)
    builder.add_node("finish", finish)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", choose_next_step, {"tools": "tools", "finish": "finish"})
    builder.add_edge("tools", "model")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)


async def current_messages(graph: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    state = await graph.aget_state(config)
    return list(state.values.get("messages", []))


async def show_history(graph: Any, config: dict[str, Any]) -> None:
    messages = await current_messages(graph, config)
    print(f"\n[记忆] 当前会话共有 {len(messages)} 条消息：")
    for message in messages:
        if message.get("role") in {"user", "assistant"} and message.get("content"):
            print(f"- {message['role']}: {message['content']}")


async def chat(thread_id: str) -> int:
    """Run an interactive agent and retain its state after the program exits."""
    client = OpenAI()
    model = os.getenv("OPENAI_MODEL", "deepseek-v4-flash")
    async with Client(mcp) as mcp_client:
        listed = await mcp_client.list_tools()
        print("[MCP 发现工具] " + ", ".join(tool.name for tool in listed.tools))
        async with AsyncSqliteSaver.from_conn_string(str(DATABASE_PATH)) as checkpointer:
            await checkpointer.setup()
            graph = build_graph(client, model, mcp_client, listed.tools, checkpointer)
            print("第八步：完整学习助手（LangGraph + SQLite + MCP + DeepSeek）")
            print(f"记忆数据库：{DATABASE_PATH.name}（仅保存在当前项目文件夹）")
            print("输入问题开始聊天；/history 查看记忆；/new 新建会话；/exit 退出。")
            while True:
                config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 12}
                saved_messages = await current_messages(graph, config)
                print(f"当前会话编号：{thread_id}（已保存 {len(saved_messages)} 条消息）")
                try:
                    user_text = input("你 > ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n已退出。下次用相同 --thread 可以继续这段对话。")
                    return 0
                if not user_text:
                    continue
                if user_text == "/exit":
                    print("已退出。下次用相同 --thread 可以继续这段对话。")
                    return 0
                if user_text == "/history":
                    await show_history(graph, config)
                    continue
                if user_text == "/new":
                    thread_id = f"learning-{uuid.uuid4().hex[:8]}"
                    print(f"已新建空白会话，记忆编号：{thread_id}")
                    continue

                messages: list[dict[str, Any]] = [{"role": "user", "content": user_text}]
                if not saved_messages:
                    messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
                try:
                    final_state = await graph.ainvoke({"messages": messages}, config=config)
                    print("\n助手 >")
                    print(final_state["messages"][-1].get("content") or "模型没有返回文字。")
                except GraphRecursionError:
                    print("工具循环次数过多，程序已安全停止本轮。", file=sys.stderr)
                except AuthenticationError:
                    print("鉴权失败：请检查 .env 中的 DeepSeek API Key。", file=sys.stderr)
                except RateLimitError:
                    print("请求过于频繁或余额不足，请稍后再试。", file=sys.stderr)
                except APIConnectionError:
                    print("无法连接 DeepSeek，请检查网络和 OPENAI_BASE_URL。", file=sys.stderr)
                except APIStatusError as error:
                    print(f"API 返回错误 {error.status_code}: {error.message}", file=sys.stderr)


def main() -> int:
    logging.getLogger().setLevel(logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 缺失。请先完成第一步的 .env 配置。", file=sys.stderr)
        return 2
    return asyncio.run(chat(parse_args().thread))


if __name__ == "__main__":
    raise SystemExit(main())
