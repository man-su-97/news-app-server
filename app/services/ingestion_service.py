import logging
from collections import defaultdict

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
    def __init__(
        self,
        source_repo: SourceRepository,
        article_repo: ArticleRepository,
        raw_repo: RawIngestionRepository | None = None,
        ai_provider_repo: AIProviderRepository | None = None,
    ) -> None:
        self.source_repo = source_repo
        self.article_repo = article_repo
        self.raw_repo = raw_repo
        self.ai_provider_repo = ai_provider_repo

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def ingest(self, source: Source) -> int:
        """Full ingestion pipeline for one source.

        Flow:
          fetch → raw store (idempotent) → normalize → validate →
          AI fallback → batch upsert → update raw event statuses

        The active AI provider is loaded once per ingest() call (one DB query)
        and passed to every _normalize_one() call, avoiding per-article DB hits.
        """
        raw_items = await self._fetch_items(source)
        if not raw_items:
            logger.info("No items fetched from source_id=%s", source.id)
            return 0

        # Dual-write: persist every raw payload before normalization (idempotent).
        if self.raw_repo:
            new_count = await self.raw_repo.store_batch(source.id, raw_items)
            logger.debug(
                "Raw events: %d new of %d fetched (source_id=%s)",
                new_count, len(raw_items), source.id,
            )

        # Load active AI provider once for the entire batch.
        # Priority: DB-configured active provider → ANTHROPIC_API_KEY env var → None
        ai_provider = await self._load_ai_provider()
        if ai_provider is None:
            logger.debug(
                "No AI provider configured — deterministic-only normalization (source_id=%s)",
                source.id,
            )

        valid_articles: list[dict] = []
        normalized_hashes: dict[str, str] = {}   # hash → normalizer label
        failed_hashes: list[str] = []

        for raw in raw_items:
            content_hash = compute_content_hash(source.id, raw)
            article, label = await self._normalize_one(raw, source.type, ai_provider)
            if article is not None:
                valid_articles.append(article)
                normalized_hashes[content_hash] = label
            else:
                failed_hashes.append(content_hash)

        # Single batch upsert — one DB round-trip regardless of article count.
        count = await self.article_repo.upsert_batch(valid_articles, source.id)

        # Best-effort: status update failure must not roll back written articles.
        if self.raw_repo:
            await self._update_raw_statuses(source.id, normalized_hashes, failed_hashes)

        logger.info(
            "Ingestion complete: %d written, %d failed validation — source_id=%s",
            count, len(failed_hashes), source.id,
        )
        return count

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_ai_provider(self) -> AIProvider | None:
        """Resolve the AI provider to use for this ingest run.

        Resolution order:
        1. DB-configured active provider (set via POST /ai-providers + activate)
        2. ANTHROPIC_API_KEY environment variable (backwards compat)
        3. None → deterministic normalization only
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
        """Fetch from the source and coerce every item to a plain Python dict.

        Coercion happens here so raw_repo.store_batch() gets clean dicts for JSONB.
        to_plain_dict() is idempotent — normalize() calling it again is a no-op.
        """
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

    async def _normalize_one(
        self,
        raw: dict,
        source_type: str,
        ai_provider: AIProvider | None,
    ) -> tuple[dict | None, str]:
        """Deterministic normalization first, then AI fallback if configured.

        Returns (normalized_dict, normalizer_label) on success.
        Returns (None, "") when all passes fail — caller discards the item.
        """
        # Deterministic pass
        try:
            data = normalize(raw)
            if validate(data).valid:
                return data, "deterministic"
            logger.debug("Deterministic output invalid — routing to AI fallback")
        except Exception as exc:
            logger.error("Deterministic normalization raised: %s", exc)

        # AI fallback
        if ai_provider is not None:
            try:
                ai_data = await ai_provider.normalize(raw, source_type)
                if ai_data is not None and validate(ai_data).valid:
                    return ai_data, ai_provider.model_id
                logger.warning(
                    "AI provider %s produced invalid output for source_type=%s",
                    ai_provider.model_id, source_type,
                )
            except Exception as exc:
                logger.error("AI provider %s raised: %s", ai_provider.model_id, exc)

        return None, ""

    async def _update_raw_statuses(
        self,
        source_id: int,
        normalized: dict[str, str],
        failed: list[str],
    ) -> None:
        try:
            if normalized:
                by_normalizer: dict[str, list[str]] = defaultdict(list)
                for h, label in normalized.items():
                    by_normalizer[label].append(h)
                await self.raw_repo.mark_normalized(source_id, dict(by_normalizer))
            if failed:
                await self.raw_repo.mark_failed(source_id, failed, "validation_failed")
        except Exception as exc:
            logger.warning(
                "Failed to update raw event statuses for source_id=%s: %s",
                source_id, exc,
            )
