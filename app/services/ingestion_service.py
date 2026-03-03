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


_CRIME_KEYWORDS: frozenset[str] = frozenset({
    "murder", "kill", "killed", "killing", "dead", "death", "dies", "died",
    "shoot", "shot", "gun", "firing", "stabbed", "stab", "knife",
    "assault", "attack", "attacked", "beat", "beaten", "torture",
    "rape", "molestation", "molest", "sexual assault",
    "arrest", "arrested", "police", "fir", "remand", "custody",
    "jail", "prison", "bail", "convicted", "sentenced", "charged",
    "court", "verdict", "accused", "detained", "detained",
    "robbery", "robbed", "theft", "stolen", "steal", "loot", "burglary",
    "fraud", "scam", "cheated", "embezzle",
    "terror", "terrorist", "bomb", "blast", "explosion",
    "drug", "narco", "trafficking", "smuggl",
    "kidnap", "abduct", "hostage",
    "extort", "ransom",
    "gang", "mob", "cartel",
    "corrupt", "bribe",
    "hack", "cyber crime", "cybercrime",
    "crime", "criminal", "victim", "suspect", "perpetrator",
    "violence", "violent", "offence", "offense",
})


def _has_crime_keywords(raw: dict) -> bool:
    text = " ".join(filter(None, [
        str(raw.get("title", "")),
        str(raw.get("summary", "")),
        str(raw.get("description", "")),
        str(raw.get("content", "")),
    ])).lower()
    return any(kw in text for kw in _CRIME_KEYWORDS)


class _RateLimiter:
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
    msg = str(exc).lower()
    return any(kw in msg for kw in (
        "429", "rate limit", "quota",
        "resource_exhausted",
        "resourceexhausted",
        "too many requests",
    ))


# Per-provider-type limiter cache: { provider_type → (rate_limiter, semaphore) }
_limiter_cache: dict[str, tuple["_RateLimiter", asyncio.Semaphore]] = {}


def _limits_for_provider(provider_type: str) -> tuple[int, int]:
    """Return (requests_per_minute, max_items_per_run) for the given provider type."""
    if provider_type == "ollama":
        return settings.OLLAMA_REQUESTS_PER_MINUTE, settings.OLLAMA_MAX_ITEMS_PER_RUN
    if provider_type in (
        "gemini", "gemini_langgraph", "gemini_multimodal", "anthropic", "openai", "custom"
    ):
        return settings.CLOUD_REQUESTS_PER_MINUTE, settings.CLOUD_MAX_ITEMS_PER_RUN
    return settings.AI_REQUESTS_PER_MINUTE, settings.AI_MAX_ITEMS_PER_RUN


def _get_limiter_for(provider_type: str) -> tuple["_RateLimiter", asyncio.Semaphore]:
    if provider_type not in _limiter_cache:
        rpm, _ = _limits_for_provider(provider_type)
        limiter = _RateLimiter(rpm)
        # Ollama: single GPU runs one inference at a time — enforce concurrency=1
        # to avoid queuing multiple requests in VRAM simultaneously.
        concurrency = (
            settings.OLLAMA_CONCURRENCY
            if provider_type == "ollama"
            else _concurrency_from_rpm(rpm)
        )
        semaphore = asyncio.Semaphore(concurrency)
        logger.info(
            "AI rate limiter for %r — RPM=%s, concurrency=%d, "
            "retry_attempts=%d, retry_delay=%.0fs",
            provider_type,
            rpm if rpm > 0 else "unlimited",
            concurrency,
            settings.AI_RETRY_ATTEMPTS,
            settings.AI_RETRY_DELAY_SECONDS,
        )
        _limiter_cache[provider_type] = (limiter, semaphore)
    return _limiter_cache[provider_type]


