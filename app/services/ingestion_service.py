"""
app/services/ingestion_service.py — Core Ingestion Pipeline
============================================================
Orchestrates the full pipeline from raw fetch to publication-ready articles.

Pipeline (in order):
  1. FETCH         Call RSSFetcher or RestFetcher to get raw items from the source
  2. STORE RAW     Save every raw payload to raw_ingestion (idempotent dedup)
                   Returns {content_hash: raw_ingestion_id} for FK linking
  3. LOAD AI       Resolve which AI provider to use (DB config or env fallback)
  4. AI FILTER     Concurrently call AI for each item — classify + extract fields
  5. SPLIT         Separate crime articles from non-crime/failed ones
  6. FILTER STAGE  Insert crime articles into filter_articles
                   Returns {main_url: filter_article_id} for FK linking
  7. POST STAGE    Insert enriched articles into post_processed_articles
  8. AUDIT         Update raw_ingestion statuses (filtered / filtered_out / failed)

Key design decisions:
  - SINGLE AI CALL per article — extracts fields AND classifies in one prompt
  - CONCURRENT processing with asyncio.Semaphore + rate limiter
  - BEST-EFFORT: failure on one article never drops others
  - IDEMPOTENT: running the same source twice safely upserts, never duplicates
"""

import asyncio
import logging
import time as _time
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.source import Source
from app.repositories.ai_provider_repo import AIProviderRepository
from app.repositories.filter_article_repo import FilterArticleRepository
from app.repositories.post_processed_article_repo import PostProcessedArticleRepository
from app.repositories.raw_ingestion_repo import RawIngestionRepository, compute_content_hash
from app.repositories.source_repo import SourceRepository
from app.services.fetchers.rest_fetcher import RestFetcher
from app.services.fetchers.rss_fetcher import RSSFetcher
from app.services.normalization.ai_processor import get_env_fallback_provider
from app.services.normalization.provider_factory import create_from_config
from app.services.normalization.providers.base import AIProvider
from app.services.normalization.resolvers import CategoryResolver, LocationResolver, load_resolvers
from app.services.source_normalizer import to_plain_dict

logger = logging.getLogger(__name__)


class _RateLimiter:
    """Enforces a minimum interval between AI API calls.

    rpm=0 means unlimited — no delay applied (paid plans).
    """

    def __init__(self, rpm: int) -> None:
        self._interval = (60.0 / rpm) if rpm > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last: float = 0.0

    async def wait(self) -> None:
        if self._interval == 0.0:
            return
        async with self._lock:
            elapsed = _time.monotonic() - self._last
            gap = self._interval - elapsed
            if gap > 0:
                logger.debug(
                    "Rate limiter: sleeping %.1fs to respect %d RPM",
                    gap,
                    round(60 / self._interval),
                )
                await asyncio.sleep(gap)
            self._last = _time.monotonic()


