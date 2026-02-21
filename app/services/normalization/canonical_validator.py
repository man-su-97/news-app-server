"""
app/services/normalization/canonical_validator.py — Article Quality Gate
=========================================================================
After normalization (deterministic or AI), every article passes through
this validator before being saved to the database.

Purpose: enforce a minimum quality bar so we never store useless rows.
An article that fails validation is either:
  a) Retried with AI normalization (if AI is configured and first pass was deterministic)
  b) Dropped and marked as "failed" in raw_ingestion_events

What does "valid" mean?
  - title is non-empty and not a placeholder like "Untitled" or "N/A"
  - url is an absolute HTTP(S) URL (starts with http:// or https://)

Why only validate these two fields?
  Architecture decision: we validate the MINIMUM required for a usable article.
  Other fields (description, image_url, published_at) are optional — an article
  without a description or image is still a valid article worth showing.
  But an article with no title or no URL is unusable in the frontend.
"""

import logging
from dataclasses import dataclass, field   # dataclass creates simple data holder classes

logger = logging.getLogger(__name__)

# Titles that a failed/lazy normalizer produces.
# These are rejected because they're not real article titles.
_PLACEHOLDER_TITLES = frozenset({"untitled", "", "no title", "n/a", "none"})
# frozenset is used (not set) because it's immutable — prevents accidental modification.
# .lower() is applied before checking, so "UNTITLED" and "Untitled" both match.


@dataclass
class ValidationResult:
    """The result of validating one article.

    valid:  True if the article passes all checks and should be saved.
    errors: List of human-readable error descriptions (for logging and DB storage).

    Architecture note: using a dataclass instead of a plain dict makes this
    self-documenting — result.valid is clearer than result["valid"].
    """
    valid: bool
    # field(default_factory=list) creates a new empty list for each ValidationResult.
    # If we used errors: list[str] = [], ALL instances would share the SAME list (Python bug).
    errors: list[str] = field(default_factory=list)


def validate(article: dict) -> ValidationResult:
    """Gate-check a normalized article dict before saving it to the database.

    Called by IngestionService after BOTH deterministic normalization AND
    AI normalization. Both paths must produce an article that passes this check.

    Returns:
      ValidationResult(valid=True)  → article is saved
      ValidationResult(valid=False) → article is dropped (or retried with AI)
    """
    errors: list[str] = []   # collect all errors (not just the first one)

    # --- Check 1: Title is present and meaningful ---
    title = (article.get("title") or "").strip()  # get title, strip whitespace
    if title.lower() in _PLACEHOLDER_TITLES:
        # The normalizer couldn't extract a real title
        errors.append(f"title is absent or placeholder: {article.get('title')!r}")

    # --- Check 2: URL is an absolute HTTP(S) URL ---
    url = article.get("url") or ""
    if not url.startswith(("http://", "https://")):
        # Missing URL, relative URL (/path), or non-HTTP URL (ftp://)
        errors.append(f"url is missing or not HTTP(S): {url!r}")

    # If any errors were collected, the article is invalid
    if errors:
        logger.warning(
            "Normalization validation failed — url=%r title=%r errors=%s",
            url,
            title,
            errors,
        )
        return ValidationResult(valid=False, errors=errors)

    # All checks passed — article is good to save
    return ValidationResult(valid=True)