class IngestionService:
    def __init__(
        self,
        source_repo: SourceRepository,
        raw_repo: RawIngestionRepository | None = None,
        filter_article_repo: FilterArticleRepository | None = None,
        post_processed_repo: PostProcessedArticleRepository | None = None,
        ai_provider_repo: AIProviderRepository | None = None,
        db: AsyncSession | None = None,
    ) -> None:
        self.source_repo = source_repo
        self.raw_repo = raw_repo
        self.filter_article_repo = filter_article_repo
        self.post_processed_repo = post_processed_repo
        self.ai_provider_repo = ai_provider_repo
        self._db = db

    async def ingest(self, source: Source) -> int:
        """Run the full ingestion pipeline for one source. Returns post_processed count."""
        raw_items = await self._fetch_items(source)
        if not raw_items:
            logger.info("No items fetched from source_id=%s", source.id)
            return 0

        # Load provider first so we know its type (determines rate limits + item cap).
        ai_provider, provider_type = await self._load_ai_provider()
        if ai_provider is None:
            logger.warning(
                "No AI provider configured — skipping source_id=%s. "
                "Set GEMINI_API_KEY in .env or configure via POST /ai-providers/",
                source.id,
            )
            return 0

        _, max_items = _limits_for_provider(provider_type)
        if len(raw_items) > max_items:
            logger.debug(
                "Capping fetch from %d → %d items (%s) — source_id=%s",
                len(raw_items), max_items, provider_type, source.id,
            )
            raw_items = raw_items[:max_items]

        # Compute hashes once — reused for store_batch and all downstream filtering.
        all_pairs: list[tuple[str, dict]] = [
            (compute_content_hash(source.id, raw), raw) for raw in raw_items
        ]

        hash_to_raw_id: dict[str, int] = {}
        unprocessed_hashes: set[str] = set()
        if self.raw_repo:
            hash_to_raw_id, unprocessed_hashes = await self.raw_repo.store_batch(
                source.id, all_pairs
            )
            logger.info(
                "[RAW_SAVE] %d stored (%d to process) — source_id=%s",
                len(hash_to_raw_id), len(unprocessed_hashes), source.id,
            )

        # Filter to only articles that need processing (new + previously stuck-pending).
        new_pairs = [(ch, raw) for ch, raw in all_pairs if ch in unprocessed_hashes]

        if not new_pairs:
            logger.info(
                "No new articles to process — source_id=%s (all %d already seen)",
                source.id, len(all_pairs),
            )
            return 0

        # Single-pass keyword filter — avoids calling _has_crime_keywords twice per article.
        items: list[tuple[str, dict]] = []
        pre_filtered_hashes: list[str] = []
        for ch, raw in new_pairs:
            if _has_crime_keywords(raw):
                items.append((ch, raw))
            else:
                pre_filtered_hashes.append(ch)

        if pre_filtered_hashes:
            logger.info(
                "Keyword pre-filter: %d/%d skipped (no crime keywords) — source_id=%s",
                len(pre_filtered_hashes), len(new_pairs), source.id,
            )

        if not items:
            if self.raw_repo and pre_filtered_hashes:
                await self.raw_repo.mark_filtered_out(
                    source.id, pre_filtered_hashes, ai_provider.model_id
                )
            logger.info(
                "No crime-keyword articles to AI-process — source_id=%s", source.id
            )
            return 0

        rate_limiter, semaphore = _get_limiter_for(provider_type)

        logger.info(
            "[AI_EXTRACT] %d articles queued for AI — source_id=%s",
            len(items), source.id,
        )

        async def process_with_semaphore(
            content_hash: str, raw: dict
        ) -> tuple[str, dict | None]:
            async with semaphore:
                await rate_limiter.wait()
                result = await self._process_one(raw, source.type, ai_provider)
                return content_hash, result

        # For Ollama: process in batches with a GPU cooldown between each batch.
        # Prevents continuous load and thermal throttling on single-GPU setups.
        batch_size = settings.OLLAMA_BATCH_SIZE if provider_type == "ollama" else len(items)
        cooldown = settings.OLLAMA_BATCH_COOLDOWN_SECONDS if provider_type == "ollama" else 0.0

        results: list = []
        for batch_start in range(0, len(items), batch_size):
            batch = items[batch_start: batch_start + batch_size]
            batch_results = await asyncio.gather(
                *[process_with_semaphore(ch, raw) for ch, raw in batch],
                return_exceptions=True,
            )
            results.extend(batch_results)
            remaining = len(items) - (batch_start + len(batch))
            if cooldown > 0 and remaining > 0:
                logger.info(
                    "GPU cooldown: %.0fs pause after articles %d-%d (%d remaining) — source_id=%s",
                    cooldown, batch_start + 1, batch_start + len(batch), remaining, source.id,
                )
                await asyncio.sleep(cooldown)

        crime_articles: list[dict] = []
        filtered_hashes: dict[str, list[str]] = defaultdict(list)
        filtered_out_hashes: list[str] = list(pre_filtered_hashes)
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

        # Resolve category and location FKs from AI string labels to DB integer IDs.
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
                    article["sub_category_ids"] = cat_resolver.resolve_all(
                        article.get("sub_category_ids", [])
                    )
                    article["category_ids"] = cat_resolver.resolve_categories_from_ids(
                        article["sub_category_ids"]
                    )
                    article["sub_category_id"] = cat_resolver.resolve(
                        article.get("sub_category")
                    )
                if loc_resolver:
                    state_id = loc_resolver.resolve(article.get("location"))
                    article["location_id"] = state_id
                    article["location_state_id"] = state_id

        url_to_filter_id: dict[str, int] = {}
        if crime_articles and self.filter_article_repo:
            url_to_filter_id = await self.filter_article_repo.insert_batch(
                crime_articles, hash_to_raw_id
            )
            logger.info(
                "filter_articles: %d rows written — source_id=%s",
                len(url_to_filter_id),
                source.id,
            )

        count = 0
        if crime_articles and self.post_processed_repo and url_to_filter_id:
            count = await self.post_processed_repo.insert_batch(
                crime_articles, url_to_filter_id
            )
            scored = sum(1 for a in crime_articles if a.get("imp_score") is not None)
            logger.info(
                "post_processed_articles: %d written, %d scored — source_id=%s",
                count,
                scored,
                source.id,
            )

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

    async def _load_ai_provider(self) -> tuple[AIProvider | None, str]:
        """Return (provider, provider_type) — type is used to select rate limits."""
        if self.ai_provider_repo is not None:
            try:
                config = await self.ai_provider_repo.get_active()
                if config is not None:
                    return create_from_config(config), config.provider
            except Exception as exc:
                logger.warning(
                    "Could not load DB AI provider config, falling back to env: %s", exc
                )
        # Env fallback — mirror resolution order from ai_processor.py
        if settings.OLLAMA_MODEL:
            provider_type = "ollama"
        elif settings.GEMINI_API_KEY:
            provider_type = "gemini_multimodal"
        elif settings.ANTHROPIC_API_KEY:
            provider_type = "anthropic"
        else:
            provider_type = "unknown"
        return get_env_fallback_provider(), provider_type

    async def _fetch_items(self, source: Source) -> list[dict]:
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
        article = await self._call_with_retry(
            lambda: ai_provider.process(raw, source_type),
            "ai_provider.process",
        )
        if article is None:
            return None

        # Non-crime articles have no URL; pass them through so the gather loop
        # can correctly classify them as filtered_out (not failed).
        if not article.get("is_crime", True):
            return article

        url = article.get("url", "")
        if not url or not url.startswith(("http://", "https://")):
            logger.warning(
                "AI returned crime article without valid URL — dropping: %r",
                article.get("title", "")[:60],
            )
            return None

        return article

    async def _update_raw_statuses(
        self,
        source_id: int,
        filtered: dict[str, list[str]],
        filtered_out: list[str],
        failed: list[str],
        model_id: str,
    ) -> None:
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
