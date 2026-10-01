"""A tiny, dependency-free lexical retriever for the project's local notes.

It is intentionally transparent: every answer can show the exact note chunk
that was retrieved, before you move on to embedding models and vector stores.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path
import re


NOTES_DIRECTORY = Path(__file__).with_name("notes")
NOTE_SUFFIXES = {".md", ".txt"}
MAX_CHUNK_CHARACTERS = 420


@dataclass(frozen=True)
class RetrievedChunk:
    """One ranked source passage returned by retrieval."""

    source: str
    chunk_number: int
    text: str
    score: float

    @property
    def citation(self) -> str:
        return f"{self.source}#片段{self.chunk_number}"


def tokenize(text: str) -> list[str]:
    """Keep English terms whole and use individual Chinese characters as tokens."""
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text.lower())


def split_into_chunks(text: str, *, max_characters: int = MAX_CHUNK_CHARACTERS) -> list[str]:
    """Split Markdown/text into readable paragraphs without cutting short paragraphs."""
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_characters:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(
                paragraph[start : start + max_characters]
                for start in range(0, len(paragraph), max_characters)
            )
        elif not current:
            current = paragraph
        elif len(current) + 1 + len(paragraph) <= max_characters:
            current = f"{current}\n{paragraph}"
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def load_note_chunks(notes_directory: Path = NOTES_DIRECTORY) -> list[RetrievedChunk]:
    """Read only local .md/.txt notes and assign each passage a stable citation."""
    chunks: list[RetrievedChunk] = []
    if not notes_directory.is_dir():
        return chunks
    for path in sorted(notes_directory.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.suffix.lower() not in NOTE_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, chunk in enumerate(split_into_chunks(text), start=1):
            chunks.append(RetrievedChunk(path.name, number, chunk, 0.0))
    return chunks


def retrieve(query: str, *, notes_directory: Path = NOTES_DIRECTORY, limit: int = 3) -> list[RetrievedChunk]:
    """Rank local passages with the BM25 lexical retrieval formula."""
    if not isinstance(query, str) or not query.strip() or limit < 1:
        return []
    documents = load_note_chunks(notes_directory)
    query_tokens = tokenize(query)
    if not documents or not query_tokens:
        return []

    document_tokens = [tokenize(document.text) for document in documents]
    document_frequencies: Counter[str] = Counter(
        token for tokens in document_tokens for token in set(tokens)
    )
    average_length = sum(len(tokens) for tokens in document_tokens) / len(document_tokens)
    k1, b = 1.5, 0.75
    query_counts = Counter(query_tokens)
    ranked: list[RetrievedChunk] = []

    for document, tokens in zip(documents, document_tokens, strict=True):
        frequencies = Counter(tokens)
        score = 0.0
        for token, query_frequency in query_counts.items():
            frequency = frequencies[token]
            if not frequency:
                continue
            inverse_document_frequency = math.log(
                1 + (len(documents) - document_frequencies[token] + 0.5) / (document_frequencies[token] + 0.5)
            )
            denominator = frequency + k1 * (1 - b + b * len(tokens) / average_length)
            score += query_frequency * inverse_document_frequency * frequency * (k1 + 1) / denominator
        if score > 0:
            ranked.append(RetrievedChunk(document.source, document.chunk_number, document.text, score))
    return sorted(ranked, key=lambda item: (-item.score, item.source, item.chunk_number))[:limit]


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Make retrieved evidence easy for an LLM and a human to inspect."""
    if not chunks:
        return "本地知识库中没有找到相关片段。"
    return "\n\n".join(f"[来源：{chunk.citation}]\n{chunk.text}" for chunk in chunks)
