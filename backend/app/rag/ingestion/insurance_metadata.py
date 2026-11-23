"""Insurance document intelligence: classification and metadata extraction
(FR-031, FR-036, FR-062, FR-067, FR-068, FR-069, extension section 11).

Rule-based and deterministic so every value is explainable and auditable; an
ML/LLM classifier can be plugged in behind `classify_document` later.  Values
carry a confidence; low-confidence classifications are routed to review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from dateutil import parser as dateparser

DOC_TYPE_RULES: dict[str, list[str]] = {
    "policy_wording": ["policy wording", "insuring clause", "insuring agreement", "general exclusions", "definitions",
                       "we will pay", "the insured", "conditions of this policy", "operative clause"],
    "policy_schedule": ["policy schedule", "schedule of insurance", "period of insurance", "premium payable",
                        "policy number", "insured name", "sum insured"],
    "endorsement": ["endorsement", "this endorsement", "attaching to and forming part", "is hereby amended",
                    "endt", "rider"],
    "claims_manual": ["claims manual", "claim handling", "claims procedure", "first notice of loss", "fnol",
                      "claims adjuster", "loss assessment", "settlement of claim", "surveyor"],
    "underwriting_guideline": ["underwriting guideline", "underwriting manual", "risk acceptance", "acceptance criteria",
                               "referral to underwriter", "loading", "declinature", "risk appetite"],
    "product_brochure": ["brochure", "key features", "why choose", "benefits at a glance", "product highlights"],
    "regulatory_circular": ["circular", "regulator", "irdai", "apra", "hereby directed", "all insurers",
                            "regulatory requirement", "authority", "gazette"],
    "sop": ["standard operating procedure", "sop", "procedure", "step 1", "responsibilities", "process owner"],
    "customer_communication": ["dear customer", "dear sir", "dear madam", "yours sincerely", "we are writing to"],
    "authority_matrix": ["authority matrix", "approval limit", "delegated authority", "authority limit",
                         "escalation path"],
    "faq": ["frequently asked questions", "faq", "q:", "question:"],
}

LINE_RULES: dict[str, list[str]] = {
    "motor": ["motor", "vehicle", "car ", "own damage", "third party liability", "driver", "registration number"],
    "home": ["home insurance", "householder", "building", "contents", "dwelling", "homeowner"],
    "health": ["health", "hospitalisation", "hospitalization", "pre-authorisation", "pre-authorization", "cashless",
               "network hospital", "co-payment", "medical expenses"],
    "life": ["life assured", "sum assured", "nominee", "surrender value", "paid-up", "maturity benefit",
             "death benefit", "revival"],
    "travel": ["travel insurance", "trip cancellation", "baggage", "overseas medical"],
    "marine": ["marine", "cargo", "hull", "voyage", "bill of lading"],
    "liability": ["public liability", "professional indemnity", "directors and officers", "product liability"],
    "property": ["fire insurance", "industrial all risks", "property damage", "business interruption"],
    "cyber": ["cyber", "data breach", "ransomware", "network security"],
    "workers_comp": ["workers compensation", "workmen compensation", "employees compensation"],
}

JURISDICTIONS = {
    "new south wales": "AU-NSW", "nsw": "AU-NSW", "victoria": "AU-VIC", "queensland": "AU-QLD", "australia": "AU",
    "india": "IN", "maharashtra": "IN-MH", "karnataka": "IN-KA", "tamil nadu": "IN-TN", "delhi": "IN-DL",
    "united kingdom": "GB", "england": "GB-ENG", "california": "US-CA", "new york": "US-NY", "texas": "US-TX",
    "united states": "US", "singapore": "SG", "united arab emirates": "AE", "canada": "CA", "ontario": "CA-ON",
}

COVERAGE_TYPES = ["comprehensive", "third party", "all risks", "named perils", "own damage", "standalone",
                  "family floater", "individual", "term", "endowment", "whole life", "unit linked"]

_POLICY_NO = re.compile(r"\bpolicy\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{4,24})", re.I)
_CLAIM_NO = re.compile(r"\bclaim\s*(?:no\.?|number|#|ref(?:erence)?)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{4,24})", re.I)
_CODE = re.compile(r"\b(?:POL|CLM|END|ENDT|FORM|UW|CIR|SOP)[-/ ]?\d{2,6}(?:[-/]\d{1,8})*[A-Z]?\b")
_CLAUSE = re.compile(r"\b(?:clause|section|article|condition|exclusion|endorsement)\s+(\d+(?:\.\d+){0,4}[a-z]?)\b", re.I)
_MONEY = r"((?:INR|USD|AUD|EUR|GBP|Rs\.?|₹|\$|€|£)\s?[\d,]+(?:\.\d+)?(?:\s*(?:lakh|lakhs|crore|million|m|k))?|[\d,]{3,}(?:\.\d+)?\s*(?:INR|USD|AUD|EUR|GBP))"
_SUM_INSURED = re.compile(r"\bsum\s+(?:insured|assured)\b[^\n\d₹$€£]{0,40}" + _MONEY, re.I)
_DEDUCTIBLE = re.compile(r"\b(?:deductible|excess|co-?payment)\b[^\n\d₹$€£]{0,40}(" + _MONEY[1:-1] + r"|\d{1,2}(?:\.\d+)?\s?%)", re.I)
_WAITING = re.compile(r"\bwaiting\s+period\s+(?:of\s+)?(\d{1,3}\s*(?:days?|months?|years?))", re.I)
_DATE = r"(\d{1,2}(?:st|nd|rd|th)?[ /.\-](?:\d{1,2}|[A-Za-z]{3,9})[ /.\-,]*\d{2,4}|\d{4}-\d{2}-\d{2})"
_EFFECTIVE = re.compile(r"\b(?:effective|commencement|inception|valid)\s*(?:date|from|on)?\s*[:\-]?\s*" + _DATE, re.I)
_EXPIRY = re.compile(r"\b(?:expiry|expiration|expires|valid\s+until|valid\s+till|end\s+date)\s*(?:date|on)?\s*[:\-]?\s*" + _DATE, re.I)
_EXCLUSION_HEAD = re.compile(r"^#{1,6}\s*(.*exclusion.*)$", re.I | re.M)


@dataclass
class InsuranceMetadata:
    document_type: str
    document_type_confidence: float
    insurance_line: str | None
    jurisdictions: list[str]
    policy_numbers: list[str] = field(default_factory=list)
    claim_numbers: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    coverage_types: list[str] = field(default_factory=list)
    sum_insured: list[str] = field(default_factory=list)
    deductibles: list[str] = field(default_factory=list)
    waiting_periods: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    effective_from: date | None = None
    effective_to: date | None = None

    def as_pairs(self) -> list[tuple[str, str, float]]:
        out: list[tuple[str, str, float]] = [("document_type", self.document_type, self.document_type_confidence)]
        if self.insurance_line:
            out.append(("insurance_line", self.insurance_line, 0.7))
        for key, values in (("policy_number", self.policy_numbers), ("claim_number", self.claim_numbers),
                            ("reference_code", self.codes), ("coverage_type", self.coverage_types),
                            ("sum_insured", self.sum_insured), ("deductible", self.deductibles),
                            ("waiting_period", self.waiting_periods), ("exclusion", self.exclusions),
                            ("jurisdiction", self.jurisdictions)):
            out.extend((key, v[:500], 0.8) for v in values)
        if self.effective_from:
            out.append(("effective_date", self.effective_from.isoformat(), 0.7))
        if self.effective_to:
            out.append(("expiration_date", self.effective_to.isoformat(), 0.7))
        return out


def _score(text_low: str, rules: dict[str, list[str]]) -> tuple[str | None, float]:
    scores = {k: sum(text_low.count(term) for term in terms) for k, terms in rules.items()}
    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    if scores[best] == 0:
        return None, 0.0
    return best, round(scores[best] / total, 3)


def _parse_date(raw: str) -> date | None:
    try:
        return dateparser.parse(raw, dayfirst=True, fuzzy=True).date()
    except (ValueError, OverflowError, TypeError):
        return None


def _uniq(values: list[str], limit: int = 20) -> list[str]:
    seen: list[str] = []
    for v in values:
        v = v.strip().rstrip(".,;")
        if v and v not in seen:
            seen.append(v)
    return seen[:limit]


def extract_identifiers(text: str) -> list[str]:
    ids = [m.group(1) for m in _POLICY_NO.finditer(text)] + [m.group(1) for m in _CLAIM_NO.finditer(text)]
    ids += [m.group(0) for m in _CODE.finditer(text)]
    ids += [f"clause {m.group(1)}" for m in _CLAUSE.finditer(text)]
    return _uniq(ids, 50)


def classify_document(title: str | None, text: str) -> tuple[str, float]:
    head = ((title or "") + " " + (title or "") + " " + text[:6000]).lower()
    doc_type, conf = _score(head, DOC_TYPE_RULES)
    return (doc_type or "other"), conf


def extract_metadata(title: str | None, text: str) -> InsuranceMetadata:
    low = text.lower()
    doc_type, conf = classify_document(title, text)
    line, _ = _score(((title or "") + " " + low[:20000]), LINE_RULES)
    jur = _uniq([code for name, code in JURISDICTIONS.items() if re.search(r"\b" + re.escape(name) + r"\b", low)])
    eff = next((d for d in (_parse_date(m.group(1)) for m in _EFFECTIVE.finditer(text)) if d), None)
    exp = next((d for d in (_parse_date(m.group(1)) for m in _EXPIRY.finditer(text)) if d), None)
    if eff and exp and exp < eff:
        exp = None
    return InsuranceMetadata(
        document_type=doc_type, document_type_confidence=conf, insurance_line=line, jurisdictions=jur,
        policy_numbers=_uniq([m.group(1) for m in _POLICY_NO.finditer(text)]),
        claim_numbers=_uniq([m.group(1) for m in _CLAIM_NO.finditer(text)]),
        codes=_uniq([m.group(0) for m in _CODE.finditer(text)]),
        coverage_types=[c for c in COVERAGE_TYPES if c in low][:10],
        sum_insured=_uniq([m.group(1) for m in _SUM_INSURED.finditer(text)]),
        deductibles=_uniq([m.group(1) for m in _DEDUCTIBLE.finditer(text)]),
        waiting_periods=_uniq([m.group(1) for m in _WAITING.finditer(text)]),
        exclusions=_uniq([m.group(1) for m in _EXCLUSION_HEAD.finditer(text)]),
        effective_from=eff, effective_to=exp)
