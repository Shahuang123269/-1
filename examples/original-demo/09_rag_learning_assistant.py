r"""Day 9: answer a question from ranked local note passages (a transparent RAG).

Run:
    .\.venv\Scripts\python.exe 09_rag_learning_assistant.py "根据笔记解释 RAG 是什么？"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError

from rag_retrieval import format_context, retrieve


SYSTEM_PROMPT = """你是一名严谨、友好的中文 AI 学习助手。
只使用用户问题后给出的“本地检索片段”回答，不能补充自己的通用知识。
每个事实性结论后都要标注对应来源，格式为【文件名#片段N】。
如果片段不足以回答，明确说“本地知识库中没有足够信息”，不要猜测。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Answer from ranked local notes with source citations.")
    parser.add_argument("prompt", help="要向本地知识库提问的问题。")
    return parser.parse_args()


def build_messages(question: str, context: str) -> list[dict[str, str]]:
    """Keep evidence separate from instructions so it is treated as retrieved data."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"问题：{question}\n\n本地检索片段：\n{context}"},
    ]


def answer(question: str) -> str:
    chunks = retrieve(question)
    print(f"[检索] 从本地笔记找到 {len(chunks)} 个相关片段。")
    if not chunks:
        return "本地知识库中没有足够信息，无法依据笔记回答。"
    for chunk in chunks:
        print(f"[来源] {chunk.citation}（相关度 {chunk.score:.2f}）")

    response = OpenAI().chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "deepseek-v4-flash"),
        messages=build_messages(question, format_context(chunks)),
        extra_body={"thinking": {"type": "disabled"}},
    )
    return response.choices[0].message.content or "模型没有返回文字。"


def main() -> int:
    logging.getLogger().setLevel(logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 缺失。请先完成第一步的 .env 配置。", file=sys.stderr)
        return 2
    try:
        print("[最终回答]")
        print(answer(parse_args().prompt))
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
