"""Token counting for prompt-budget enforcement.

Uses tiktoken (already pulled in by the OpenAI/LangChain stack) to count tokens
the way the model does. Falls back to a ~4-chars-per-token estimate if tiktoken
or the model encoding is unavailable, so callers never crash on counting.
"""

import logging

logger = logging.getLogger(__name__)

_encoders: dict[str, object] = {}


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    if not text:
        return 0
    try:
        import tiktoken

        enc = _encoders.get(model)
        if enc is None:
            try:
                enc = tiktoken.encoding_for_model(model)
            except KeyError:
                enc = tiktoken.get_encoding("o200k_base")
            _encoders[model] = enc
        return len(enc.encode(text))
    except Exception as exc:  # tiktoken missing / offline → estimate
        logger.debug("tiktoken unavailable (%s); estimating tokens", exc)
        return max(1, len(text) // 4)
