"""pipeline_enhancements

Expand-phase additions to the multi-stage AI pipeline schema.

Changes in this migration (all backward-compatible additions):

  filter_articles:
    + sub_category_ids  JSONB       — multi-label classification array (replaces single FK)
    + location_state_id INTEGER FK  — state FK resolved from AI location string

  post_processed_articles:
    + imp_score  INTEGER             — 1-100 importance score from post-processing AI

  NEW TABLE: final_articles
    — top-ranked articles selected by PublishingService for the public feed

Expand → migrate → contract strategy:
  - The old filter_articles.sub_category_id single FK is KEPT in this migration.
    It will be removed in a future cleanup migration once all consumers are updated.
  - All new columns are nullable, so the migration is zero-downtime safe.

Revision ID: j6k7l8m9n012
Revises: i5j6k7l8m901
Create Date: 2026-02-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "j6k7l8m9n012"
down_revision: Union[str, Sequence[str], None] = "i5j6k7l8m901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# UPGRADE
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. filter_articles — add multi-label sub_category_ids (JSONB)
    #
    #    Old design: single sub_category_id FK — only one crime type per article.
    #    New design: JSONB array of integer IDs — articles can span categories
    #    (e.g. a kidnapping-for-ransom spans Violent Crime + Financial Crime).
    #
    #    Default '[]' means "no categories assigned yet" (not null) so JSON
    #    containment queries (@>) work without null-checks.
    # -----------------------------------------------------------------------
    op.add_column(
        "filter_articles",
        sa.Column(
            "sub_category_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )

    # -----------------------------------------------------------------------
    # 2. filter_articles — add location_state_id FK → state table
    #
    #    Previously, location was only stored in post_processed_articles.
    #    Adding it to filter_articles allows the filter stage to record the
    #    location as soon as it's identified, even before post-processing.
    # -----------------------------------------------------------------------
    op.add_column(
        "filter_articles",
        sa.Column("location_state_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "filter_articles_location_state_id_fkey",
        "filter_articles",
        "state",
        ["location_state_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_filter_articles_location_state_id",
        "filter_articles",
        ["location_state_id"],
        unique=False,
    )

    # -----------------------------------------------------------------------
    # 3. post_processed_articles — add imp_score (1-100 importance score)
    #
    #    Old: importance_score was 1-10 from the single-pass AI.
    #    New: imp_score is 1-100 from the dedicated post-processing AI call,
    #    allowing finer ranking granularity for the PublishingService.
    #
    #    Nullable: rows already in the table remain valid, imp_score=NULL means
    #    "not yet scored" — PublishingService handles NULLs by treating them as 0.
    # -----------------------------------------------------------------------
    op.add_column(
        "post_processed_articles",
        sa.Column("imp_score", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_post_processed_articles_imp_score",
        "post_processed_articles",
        ["imp_score"],
        unique=False,
    )

    # -----------------------------------------------------------------------
    # 4. CREATE final_articles
    #
    #    Purpose: the PUBLIC news feed — top-ranked articles selected and
    #    published by PublishingService.
    #
    #    rank_score: a float computed from imp_score + time decay + category
    #    priority. Higher = shown first. Recalculated on each publishing cycle.
    #
    #    post_processed_article_id: unique, so each post-processed article
    #    appears at most once in the final feed. On re-publication (same article
    #    but updated rank_score), an upsert updates the existing row.
    # -----------------------------------------------------------------------
    op.create_table(
        "final_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_processed_article_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column(
            "reference_urls",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "rank_score",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["post_processed_article_id"],
            ["post_processed_articles.id"],
            ondelete="SET NULL",
            name="final_articles_post_processed_article_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "post_processed_article_id",
            name="uq_final_articles_post_processed_article_id",
        ),
    )
    op.create_index(
        "ix_final_articles_post_processed_article_id",
        "final_articles",
        ["post_processed_article_id"],
        unique=True,
    )
    op.create_index(
        "ix_final_articles_rank_score",
        "final_articles",
        ["rank_score"],
        unique=False,
        postgresql_using="btree",
    )
    op.create_index(
        op.f("ix_final_articles_title"),
        "final_articles",
        ["title"],
        unique=False,
    )


# ---------------------------------------------------------------------------
# DOWNGRADE
# Reverses every step in reverse order.
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Drop final_articles
    op.drop_index(op.f("ix_final_articles_title"), table_name="final_articles")
    op.drop_index("ix_final_articles_rank_score", table_name="final_articles")
    op.drop_index(
        "ix_final_articles_post_processed_article_id", table_name="final_articles"
    )
    op.drop_table("final_articles")

    # Drop imp_score from post_processed_articles
    op.drop_index(
        "ix_post_processed_articles_imp_score", table_name="post_processed_articles"
    )
    op.drop_column("post_processed_articles", "imp_score")

    # Drop location_state_id from filter_articles
    op.drop_index(
        "ix_filter_articles_location_state_id", table_name="filter_articles"
    )
    op.drop_constraint(
        "filter_articles_location_state_id_fkey",
        "filter_articles",
        type_="foreignkey",
    )
    op.drop_column("filter_articles", "location_state_id")

    # Drop sub_category_ids from filter_articles
    op.drop_column("filter_articles", "sub_category_ids")
