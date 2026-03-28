"""filtered_articles_cleanup

Three cleanup changes to the filter stage schema:

  1. RENAME filter_articles → filtered_articles
     More descriptive name: the table stores articles that have BEEN filtered
     (crime-relevant), not articles yet to be filtered.

  2. DROP category_id (singular FK to master_category)
     An intermediate migration added this orphaned column before the design
     settled on category_ids (plural JSONB array, added below).
     The column has been writing NULL since it was added — safe to drop.

  3. ADD category_ids JSONB
     Parent-level category IDs derived from sub_category_ids.
     e.g. sub_category_ids=[1,3] (Murder+Terrorism) → category_ids=[1,2]
     Populated by CategoryResolver.resolve_categories_from_ids() in
     IngestionService. Default '[]' keeps @> containment queries null-safe.

PostgreSQL note on the rename:
  FKs referencing filter_articles (i.e. post_processed_articles.filter_article_id)
  are tracked internally by OID — they continue to work without being dropped
  and recreated. The constraint definition will automatically show the new name.

Revision ID: k7l8m9n0o123
Revises: j6k7l8m9n012
Create Date: 2026-02-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "k7l8m9n0o123"
down_revision: Union[str, Sequence[str], None] = "j6k7l8m9n012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# UPGRADE
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Drop the orphaned category_id (singular FK) from filter_articles.
    #    This column was added by an intermediate migration that has since been
    #    superseded by category_ids (plural JSONB array added below).
    #    Order: drop index first, then FK constraint, then the column.
    # -----------------------------------------------------------------------
    op.drop_index("ix_filter_articles_category_id", table_name="filter_articles")
    op.drop_constraint(
        "filter_articles_category_id_fkey",
        "filter_articles",
        type_="foreignkey",
    )
    op.drop_column("filter_articles", "category_id")

    # -----------------------------------------------------------------------
    # 2. Rename the table.
    #    PostgreSQL tracks FK references (post_processed_articles → filter_articles)
    #    by internal OID, so no need to drop/recreate those constraints.
    # -----------------------------------------------------------------------
    op.rename_table("filter_articles", "filtered_articles")

    # -----------------------------------------------------------------------
    # 3. Add category_ids JSONB column.
    #    Stores the parent master_category IDs derived from sub_category_ids.
    #    Default '[]' (not NULL) so @> containment queries work without null-checks.
    # -----------------------------------------------------------------------
    op.add_column(
        "filtered_articles",
        sa.Column(
            "category_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


# ---------------------------------------------------------------------------
# DOWNGRADE
# Reverses every step in reverse order.
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Drop category_ids
    op.drop_column("filtered_articles", "category_ids")

    # Rename back
    op.rename_table("filtered_articles", "filter_articles")

    # Restore category_id column + FK + index (orphaned column from intermediate migration)
    op.add_column(
        "filter_articles",
        sa.Column("category_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "filter_articles_category_id_fkey",
        "filter_articles",
        "master_category",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_filter_articles_category_id",
        "filter_articles",
        ["category_id"],
        unique=False,
    )
