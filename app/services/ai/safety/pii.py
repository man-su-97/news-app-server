"""Regex-based PII redaction.

Replaces the common, high-precision PII shapes (email, SSN, credit-card, phone)
with typed placeholders before text is sent to the model. Regex is a pragmatic
baseline; a production system would use an NER-based tool such as Microsoft
Presidio for names/addresses. Order matters — the more specific patterns
(SSN, card) run before the greedier phone pattern.
"""

import re

# (pattern, replacement), applied in order.
_RULES = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\+?\d[\d().\-\s]{8,}\d"), "[PHONE]"),
]


def redact_pii(text: str) -> str:
    if not text:
        return text
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
