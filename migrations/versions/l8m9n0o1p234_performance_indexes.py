"""performance_indexes

Adds indexes that significantly speed up the most common query patterns:

  1. GIN index on filtered_articles.sub_category_ids
     The @> containment operator (used for category filtering) does a full
     table scan without a GIN index. GIN turns it into an O(log n) lookup.
     Pattern: "show me all fraud + cybercrime articles"

  2. GIN index on filtered_articles.category_ids
     Same reasoning — parent category filtering also uses @> containment.
     Pattern: "show me all Financial Crime articles"

  3. B-tree index on raw_ingestion.status
     The scheduler and admin endpoints frequently query
     "WHERE status = 'pending'" or "WHERE status = 'failed'".
     Without an index this is a sequential scan on the growing inbox table.

  4. Partial index on post_processed_articles.imp_score (NOT NULL only)
     PublishingService always queries "ORDER BY imp_score DESC WHERE imp_score IS NOT NULL".
     The partial index excludes the un-scored rows, making the publishing query
     much tighter on large tables.

All are additive — zero-downtime safe.

Revision ID: l8m9n0o1p234
Revises: k7l8m9n0o123
Create Date: 2026-02-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "l8m9n0o1p234"
down_revision: Union[str, Sequence[str], None] = "k7l8m9n0o123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. GIN index on filtered_articles.sub_category_ids
    #    Accelerates: sub_category_ids @> '[2]'  (containment filter)
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_filtered_articles_sub_category_ids_gin",
        "filtered_articles",
        ["sub_category_ids"],
        unique=False,
        postgresql_using="gin",
    )

    # -----------------------------------------------------------------------
    # 2. GIN index on filtered_articles.category_ids
    #    Accelerates: category_ids @> '[1]'  (parent category filter)
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_filtered_articles_category_ids_gin",
        "filtered_articles",
        ["category_ids"],
        unique=False,
        postgresql_using="gin",
    )

    # -----------------------------------------------------------------------
    # 3. B-tree index on raw_ingestion.status
    #    Accelerates: WHERE status = 'pending' / 'failed' / 'filtered_out'
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_raw_ingestion_status",
        "raw_ingestion",
        ["status"],
        unique=False,
    )

    # -----------------------------------------------------------------------
    # 4. Partial index on post_processed_articles.imp_score (scored rows only)
    #    Accelerates: ORDER BY imp_score DESC WHERE imp_score IS NOT NULL
    #    Ignores un-scored rows (imp_score IS NULL) to keep the index small.
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_post_processed_articles_imp_score_scored",
        "post_processed_articles",
        ["imp_score"],
        unique=False,
        postgresql_where=sa.text("imp_score IS NOT NULL"),
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_post_processed_articles_imp_score_scored",
        table_name="post_processed_articles",
    )
    op.drop_index("ix_raw_ingestion_status", table_name="raw_ingestion")
    op.drop_index(
        "ix_filtered_articles_category_ids_gin", table_name="filtered_articles"
    )
    op.drop_index(
        "ix_filtered_articles_sub_category_ids_gin", table_name="filtered_articles"
    )
