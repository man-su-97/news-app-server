"""
app/services/ingestion_service.py — Core Ingestion Pipeline
============================================================
This is the most important service in the application.
It orchestrates the entire pipeline from fetching raw news to storing
enriched articles in the database.

Pipeline (in order):
  1. FETCH:    Call RSSFetcher or RestFetcher to get raw items from the source
  2. STORE:    Save every raw payload to raw_ingestion_events (idempotent dedup)
  3. NORMALIZE: For each item, try deterministic rules first, then AI fallback
  4. VALIDATE: Reject articles with missing title or invalid URL
  5. ENRICH:   Call LangGraph agent → classify crime type, location, importance score
  6. FILTER:   Drop non-crime articles (is_crime=False)
  7. UPSERT:   Batch-insert all valid crime articles into the articles table
  8. AUDIT:    Update raw_ingestion_events with success/failure status

Key design principles:
  - Best-effort: enrichment failure NEVER drops an article
  - Idempotent: running the same source twice produces the same result
  - Batch writes: single DB round-trip for the entire batch (not per-article)
  - Isolation: AI provider is loaded once per batch, not once per article

Architecture diagram:
  IngestionService
    ├── source_repo:        reads source config
    ├── article_repo:       writes final articles
    ├── raw_repo:           writes raw events + updates their status
    └── ai_provider_repo:   loads the active AI provider config
"""

import logging
from collections import defaultdict  # dict where missing keys auto-get a default value

from app.models.source import Source
from app.repositories.ai_provider_repo import AIProviderRepository
from app.repositories.article_repo import ArticleRepository
from app.repositories.raw_ingestion_repo import RawIngestionRepository, compute_content_hash
from app.repositories.source_repo import SourceRepository
from app.services.fetchers.rest_fetcher import RestFetcher
from app.services.fetchers.rss_fetcher import RSSFetcher
from app.services.normalization.ai_processor import get_env_fallback_provider
from app.services.normalization.canonical_validator import validate
from app.services.normalization.provider_factory import create_from_config
from app.services.normalization.providers.base import AIProvider
from app.services.source_normalizer import normalize, to_plain_dict

logger = logging.getLogger(__name__)


