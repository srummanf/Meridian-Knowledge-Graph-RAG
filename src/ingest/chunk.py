"""Corpus -> chunks.

Policy (architecture.md §6, phases.md §1.2):

* One chunk per document. ``chunk_id = "<relpath-under-data>"``.
* A document over :data:`SPLIT_THRESHOLD_TOKENS` is split on its ``##`` headings,
  then the resulting sections are *packed* greedily into sub-chunks of about
  :data:`TARGET_SUBCHUNK_TOKENS` tokens (not one chunk per heading — the sections
  in this corpus are only ~30 tokens each). A split chunk's id is
  ``"<relpath>#<slug-of-first-section>"``.

Token counts are estimated from character length (``chars / 4``); calibrated
against the ``bge-small`` tokenizer over this corpus the ratio runs 3.5–4.9, so
``4`` is a slight over-estimate, which biases toward splitting — acceptable.
"""

from __future__ import annotations

from pathlib import Path

from langchain_text_splitters import MarkdownHeaderTextSplitter
from pydantic import BaseModel, Field

from src.config import DATA_DIR
from src.models.domain import slugify

SPLIT_THRESHOLD_TOKENS = 280
TARGET_SUBCHUNK_TOKENS = 250
CHARS_PER_TOKEN = 4
MIN_CHUNK_CHARS = 20

EXCLUDED_FILES = frozenset({"ONTOLOGY.md", "SCHEMA.md", "README.md"})
EXCLUDED_DIRS = frozenset({"benchmark"})

_HEADERS_TO_SPLIT_ON = [("##", "section")]


class Chunk(BaseModel):
    """One unit of text sent to extraction and to the vector store."""

    chunk_id: str = Field(min_length=1)
    document: str = Field(min_length=1)  # relpath under data/, forward slashes
    content: str = Field(min_length=1)


def estimate_tokens(text: str) -> int:
    """Rough token count: character length over :data:`CHARS_PER_TOKEN`."""
    return round(len(text) / CHARS_PER_TOKEN)


def corpus_files(data_dir: Path = DATA_DIR) -> list[Path]:
    """Every corpus ``.md`` file, excluding the spec docs and the benchmark."""
    files = [
        p
        for p in sorted(data_dir.rglob("*.md"))
        if p.name not in EXCLUDED_FILES
        and not (EXCLUDED_DIRS & set(p.relative_to(data_dir).parts))
    ]
    return files


def _relpath(path: Path, data_dir: Path) -> str:
    return path.relative_to(data_dir).as_posix()


def _pack_sections(fragments: list[str]) -> list[list[str]]:
    """Greedily group section texts into ~:data:`TARGET_SUBCHUNK_TOKENS` bundles."""
    groups: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for fragment in fragments:
        tokens = estimate_tokens(fragment)
        if current and current_tokens + tokens > TARGET_SUBCHUNK_TOKENS:
            groups.append(current)
            current, current_tokens = [], 0
        current.append(fragment)
        current_tokens += tokens
    if current:
        groups.append(current)
    return groups


def _first_section_slug(text: str, fallback: str) -> str:
    """Slug of the first ``## Heading`` line in ``text``; ``fallback`` if none."""
    for line in text.splitlines():
        if line.startswith("## "):
            return slugify(line[3:])
    return fallback


def chunk_document(path: Path, data_dir: Path = DATA_DIR) -> list[Chunk]:
    """Split one document into one or more :class:`Chunk` objects."""
    text = path.read_text(encoding="utf-8").strip()
    relpath = _relpath(path, data_dir)

    if estimate_tokens(text) <= SPLIT_THRESHOLD_TOKENS:
        return [Chunk(chunk_id=relpath, document=relpath, content=text)]

    splitter = MarkdownHeaderTextSplitter(_HEADERS_TO_SPLIT_ON, strip_headers=False)
    fragments = [doc.page_content.strip() for doc in splitter.split_text(text)]
    fragments = [f for f in fragments if f]
    groups = _pack_sections(fragments)

    if len(groups) <= 1:  # everything repacked into one bundle after all
        return [Chunk(chunk_id=relpath, document=relpath, content=text)]

    chunks: list[Chunk] = []
    seen: set[str] = set()
    for index, group in enumerate(groups):
        content = "\n\n".join(group)
        slug = _first_section_slug(content, fallback=f"part-{index + 1}")
        while slug in seen:
            slug = f"{slug}-{index + 1}"
        seen.add(slug)
        chunks.append(
            Chunk(chunk_id=f"{relpath}#{slug}", document=relpath, content=content)
        )
    return chunks


def chunk_corpus(data_dir: Path = DATA_DIR) -> list[Chunk]:
    """Chunk every corpus document. Chunk ids are unique across the result."""
    chunks: list[Chunk] = []
    for path in corpus_files(data_dir):
        chunks.extend(chunk_document(path, data_dir))
    return chunks
