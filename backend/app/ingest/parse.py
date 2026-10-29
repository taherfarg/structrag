"""File bytes -> ordered blocks (heading / paragraph / table) with page and character anchors.

Heading evidence, strongest first:
  outline   PDF bookmarks
  explicit  DOCX heading styles, Markdown `#`
  inferred  font size, bold, section numbering (`3.2.1 Title`), ALL CAPS lines
"""

import io
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Literal

log = logging.getLogger(__name__)

SUPPORTED = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


@dataclass
class Block:
    kind: Literal["heading", "paragraph", "table"]
    text: str
    page: int | None = None
    level: int | None = None
    source: str = "none"  # heading evidence: outline / explicit / inferred
    size: float | None = None
    bold: bool = False
    char_start: int = 0
    char_end: int = 0


@dataclass
class ParsedDoc:
    title: str
    blocks: list[Block]
    page_count: int | None
    method: str
    warnings: list[str] = field(default_factory=list)


def parse(data: bytes, filename: str) -> ParsedDoc:
    ext = PurePath(filename).suffix.lower()
    stem = PurePath(filename).stem
    if ext == ".pdf":
        doc = parse_pdf(data, stem)
    elif ext == ".docx":
        doc = parse_docx(data, stem)
    elif ext in (".md", ".markdown"):
        doc = parse_markdown(data.decode("utf-8", errors="replace"), stem)
    elif ext == ".txt":
        doc = parse_text(data.decode("utf-8", errors="replace"), stem)
    else:
        raise ValueError(f"unsupported file type: {ext}")
    doc.blocks = [b for b in doc.blocks if b.text.strip()]
    _promote_title(doc, stem)
    _assign_offsets(doc.blocks)
    return doc


# ---------------------------------------------------------------- shared helpers
NUMBERED = re.compile(r"^(?:(?:section|chapter|part)\s+)?(\d{1,2}(?:\.\d{1,3}){0,4})\.?\s+(\S.*)$", re.I)


