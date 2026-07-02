"""Heuristic prompt-injection detection.

A curated set of patterns for the most common override attempts ("ignore previous
instructions", "reveal your system prompt", role-swap, jailbreak). This is a
lightweight first line of defence — a production system would add a trained
classifier and treat *retrieved documents* as untrusted too. Kept pure and
deterministic so it is easy to unit-test and reason about.
"""

import re

_PATTERNS = [
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(the\s+)?(previous|prior|above)",
    r"forget\s+(everything|all|the\s+above)",
    r"reveal\s+(your\s+)?(system\s+)?prompt",
    r"(show|print|repeat)\s+(your\s+)?(system\s+)?prompt",
    r"system\s+prompt",
    r"you\s+are\s+now\b",
    r"act\s+as\b",
    r"developer\s+mode",
    r"jailbreak",
    r"do\s+anything\s+now",
]

_REGEX = re.compile("|".join(_PATTERNS), re.IGNORECASE)


def contains_injection(text: str) -> bool:
    """True if the text looks like a prompt-injection / override attempt."""
    return bool(_REGEX.search(text or ""))
