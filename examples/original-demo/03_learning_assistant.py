r"""Day 3: a small DeepSeek learning assistant with two local tools.

Run:
    .\.venv\Scripts\python.exe 03_learning_assistant.py "根据我的笔记解释 LangGraph 是什么？"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError

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
                "properties": {
                    "expression": {"type": "string", "description": "例如 '(25 + 17) * 3'。"}
                },
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
                "properties": {
                    "query": {"type": "string", "description": "要检索的主题，例如 'LangGraph 状态图'。"}
                },
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask DeepSeek with calculator and local-note tools.")
    parser.add_argument("prompt", help="要交给学习助手的问题。")
    return parser.parse_args()


def run_tool(call: Any) -> str:
    """Validate model-produced arguments, then run only approved local tools."""
    try:
        arguments = json.loads(call.function.arguments)
    except json.JSONDecodeError:
        return "工具参数不是有效 JSON。"

    if call.function.name == "calculate":
        try:
            expression = arguments["expression"]
            result = calculate(expression)
        except (KeyError, TypeError, CalculationError) as error:
            result = f"计算失败：{error}"
        print(f"[工具调用] calculate(expression={expression!r})" if "expression" in locals() else "[工具调用] calculate(参数无效)")
        print(f"[工具结果] {result}")
        return result

    if call.function.name == "search_notes":
        query = arguments.get("query")
        result = search_notes(query) if isinstance(query, str) else "检索失败：query 必须是文字。"
        print(f"[工具调用] search_notes(query={query!r})")
        print(f"[工具结果] 已返回 {len(result)} 个字符的本地笔记内容。")
        return result

    return "这个工具不在允许列表中。"


def main() -> int:
    load_dotenv()
    args = parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 缺失。请先完成第一步的 .env 配置。", file=sys.stderr)
        return 2

    client = OpenAI()
    model = os.getenv("OPENAI_MODEL", "deepseek-v4-flash")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": args.prompt},
    ]

    try:
        for _round in range(4):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                # Non-thinking mode keeps the learning loop short and transparent.
                extra_body={"thinking": {"type": "disabled"}},
            )
            message = response.choices[0].message

            if not message.tool_calls:
                print("\n[最终回答]")
                print(message.content or "模型没有返回文字。")
                return 0

            messages.append(message.model_dump(exclude_none=True))
            for call in message.tool_calls:
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": run_tool(call)}
                )

        print("工具调用次数超过上限，程序已安全停止。", file=sys.stderr)
        return 7
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
