"""Citation formatting and verification (FR-119..FR-121, FR-109, FR-142).

After generation every [S#] marker must (a) refer to a passage that was in the
authorised context and (b) be supported by that passage (lexical support
check).  Unknown markers are removed and reported; statements without any
citation are flagged when citations are required.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.embeddings.providers import normalise_terms

_MARK = re.compile(r"\[(S\d+)\]")
_MULTI = re.compile(r"\[((?:S\d+\s*,\s*)+S\d+)\]")
_SENT = re.compile(r"(?<=[.!?])\s+(?!\[S\d)")  # keep trailing [S#] markers with their sentence


@dataclass
class CitationReport:
    answer: str
    cited: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    uncited_sentences: int = 0
    total_sentences: int = 0

    @property
    def coverage(self) -> float:
        return 1.0 if self.total_sentences == 0 else round(1 - self.uncited_sentences / self.total_sentences, 3)


def validate_citations(answer: str, passages: dict[str, str], min_support: float = 0.2) -> CitationReport:
    report = CitationReport(answer=answer)

    def _fix(m: re.Match[str]) -> str:
        sid = m.group(1)
        if sid not in passages:
            report.removed.append(sid)
            return ""
        return m.group(0)

    # The model sometimes writes several ids in one bracket ("[S1, S2]"). Split them into "[S1][S2]" first,
    # otherwise they are not counted as citations and a correct answer is abstained.
    answer = _MULTI.sub(lambda m: "".join(f"[{sid}]" for sid in re.findall(r"S\d+", m.group(1))), answer)
    cleaned = _MARK.sub(_fix, answer)
    report.answer = answer
    sentences = [s for s in _SENT.split(cleaned) if s.strip()]
    for sent in sentences:
        marks = _MARK.findall(sent)
        body = _MARK.sub("", sent)
        terms = set(normalise_terms(body))
        if len(terms) < 3 or body.strip().lower().startswith(("based on the approved sources", "note:")) and not marks:
            continue
        report.total_sentences += 1
        if not marks:
            report.uncited_sentences += 1
            continue
        for sid in marks:
            p_terms = set(normalise_terms(passages[sid]))
            support = len(terms & p_terms) / max(1, len(terms))
            if support < min_support and sid not in report.unsupported:
                report.unsupported.append(sid)
            if sid not in report.cited:
                report.cited.append(sid)
    report.answer = re.sub(r"\s{2,}", " ", cleaned).strip()
    return report