def _concurrency_from_rpm(rpm: int) -> int:
    if rpm == 0:
        return 10
    if rpm <= 10:
        return 1
    if rpm <= 30:
        return 2
    if rpm <= 100:
        return 5
    return 10


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect rate limit / quota errors from any AI provider.

    Covers: HTTP 429, Gemini ResourceExhausted, OpenAI rate limit strings.
    """
    msg = str(exc).lower()
    return any(kw in msg for kw in (
        "429", "rate limit", "quota",
        "resource_exhausted",   # with underscore (some wrappers)
        "resourceexhausted",    # google.api_core camelCase lowercased
        "too many requests",
    ))


# ---- Process-level singletons -----------------------------------------------
# ONE rate limiter and semaphore for the entire process, shared across ALL
# concurrent ingestion runs (multiple sources via asyncio.gather in the scheduler)
# AND across both pipeline stages (filter + post-process).
#
# Why global?
#   The scheduler runs sources concurrently. Without a shared limiter, N sources
#   each create their own _RateLimiter and fire at N× the intended RPM — blowing
#   through the free-tier quota in minutes.
#
# Lazily initialized on first async call so asyncio primitives bind to the
# running event loop (Python 3.10+ handles this correctly).
_global_rate_limiter: "_RateLimiter | None" = None
_global_semaphore: "asyncio.Semaphore | None" = None


def _get_global_limiter() -> tuple["_RateLimiter", asyncio.Semaphore]:
    """Return (or lazily create) the shared process-level limiter + semaphore."""
    global _global_rate_limiter, _global_semaphore
    if _global_rate_limiter is None:
        rpm = settings.AI_REQUESTS_PER_MINUTE
        _global_rate_limiter = _RateLimiter(rpm)
        _global_semaphore = asyncio.Semaphore(_concurrency_from_rpm(rpm))
        logger.info(
            "AI rate limiter initialised — RPM=%s, concurrency=%d, "
            "retry_attempts=%d, retry_delay=%.0fs",
            rpm if rpm > 0 else "unlimited",
            _concurrency_from_rpm(rpm),
            settings.AI_RETRY_ATTEMPTS,
            settings.AI_RETRY_DELAY_SECONDS,
        )
    return _global_rate_limiter, _global_semaphore  # type: ignore[return-value]


class IngestionService:
    """Orchestrates the fetch → AI filter → store pipeline for one source.

    Constructor takes all required repositories — no raw DB sessions here.
    This keeps the service testable: tests can pass mock repos.
    """

    def __init__(
        self,
        source_repo: SourceRepository,
        raw_repo: RawIngestionRepository | None = None,
        filter_article_repo: FilterArticleRepository | None = None,
        post_processed_repo: PostProcessedArticleRepository | None = None,
        ai_provider_repo: AIProviderRepository | None = None,
        db: AsyncSession | None = None,
        # Kept for backwards compatibility — ignored in new pipeline
        article_repo: object | None = None,
    ) -> None:
        self.source_repo = source_repo
        self.raw_repo = raw_repo
        self.filter_article_repo = filter_article_repo
        self.post_processed_repo = post_processed_repo
        self.ai_provider_repo = ai_provider_repo
        self._db = db   # used to load resolvers once per ingest run

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def ingest(self, source: Source) -> int:
        """Run the full ingestion pipeline for one source.

        Returns the count of post_processed_articles rows written.
        Called by POST /ingest/ and the scheduler.
        """
        # Step 1: FETCH
        raw_items = await self._fetch_items(source)
        if not raw_items:
            logger.info("No items fetched from source_id=%s", source.id)
            return 0

        # Step 2: STORE RAW — dual-write before any AI processing
        hash_to_raw_id: dict[str, int] = {}
        if self.raw_repo:
            hash_to_raw_id = await self.raw_repo.store_batch(source.id, raw_items)
            logger.debug(
                "raw_ingestion: stored %d hashes for source_id=%s",
                len(hash_to_raw_id),
                source.id,
            )

        # Step 3: LOAD AI PROVIDER
        ai_provider = await self._load_ai_provider()
        if ai_provider is None:
            logger.warning(
                "No AI provider configured — skipping source_id=%s. "
                "Set GEMINI_API_KEY in .env or configure via POST /ai-providers/",
                source.id,
            )
            return 0

        # Build (content_hash, raw_payload) pairs — content_hash links to raw_ingestion
        items = [(compute_content_hash(source.id, raw), raw) for raw in raw_items]

        # Step 4: AI FILTER — concurrent, rate-limited
        # Use the shared process-level limiter so all concurrent sources
        # (scheduler runs them in parallel) count against the same quota.
        rate_limiter, semaphore = _get_global_limiter()

        logger.info("AI processing: %d articles — source_id=%s", len(items), source.id)

        async def process_with_semaphore(
            content_hash: str, raw: dict
        ) -> tuple[str, dict | None]:
            async with semaphore:
                await rate_limiter.wait()
                result = await self._process_one(raw, source.type, ai_provider)
                return content_hash, result

        results = await asyncio.gather(
            *[process_with_semaphore(ch, raw) for ch, raw in items],
            return_exceptions=True,
        )

        # Step 5: SPLIT into buckets
        crime_articles: list[dict] = []
        filtered_hashes: dict[str, list[str]] = defaultdict(list)  # model_id → hashes
        filtered_out_hashes: list[str] = []
        failed_hashes: list[str] = []

        for i, result in enumerate(results):
            content_hash = items[i][0]

            if isinstance(result, Exception):
                logger.error("gather error for article hash=%s: %s", content_hash[:8], result)
                failed_hashes.append(content_hash)
                continue

            _, article = result

            if article is None:
                failed_hashes.append(content_hash)
                continue

            if not article.get("is_crime", True):
                logger.debug("Filtered out (non-crime): %r", article.get("url", "")[:60])
                filtered_out_hashes.append(content_hash)
                continue

            # Attach the content_hash so filter_article_repo can look up raw_ingestion_id
            article["content_hash"] = content_hash
            crime_articles.append(article)
            filtered_hashes[ai_provider.model_id].append(content_hash)

        logger.info(
            "Filter stage: %d crime, %d filtered_out, %d failed — source_id=%s",
            len(crime_articles),
            len(filtered_out_hashes),
            len(failed_hashes),
            source.id,
        )

        # Step 5b: RESOLVE FKs — translate AI strings to DB ids (one DB query each)
        # Gracefully skip if no DB session available (test/legacy callers).
        cat_resolver: CategoryResolver | None = None
        loc_resolver: LocationResolver | None = None
        if self._db is not None and crime_articles:
            try:
                cat_resolver, loc_resolver = await load_resolvers(self._db)
            except Exception as exc:
                logger.warning("Could not load resolvers (FKs will be NULL): %s", exc)

        if crime_articles and (cat_resolver or loc_resolver):
            for article in crime_articles:
                if cat_resolver:
                    # Legacy single FK (kept for backward compat)
                    article["sub_category_id"] = cat_resolver.resolve(
                        article.get("sub_category")
                    )
                    # New multi-label JSONB array — resolve each AI string to a DB id
                    article["sub_category_ids"] = cat_resolver.resolve_all(
                        article.get("sub_category_ids", [])
                    )
                if loc_resolver:
                    state_id = loc_resolver.resolve(article.get("location"))
                    article["location_id"] = state_id
                    article["location_state_id"] = state_id  # also for filter_articles

        # Step 5c: STAGE 2 — AI post-processing for crime articles
        # Makes a second AI call per crime article to:
        #   - Rewrite title and description for publication quality
        #   - Discover reference URLs (via web search in supported providers)
        #   - Assign a 1-100 importance score (finer than stage 1's 1-10)
        if crime_articles:
            crime_articles = await self._run_post_processing(
                crime_articles, ai_provider, rate_limiter, semaphore
            )

        # Step 6: FILTER STAGE — write to filter_articles
        url_to_filter_id: dict[str, int] = {}
        if crime_articles and self.filter_article_repo:
            url_to_filter_id = await self.filter_article_repo.insert_batch(
                crime_articles, hash_to_raw_id
            )
            logger.debug(
                "filter_articles: %d rows written — source_id=%s",
                len(url_to_filter_id),
                source.id,
            )

        # Step 7: POST-PROCESSING STAGE — write to post_processed_articles
        count = 0
        if crime_articles and self.post_processed_repo and url_to_filter_id:
            count = await self.post_processed_repo.insert_batch(
                crime_articles, url_to_filter_id
            )
            logger.debug(
                "post_processed_articles: %d rows written — source_id=%s",
                count,
                source.id,
            )

        # Step 8: AUDIT — update raw_ingestion statuses (best-effort)
        if self.raw_repo:
            await self._update_raw_statuses(
                source_id=source.id,
                filtered=dict(filtered_hashes),
                filtered_out=filtered_out_hashes,
                failed=failed_hashes,
                model_id=ai_provider.model_id,
            )

        logger.info(
            "Ingestion complete: %d written, %d filtered_out, %d failed — source_id=%s",
            count,
            len(filtered_out_hashes),
            len(failed_hashes),
            source.id,
        )
        return count

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_ai_provider(self) -> AIProvider | None:
        """Resolve the AI provider.

        Priority: DB active config → GEMINI_API_KEY env → ANTHROPIC_API_KEY env → None
        """
        if self.ai_provider_repo is not None:
            try:
                config = await self.ai_provider_repo.get_active()
                if config is not None:
                    return create_from_config(config)
            except Exception as exc:
                logger.warning(
                    "Could not load DB AI provider config, falling back to env: %s", exc
                )
        return get_env_fallback_provider()

    async def _fetch_items(self, source: Source) -> list[dict]:
        """Fetch raw items from the source using the appropriate fetcher."""
        try:
            if source.type == "rss":
                feed = await RSSFetcher().fetch(source.url)
                return [to_plain_dict(entry) for entry in feed.entries]

            if source.type == "rest":
                headers = (source.config or {}).get("headers", {})
                items = await RestFetcher().fetch(source.url, headers=headers)
                return [to_plain_dict(item) for item in items]

            raise ValueError(f"Unknown source type: {source.type!r}")
        except Exception as exc:
            logger.error("Fetch failed for source_id=%s: %s", source.id, exc)
            return []

    async def _call_with_retry(self, coro_fn, label: str) -> dict | None:
        """Call coro_fn() with exponential backoff on rate limit / quota errors.

        Uses AI_RETRY_ATTEMPTS and AI_RETRY_DELAY_SECONDS from config.
        Non-rate-limit errors are logged and returned as None immediately.
        """
        delay = settings.AI_RETRY_DELAY_SECONDS
        for attempt in range(settings.AI_RETRY_ATTEMPTS):
            try:
                return await coro_fn()
            except Exception as exc:
                if _is_rate_limit_error(exc) and attempt < settings.AI_RETRY_ATTEMPTS - 1:
                    wait = delay * (2 ** attempt)
                    logger.warning(
                        "%s: rate limit hit (attempt %d/%d), backing off %.0fs — %s",
                        label, attempt + 1, settings.AI_RETRY_ATTEMPTS, wait, exc,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.error("%s failed: %s", label, exc)
                return None
        return None

    async def _process_one(
        self,
        raw: dict,
        source_type: str,
        ai_provider: AIProvider,
    ) -> dict | None:
        """Run one article through the AI provider. Retries on rate limit errors."""
        article = await self._call_with_retry(
            lambda: ai_provider.process(raw, source_type),
            "ai_provider.process",
        )
        if article is None:
            return None

        url = article.get("url", "")
        if not url or not url.startswith(("http://", "https://")):
            logger.warning(
                "AI returned article without valid URL — dropping: %r",
                article.get("title", "")[:60],
            )
            return None

        return article

    async def _run_post_processing(
        self,
        crime_articles: list[dict],
        ai_provider: AIProvider,
        rate_limiter: "_RateLimiter",
        semaphore: asyncio.Semaphore,
    ) -> list[dict]:
        """Run stage 2 post-processing concurrently for all crime articles.

        Calls ai_provider.post_process() for each article. If the provider
        does not support post_process() (returns None), the article is returned
        unchanged — stage 1 data is used as-is in post_processed_articles.

        Uses the SAME rate_limiter and semaphore as stage 1 so both stages
        share the same per-minute budget — no burst between stages.

        Returns the same list with stage 2 fields merged in where available:
          - rewritten_title, rewritten_description, reference_urls, imp_score
        """
        async def post_process_one(article: dict) -> dict:
            async with semaphore:
                await rate_limiter.wait()
                result = await self._call_with_retry(
                    lambda: ai_provider.post_process(article),
                    "ai_provider.post_process",
                )

            if result:
                # Merge stage 2 fields into the article dict
                article["rewritten_title"] = result.get("rewritten_title")
                article["rewritten_description"] = result.get("rewritten_description")
                article["stage2_reference_urls"] = result.get("reference_urls", [])
                article["imp_score"] = result.get("imp_score")
                logger.debug(
                    "Stage 2 done: imp_score=%s title=%r",
                    article["imp_score"],
                    (article["rewritten_title"] or article["title"])[:60],
                )
            return article

        updated = await asyncio.gather(
            *[post_process_one(a) for a in crime_articles],
            return_exceptions=True,
        )

        # Return only successful results; re-use original on exception
        final = []
        for i, item in enumerate(updated):
            if isinstance(item, Exception):
                logger.error(
                    "post_processing gather error for article %d: %s", i, item
                )
                final.append(crime_articles[i])   # keep original stage 1 data
            else:
                final.append(item)

        scored = sum(1 for a in final if a.get("imp_score") is not None)
        logger.info(
            "Stage 2 complete: %d/%d articles scored — source run",
            scored, len(final),
        )
        return final

    async def _update_raw_statuses(
        self,
        source_id: int,
        filtered: dict[str, list[str]],      # {model_id: [hashes]}
        filtered_out: list[str],
        failed: list[str],
        model_id: str,
    ) -> None:
        """Update raw_ingestion rows with pipeline outcome. Best-effort."""
        try:
            if filtered:
                await self.raw_repo.mark_filtered(source_id, filtered)
            if filtered_out:
                await self.raw_repo.mark_filtered_out(source_id, filtered_out, model_id)
            if failed:
                await self.raw_repo.mark_failed(source_id, failed, "processing_failed")
        except Exception as exc:
            logger.warning(
                "Failed to update raw_ingestion statuses for source_id=%s: %s",
                source_id,
                exc,
            )
