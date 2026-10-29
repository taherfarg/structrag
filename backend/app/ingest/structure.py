"""Blocks -> section tree with stable ids, and section-bounded chunks."""

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache

import tiktoken

from .parse import Block, ParsedDoc

CONFIDENCE = {"outline": 0.95, "explicit": 0.9, "inferred": 0.6, "none": 0.3}


@lru_cache
def _enc():
    return tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    return len(_enc().encode(text, disallowed_special=()))


@dataclass
class SectionNode:
    id: str
    parent_id: str | None
    level: int
    ordinal: int
    heading: str
    path: list[str]
    heading_source: str
    page_start: int | None = None
    page_end: int | None = None
    char_start: int = 0
    char_end: int = 0
    blocks: list[Block] = field(default_factory=list)
    children: list["SectionNode"] = field(default_factory=list)

    @property
    def content(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)

    def to_tree(self) -> dict:
        return {"id": self.id, "heading": self.heading, "level": self.level, "page": self.page_start,
                "children": [c.to_tree() for c in self.children]}


@dataclass
class ChunkRec:
    id: str
    section_id: str
    ordinal: int
    text: str
    page: int | None
    char_start: int
    char_end: int
    token_count: int
    content_hash: str


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def build_tree(doc: ParsedDoc, document_id: str) -> tuple[SectionNode, list[SectionNode], float]:
    """Returns (root, sections in reading order, parse confidence).

    Levels are tree depths (root = 0), so a document that jumps from H1 to H3
    still nests H3 directly under H1. Ids hash the heading path plus the
    occurrence count of that path, so re-indexing the same file reproduces them.
    """
    root = SectionNode(f"sec_{_hash(document_id, '')[:16]}", None, 0, 0, doc.title, [], "none")
    flat = [root]
    stack: list[tuple[int, SectionNode]] = [(0, root)]  # (raw heading level, node)
    seen: dict[tuple[str, ...], int] = {}
    for b in doc.blocks:
        if b.kind != "heading":
            node = stack[-1][1]
            node.blocks.append(b)
            continue
        raw = max(b.level or 1, 1)
        while len(stack) > 1 and stack[-1][0] >= raw:
            stack.pop()
        parent = stack[-1][1]
        path = [*parent.path, " ".join(b.text.split())]
        occ = seen.get(tuple(path), 0)
        seen[tuple(path)] = occ + 1
        node = SectionNode(
            id=f"sec_{_hash(document_id, *path, str(occ))[:16]}",
            parent_id=parent.id, level=parent.level + 1, ordinal=len(flat),
            heading=path[-1], path=path, heading_source=b.source,
            page_start=b.page, page_end=b.page, char_start=b.char_start, char_end=b.char_end,
        )
        parent.children.append(node)
        flat.append(node)
        stack.append((raw, node))

    for n in flat:
        pages = [p for p in [n.page_start, *(b.page for b in n.blocks)] if p is not None]
        if pages:
            n.page_start, n.page_end = min(pages), max(pages)
        if n.blocks:
            n.char_end = n.blocks[-1].char_end

    sources = [n.heading_source for n in flat[1:]]
    if not sources:
        confidence = CONFIDENCE["none"]
    else:
        main = max(set(sources), key=sources.count)
        confidence = CONFIDENCE[main] * (0.5 + 0.5 * sources.count(main) / len(sources))
    return root, flat, round(confidence, 3)


def chunk_section(node: SectionNode, max_tokens: int) -> list[ChunkRec]:
    """Pack whole blocks up to max_tokens; split oversized blocks by sentence, then by tokens.

    A chunk never spans two sections, and chunk text is the original text only
    (no heading prefix), so the vector baseline sees no structure.
    """
    pieces: list[tuple[str, int, int | None]] = []  # (text, char_start, page)
    for b in node.blocks:
        if count_tokens(b.text) <= max_tokens:
            pieces.append((b.text, b.char_start, b.page))
        else:
            pieces += [(t, b.char_start + off, b.page) for t, off in _split(b, max_tokens)]

    chunks: list[ChunkRec] = []
    buf: list[tuple[str, int, int | None]] = []

    def emit():
        text = "\n\n".join(p[0] for p in buf)
        h = _hash(text)[:32]
        start = buf[0][1]
        chunks.append(ChunkRec(f"chk_{_hash(node.id, str(len(chunks)), h)[:16]}", node.id, len(chunks), text,
                               buf[0][2], start, buf[-1][1] + len(buf[-1][0]), count_tokens(text), h))

    used = 0
    for p in pieces:
        n = count_tokens(p[0])
        if buf and used + n > max_tokens:
            emit()
            buf, used = [], 0
        buf.append(p)
        used += n
    if buf:
        emit()
    return chunks


def _split(b: Block, max_tokens: int) -> list[tuple[str, int]]:
    """Oversized block -> (piece, offset within block). Tables split by rows and keep their header."""
    import re

    text = b.text
    if b.kind == "table":
        lines = text.split("\n")
        header, rows = lines[:2], lines[2:]
        out, cur, cur_start, pos = [], [], None, len("\n".join(header)) + 1
        for row in rows:
            if cur and count_tokens("\n".join(header + cur + [row])) > max_tokens:
                out.append(("\n".join(header + cur), cur_start))
                cur, cur_start = [], None
            if cur_start is None:
                cur_start = pos
            cur.append(row)
            pos += len(row) + 1
        if cur:
            out.append(("\n".join(header + cur), cur_start))
        return out

    sentences, out, cur, cur_start = [], [], "", 0
    pos = 0
    for s in re.split(r"(?<=[.!?])\s+", text):
        start = text.find(s, pos)
        pos = start + len(s)
        sentences.append((s, start))
    for s, start in sentences:
        if count_tokens(s) > max_tokens:  # one giant sentence: cut by tokens
            if cur:
                out.append((cur, cur_start))
                cur = ""
            ids = _enc().encode(s, disallowed_special=())
            off = start
            for i in range(0, len(ids), max_tokens):
                piece = _enc().decode(ids[i : i + max_tokens])
                out.append((piece, off))
                off += len(piece)
            continue
        if cur and count_tokens(cur + " " + s) > max_tokens:
            out.append((cur, cur_start))
            cur = ""
        if not cur:
            cur, cur_start = s, start
        else:
            cur += " " + s
    if cur:
        out.append((cur, cur_start))
    return out
