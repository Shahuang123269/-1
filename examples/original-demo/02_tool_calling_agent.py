r"""Day 2: let a DeepSeek model decide when to use a calculator tool.

Run:
    .\.venv\Scripts\python.exe 02_tool_calling_agent.py "(25 + 17) * 3 等于多少？"
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


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "计算一个只包含数字和基本算术运算符的表达式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "例如 '(25 + 17) * 3'。",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    }
]

SYSTEM_PROMPT = """你是一个简洁、友好的中文助手。
当用户问题需要进行任何算术计算时，必须调用 calculate 工具，不能心算。
收到工具结果后，用中文给出最终答案。普通概念问题不需要调用工具。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask DeepSeek, with a calculator tool available.")
    parser.add_argument("prompt", help="要交给助手的问题。")
    return parser.parse_args()


def run_calculator(call: Any) -> str:
    """Validate model-produced JSON, then execute the one approved local tool."""
    try:
        arguments = json.loads(call.function.arguments)
        expression = arguments["expression"]
        result = calculate(expression)
    except (json.JSONDecodeError, KeyError, TypeError, CalculationError) as error:
        result = f"计算失败：{error}"

    print(f"[工具调用] calculate(expression={expression!r})" if "expression" in locals() else "[工具调用] 参数无效")
    print(f"[工具结果] {result}")
    return result


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
        for _round in range(3):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                # DeepSeek's thinking-mode tool flow needs extra state. We turn it
                # off here so the tool-calling mechanism stays visible to beginners.
                extra_body={"thinking": {"type": "disabled"}},
            )
            message = response.choices[0].message

            if not message.tool_calls:
                print("\n[最终回答]")
                print(message.content or "模型没有返回文字。")
                return 0

            messages.append(message.model_dump(exclude_none=True))
            for call in message.tool_calls:
                if call.function.name != "calculate":
                    tool_output = "这个工具不在允许列表中。"
                else:
                    tool_output = run_calculator(call)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": tool_output,
                    }
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