class IngestionService:
    """Orchestrates the fetch → normalize → enrich → store pipeline for one source.

    Constructor takes all required repositories via dependency injection.
    This makes the service testable: tests can pass mock repos instead of
    creating real DB sessions.
    """

    def __init__(
        self,
        source_repo: SourceRepository,
        article_repo: ArticleRepository,
        raw_repo: RawIngestionRepository | None = None,         # optional — some callers don't need audit
        ai_provider_repo: AIProviderRepository | None = None,  # optional — falls back to env var
    ) -> None:
        self.source_repo = source_repo
        self.article_repo = article_repo
        self.raw_repo = raw_repo
        self.ai_provider_repo = ai_provider_repo

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def ingest(self, source: Source) -> int:
        """Run the full ingestion pipeline for one source. Returns articles written count.

        This method is called by:
          - POST /ingest/ route (manual trigger)
          - scheduler.py _ingest_one_source() (automatic every 5 minutes)

        Architecture: the AI provider is loaded ONCE per batch (not per article).
        This avoids one DB query per article — for a batch of 50 articles, that's
        49 saved queries.
        """
        # Step 1: FETCH — get raw items from the source URL
        raw_items = await self._fetch_items(source)
        if not raw_items:
            logger.info("No items fetched from source_id=%s", source.id)
            return 0

        # Step 2: STORE RAW — persist every raw payload before processing.
        # "Dual-write" pattern: if normalization crashes, we haven't lost the data.
        # compute_content_hash() is used as a dedup key (duplicate payloads skipped).
        if self.raw_repo:
            new_count = await self.raw_repo.store_batch(source.id, raw_items)
            logger.debug(
                "Raw events: %d new of %d fetched (source_id=%s)",
                new_count, len(raw_items), source.id,
            )

        # Step 3: LOAD AI PROVIDER — resolve which AI to use for this batch.
        # Priority: DB-configured active provider → GEMINI_API_KEY env var
        #         → ANTHROPIC_API_KEY env var → None (deterministic only)
        ai_provider = await self._load_ai_provider()
        if ai_provider is None:
            logger.debug(
                "No AI provider configured — deterministic-only normalization (source_id=%s)",
                source.id,
            )

        # Step 4-7: NORMALIZE + ENRICH + FILTER each article
        valid_articles: list[dict] = []
        normalized_hashes: dict[str, str] = {}   # hash → normalizer label (for audit)
        failed_hashes: list[str] = []            # hashes that failed (for audit)

        for raw in raw_items:
            # Compute the same hash used in store_batch — links this loop to the stored raw event
            content_hash = compute_content_hash(source.id, raw)

            # NORMALIZE: deterministic rules first, AI fallback if needed
            article, label = await self._normalize_one(raw, source.type, ai_provider)

            if article is not None:
                # ENRICH + FILTER: only if AI provider is configured
                if ai_provider is not None:
                    # Call AI to classify crime type, extract location, generate summary, score it
                    enrichment = await self._enrich_one(article, ai_provider)
                    # Merge enrichment fields into the article dict
                    # (article now has category, sub_category, location, region, summary, score)
                    article.update(enrichment)

                    # FILTER: drop non-crime articles (this is a crime-only news app)
                    # is_crime=True by default — enrichment failure NEVER drops articles
                    if not article.get("is_crime", True):
                        logger.debug(
                            "Dropping non-crime article: %r", article.get("url", "")
                        )
                        # Still count as "failed" in raw events (processed but not saved)
                        failed_hashes.append(content_hash)
                        continue  # Skip to the next article — don't add to valid_articles

                # Article passed all checks — add to the batch for DB insert
                valid_articles.append(article)
                normalized_hashes[content_hash] = label
            else:
                # Normalization failed (no title, no URL, AI error)
                failed_hashes.append(content_hash)

        # Step 8: UPSERT — single batch DB write for ALL valid articles.
        # One DB round-trip regardless of batch size (50 articles = 1 query, not 50).
        count = await self.article_repo.upsert_batch(valid_articles, source.id)

        # Step 9: AUDIT — update raw_ingestion_events with success/failure status.
        # best-effort: if this fails, the articles are already written — don't roll back.
        if self.raw_repo:
            await self._update_raw_statuses(source.id, normalized_hashes, failed_hashes)

        logger.info(
            "Ingestion complete: %d written, %d failed validation — source_id=%s",
            count, len(failed_hashes), source.id,
        )
        return count  # number of articles saved (for the HTTP response and scheduler log)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_ai_provider(self) -> AIProvider | None:
        """Resolve the AI provider to use for this ingest run.

        Resolution order (first match wins):
          1. DB-configured active provider (via POST /ai-providers + activate)
          2. GEMINI_API_KEY environment variable → GeminiLangGraphProvider
          3. ANTHROPIC_API_KEY environment variable → AnthropicProvider (legacy)
          4. None → deterministic normalization only, no enrichment

        The DB check is wrapped in try/except: if the DB is down or the config
        is corrupted, we fall back to env vars instead of failing the entire batch.
        """
        if self.ai_provider_repo is not None:
            try:
                config = await self.ai_provider_repo.get_active()
                if config is not None:
                    # create_from_config() returns a cached provider instance
                    return create_from_config(config)
            except Exception as exc:
                logger.warning(
                    "Could not load DB AI provider config, falling back to env: %s", exc
                )

        # Fallback: check environment variables
        return get_env_fallback_provider()

    async def _fetch_items(self, source: Source) -> list[dict]:
        """Fetch raw items from the source URL using the appropriate fetcher.

        Dispatches to RSSFetcher (for RSS feeds) or RestFetcher (for REST APIs)
        based on source.type.

        Returns a list of plain Python dicts.
        to_plain_dict() converts feedparser's special objects to JSON-serializable dicts
        (needed before storing to JSONB). It's idempotent — safe to call on plain dicts too.

        Returns [] on any error (fetch failed, network down, unknown type).
        The caller handles the empty list gracefully.
        """
        try:
            if source.type == "rss":
                # RSSFetcher returns a feedparser Feed object
                feed = await RSSFetcher().fetch(source.url)
                # Convert feedparser's FeedParserDict entries to plain dicts
                return [to_plain_dict(entry) for entry in feed.entries]

            if source.type == "rest":
                # Get custom headers from source config (e.g. API keys)
                headers = (source.config or {}).get("headers", {})
                # RestFetcher returns a plain list of dicts already
                items = await RestFetcher().fetch(source.url, headers=headers)
                # to_plain_dict() is idempotent — safe to call on already-plain dicts
                return [to_plain_dict(item) for item in items]

            # Unknown source type — raise so it gets caught below and logged
            raise ValueError(f"Unknown source type: {source.type!r}")
        except Exception as exc:
            # Any fetch error (network, parsing, unknown type) returns empty list.
            # This source is skipped; other sources in the batch are unaffected.
            logger.error("Fetch failed for source_id=%s: %s", source.id, exc)
            return []

    async def _normalize_one(
        self,
        raw: dict,
        source_type: str,
        ai_provider: AIProvider | None,
    ) -> tuple[dict | None, str]:
        """Normalize one raw item. Returns (article_dict, normalizer_label) or (None, "").

        Two-pass normalization strategy:
          Pass 1 (deterministic): fast rule-based extraction. No API calls.
            If result passes validation → return it immediately.
            If validation fails → try AI fallback.
          Pass 2 (AI fallback): send raw payload to AI for extraction.
            Only used if: AI is configured AND deterministic pass failed.
            If AI result passes validation → return it.
            If AI also fails → return (None, "") — article is dropped.

        Why deterministic first?
          - Speed: deterministic is instant (~0ms), AI is ~1-2 seconds
          - Cost: AI APIs charge per token — avoiding AI for well-structured sources saves money
          - Reliability: deterministic works even when AI APIs are down
        """
        # Pass 1: Deterministic normalization — fast, no API calls
        try:
            data = normalize(raw)             # extract title/url/etc from raw dict
            if validate(data).valid:
                # Good article — return immediately without calling AI
                return data, "deterministic"
            # Validation failed (e.g. missing URL) — log and fall through to AI
            logger.debug("Deterministic output invalid — routing to AI fallback")
        except Exception as exc:
            # normalize() itself raised (shouldn't happen with well-formed data)
            logger.error("Deterministic normalization raised: %s", exc)

        # Pass 2: AI fallback — only if AI is configured
        if ai_provider is not None:
            try:
                # Send raw payload to AI for extraction
                ai_data = await ai_provider.normalize(raw, source_type)
                if ai_data is not None and validate(ai_data).valid:
                    # AI produced a valid article
                    return ai_data, ai_provider.model_id
                logger.warning(
                    "AI provider %s produced invalid output for source_type=%s",
                    ai_provider.model_id, source_type,
                )
            except Exception as exc:
                logger.error("AI provider %s raised: %s", ai_provider.model_id, exc)

        # Both passes failed — this article is dropped
        return None, ""

    async def _enrich_one(self, article: dict, ai_provider: AIProvider) -> dict:
        """Call the AI provider's enrich() method to add classification fields.

        Best-effort wrapper: ANY exception is caught and logged.
        Always returns a valid dict — never raises.

        On success: returns dict with is_crime, category, sub_category, location,
                    region, summary, importance_score
        On failure: returns all-None dict (with is_crime=True so article isn't dropped)
        """
        # The null enrichment — returned if anything goes wrong
        _null = {"is_crime": True, "category": None, "sub_category": None,
                 "location": None, "region": None, "summary": None, "importance_score": None}
        try:
            # ai_provider.enrich() is itself guaranteed to never raise (it has its own try/except)
            # But we add an outer try/except here as an extra safety net
            return await ai_provider.enrich(article)
        except Exception as exc:
            logger.warning(
                "Enrichment failed for article %r (provider=%s): %s",
                article.get("url", ""),
                ai_provider.model_id,
                exc,
            )
            return _null

    async def _update_raw_statuses(
        self,
        source_id: int,
        normalized: dict[str, str],   # {hash: normalizer_label} for successful articles
        failed: list[str],            # [hash, ...] for failed articles
    ) -> None:
        """Update raw_ingestion_events with the outcome of this ingest run.

        This is BEST-EFFORT: if this fails, the articles are already written to the DB.
        We never roll back written articles because raw status update failed.
        The try/except here ensures that a raw status update failure is just logged,
        not propagated up as an HTTP 500 error.

        normalized dict is grouped by normalizer label (for the normalized_by column):
          {"deterministic": [...], "ai:gemini_langgraph:gemini-2.0-flash": [...]}
        """
        try:
            if normalized:
                # Group hashes by their normalizer for the batch update
                by_normalizer: dict[str, list[str]] = defaultdict(list)
                for h, label in normalized.items():
                    by_normalizer[label].append(h)
                # Single batch UPDATE per normalizer label
                await self.raw_repo.mark_normalized(source_id, dict(by_normalizer))
            if failed:
                # Batch UPDATE for all failed articles
                await self.raw_repo.mark_failed(source_id, failed, "validation_failed")
        except Exception as exc:
            # Don't let audit failures bubble up — articles are already saved
            logger.warning(
                "Failed to update raw event statuses for source_id=%s: %s",
                source_id, exc,
            )
