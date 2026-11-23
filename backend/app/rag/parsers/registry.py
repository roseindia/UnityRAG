"""Format-specific parsers (FR-033..FR-035, FR-054..FR-058, FR-060, FR-137..FR-139).

Each parser returns page-level text with headings marked in Markdown style
("#", "##") so the structure-aware chunker can recover the section hierarchy,
and tables rendered with their headers.
"""
from __future__ import annotations

import csv
import io
import logging
import re

from app.core.config import get_settings
from app.rag.ocr.tesseract import ocr_available, ocr_bytes, ocr_image
from app.rag.parsers.base import ParsedDocument, ParsedPage, ParsedTable, UnsupportedFormat, decode_text, detect_format, strip_hidden

log = logging.getLogger("app.parsers")


# --- PDF ------------------------------------------------------------------------------
def _pdf_security_flags(reader) -> list[str]:
    flags: list[str] = []
    try:
        root = reader.trailer["/Root"]
        if "/OpenAction" in root or "/AA" in root:
            flags.append("pdf_auto_action")
        names = root.get("/Names", {})
        if "/JavaScript" in names:
            flags.append("pdf_javascript")
        if "/EmbeddedFiles" in names:
            flags.append("pdf_embedded_files")
        if "/AcroForm" in root:
            flags.append("pdf_form_fields")
    except Exception:  # malformed trailer: report, do not crash the parser
        flags.append("pdf_unreadable_catalog")
    return flags


def parse_pdf(data: bytes) -> ParsedDocument:
    from pypdf import PdfReader

    s = get_settings()
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise UnsupportedFormat("encrypted PDF cannot be processed") from exc
    flags = _pdf_security_flags(reader)
    pages: list[ParsedPage] = []
    pdfium_doc = None
    title = None
    try:
        title = (reader.metadata.title if reader.metadata else None) or None
    except Exception:
        title = None
    for i, page in enumerate(reader.pages, start=1):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        txt = strip_hidden(txt, flags)
        if len(txt.strip()) >= s.ocr_min_chars_per_page:
            pages.append(ParsedPage(page_number=i, text=txt, extraction="text"))
            continue
        # Scanned / image-only page -> render and OCR (FR-032, FR-054).
        if not ocr_available():
            pages.append(ParsedPage(page_number=i, text=txt, extraction="text", ocr_confidence=0.0))
            continue
        try:
            import pypdfium2 as pdfium

            pdfium_doc = pdfium_doc or pdfium.PdfDocument(data)
            img = pdfium_doc[i - 1].render(scale=2.0).to_pil()
            res = ocr_image(img)
            pages.append(ParsedPage(page_number=i, text=res.text, extraction="ocr", ocr_confidence=res.confidence))
        except Exception as exc:
            log.warning("OCR failed for page %s: %s", i, type(exc).__name__)
            pages.append(ParsedPage(page_number=i, text=txt, extraction="text", ocr_confidence=0.0))
    # Tables (best effort, born-digital PDFs only)
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for i, p in enumerate(pdf.pages[:200], start=1):
                for tbl in p.extract_tables() or []:
                    rows = [[(c or "").strip() for c in r] for r in tbl if r and any(c for c in r)]
                    if len(rows) >= 2:
                        pages[i - 1].tables.append(ParsedTable(headers=rows[0], rows=rows[1:]))
    except Exception as exc:
        log.info("pdf table extraction skipped: %s", type(exc).__name__)
    return ParsedDocument(format="pdf", pages=pages, title=title, parser="pypdf+pdfplumber", security_flags=flags)


