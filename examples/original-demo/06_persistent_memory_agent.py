r"""Day 6: a LangGraph assistant that preserves one conversation in SQLite.

Run:
    .\.venv\Scripts\python.exe 06_persistent_memory_agent.py --thread xiaowang
"""

from __future__ import annotations

import argparse
import json
import operator
import os
from pathlib import Path
import sqlite3
import sys
import uuid
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError
from typing_extensions import TypedDict

from calculator import CalculationError, calculate
from note_search import search_notes


DATABASE_PATH = Path(__file__).with_name("agent_memory.sqlite")
SYSTEM_PROMPT = """你是一名简洁、友好的中文 AI 学习助手。
结合当前对话中的已有信息回答后续问题；不知道时请直接说不知道，不要编造。
当用户询问 LLM、Agent、Tool、LangGraph 或“笔记里有什么”时，必须先调用 search_notes。
回答笔记相关问题时，只能依据工具返回的笔记；没有相关内容时直接说明。
需要算术计算时必须调用 calculate，不能心算。"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "计算一个只包含数字和基本算术运算符的表达式。",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "例如 '(25 + 17) * 3'。"}},
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "在项目 notes 文件夹中的本地学习笔记里检索相关内容。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "要检索的主题。"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]


class AgentState(TypedDict):
    """Messages are appended and checkpointed under one thread ID."""

    messages: Annotated[list[dict[str, Any]], operator.add]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeepSeek learning agent with SQLite-backed LangGraph memory.")
    parser.add_argument("--thread", default="my-persistent-session", help="要继续的会话编号，例如 xiaowang。")
    return parser.parse_args()


def call_model(state: AgentState, *, client: OpenAI, model: str) -> dict[str, list[dict[str, Any]]]:
    print("[节点：model] 从 SQLite 读取对话状态并调用模型")
    response = client.chat.completions.create(
        model=model,
        messages=state["messages"],
        tools=TOOLS,
        tool_choice="auto",
        extra_body={"thinking": {"type": "disabled"}},
    )
    return {"messages": [response.choices[0].message.model_dump(exclude_none=True)]}


def execute_tool(call: dict[str, Any]) -> str:
    """Validate arguments and execute only approved local tools."""
    name = call.get("function", {}).get("name")
    try:
        arguments = json.loads(call.get("function", {}).get("arguments", "{}"))
    except json.JSONDecodeError:
        return "工具参数不是有效 JSON。"
    if name == "calculate":
        try:
            expression = arguments["expression"]
            result = calculate(expression)
        except (KeyError, TypeError, CalculationError) as error:
            result = f"计算失败：{error}"
        print(f"  [工具调用] calculate(expression={expression!r})" if "expression" in locals() else "  [工具调用] calculate(参数无效)")
        print(f"  [工具结果] {result}")
        return result
    if name == "search_notes":
        query = arguments.get("query")
        result = search_notes(query) if isinstance(query, str) else "检索失败：query 必须是文字。"
        print(f"  [工具调用] search_notes(query={query!r})")
        print(f"  [工具结果] 已返回 {len(result)} 个字符的本地笔记内容。")
        return result
    return "这个工具不在允许列表中。"


def run_tools(state: AgentState) -> dict[str, list[dict[str, str]]]:
    print("[节点：tools] 执行本地工具")
    outputs = []
    for call in state["messages"][-1].get("tool_calls", []):
        outputs.append({"role": "tool", "tool_call_id": call["id"], "content": execute_tool(call)})
    return {"messages": outputs}


def choose_next_step(state: AgentState) -> Literal["tools", "finish"]:
    if state["messages"][-1].get("tool_calls"):
        print("[条件边] model → tools")
        return "tools"
    print("[条件边] model → finish")
    return "finish"


def finish(_: AgentState) -> dict[str, str]:
    print("[节点：finish] 本轮结束，状态已经写入 SQLite")
    return {}


def build_graph(client: OpenAI, model: str, connection: sqlite3.Connection):
    """Compile the graph with a SQLite checkpointer (persistent local memory)."""
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    builder = StateGraph(AgentState)
    builder.add_node("model", lambda state: call_model(state, client=client, model=model))
    builder.add_node("tools", run_tools)
    builder.add_node("finish", finish)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", choose_next_step, {"tools": "tools", "finish": "finish"})
    builder.add_edge("tools", "model")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)


def current_messages(graph: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    return list(graph.get_state(config).values.get("messages", []))


def show_history(graph: Any, config: dict[str, Any]) -> None:
    messages = current_messages(graph, config)
    print(f"\n[记忆] 当前会话共有 {len(messages)} 条消息：")
    for message in messages:
        if message.get("role") in {"user", "assistant"} and message.get("content"):
            print(f"- {message['role']}: {message['content']}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    load_dotenv()
    args = parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 缺失。请先完成第一步的 .env 配置。", file=sys.stderr)
        return 2

    # This database contains conversation text. Keep it local and private.
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    graph = build_graph(OpenAI(), os.getenv("OPENAI_MODEL", "deepseek-v4-flash"), connection)
    thread_id = args.thread
    try:
        print("第六步：带持久记忆的 LangGraph 学习助手")
        print(f"记忆数据库：{DATABASE_PATH.name}（仅保存在当前项目文件夹）")
        print("输入问题开始聊天；/history 查看记忆；/new 新建会话；/exit 退出。")
        while True:
            config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 12}
            saved_messages = current_messages(graph, config)
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
                show_history(graph, config)
                continue
            if user_text == "/new":
                thread_id = f"learning-{uuid.uuid4().hex[:8]}"
                print(f"已新建空白会话，记忆编号：{thread_id}")
                continue

            messages = [{"role": "user", "content": user_text}]
            if not saved_messages:
                messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
            try:
                final_state = graph.invoke({"messages": messages}, config=config)
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
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
