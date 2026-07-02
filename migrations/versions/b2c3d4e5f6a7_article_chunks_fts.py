"""article_chunks full-text search (content_tsv + GIN)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Generated-stored tsvector: always consistent with `content`, no app-side
    # maintenance, survives re-indexing. Powers the lexical arm of hybrid search.
    op.add_column(
        "article_chunks",
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=False,
        ),
    )
    # GIN index for full-text `@@` matching.
    op.create_index(
        "ix_article_chunks_content_tsv",
        "article_chunks",
        ["content_tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_article_chunks_content_tsv", table_name="article_chunks")
    op.drop_column("article_chunks", "content_tsv")
