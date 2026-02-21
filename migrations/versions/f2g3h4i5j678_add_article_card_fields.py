"""add_article_card_fields

Adds summary, location, and region columns to the articles table.
These fields are populated by the LangGraph enrichment agent and are used
by the frontend to display news cards with location/region filtering.

Revision ID: f2g3h4i5j678
Revises: e1f2a3b4c567
Create Date: 2026-02-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2g3h4i5j678"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c567"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("articles", sa.Column("location", sa.String(200), nullable=True))
    op.add_column("articles", sa.Column("region", sa.String(100), nullable=True))
    op.create_index("ix_articles_region", "articles", ["region"])


def downgrade() -> None:
    op.drop_index("ix_articles_region", table_name="articles")
    op.drop_column("articles", "region")
    op.drop_column("articles", "location")
    op.drop_column("articles", "summary")