def norm(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


def _assign_offsets(blocks: list[Block]) -> None:
    """Offsets into the document text formed by joining blocks with blank lines."""
    pos = 0
    for b in blocks:
        b.char_start, b.char_end = pos, pos + len(b.text)
        pos = b.char_end + 2


def _promote_title(doc: ParsedDoc, stem: str) -> None:
    """A lone top-level heading at the very start is the document title, not a section.

    Only when the file gave no title of its own, or that title is this heading.
    """
    heads = [b for b in doc.blocks if b.kind == "heading"]
    if not heads or doc.blocks[0] is not heads[0]:
        return
    if norm(doc.title) == norm(heads[0].text):  # the file's own title, repeated as a heading
        doc.blocks.pop(0)
        return
    if doc.title != stem:
        return
    top = min(h.level or 1 for h in heads)
    if (heads[0].level or 1) == top and sum(1 for h in heads if (h.level or 1) == top) == 1 and len(heads) > 1:
        doc.title = heads[0].text.strip()
        doc.blocks.pop(0)


def infer_headings(blocks: list[Block]) -> int:
    """Mark paragraph blocks that look like headings. Returns how many were found."""
    sized = [(b.size, len(b.text)) for b in blocks if b.kind == "paragraph" and b.size]
    body = None
    if sized:
        weights: Counter[float] = Counter()
        for size, n in sized:
            weights[round(size * 2) / 2] += n
        body = weights.most_common(1)[0][0]

    candidates: list[tuple[Block, int | None]] = []  # (block, numbering depth)
    for b in blocks:
        if b.kind != "paragraph":
            continue
        t = " ".join(b.text.split())
        if not t or len(t) > 120 or len(t.split()) > 14 or b.text.count("\n") > 1:
            continue
        if t[0].islower() or t.endswith((",", ";")):
            continue
        m = NUMBERED.match(t)
        bigger = body is not None and b.size is not None and b.size >= body * 1.12
        emphasised = bigger or (b.bold and (body is None or (b.size or body) >= body * 0.98))
        has_font = body is not None and b.size is not None
        if m and not t.endswith(".") and (emphasised or not has_font):
            candidates.append((b, m.group(1).count(".") + 1))
        elif emphasised and not t.endswith("."):
            candidates.append((b, None))
        elif not has_font and t.isupper() and len(t.split()) <= 8 and any(c.isalpha() for c in t):
            candidates.append((b, None))

    # Unnumbered headings take levels from their font size rank; bold-at-body-size sits lowest.
    sizes = sorted({round((b.size or 0) * 2) / 2 for b, d in candidates if d is None}, reverse=True)
    for b, depth in candidates:
        b.kind, b.source = "heading", "inferred"
        b.level = depth if depth is not None else sizes.index(round((b.size or 0) * 2) / 2) + 1
    return len(candidates)


# ---------------------------------------------------------------- PDF
def parse_pdf(data: bytes, stem: str) -> ParsedDoc:
    import pymupdf

    pdf = pymupdf.open(stream=data, filetype="pdf")
    warnings: list[str] = []
    method = "pdf"
    pages: list[list[tuple[Block, bool]]] = []  # (block, sits in the header/footer band)
    edge_text: Counter[str] = Counter()

    for pno, page in enumerate(pdf, start=1):
        height = page.rect.height or 1
        items: list[tuple[float, Block, bool]] = []  # (y, block, is_edge)
        table_boxes = []
        try:
            for tab in page.find_tables().tables:
                md = tab.to_markdown(clean=True).strip()
                if md:
                    table_boxes.append(pymupdf.Rect(tab.bbox))
                    items.append((tab.bbox[1], Block("table", md, page=pno), False))
        except Exception as e:  # table detection is best effort
            warnings.append(f"table detection failed on page {pno}: {e}")

        raw = page.get_text("dict", sort=True)
        if not any(b.get("type") == 0 for b in raw["blocks"]):
            try:
                tp = page.get_textpage_ocr(full=True)
                raw = page.get_text("dict", sort=True, textpage=tp)
                method = "pdf+ocr"
            except Exception:
                warnings.append(f"page {pno} has no text layer and OCR is unavailable")

        for blk in raw["blocks"]:
            if blk.get("type") != 0:
                continue
            for seg_text, size, bold, bbox in _segments(blk):
                center = pymupdf.Point((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
                if any(center in r for r in table_boxes):
                    continue
                edge = bbox[1] < height * 0.08 or bbox[3] > height * 0.92
                if edge:
                    edge_text[re.sub(r"\d+", "#", norm(seg_text))] += 1
                items.append((bbox[1], Block("paragraph", seg_text, page=pno, size=size, bold=bold), edge))
        items.sort(key=lambda it: it[0])
        pages.append([(b, e) for _, b, e in items])

    # Drop running headers/footers: edge lines repeated on at least half the pages.
    repeated = {t for t, n in edge_text.items() if len(pdf) >= 3 and n >= len(pdf) / 2}
    blocks: list[Block] = []
    for page_blocks in pages:
        for b, edge in page_blocks:
            key = re.sub(r"\d+", "#", norm(b.text))
            if edge and (key in repeated or re.fullmatch(r"(page )?#( of #)?", key)):
                continue
            blocks.append(b)

    toc = [(lvl, title.strip(), page) for lvl, title, page in pdf.get_toc(simple=True) if title.strip()]
    if len(toc) >= 2:
        _apply_outline(blocks, toc)
        method += "+outline"
    elif infer_headings(blocks):
        method += "+inferred"
    else:
        warnings.append("no headings found; document indexed as a single section")

    meta_title = (pdf.metadata or {}).get("title") or ""
    return ParsedDoc(meta_title.strip() or stem, blocks, len(pdf), method, warnings)


def _segments(blk: dict):
    """Split a PyMuPDF text block where font size or weight changes between lines."""
    seg_lines: list[str] = []
    seg_size = seg_bold = None
    x0 = y0 = x1 = y1 = None
    for line in blk["lines"]:
        spans = [s for s in line["spans"] if s["text"].strip()]
        if not spans:
            continue
        # NFKC folds ligatures (the "fi" in "Certificate" arrives as U+FB01) and other presentation forms.
        text = unicodedata.normalize("NFKC", "".join(s["text"] for s in line["spans"])).strip()
        n = sum(len(s["text"]) for s in spans)
        size = round(sum(s["size"] * len(s["text"]) for s in spans) / n, 1)
        bold = all((s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
        if seg_lines and (abs(size - seg_size) > 0.6 or bold != seg_bold):
            yield _join_lines(seg_lines), seg_size, seg_bold, (x0, y0, x1, y1)
            seg_lines = []
        if not seg_lines:
            seg_size, seg_bold = size, bold
            x0, y0, x1, y1 = line["bbox"]
        seg_lines.append(text)
        x1, y1 = max(x1, line["bbox"][2]), line["bbox"][3]
    if seg_lines:
        yield _join_lines(seg_lines), seg_size, seg_bold, (x0, y0, x1, y1)


def _join_lines(lines: list[str]) -> str:
    out = lines[0]
    for line in lines[1:]:
        out = out[:-1] + line if out.endswith("-") and line[:1].islower() else out + " " + line
    return out


def _apply_outline(blocks: list[Block], toc: list[tuple[int, str, int]]) -> None:
    """Mark the block each bookmark points at; insert a heading when no block matches."""
    cursor = 0
    for lvl, title, page in toc:
        want = norm(NUMBERED.sub(r"\2", title))
        hit = None
        for i in range(cursor, len(blocks)):
            b = blocks[i]
            if b.page is not None and page > 0 and b.page > page:
                break
            if b.page is not None and page > 0 and b.page < page:
                continue
            got = norm(NUMBERED.sub(r"\2", " ".join(b.text.split())))
            if b.kind == "paragraph" and len(got) <= len(want) + 12 and want and want in got:
                hit = i
                break
        if hit is None:
            hit = next((i for i in range(cursor, len(blocks)) if (blocks[i].page or 0) >= page), len(blocks))
            blocks.insert(hit, Block("heading", title, page=page if page > 0 else None, level=lvl, source="outline"))
        else:
            blocks[hit].kind, blocks[hit].level, blocks[hit].source = "heading", lvl, "outline"
        cursor = hit + 1


# ---------------------------------------------------------------- DOCX
def parse_docx(data: bytes, stem: str) -> ParsedDoc:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(data))
    blocks: list[Block] = []
    title = (d.core_properties.title or "").strip()
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "tbl":
            rows = [" | ".join(c.text.strip().replace("\n", " ") for c in r.cells) for r in Table(el, d).rows]
            if rows:
                sep = " | ".join("---" for _ in rows[0].split(" | "))
                blocks.append(Block("table", "\n".join([rows[0], sep, *rows[1:]])))
            continue
        if tag != "p":
            continue
        p = Paragraph(el, d)
        text = p.text.strip()
        if not text:
            continue
        style = (p.style.name if p.style is not None else "") or ""
        if style == "Title" and not title:
            title = text
            continue
        level = _docx_level(p, style)
        if level is not None:
            blocks.append(Block("heading", text, level=level, source="explicit"))
            continue
        sizes = [r.font.size.pt for r in p.runs if r.font.size is not None and r.text.strip()]
        style_size = p.style.font.size.pt if p.style is not None and p.style.font.size is not None else None
        bold = all(bool(r.bold) or bool(p.style is not None and p.style.font.bold) for r in p.runs if r.text.strip())
        blocks.append(Block("paragraph", text, size=max(sizes) if sizes else style_size, bold=bold))

    method = "docx"
    warnings: list[str] = []
    if any(b.kind == "heading" for b in blocks):
        method += "+styles"
    elif infer_headings(blocks):
        method += "+inferred"
    else:
        warnings.append("no headings found; document indexed as a single section")
    return ParsedDoc(title or stem, blocks, None, method, warnings)


def _docx_level(p, style: str) -> int | None:
    m = re.match(r"heading\s*(\d)", style, re.I)
    if m:
        return int(m.group(1))
    ppr = p._p.pPr
    lvl = ppr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}outlineLvl") if ppr is not None else None
    if lvl is not None:
        val = lvl.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
        if val is not None and val.isdigit() and int(val) < 9:
            return int(val) + 1
    return None


# ---------------------------------------------------------------- Markdown / text
def parse_markdown(src: str, stem: str) -> ParsedDoc:
    from markdown_it import MarkdownIt

    if src.startswith("---\n"):
        end = src.find("\n---", 4)
        if end != -1:
            src = "\n" * src[: end + 4].count("\n") + src[end + 4 :]  # keep line numbers
    lines = src.splitlines()
    tokens = MarkdownIt("commonmark").enable("table").parse(src)
    blocks: list[Block] = []
    for i, t in enumerate(tokens):
        if t.level != 0 or not t.map or t.type.endswith("_close"):
            continue
        if t.type == "heading_open":
            blocks.append(Block("heading", tokens[i + 1].content.strip(), level=int(t.tag[1]), source="explicit"))
        elif t.type in {"paragraph_open", "bullet_list_open", "ordered_list_open", "blockquote_open",
                        "fence", "code_block", "html_block", "table_open"}:
            text = "\n".join(lines[t.map[0] : t.map[1]]).strip()
            blocks.append(Block("table" if t.type == "table_open" else "paragraph", text))
    method = "markdown"
    warnings = [] if any(b.kind == "heading" for b in blocks) else ["no headings found; document indexed as a single section"]
    return ParsedDoc(stem, blocks, None, method, warnings)


def parse_text(src: str, stem: str) -> ParsedDoc:
    blocks = [Block("paragraph", p.strip()) for p in re.split(r"\n\s*\n", src) if p.strip()]
    # A short first line glued to its paragraph is often a heading: split it off.
    split: list[Block] = []
    for b in blocks:
        first, _, rest = b.text.partition("\n")
        if rest and len(first) <= 80 and (NUMBERED.match(first) or first.isupper()) and not first.endswith("."):
            split += [Block("paragraph", first.strip()), Block("paragraph", rest.strip())]
        else:
            split.append(b)
    method = "text+inferred" if infer_headings(split) else "text"
    warnings = [] if method != "text" else ["no headings found; document indexed as a single section"]
    return ParsedDoc(stem, split, None, method, warnings)
