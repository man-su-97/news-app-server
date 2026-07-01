"""article_chunks + pgvector

Revision ID: a1b2c3d4e5f6
Revises: 29df1b34a087
Create Date: 2026-07-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "29df1b34a087"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    # pgvector extension (the pgvector/pgvector image ships the shared library).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "article_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_id", "chunk_index", name="uq_article_chunk_index"
        ),
    )
    op.create_index(
        op.f("ix_article_chunks_article_id"),
        "article_chunks",
        ["article_id"],
        unique=False,
    )
    # HNSW index for approximate-nearest-neighbour cosine search. No training
    # step (unlike IVFFlat) and handles incremental inserts well.
    op.execute(
        "CREATE INDEX ix_article_chunks_embedding_hnsw "
        "ON article_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_article_chunks_embedding_hnsw", table_name="article_chunks")
    op.drop_index(
        op.f("ix_article_chunks_article_id"), table_name="article_chunks"
    )
    op.drop_table("article_chunks")
