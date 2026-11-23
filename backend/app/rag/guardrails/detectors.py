"""Guardrail detectors (FR-135..FR-152, FR-237, FR-238).

Deterministic, versioned rules.  They complement - never replace - tenant
isolation and authorisation, which are enforced by RLS and the retrieval
service before any content reaches a model.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

RULES_VERSION = "2026.11.1"

_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("override_instructions", re.compile(r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|all|system|earlier)\b[^.\n]{0,20}\b(instructions?|rules?|prompts?|directions?)", re.I), "high"),
    ("role_change", re.compile(r"\b(you are now|act as|pretend to be|roleplay as|from now on you)\b", re.I), "medium"),
    ("system_prompt_extraction", re.compile(r"\b(reveal|show|print|repeat|display|leak|tell me)\b[^.\n]{0,40}\b(system prompt|hidden prompt|instructions you were given|your prompt|initial prompt|guardrail rules?)", re.I), "high"),
    ("developer_mode", re.compile(r"\b(developer mode|dan mode|jailbreak|do anything now|no restrictions|without (any )?restrictions)\b", re.I), "high"),
    ("disable_controls", re.compile(r"\b(disable|bypass|turn off|circumvent)\b[^.\n]{0,30}\b(safety|guardrails?|filters?|security|permissions?|access control)", re.I), "high"),
    ("tool_exfiltration", re.compile(r"\b(send|post|upload|exfiltrate|forward|email)\b[^.\n]{0,40}\b(https?://|to (this|the following) (url|address|webhook))", re.I), "high"),
    ("cross_tenant", re.compile(r"\b(other|another|all)\s+(tenants?|compan(y|ies)|customers?' data)\b|\btenant[_ ]?id\s*[=:]", re.I), "high"),
    ("markdown_image_exfil", re.compile(r"!\[[^\]]*\]\(\s*https?://", re.I), "high"),
    ("instruction_marker", re.compile(r"(^|\n)\s*(###\s*)?(system|assistant|instruction)s?\s*:", re.I), "medium"),
]
_REGULATED_DECISION = re.compile(
    r"\b(claim (is|has been|will be) (approved|rejected|denied|accepted|settled)|"
    r"(we|i) (approve|reject|deny|decline) (the|this|your) (claim|proposal|risk|application)|"
    r"(risk|proposal|application) (is|has been) (accepted|declined)|"
    r"(the )?final coverage (is|will be) determined|binding premium (is|of))", re.I)
_DECISION_REQUEST = re.compile(r"\b(approve|reject|deny|settle|decline|accept)\b[^?.\n]{0,30}\b(this|my|the|claim|risk|proposal)\b.*\b(claim|risk|proposal|application)\b"
                               r"|\b(should i|can you) (approve|reject|deny|decline|settle)\b|\bcalculate (the )?binding premium\b", re.I)
_ABUSE = re.compile(r"\b(kill yourself|how to make (a )?bomb|launder money|commit insurance fraud|fake (a|the) claim)\b", re.I)

_PII: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("payment_card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("phone", re.compile(r"(?<!\w)(?<!\d[ -])(?:\+?\d{1,3}[ -]?)?(?:\(?\d{2,4}\)?[ -]?)\d{3,4}[ -]?\d{3,4}(?!\w)(?![ -]\d)")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("national_id", re.compile(r"\b\d{3}-\d{2}-\d{4}\b|(?<!\d )\b\d{4}\s\d{4}\s\d{4}\b(?!\s\d)|\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("credential", re.compile(r"(?i)\b(password|passwd|api[_-]?key|secret)\s*[:=]\s*\S+")),
]
_HEALTH = re.compile(r"\b(diagnos(is|ed)|HIV|cancer|diabetes|pregnan(t|cy)|psychiatric|medical history|prescription)\b", re.I)


@dataclass
class Detection:
    rule_id: str
    severity: str
    category: str
    span: tuple[int, int] | None = None


@dataclass
class ScanResult:
    detections: list[Detection] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.detections)

    @property
    def max_severity(self) -> str:
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        return max((d.severity for d in self.detections), key=lambda s: order[s], default="low")


def _luhn(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(nums) <= 19:
        return False
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _decoded_variants(text: str) -> list[str]:
    """Detect simple obfuscation (base64 blobs, spaced letters) used to smuggle instructions (FR-144)."""
    out = [text]
    for blob in re.findall(r"[A-Za-z0-9+/]{24,}={0,2}", text)[:5]:
        try:
            dec = base64.b64decode(blob + "=" * (-len(blob) % 4)).decode("utf-8")
            if dec.isprintable():
                out.append(dec)
        except Exception:  # noqa: S112 - a blob that does not decode to text is not obfuscated input
            continue
    squeezed = re.sub(r"(?<=\b\w) (?=\w\b)", "", text)
    if squeezed != text:
        out.append(squeezed)
    return out


def scan_injection(text: str) -> ScanResult:
    res = ScanResult()
    for variant in _decoded_variants(text):
        for rule_id, pattern, severity in _INJECTION_PATTERNS:
            m = pattern.search(variant)
            if m and not any(d.rule_id == rule_id for d in res.detections):
                res.detections.append(Detection(rule_id, severity, "prompt_injection",
                                                m.span() if variant is text else None))
    return res


def scan_input(text: str) -> ScanResult:
    res = scan_injection(text)
    if _ABUSE.search(text):
        res.detections.append(Detection("abuse", "high", "moderation"))
    if _DECISION_REQUEST.search(text):
        res.detections.append(Detection("regulated_decision_request", "medium", "knowledge_boundary"))
    return res


def find_pii(text: str) -> list[tuple[str, tuple[int, int]]]:
    """Detected spans; overlapping matches resolved in pattern priority order."""
    found: list[tuple[str, tuple[int, int]]] = []
    for kind, pattern in _PII:
        for m in pattern.finditer(text):
            if kind == "payment_card" and not _luhn(m.group(0)):
                continue
            if kind == "phone" and not 9 <= len(re.sub(r"\D", "", m.group(0))) <= 13:
                continue
            a, b = m.span()
            if any(a < y and x < b for _, (x, y) in found):
                continue
            found.append((kind, (a, b)))
    return found


def sensitivity_tags(text: str) -> list[str]:
    tags = sorted({kind for kind, _ in find_pii(text)})
    if _HEALTH.search(text):
        tags.append("health")
    return tags


def mask_pii(text: str, allowed: set[str] | None = None) -> tuple[str, int]:
    allowed = allowed or set()
    spans = sorted(((k, s) for k, s in find_pii(text) if k not in allowed), key=lambda x: x[1][0], reverse=True)
    n = 0
    last_start = len(text) + 1
    for kind, (a, b) in spans:
        if b > last_start:
            continue
        text = text[:a] + f"[{kind.upper()} REDACTED]" + text[b:]
        last_start = a
        n += 1
    return text, n


def regulated_decision_statements(text: str) -> list[str]:
    return [m.group(0) for m in _REGULATED_DECISION.finditer(text)]


_URL = re.compile(r"https?://[^\s)\]>\"']+", re.I)


def neutralise_links(text: str, allowed_hosts: set[str] | None = None) -> tuple[str, int]:
    """Strip markdown images and non-allow-listed links from output (FR-141, FR-146)."""
    allowed_hosts = allowed_hosts or set()
    text, n_img = re.subn(r"!\[[^\]]*\]\([^)]*\)", "[image removed]", text)
    count = n_img

    def repl(m: re.Match[str]) -> str:
        nonlocal count
        host = re.sub(r"^https?://", "", m.group(0)).split("/")[0].lower()
        if host in allowed_hosts:
            return m.group(0)
        count += 1
        return "[link removed]"

    return _URL.sub(repl, text), count
