"""add_ai_provider_configs

Revision ID: d9e4f5a6b789
Revises: c8f2a1e3b456
Create Date: 2026-02-20 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d9e4f5a6b789"
down_revision: Union[str, Sequence[str], None] = "c8f2a1e3b456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("api_key", sa.String(length=500), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Partial unique index: at most one active row at all times.
    # The application activate() method enforces this, but the index gives
    # a DB-level guarantee and enables efficient get_active() lookups.
    op.create_index(
        "ix_ai_provider_configs_single_active",
        "ai_provider_configs",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_provider_configs_single_active",
        table_name="ai_provider_configs",
    )
    op.drop_table("ai_provider_configs")