# --- DOCX ------------------------------------------------------------------------------
def parse_docx(data: bytes) -> ParsedDocument:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(data))
    flags: list[str] = []
    lines: list[str] = []
    tables: list[ParsedTable] = []
    title = d.core_properties.title or None
    for child in d.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(child, d)
            text = strip_hidden(p.text.strip(), flags)
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            if style.lower().startswith("heading"):
                level = re.sub(r"\D", "", style) or "1"
                lines.append("#" * min(int(level), 6) + " " + text)
            elif style.lower() == "title":
                title = title or text
                lines.append("# " + text)
            else:
                lines.append(text)
        elif tag == "tbl":
            t = Table(child, d)
            rows = []
            for r in t.rows:
                cells, prev = [], None
                for c in r.cells:
                    if c._tc is prev:
                        continue
                    prev = c._tc
                    cells.append(re.sub(r"\s+", " ", c.text).strip())
                rows.append(cells)
            if rows:
                tbl = ParsedTable(headers=rows[0], rows=rows[1:])
                tables.append(tbl)
                lines.append(tbl.to_text())
    if not title:
        title = next((l[2:].strip() for l in lines if l.startswith("# ")), None)
    page = ParsedPage(page_number=1, text="\n".join(lines), tables=tables, extraction="mixed" if tables else "text")
    return ParsedDocument(format="docx", pages=[page], title=title, parser="python-docx", security_flags=flags)


# --- XLSX ------------------------------------------------------------------------------
def parse_xlsx(data: bytes) -> ParsedDocument:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    pages = []
    n = 0
    for ws in wb.worksheets:
        if getattr(ws, "sheet_state", "visible") != "visible":
            continue  # hidden sheets ignored by default (FR-056)
        rows = [[("" if v is None else str(v)).strip() for v in row] for row in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        n += 1
        headers = rows[0]
        body = rows[1:]
        tbl = ParsedTable(headers=headers, rows=body, caption=ws.title)
        lines = [f"# Sheet: {ws.title}"]
        for r in body:
            lines.append("; ".join(f"{h}: {v}" for h, v in zip(headers, r, strict=False) if v))
        pages.append(ParsedPage(page_number=n, text="\n".join(lines), tables=[tbl], extraction="table", label=ws.title))
    return ParsedDocument(format="xlsx", pages=pages, parser="openpyxl")


# --- PPTX ------------------------------------------------------------------------------
def parse_pptx(data: bytes, include_notes: bool = True) -> ParsedDocument:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    flags: list[str] = []
    pages = []
    for i, slide in enumerate(prs.slides, start=1):
        lines: list[str] = []
        tables: list[ParsedTable] = []
        title_shape = slide.shapes.title
        if title_shape is not None and title_shape.text.strip():
            lines.append("# " + title_shape.text.strip())
        for shape in slide.shapes:
            if shape == title_shape:
                continue
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[c.text.strip() for c in r.cells] for r in shape.table.rows]
                if rows:
                    tbl = ParsedTable(headers=rows[0], rows=rows[1:])
                    tables.append(tbl)
                    lines.append(tbl.to_text())
            elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                t = shape.text_frame.text.strip()
                if t:
                    lines.append(t)
            alt = getattr(shape, "_element", None)
            descr = alt.xpath("./*[1]/p:cNvPr/@descr") if alt is not None else []
            if descr:
                lines.append(f"[Image: {descr[0]}]")
        if include_notes and slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                lines.append("Speaker notes: " + notes)
        pages.append(ParsedPage(page_number=i, text=strip_hidden("\n".join(lines), flags), tables=tables,
                                label=f"Slide {i}"))
    return ParsedDocument(format="pptx", pages=pages, parser="python-pptx", security_flags=flags)


# --- HTML ------------------------------------------------------------------------------
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0"
                           r"|left\s*:\s*-\d{3,}px|text-indent\s*:\s*-\d{3,}", re.I)


