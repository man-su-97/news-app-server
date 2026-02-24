"""
app/repositories/raw_ingestion_repo.py — Raw Ingestion DB Operations
=====================================================================
All database operations for the "raw_ingestion" table.

Two responsibilities:
  1. Deduplication: store_batch() uses content_hash to skip already-seen payloads.
  2. Status tracking: mark_filtered/mark_processed/mark_failed update each row's
     lifecycle state so you always know where in the pipeline each payload is.

Status lifecycle:
  pending → filtered (survived AI crime filter; filter_articles row created)
  pending → filtered_out (AI determined not crime)
  pending → failed (processing error)
  filtered → processed (post_processed_articles row created)

Class renamed from RawIngestionEvent → RawIngestion to match the renamed table/model.
store_batch() now returns {content_hash: row_id} so callers can link filter_articles.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw_event import RawIngestion

logger = logging.getLogger(__name__)


def compute_content_hash(source_id: int, raw_payload: dict) -> str:
    """SHA-256 hex of (source_id + sorted JSON payload).

    sort_keys=True makes this deterministic regardless of key ordering.
    Prepending source_id ensures the same article from two sources hashes differently.
    """
    payload_str = json.dumps(raw_payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{source_id}:{payload_str}".encode()).hexdigest()


class RawIngestionRepository:
    """Handles all database operations for the raw_ingestion table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def store_batch(
        self, source_id: int, raw_items: list[dict]
    ) -> dict[str, int]:
        """Persist raw payloads before processing. Silently skips duplicates.

        Returns {content_hash: raw_ingestion_id} for ALL items — both newly
        inserted rows AND already-existing rows (via SELECT after INSERT).
        This lets the ingestion service link filter_articles.raw_ingestion_id
        without an extra round-trip for each article.

        ON CONFLICT DO NOTHING: duplicate content_hash rows are skipped.
        The subsequent SELECT retrieves IDs for all hashes (old and new).
        """
        if not raw_items:
            return {}

        rows = [
            {
                "source_id": source_id,
                "content_hash": compute_content_hash(source_id, item),
                "raw_payload": item,
                "status": "pending",
            }
            for item in raw_items
        ]
        hashes = [r["content_hash"] for r in rows]

        # INSERT — skip duplicates silently
        stmt = (
            insert(RawIngestion)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["content_hash"])
        )
        await self.db.execute(stmt)
        await self.db.commit()

        # SELECT ids for ALL hashes (new + pre-existing) so the caller can
        # link filter_articles.raw_ingestion_id without extra queries.
        result = await self.db.execute(
            select(RawIngestion.content_hash, RawIngestion.id).where(
                RawIngestion.content_hash.in_(hashes)
            )
        )
        return {row.content_hash: row.id for row in result.all()}

    async def mark_filtered(
        self,
        source_id: int,
        hashes_by_normalizer: dict[str, list[str]],
    ) -> None:
        """Set status='filtered' for articles that passed the AI crime filter.

        Groups hashes by normalizer label so we can record which AI model
        processed each article (stored in normalized_by column).
        """
        for normalizer, hashes in hashes_by_normalizer.items():
            if not hashes:
                continue
            await self.db.execute(
                update(RawIngestion)
                .where(
                    RawIngestion.source_id == source_id,
                    RawIngestion.content_hash.in_(hashes),
                    RawIngestion.status == "pending",
                )
                .values(
                    status="filtered",
                    normalized_by=normalizer,
                    processed_at=datetime.now(timezone.utc),
                )
            )
        await self.db.commit()

    async def mark_filtered_out(
        self,
        source_id: int,
        content_hashes: list[str],
        normalizer: str,
    ) -> None:
        """Set status='filtered_out' for non-crime articles the AI rejected."""
        if not content_hashes:
            return
        await self.db.execute(
            update(RawIngestion)
            .where(
                RawIngestion.source_id == source_id,
                RawIngestion.content_hash.in_(content_hashes),
                RawIngestion.status == "pending",
            )
            .values(
                status="filtered_out",
                normalized_by=normalizer,
                processed_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()

    async def mark_failed(
        self, source_id: int, content_hashes: list[str], error: str
    ) -> None:
        """Set status='failed' and increment retry_count for errored articles."""
        if not content_hashes:
            return
        await self.db.execute(
            update(RawIngestion)
            .where(
                RawIngestion.source_id == source_id,
                RawIngestion.content_hash.in_(content_hashes),
                RawIngestion.status == "pending",
            )
            .values(
                status="failed",
                error_message=error,
                retry_count=RawIngestion.retry_count + 1,
                processed_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()

    async def get_all(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        source_id: int | None = None,
    ) -> list[RawIngestion]:
        """Paginated list ordered by created_at descending. Optionally filter by status or source."""
        from sqlalchemy import select
        stmt = select(RawIngestion).order_by(RawIngestion.created_at.desc())
        if status:
            stmt = stmt.where(RawIngestion.status == status)
        if source_id is not None:
            stmt = stmt.where(RawIngestion.source_id == source_id)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, row_id: int) -> RawIngestion | None:
        from sqlalchemy import select
        result = await self.db.execute(
            select(RawIngestion).where(RawIngestion.id == row_id)
        )
        return result.scalar_one_or_none()

    async def count(self, status: str | None = None, source_id: int | None = None) -> int:
        from sqlalchemy import func, select
        stmt = select(func.count()).select_from(RawIngestion)
        if status:
            stmt = stmt.where(RawIngestion.status == status)
        if source_id is not None:
            stmt = stmt.where(RawIngestion.source_id == source_id)
        result = await self.db.execute(stmt)
        return result.scalar_one()

    # Kept for backwards compat — delegates to mark_filtered
    async def mark_normalized(
        self,
        source_id: int,
        hashes_by_normalizer: dict[str, list[str]],
    ) -> None:
        """Alias for mark_filtered — used by legacy callers."""
        await self.mark_filtered(source_id, hashes_by_normalizer)
