"""Parser data model and content-signature format detection (FR-030)."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

ZERO_WIDTH = re.compile("[​‌‍⁠﻿­]")


@dataclass
class ParsedTable:
    headers: list[str]
    rows: list[list[str]]
    caption: str | None = None

    def to_text(self) -> str:
        """Header-associated rendering so values stay attached to headings (FR-035, FR-076)."""
        lines = []
        if self.caption:
            lines.append(f"Table: {self.caption}")
        lines.append("| " + " | ".join(self.headers) + " |")
        for row in self.rows:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)


@dataclass
class ParsedPage:
    page_number: int
    text: str
    tables: list[ParsedTable] = field(default_factory=list)
    extraction: str = "text"           # text | ocr | table | mixed
    ocr_confidence: float | None = None
    label: str | None = None


@dataclass
class ParsedDocument:
    format: str
    pages: list[ParsedPage]
    title: str | None = None
    parser: str = ""
    security_flags: list[str] = field(default_factory=list)   # active content, hidden text ...
    warnings: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)


class UnsupportedFormat(ValueError):
    pass


SUPPORTED = {"pdf", "docx", "xlsx", "pptx", "html", "txt", "md", "csv", "png", "jpeg", "tiff"}
MIME = {"pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "html": "text/html", "txt": "text/plain", "md": "text/markdown", "csv": "text/csv",
        "png": "image/png", "jpeg": "image/jpeg", "tiff": "image/tiff"}


def detect_format(data: bytes, filename: str) -> str:
    """Identify the format from content signatures; the extension is only a
    tie-breaker for plain-text families.  A mismatch (e.g. an executable named
    .pdf) is rejected."""
    head = data[:16]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head.startswith(b"PK\x03\x04"):
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile as exc:
            raise UnsupportedFormat("corrupt OOXML container") from exc
        if "word/document.xml" in names:
            return "docx"
        if "xl/workbook.xml" in names:
            return "xlsx"
        if "ppt/presentation.xml" in names:
            return "pptx"
        raise UnsupportedFormat("ZIP archives are not accepted")
    if head.startswith(b"MZ") or head.startswith(b"\x7fELF") or head.startswith(b"#!"):
        raise UnsupportedFormat("executable content is not accepted")
    try:
        sample = data[:65536].decode("utf-8")
    except UnicodeDecodeError:
        try:
            sample = data[:65536].decode("latin-1")
        except UnicodeDecodeError as exc:
            raise UnsupportedFormat("binary content of unknown type") from exc
    if "\x00" in sample:
        raise UnsupportedFormat("binary content of unknown type")
    low = sample.lstrip().lower()
    if low.startswith("<!doctype html") or low.startswith("<html") or ext in ("html", "htm"):
        return "html"
    if ext == "csv":
        return "csv"
    if ext in ("md", "markdown"):
        return "md"
    if ext in ("txt", "text", ""):
        return "txt"
    raise UnsupportedFormat(f"unsupported file type .{ext}")


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def strip_hidden(text: str, flags: list[str]) -> str:
    """Remove zero-width / soft-hyphen characters used to hide instructions (FR-139)."""
    cleaned, n = ZERO_WIDTH.subn("", text)
    if n:
        flags.append(f"zero_width_characters:{n}")
    return cleaned
