"""Chunking strategies (FR-070, FR-071, FR-073..FR-078).

* structure_aware (default): recovers the heading / clause hierarchy, keeps
  each clause, definition, exclusion or schedule as a coherent unit with its
  heading path, and emits parent sections + retrievable child chunks.
* recursive: splits on the largest available boundary (section, paragraph,
  sentence, word) with overlap.
* fixed: token windows with overlap for unstructured content.
Tables are kept intact or split by row groups with the header repeated.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from app.rag.ingestion.insurance_metadata import extract_identifiers
from app.rag.parsers.base import ParsedPage

CHUNKER_VERSION = "structure-aware-1.2"
_TOKEN = re.compile(r"\w+|[^\w\s]")
_SENT = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z0-9(\"'])")
_MD_HEAD = re.compile(r"^(#{1,6})\s+(.+)$")
_NUM_HEAD = re.compile(r"^((?:part|section|clause|article|schedule|endorsement|exclusion|condition)s?\s+[\dA-Z.]+[a-z]?"
                       r"|\d{1,2}(?:\.\d{1,2}){0,3}\.?)\s*[-–:.]?\s*(.{0,120})$", re.I)
_CLAUSE_REF = re.compile(r"^(?:(?:part|section|clause|article|schedule|endorsement|exclusion|condition)s?\s+)?(\d{1,2}(?:\.\d{1,2}){0,3}[a-z]?)", re.I)


def count_tokens(text: str) -> int:
    return len(_TOKEN.findall(text))


@dataclass
class Chunk:
    index: int
    chunk_type: str
    text: str
    section_path: str | None
    clause_ref: str | None
    page_from: int
    page_to: int
    token_count: int
    title: str | None = None
    parent_index: int | None = None
    identifiers: list[str] = field(default_factory=list)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


@dataclass
class _Block:
    section: list[str]
    clause_ref: str | None
    page: int
    text: str
    is_table: bool = False


def _is_heading(line: str) -> tuple[int, str] | None:
    m = _MD_HEAD.match(line)
    if m:
        return len(m.group(1)), m.group(2).strip()
    s = line.strip()
    if not 3 <= len(s) <= 120 or s.endswith((",", ";")):
        return None
    m2 = _NUM_HEAD.match(s)
    if m2 and len(s.split()) <= 10 and not s.endswith("."):
        num = m2.group(1)
        depth = num.rstrip(".").count(".") + 1 if num[0].isdigit() else 1
        return min(depth + 1, 6), s
    if s.isupper() and len(s.split()) <= 10 and re.search(r"[A-Z]{3}", s):
        return 1, s.title()
    return None


def _blocks(pages: list[ParsedPage]) -> list[_Block]:
    stack: list[tuple[int, str]] = []
    out: list[_Block] = []
    buf: list[str] = []
    buf_page = 1

    def flush(page: int) -> None:
        nonlocal buf
        text = "\n".join(buf).strip()
        if text:
            path = [h for _, h in stack]
            ref = None
            for _, h in reversed(stack):
                m = _CLAUSE_REF.match(h)
                if m:
                    ref = m.group(1)
                    break
            out.append(_Block(path, ref, page, text))
        buf = []

    for page in pages:
        table_texts = {t.to_text() for t in page.tables}
        for raw in page.text.split("\n"):
            line = raw.rstrip()
            if not line.strip():
                if buf:
                    buf.append("")
                continue
            if line in table_texts:
                continue
            head = _is_heading(line)
            if head:
                flush(buf_page)
                level, title = head
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                buf_page = page.page_number
                continue
            if not buf:
                buf_page = page.page_number
            buf.append(line)
        flush(buf_page)
        for t in page.tables:
            out.append(_Block([h for _, h in stack] + ([t.caption] if t.caption else []), None, page.page_number,
                              t.to_text(), is_table=True))
    return out


def _split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        parts.extend(s.strip() for s in _SENT.split(para) if s.strip())
    return parts


def _window(units: list[str], size: int, overlap: int) -> list[str]:
    """Greedy packing of units into chunks of <= size tokens with token overlap."""
    chunks: list[str] = []
    cur: list[str] = []
    cur_tok = 0
    for unit in units:
        t = count_tokens(unit)
        if t > size:  # very long sentence -> hard split on words
            words = unit.split()
            step = max(1, int(size * 0.75))
            for i in range(0, len(words), step):
                units_part = " ".join(words[i:i + size])
                if cur:
                    chunks.append(" ".join(cur))
                    cur, cur_tok = [], 0
                chunks.append(units_part)
            continue
        if cur and cur_tok + t > size:
            chunks.append(" ".join(cur))
            keep: list[str] = []
            ktok = 0
            for prev in reversed(cur):
                pt = count_tokens(prev)
                if ktok + pt > overlap:
                    break
                keep.insert(0, prev)
                ktok += pt
            cur, cur_tok = keep, ktok
        cur.append(unit)
        cur_tok += t
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def _split_table(text: str, size: int) -> list[str]:
    lines = text.split("\n")
    head_lines = [l for l in lines[:2] if l.startswith("Table:")]
    header = next((l for l in lines if l.startswith("|")), "")
    rows = [l for l in lines if l.startswith("|") and l != header]
    if count_tokens(text) <= size or not rows:
        return [text]
    groups, cur = [], []
    for r in rows:
        if cur and count_tokens("\n".join(head_lines + [header] + cur + [r])) > size:
            groups.append("\n".join(head_lines + [header] + cur))
            cur = []
        cur.append(r)
    if cur:
        groups.append("\n".join(head_lines + [header] + cur))
    return groups


def chunk_document(pages: list[ParsedPage], *, strategy: str = "structure_aware", chunk_size: int = 350,
                   chunk_overlap: int = 40, parent_child: bool = True, title: str | None = None) -> list[Chunk]:
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    chunks: list[Chunk] = []

    def add(kind: str, text: str, path: list[str], ref: str | None, p_from: int, p_to: int,
            parent: int | None = None) -> int:
        idx = len(chunks)
        section = " > ".join(path) if path else None
        chunks.append(Chunk(index=idx, chunk_type=kind, text=text, section_path=section, clause_ref=ref,
                            page_from=p_from, page_to=p_to, token_count=count_tokens(text), title=title,
                            parent_index=parent, identifiers=extract_identifiers((section or "") + "\n" + text)))
        return idx

    if strategy == "fixed":
        for page in pages:
            words = page.text.split()
            step = chunk_size - chunk_overlap
            for i in range(0, max(len(words), 1), step):
                piece = " ".join(words[i:i + chunk_size]).strip()
                if piece:
                    add("text", piece, [], None, page.page_number, page.page_number)
        return chunks

    blocks = _blocks(pages)
    if strategy == "recursive":
        for b in blocks:
            if b.is_table:
                for part in _split_table(b.text, chunk_size):
                    add("table", part, b.section, b.clause_ref, b.page, b.page)
                continue
            for piece in _window(_split_sentences(b.text), chunk_size, chunk_overlap):
                add("text", piece, b.section, b.clause_ref, b.page, b.page)
        return chunks

    # structure-aware: merge consecutive blocks of the same section into one unit
    units: list[_Block] = []
    for b in blocks:
        if units and not b.is_table and not units[-1].is_table and units[-1].section == b.section:
            units[-1].text += "\n" + b.text
            continue
        units.append(_Block(list(b.section), b.clause_ref, b.page, b.text, b.is_table))
    last_page = {id(u): u.page for u in units}
    for i, u in enumerate(units):
        if not u.is_table:
            nxt = units[i + 1].page if i + 1 < len(units) else u.page
            last_page[id(u)] = max(u.page, nxt if nxt - u.page <= 2 else u.page)
    for u in units:
        p_to = last_page[id(u)]
        lowered = " ".join(u.section).lower()
        if u.is_table:
            for part in _split_table(u.text, chunk_size):
                add("table", part, u.section, u.clause_ref, u.page, u.page)
            continue
        kind = "definition" if "definition" in lowered else "text"
        tokens = count_tokens(u.text)
        prefix = (" > ".join(u.section) + "\n") if u.section else ""
        if tokens <= chunk_size:
            add(kind, prefix + u.text, u.section, u.clause_ref, u.page, p_to)
            continue
        parent = None
        if parent_child:
            parent_text = u.text if tokens <= chunk_size * 6 else " ".join(u.text.split()[: chunk_size * 6])
            parent = add("parent", prefix + parent_text, u.section, u.clause_ref, u.page, p_to)
        for piece in _window(_split_sentences(u.text), chunk_size, chunk_overlap):
            add("child" if parent_child else kind, prefix + piece, u.section, u.clause_ref, u.page, p_to, parent)
    return chunks
