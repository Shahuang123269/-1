r"""Day 5: a LangGraph chat agent with short-term, in-process memory.

Run:
    .\.venv\Scripts\python.exe 05_memory_chat_agent.py
"""

from __future__ import annotations

import argparse
import json
import operator
import os
import sys
import uuid
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError
from typing_extensions import TypedDict

from calculator import CalculationError, calculate
from note_search import search_notes


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
                "properties": {"query": {"type": "string", "description": "要检索的主题，例如 'LangGraph 状态图'。"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]

SYSTEM_PROMPT = """你是一名简洁、友好的中文 AI 学习助手。
你要结合当前对话中的已有信息回答后续问题；不知道时请直接说不知道，不要编造。
当用户询问 LLM、Agent、Tool、LangGraph 或“笔记里有什么”这类学习问题时，必须先调用 search_notes。
回答笔记相关问题时，只能依据工具返回的笔记；若没有相关内容，要直接说明“本地笔记中没有相关资料”。
当用户问题需要算术计算时，必须调用 calculate，不能心算。
收到工具结果后，用中文给出最终答案，并在最后标出使用的笔记文件名。"""


class AgentState(TypedDict):
    """State that is appended to and saved for one LangGraph conversation thread."""

    messages: Annotated[list[dict[str, Any]], operator.add]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A DeepSeek learning chat agent with LangGraph memory.")
    parser.add_argument("--thread", default="my-learning-session", help="本次聊天的记忆编号。")
    return parser.parse_args()


def call_model(state: AgentState, *, client: OpenAI, model: str) -> dict[str, list[dict[str, Any]]]:
    """Node: give the complete conversation state to the model."""
    print("[节点：model] 读取当前对话记忆并调用模型")
    response = client.chat.completions.create(
        model=model,
        messages=state["messages"],
        tools=TOOLS,
        tool_choice="auto",
        extra_body={"thinking": {"type": "disabled"}},
    )
    return {"messages": [response.choices[0].message.model_dump(exclude_none=True)]}


def run_tools(state: AgentState) -> dict[str, list[dict[str, str]]]:
    """Node: run the tool calls requested by the last model message."""
    print("[节点：tools] 执行本地工具")
    outputs: list[dict[str, str]] = []
    for call in state["messages"][-1].get("tool_calls", []):
        outputs.append({"role": "tool", "tool_call_id": call["id"], "content": execute_tool(call)})
    return {"messages": outputs}


def execute_tool(call: dict[str, Any]) -> str:
    """Execute only a validated calculation or local note lookup."""
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


def choose_next_step(state: AgentState) -> Literal["tools", "finish"]:
    """Conditional edge: tools requested means loop; otherwise finish the turn."""
    if state["messages"][-1].get("tool_calls"):
        print("[条件边] model → tools")
        return "tools"
    print("[条件边] model → finish")
    return "finish"


def finish(_: AgentState) -> dict[str, str]:
    """A named ending node makes the graph's completion visible."""
    print("[节点：finish] 本轮聊天结束，记忆已保存")
    return {}


def build_graph(client: OpenAI, model: str):
    """Compile the graph with an in-memory checkpointer for short-term memory."""
    builder = StateGraph(AgentState)
    builder.add_node("model", lambda state: call_model(state, client=client, model=model))
    builder.add_node("tools", run_tools)
    builder.add_node("finish", finish)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", choose_next_step, {"tools": "tools", "finish": "finish"})
    builder.add_edge("tools", "model")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=InMemorySaver())


def show_history(graph: Any, config: dict[str, Any]) -> None:
    """Display the current in-memory message history without making an API call."""
    state = graph.get_state(config).values
    messages = state.get("messages", [])
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

    graph = build_graph(OpenAI(), os.getenv("OPENAI_MODEL", "deepseek-v4-flash"))
    thread_id = args.thread
    first_turn = True
    print("第五步：带短期记忆的 LangGraph 学习助手")
    print("输入问题开始聊天；/history 查看记忆；/new 新建会话；/exit 退出。")
    print(f"当前记忆编号：{thread_id}")

    while True:
        try:
            user_text = input("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0

        if not user_text:
            continue
        if user_text == "/exit":
            print("已退出。关闭程序后，本次短期记忆会清空。")
            return 0
        if user_text == "/history":
            show_history(graph, {"configurable": {"thread_id": thread_id}})
            continue
        if user_text == "/new":
            thread_id = f"learning-{uuid.uuid4().hex[:8]}"
            first_turn = True
            print(f"已新建空白会话，记忆编号：{thread_id}")
            continue

        messages = [{"role": "user", "content": user_text}]
        if first_turn:
            messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
            first_turn = False
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 12}
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


if __name__ == "__main__":
    raise SystemExit(main())
