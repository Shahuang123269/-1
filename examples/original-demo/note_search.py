"""A tiny, local-only note search tool for Day 3 of the Mini Agent lab."""

from __future__ import annotations

import re
from pathlib import Path


NOTES_DIRECTORY = Path(__file__).parent / "notes"
_COMMON_CHINESE_CHARACTERS = set("的一是在不了有和与及我你他她它这那请问把给根据我的笔记解释什么吗呢吧啊")


def search_notes(query: str, limit: int = 3) -> str:
    """Return the most relevant local Markdown notes for *query*.

    This deliberately uses simple keyword matching instead of a vector database.
    It makes the retrieval step visible before later lessons introduce embeddings.
    """
    if not isinstance(query, str) or not query.strip():
        return "检索失败：问题不能为空。"
    if len(query) > 200:
        return "检索失败：问题过长，最多 200 个字符。"
    if not isinstance(limit, int) or not 1 <= limit <= 5:
        return "检索失败：limit 必须在 1 到 5 之间。"

    documents = list(NOTES_DIRECTORY.glob("*.md"))
    if not documents:
        return "没有找到本地笔记。"

    ranked: list[tuple[int, Path, str]] = []
    for path in documents:
        content = path.read_text(encoding="utf-8")
        score = _score(query, content)
        if score > 0:
            ranked.append((score, path, content))

    if not ranked:
        return "本地笔记中没有找到相关内容。"

    ranked.sort(key=lambda item: (-item[0], item[1].name))
    excerpts = []
    for _score_value, path, content in ranked[:limit]:
        excerpt = content.strip()[:900]
        excerpts.append(f"来源：{path.name}\n---\n{excerpt}")
    return "\n\n".join(excerpts)


def _score(query: str, content: str) -> int:
    """Score a document with English keywords and Chinese character bigrams."""
    query_lower = query.lower()
    content_lower = content.lower()
    score = 0

    for token in re.findall(r"[a-z][a-z0-9_-]{1,}", query_lower):
        score += content_lower.count(token) * 20

    chinese = "".join(
        character
        for character in query
        if "\u4e00" <= character <= "\u9fff" and character not in _COMMON_CHINESE_CHARACTERS
    )
    for bigram in {chinese[index : index + 2] for index in range(len(chinese) - 1)}:
        score += content.count(bigram) * 3

    return score
