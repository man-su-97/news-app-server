"""add_enrichment_fields

Revision ID: e1f2a3b4c567
Revises: d9e4f5a6b789
Create Date: 2026-02-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e1f2a3b4c567"
down_revision: Union[str, Sequence[str], None] = "d9e4f5a6b789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("category", sa.String(50), nullable=True))
    op.add_column("articles", sa.Column("sub_category", sa.String(50), nullable=True))
    op.add_column("articles", sa.Column("importance_score", sa.Integer(), nullable=True))
    op.create_index("ix_articles_category", "articles", ["category"])


def downgrade() -> None:
    op.drop_index("ix_articles_category", table_name="articles")
    op.drop_column("articles", "importance_score")
    op.drop_column("articles", "sub_category")
    op.drop_column("articles", "category")