def parse_html(data: bytes) -> ParsedDocument:
    from bs4 import BeautifulSoup, Comment

    flags: list[str] = []
    soup = BeautifulSoup(decode_text(data), "lxml")
    title = soup.title.get_text(strip=True) if soup.title else None
    for tag in soup(["script", "style", "noscript", "iframe", "object", "embed", "nav", "footer", "header", "form",
                     "template", "svg"]):
        if tag.name in ("script", "iframe", "object", "embed"):
            flags.append(f"html_{tag.name}_removed")
        tag.decompose()
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for el in soup.find_all(True):
        if el.attrs is None:
            continue
        style = el.get("style", "") or ""
        if el.has_attr("hidden") or el.get("aria-hidden") == "true" or _HIDDEN_STYLE.search(style):
            flags.append("html_hidden_element_removed")
            el.decompose()
    lines: list[str] = []
    body = soup.body or soup
    for el in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "pre", "blockquote", "dd", "dt"]):
        if el.find_parent(["table"]) and el.name != "table":
            continue
        if el.name.startswith("h"):
            lines.append("#" * int(el.name[1]) + " " + el.get_text(" ", strip=True))
        elif el.name == "table":
            rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in el.find_all("tr")]
            rows = [r for r in rows if r]
            if rows:
                lines.append(ParsedTable(headers=rows[0], rows=rows[1:]).to_text())
        elif el.name == "li":
            lines.append("- " + el.get_text(" ", strip=True))
        else:
            t = el.get_text(" ", strip=True)
            if t:
                lines.append(t)
    text_ = strip_hidden("\n".join(lines), flags)
    return ParsedDocument(format="html", pages=[ParsedPage(1, text_)], title=title, parser="beautifulsoup",
                          security_flags=sorted(set(flags)))


# --- plain text family ------------------------------------------------------------------
def parse_text(data: bytes, fmt: str) -> ParsedDocument:
    flags: list[str] = []
    text_ = strip_hidden(decode_text(data), flags)
    # Split very long text files into virtual pages of ~3000 characters on paragraph breaks.
    pages, buf, n = [], [], 1
    for para in re.split(r"\n\s*\n", text_):
        buf.append(para)
        if sum(len(b) for b in buf) > 3000:
            pages.append(ParsedPage(n, "\n\n".join(buf)))
            buf, n = [], n + 1
    if buf or not pages:
        pages.append(ParsedPage(n, "\n\n".join(buf)))
    title = None
    m = re.search(r"^#\s+(.+)$", text_, re.M)
    if m:
        title = m.group(1).strip()
    return ParsedDocument(format=fmt, pages=pages, title=title, parser="text", security_flags=flags)


def parse_csv(data: bytes) -> ParsedDocument:
    text_ = decode_text(data)
    try:
        dialect = csv.Sniffer().sniff(text_[:4096])
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text_), dialect) if any(c.strip() for c in r)]
    if not rows:
        return ParsedDocument(format="csv", pages=[ParsedPage(1, "")], parser="csv")
    headers, body = rows[0], rows[1:]
    lines = ["; ".join(f"{h}: {v}" for h, v in zip(headers, r, strict=False) if v) for r in body]
    return ParsedDocument(format="csv", pages=[ParsedPage(1, "\n".join(lines), tables=[ParsedTable(headers, body)],
                                                          extraction="table")], parser="csv")


def parse_image(data: bytes, fmt: str) -> ParsedDocument:
    if not ocr_available():
        raise UnsupportedFormat("OCR engine not available for image documents")
    res = ocr_bytes(data)
    return ParsedDocument(format=fmt, pages=[ParsedPage(1, res.text, extraction="ocr", ocr_confidence=res.confidence)],
                          parser="tesseract")


def parse_document(data: bytes, filename: str) -> ParsedDocument:
    fmt = detect_format(data, filename)
    if fmt == "pdf":
        return parse_pdf(data)
    if fmt == "docx":
        return parse_docx(data)
    if fmt == "xlsx":
        return parse_xlsx(data)
    if fmt == "pptx":
        return parse_pptx(data)
    if fmt == "html":
        return parse_html(data)
    if fmt == "csv":
        return parse_csv(data)
    if fmt in ("txt", "md"):
        return parse_text(data, fmt)
    if fmt in ("png", "jpeg", "tiff"):
        return parse_image(data, fmt)
    raise UnsupportedFormat(fmt)
