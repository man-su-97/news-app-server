import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw_event import RawIngestionEvent

logger = logging.getLogger(__name__)


def compute_content_hash(source_id: int, raw_payload: dict) -> str:
    """SHA-256(source_id + canonical JSON). Stable and collision-resistant dedup key."""
    payload_str = json.dumps(raw_payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{source_id}:{payload_str}".encode()).hexdigest()


class RawIngestionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def store_batch(self, source_id: int, raw_items: list[dict]) -> int:
        """Idempotent batch insert. ON CONFLICT DO NOTHING on content_hash.

        Returns the count of *new* events actually written (not previously seen).
        Duplicate payloads from the same source are silently skipped — this is the
        correct behavior for an idempotent ingestion pipeline.
        """
        if not raw_items:
            return 0

        rows = [
            {
                "source_id": source_id,
                "content_hash": compute_content_hash(source_id, item),
                "raw_payload": item,
                "status": "pending",
            }
            for item in raw_items
        ]

        stmt = (
            insert(RawIngestionEvent)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["content_hash"])
            .returning(RawIngestionEvent.id)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return len(result.fetchall())

    async def mark_normalized(
        self,
        source_id: int,
        hashes_by_normalizer: dict[str, list[str]],
    ) -> None:
        """Update status for successfully normalized events, grouped by normalizer label.

        hashes_by_normalizer: {"deterministic": [...], "ai:claude-haiku-...": [...]}
        Only transitions rows still in 'pending' status (safe to call multiple times).
        """
        for normalizer, hashes in hashes_by_normalizer.items():
            if not hashes:
                continue
            await self.db.execute(
                update(RawIngestionEvent)
                .where(
                    RawIngestionEvent.source_id == source_id,
                    RawIngestionEvent.content_hash.in_(hashes),
                    RawIngestionEvent.status == "pending",
                )
                .values(
                    status="normalized",
                    normalized_by=normalizer,
                    processed_at=datetime.now(timezone.utc),
                )
            )
        await self.db.commit()

    async def mark_failed(
        self, source_id: int, content_hashes: list[str], error: str
    ) -> None:
        """Increment retry_count and record error. Stops escalating after status='failed'."""
        if not content_hashes:
            return
        await self.db.execute(
            update(RawIngestionEvent)
            .where(
                RawIngestionEvent.source_id == source_id,
                RawIngestionEvent.content_hash.in_(content_hashes),
                RawIngestionEvent.status == "pending",
            )
            .values(
                status="failed",
                error_message=error,
                retry_count=RawIngestionEvent.retry_count + 1,
                processed_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()
