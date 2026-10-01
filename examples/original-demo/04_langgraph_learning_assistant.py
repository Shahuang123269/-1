r"""Day 4: express the learning assistant's loop as a LangGraph workflow.

Run:
    .\.venv\Scripts\python.exe 04_langgraph_learning_assistant.py "根据笔记解释 LangGraph 的状态、节点和边"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Literal

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError
from typing_extensions import TypedDict

from calculator import CalculationError, calculate
from note_search import search_notes


MAX_MODEL_CALLS = 4

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
当用户询问 LLM、Agent、Tool、LangGraph 或“笔记里有什么”这类学习问题时，必须先调用 search_notes。
回答笔记相关问题时，只能依据工具返回的笔记；若没有相关内容，要直接说明“本地笔记中没有相关资料”。
当用户问题需要算术计算时，必须调用 calculate，不能心算。
收到工具结果后，用中文给出最终答案，并在最后标出使用的笔记文件名。"""


class AgentState(TypedDict):
    """The shared information that flows through the LangGraph nodes."""

    messages: list[dict[str, Any]]
    rounds: int
    answer: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A LangGraph learning assistant using DeepSeek.")
    parser.add_argument("prompt", help="要交给学习助手的问题。")
    return parser.parse_args()


def call_model(state: AgentState, *, client: OpenAI, model: str) -> dict[str, Any]:
    """Node 1: ask the model for either a tool call or a final answer."""
    print(f"[节点：model] 第 {state['rounds'] + 1} 次调用模型")
    response = client.chat.completions.create(
        model=model,
        messages=state["messages"],
        tools=TOOLS,
        tool_choice="auto",
        # This avoids extra reasoning-state handling in a first LangGraph lesson.
        extra_body={"thinking": {"type": "disabled"}},
    )
    message = response.choices[0].message.model_dump(exclude_none=True)
    return {"messages": state["messages"] + [message], "rounds": state["rounds"] + 1}


def run_tools(state: AgentState) -> dict[str, Any]:
    """Node 2: run only the two approved local tools."""
    print("[节点：tools] 执行模型请求的本地工具")
    tool_messages: list[dict[str, str]] = []
    for call in state["messages"][-1].get("tool_calls", []):
        result = execute_tool(call)
        tool_messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    return {"messages": state["messages"] + tool_messages}


def execute_tool(call: dict[str, Any]) -> str:
    """Validate model arguments before performing a local calculation or note search."""
    name = call.get("function", {}).get("name")
    raw_arguments = call.get("function", {}).get("arguments", "{}")
    try:
        arguments = json.loads(raw_arguments)
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
    """Conditional edge: a tool call loops to tools; otherwise the graph ends."""
    has_tool_calls = bool(state["messages"][-1].get("tool_calls"))
    if has_tool_calls and state["rounds"] < MAX_MODEL_CALLS:
        print("[条件边] 模型请求了工具：model → tools")
        return "tools"
    if has_tool_calls:
        print("[条件边] 达到模型调用上限：model → finish")
    else:
        print("[条件边] 模型已给出文字回答：model → finish")
    return "finish"


def finish(state: AgentState) -> dict[str, str]:
    """Node 3: take the last model message as the final answer."""
    print("[节点：finish] 工作流结束")
    return {"answer": state["messages"][-1].get("content") or "模型没有返回文字。"}


def build_graph(client: OpenAI, model: str):
    """Create the visible graph: START → model → (tools or finish) → END."""
    builder = StateGraph(AgentState)
    builder.add_node("model", lambda state: call_model(state, client=client, model=model))
    builder.add_node("tools", run_tools)
    builder.add_node("finish", finish)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", choose_next_step, {"tools": "tools", "finish": "finish"})
    builder.add_edge("tools", "model")
    builder.add_edge("finish", END)
    return builder.compile()


def main() -> int:
    # Some Windows terminals use GBK and cannot print every emoji a model emits.
    # Replacing only unsupported characters keeps a successful answer from crashing.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    load_dotenv()
    args = parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 缺失。请先完成第一步的 .env 配置。", file=sys.stderr)
        return 2

    client = OpenAI()
    model = os.getenv("OPENAI_MODEL", "deepseek-v4-flash")
    graph = build_graph(client, model)
    initial_state: AgentState = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": args.prompt},
        ],
        "rounds": 0,
        "answer": "",
    }

    try:
        final_state = graph.invoke(initial_state)
        print("\n[最终回答]")
        print(final_state["answer"])
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
