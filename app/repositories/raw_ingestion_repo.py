"""
app/repositories/raw_ingestion_repo.py — Raw Ingestion Events DB Operations
============================================================================
All database operations for the "raw_ingestion_events" table.

This repository serves two purposes:
  1. Deduplication: store_batch() uses content_hash to silently ignore articles
     we've already seen, even across multiple fetches from the same source.
  2. Audit trail: mark_normalized() and mark_failed() track which articles
     were processed successfully and which failed, and by which normalizer.

The raw event lifecycle:
  1. fetch() → store_batch() → status="pending"
  2. normalization succeeds → mark_normalized() → status="normalized"
  3. normalization fails → mark_failed() → status="failed"
"""

import hashlib      # For SHA-256 hashing
import json         # For serializing the payload to a string before hashing
import logging
from collections import defaultdict     # dict that creates missing keys automatically
from datetime import datetime, timezone  # For timestamps

from sqlalchemy import update                         # For UPDATE statements
from sqlalchemy.dialects.postgresql import insert     # PostgreSQL upsert insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw_event import RawIngestionEvent

logger = logging.getLogger(__name__)


def compute_content_hash(source_id: int, raw_payload: dict) -> str:
    """Generate a SHA-256 hash that uniquely identifies this (source, payload) pair.

    How it works:
      1. sort_keys=True ensures the JSON is always in the same order,
         even if the source delivers keys in different order each time.
      2. default=str handles non-JSON-serializable types (like datetime objects)
         by converting them to strings.
      3. Prepend source_id so the same article from two different sources
         produces different hashes (they're separate events).
      4. SHA-256 produces a 64-character hex string that is effectively unique.

    This hash is the deduplication key — if we see the same payload from the
    same source twice, the hash will be identical and the second insert is ignored.
    """
    # Canonicalize the JSON: sort keys so order doesn't matter
    payload_str = json.dumps(raw_payload, sort_keys=True, default=str)
    # Hash: "source_id:{"key": "value", ...}"
    return hashlib.sha256(f"{source_id}:{payload_str}".encode()).hexdigest()


class RawIngestionRepository:
    """Handles all database operations for the raw_ingestion_events table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def store_batch(self, source_id: int, raw_items: list[dict]) -> int:
        """Save raw payloads to the DB before normalization. Silently skips duplicates.

        Architecture decision: "store first, process second" (dual-write pattern).
        We persist every raw payload before trying to normalize it.
        This means if normalization crashes halfway through, the raw data is safe
        and can be reprocessed without re-fetching from the source.

        ON CONFLICT DO NOTHING: if the content_hash already exists in the table,
        silently skip that row. This makes the entire operation idempotent —
        safe to call multiple times with the same data.

        Returns the count of NEW rows inserted (not counting skipped duplicates).
        """
        if not raw_items:
            return 0

        # Build insert rows: compute hash for each item
        rows = [
            {
                "source_id": source_id,
                "content_hash": compute_content_hash(source_id, item),  # dedup key
                "raw_payload": item,       # the full raw data — never modify this
                "status": "pending",       # waiting for normalization
            }
            for item in raw_items
        ]

        # INSERT INTO raw_ingestion_events (...) VALUES (...) ON CONFLICT DO NOTHING
        stmt = (
            insert(RawIngestionEvent)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["content_hash"])  # skip duplicates
            .returning(RawIngestionEvent.id)  # get IDs of newly inserted rows only
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        # len() of returned IDs = number of NEW rows (not the skipped duplicates)
        return len(result.fetchall())

    async def mark_normalized(
        self,
        source_id: int,
        hashes_by_normalizer: dict[str, list[str]],
    ) -> None:
        """Update status to "normalized" for successfully processed events.

        hashes_by_normalizer groups hashes by which normalizer processed them:
          {
            "deterministic": ["abc123...", "def456..."],
            "ai:gemini_langgraph:gemini-2.0-flash": ["ghi789..."]
          }

        We record WHICH normalizer was used (normalized_by) so we can analyze
        later what percentage of articles needed AI assistance.

        .where(status == "pending") is a safety guard: if called twice with
        the same hashes, the second call is a no-op (already "normalized").
        """
        for normalizer, hashes in hashes_by_normalizer.items():
            if not hashes:
                continue   # skip empty lists

            # UPDATE raw_ingestion_events
            # SET status='normalized', normalized_by=..., processed_at=NOW()
            # WHERE source_id=... AND content_hash IN (...) AND status='pending'
            await self.db.execute(
                update(RawIngestionEvent)
                .where(
                    RawIngestionEvent.source_id == source_id,
                    RawIngestionEvent.content_hash.in_(hashes),  # SQL IN (...) clause
                    RawIngestionEvent.status == "pending",        # safety: only pending rows
                )
                .values(
                    status="normalized",
                    normalized_by=normalizer,    # which AI/rule processed it
                    processed_at=datetime.now(timezone.utc),  # exact time of processing
                )
            )
        await self.db.commit()  # one commit for all the updates

    async def mark_failed(
        self, source_id: int, content_hashes: list[str], error: str
    ) -> None:
        """Record normalization failure for a batch of events.

        Increments retry_count so we track how many times we've attempted
        this article. Sets status="failed" to prevent re-processing.

        RawIngestionEvent.retry_count + 1 is a server-side increment —
        safer than Python-side (no race condition if two workers run at once).
        """
        if not content_hashes:
            return

        await self.db.execute(
            update(RawIngestionEvent)
            .where(
                RawIngestionEvent.source_id == source_id,
                RawIngestionEvent.content_hash.in_(content_hashes),
                RawIngestionEvent.status == "pending",  # only update pending rows
            )
            .values(
                status="failed",
                error_message=error,                            # why it failed
                retry_count=RawIngestionEvent.retry_count + 1, # increment in DB
                processed_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()
