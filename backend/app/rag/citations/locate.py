"""Locate a cited passage inside a page's text, for highlighting in the document preview.

The cited text is a chunk. It can start with a "Title > Section" breadcrumb, and its whitespace (line breaks, table
spacing) differs from the page text. Both sides are compared with whitespace collapsed and case folded, and the match
is mapped back to offsets in the original page text. The frontend mirrors this logic in `utils/highlight.ts`.
"""
from __future__ import annotations

import re


def _normalize_with_map(s: str) -> tuple[str, list[int]]:
    out: list[str] = []
    mapping: list[int] = []
    pending_space = False
    for i, ch in enumerate(s):
        # Table pipes are treated as spaces so table rows match their flattened text.
        if ch.isspace() or ch == "|":
            if out:
                pending_space = True
            continue
        if pending_space:
            out.append(" ")
            mapping.append(i)
            pending_space = False
        out.append(ch.lower())
        mapping.append(i)
    return "".join(out), mapping


def locate_passage(page_text: str, passage: str | None) -> dict[str, int] | None:
    """Return {"start", "end"} offsets of `passage` inside `page_text`, or None when it is not on the page."""
    if not page_text or not passage:
        return None
    body = passage[passage.rfind(" > ") + 3:] if " > " in passage else passage
    page_norm, mapping = _normalize_with_map(page_text)
    wanted, _ = _normalize_with_map(body)
    # Whole passage first (from its start, then shorter prefixes), then single sentences: a chunk often starts on a
    # different page than the sentence that matters, or a masked token sits inside it.
    for n in (200, 100, 60, 30):
        probe = wanted[:n].strip()
        if len(probe) < 15:
            continue
        idx = page_norm.find(probe)
        if idx < 0:
            continue
        end_norm = min(idx + len(wanted), len(page_norm))
        return {"start": mapping[idx], "end": mapping[end_norm - 1] + 1}
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", body):
        sent = _normalize_with_map(sentence)[0].strip()
        if len(sent) < 30:
            continue
        idx = page_norm.find(sent[:200])
        if idx < 0:
            continue
        end_norm = min(idx + len(sent), len(page_norm))
        return {"start": mapping[idx], "end": mapping[end_norm - 1] + 1}
    return None
