"""add_raw_ingestion_events

Revision ID: c8f2a1e3b456
Revises: 29df1b34a087
Create Date: 2026-02-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c8f2a1e3b456"
down_revision: Union[str, Sequence[str], None] = "29df1b34a087"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "raw_ingestion_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("normalized_by", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "retry_count",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash"),
    )
    op.create_index(
        op.f("ix_raw_ingestion_events_source_id"),
        "raw_ingestion_events",
        ["source_id"],
        unique=False,
    )
    # Partial index: only index rows still awaiting processing — keeps it tiny
    op.create_index(
        "ix_raw_ingestion_events_pending",
        "raw_ingestion_events",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_raw_ingestion_events_pending", table_name="raw_ingestion_events")
    op.drop_index(
        op.f("ix_raw_ingestion_events_source_id"),
        table_name="raw_ingestion_events",
    )
    op.drop_table("raw_ingestion_events")
