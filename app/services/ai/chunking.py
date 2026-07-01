"""Hand-written recursive character chunker.

Written by hand (not delegated to a library splitter) so the strategy can be
explained in depth: split long text into overlapping windows, and prefer to cut
at natural boundaries (paragraph → line → sentence → word) near the window edge
so chunks stay semantically coherent. Overlap keeps context from being lost at
the seam between two chunks.
"""

# Boundary separators tried in order of preference, from strongest to weakest.
_SEPARATORS = ["\n\n", "\n", ". ", " "]


def _find_boundary(text: str, start: int, end: int) -> int:
    """Return a cut point <= end, at the latest natural boundary after start.

    Falls back to a hard cut at `end` if no boundary is found in the window.
    """
    window = text[start:end]
    for sep in _SEPARATORS:
        idx = window.rfind(sep)
        # Require the boundary to be past the halfway point so we don't produce
        # tiny chunks when a separator happens to sit near the window start.
        if idx > len(window) // 2:
            return start + idx + len(sep)
    return end


def chunk_text(
    text: str, chunk_size: int = 1000, overlap: int = 150
) -> list[str]:
    """Split `text` into overlapping chunks of at most ~`chunk_size` characters.

    - Returns [] for empty/whitespace input.
    - Returns a single chunk when the text already fits.
    - Consecutive chunks share `overlap` characters of context.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            end = _find_boundary(text, start, end)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        # Step forward, keeping `overlap` chars of the previous window. Guard
        # against non-progress if a boundary landed at `start`.
        start = max(end - overlap, start + 1)
    return chunks


def build_article_text(
    title: str, description: str | None, content: str | None
) -> str:
    """Combine an article's fields into a single text body for chunking."""
    parts = [p for p in (title, description, content) if p]
    return "\n\n".join(parts).strip()
