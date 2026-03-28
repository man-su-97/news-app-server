"""widen_normalized_by

Increases the normalized_by column in raw_ingestion_events from VARCHAR(50) to
VARCHAR(200). The new Gemini OpenAI-compatible model ID strings like
"ai:generativelanguage.googleapis.com:gemini-2.5-flash" exceed 50 characters.

Revision ID: g3h4i5j6k789
Revises: f2g3h4i5j678
Create Date: 2026-02-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "g3h4i5j6k789"
down_revision = "f2g3h4i5j678"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "raw_ingestion_events",
        "normalized_by",
        type_=sa.String(200),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "raw_ingestion_events",
        "normalized_by",
        type_=sa.String(50),
        existing_nullable=True,
    )
