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
    payload_str = json.dumps(raw_payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{source_id}:{payload_str}".encode()).hexdigest()


class RawIngestionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def store_batch(
        self,
        source_id: int,
        hash_raw_pairs: list[tuple[str, dict]],
    ) -> tuple[dict[str, int], set[str]]:
        """Persist raw payloads, skipping duplicates.

        Accepts pre-computed (content_hash, raw_payload) pairs so the caller
        computes hashes only once.

        Returns:
          hash_to_raw_id — {content_hash: raw_ingestion_id} for all items
          unprocessed_hashes — newly inserted hashes PLUS any pre-existing rows
                               still in 'pending' status (crash-recovery: lets
                               the pipeline retry articles that were stored but
                               never completed in a previous run)
        """
        if not hash_raw_pairs:
            return {}, set()

        hashes = [ch for ch, _ in hash_raw_pairs]
        rows = [
            {
                "source_id": source_id,
                "content_hash": ch,
                "raw_payload": raw,
                "status": "pending",
            }
            for ch, raw in hash_raw_pairs
        ]

        stmt = (
            insert(RawIngestion)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["content_hash"])
            .returning(RawIngestion.content_hash)
        )
        insert_result = await self.db.execute(stmt)
        new_hashes: set[str] = {row[0] for row in insert_result.all()}
        await self.db.commit()

        # Include pre-existing pending rows so a crashed previous run can be retried.
        # Without this, articles stored-but-not-processed in a prior run stay pending
        # forever because ON CONFLICT DO NOTHING excludes them from new_hashes.
        pending_result = await self.db.execute(
            select(RawIngestion.content_hash).where(
                RawIngestion.content_hash.in_(hashes),
                RawIngestion.status == "pending",
            )
        )
        unprocessed_hashes = new_hashes | {row[0] for row in pending_result.all()}

        select_result = await self.db.execute(
            select(RawIngestion.content_hash, RawIngestion.id).where(
                RawIngestion.content_hash.in_(hashes)
            )
        )
        hash_to_raw_id = {row.content_hash: row.id for row in select_result.all()}
        return hash_to_raw_id, unprocessed_hashes

    async def mark_filtered(
        self,
        source_id: int,
        hashes_by_normalizer: dict[str, list[str]],
    ) -> None:
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

    async def mark_normalized(
        self,
        source_id: int,
        hashes_by_normalizer: dict[str, list[str]],
    ) -> None:
        await self.mark_filtered(source_id, hashes_by_normalizer)
