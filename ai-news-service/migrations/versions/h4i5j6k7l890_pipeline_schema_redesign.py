"""pipeline_schema_redesign

Major schema overhaul implementing the multi-stage AI processing pipeline.

Changes (in upgrade order):
  RENAME:   sources              → news_sources
  RENAME:   raw_ingestion_events → raw_ingestion
  DROP:     articles             (replaced by two-stage pipeline tables)
  CREATE:   master_category
  CREATE:   master_sub_category  (FK → master_category)
  CREATE:   country
  CREATE:   state                (FK → country)
  CREATE:   filter_articles      (FK → raw_ingestion, master_sub_category)
  CREATE:   post_processed_articles (FK → filter_articles, master_sub_category, state)

DATA LOSS WARNING:
  - The `articles` table is DROPPED PERMANENTLY.
  - All existing article rows will be lost.
  - Take a pg_dump backup before running this migration in production.

Revision ID: h4i5j6k7l890
Revises: g3h4i5j6k789
Create Date: 2026-02-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h4i5j6k7l890"
down_revision: Union[str, Sequence[str], None] = "g3h4i5j6k789"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# UPGRADE
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Drop the articles table (and all its indexes / FKs) first.
    #    It references sources.id via FK — must be dropped before renaming sources.
    # -----------------------------------------------------------------------
    op.drop_index("ix_articles_region", table_name="articles")
    op.drop_index("ix_articles_category", table_name="articles")
    op.drop_index(op.f("ix_articles_url"), table_name="articles")
    op.drop_index(op.f("ix_articles_title"), table_name="articles")
    op.drop_index(op.f("ix_articles_source_id"), table_name="articles")
    op.drop_index(op.f("ix_articles_published_at"), table_name="articles")
    op.drop_table("articles")

    # -----------------------------------------------------------------------
    # 2. Drop the FK on raw_ingestion_events → sources BEFORE renaming either.
    #    PostgreSQL renames don't automatically update FK references in other tables.
    # -----------------------------------------------------------------------
    op.drop_index(
        "ix_raw_ingestion_events_pending",
        table_name="raw_ingestion_events",
    )
    op.drop_index(
        op.f("ix_raw_ingestion_events_source_id"),
        table_name="raw_ingestion_events",
    )
    op.drop_constraint(
        "raw_ingestion_events_source_id_fkey",
        "raw_ingestion_events",
        type_="foreignkey",
    )

    # -----------------------------------------------------------------------
    # 3. Rename sources → news_sources
    # -----------------------------------------------------------------------
    op.rename_table("sources", "news_sources")

    # -----------------------------------------------------------------------
    # 4. Rename raw_ingestion_events → raw_ingestion
    # -----------------------------------------------------------------------
    op.rename_table("raw_ingestion_events", "raw_ingestion")

    # Restore the index names under the new table name
    op.create_index(
        "ix_raw_ingestion_source_id",
        "raw_ingestion",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_raw_ingestion_pending",
        "raw_ingestion",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # Restore the FK from raw_ingestion → news_sources (new table name)
    op.create_foreign_key(
        "raw_ingestion_source_id_fkey",
        "raw_ingestion",
        "news_sources",
        ["source_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Also rename the unique constraint on content_hash so it has a tidy name
    op.execute(
        "ALTER TABLE raw_ingestion "
        "RENAME CONSTRAINT raw_ingestion_events_content_hash_key "
        "TO raw_ingestion_content_hash_key"
    )

    # -----------------------------------------------------------------------
    # 5. Create reference / taxonomy tables
    #    Order matters: sub-tables must be created after their parent tables.
    # -----------------------------------------------------------------------

    # master_category --------------------------------------------------------
    op.create_table(
        "master_category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority_point", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # master_sub_category ----------------------------------------------------
    op.create_table(
        "master_sub_category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority_point", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["master_category.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_master_sub_category_category_id",
        "master_sub_category",
        ["category_id"],
        unique=False,
    )

    # country ----------------------------------------------------------------
    op.create_table(
        "country",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # state ------------------------------------------------------------------
    op.create_table(
        "state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("country_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(
            ["country_id"], ["country.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_state_country_id",
        "state",
        ["country_id"],
        unique=False,
    )

    # -----------------------------------------------------------------------
    # 6. Create pipeline article tables
    #    filter_articles must exist before post_processed_articles references it.
    # -----------------------------------------------------------------------

    # filter_articles --------------------------------------------------------
    op.create_table(
        "filter_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_ingestion_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("main_url", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sub_category_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["raw_ingestion_id"],
            ["raw_ingestion.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sub_category_id"],
            ["master_sub_category.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_ingestion_id"),   # one-to-one with raw_ingestion
        sa.UniqueConstraint("main_url"),
    )
    op.create_index(
        op.f("ix_filter_articles_title"),
        "filter_articles",
        ["title"],
        unique=False,
    )
    op.create_index(
        op.f("ix_filter_articles_main_url"),
        "filter_articles",
        ["main_url"],
        unique=True,
    )
    op.create_index(
        op.f("ix_filter_articles_published_at"),
        "filter_articles",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        "ix_filter_articles_sub_category_id",
        "filter_articles",
        ["sub_category_id"],
        unique=False,
    )
    op.create_index(
        "ix_filter_articles_raw_ingestion_id",
        "filter_articles",
        ["raw_ingestion_id"],
        unique=True,
    )

    # post_processed_articles ------------------------------------------------
    op.create_table(
        "post_processed_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filter_article_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column(
            "reference_urls",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sub_category_id", sa.Integer(), nullable=True),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["filter_article_id"],
            ["filter_articles.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sub_category_id"],
            ["master_sub_category.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["state.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("filter_article_id"),   # one-to-one with filter_articles
    )
    op.create_index(
        op.f("ix_post_processed_articles_title"),
        "post_processed_articles",
        ["title"],
        unique=False,
    )
    op.create_index(
        op.f("ix_post_processed_articles_published_at"),
        "post_processed_articles",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        "ix_post_processed_articles_sub_category_id",
        "post_processed_articles",
        ["sub_category_id"],
        unique=False,
    )
    op.create_index(
        "ix_post_processed_articles_location_id",
        "post_processed_articles",
        ["location_id"],
        unique=False,
    )
    op.create_index(
        "ix_post_processed_articles_filter_article_id",
        "post_processed_articles",
        ["filter_article_id"],
        unique=True,
    )


# ---------------------------------------------------------------------------
# DOWNGRADE
# Reverses every step in exactly the reverse order of upgrade().
# NOTE: article data lost during upgrade() cannot be recovered from downgrade().
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Drop new pipeline tables (reverse creation order)
    op.drop_index(
        "ix_post_processed_articles_filter_article_id",
        table_name="post_processed_articles",
    )
    op.drop_index(
        "ix_post_processed_articles_location_id",
        table_name="post_processed_articles",
    )
    op.drop_index(
        "ix_post_processed_articles_sub_category_id",
        table_name="post_processed_articles",
    )
    op.drop_index(
        op.f("ix_post_processed_articles_published_at"),
        table_name="post_processed_articles",
    )
    op.drop_index(
        op.f("ix_post_processed_articles_title"),
        table_name="post_processed_articles",
    )
    op.drop_table("post_processed_articles")

    op.drop_index(
        "ix_filter_articles_raw_ingestion_id", table_name="filter_articles"
    )
    op.drop_index(
        "ix_filter_articles_sub_category_id", table_name="filter_articles"
    )
    op.drop_index(
        op.f("ix_filter_articles_published_at"), table_name="filter_articles"
    )
    op.drop_index(
        op.f("ix_filter_articles_main_url"), table_name="filter_articles"
    )
    op.drop_index(
        op.f("ix_filter_articles_title"), table_name="filter_articles"
    )
    op.drop_table("filter_articles")

    op.drop_index("ix_state_country_id", table_name="state")
    op.drop_table("state")
    op.drop_table("country")

    op.drop_index(
        "ix_master_sub_category_category_id", table_name="master_sub_category"
    )
    op.drop_table("master_sub_category")
    op.drop_table("master_category")

    # Restore raw_ingestion → raw_ingestion_events
    op.drop_constraint(
        "raw_ingestion_source_id_fkey", "raw_ingestion", type_="foreignkey"
    )
    op.execute(
        "ALTER TABLE raw_ingestion "
        "RENAME CONSTRAINT raw_ingestion_content_hash_key "
        "TO raw_ingestion_events_content_hash_key"
    )
    op.drop_index("ix_raw_ingestion_pending", table_name="raw_ingestion")
    op.drop_index("ix_raw_ingestion_source_id", table_name="raw_ingestion")

    op.rename_table("raw_ingestion", "raw_ingestion_events")
    op.rename_table("news_sources", "sources")

    op.create_index(
        op.f("ix_raw_ingestion_events_source_id"),
        "raw_ingestion_events",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_raw_ingestion_events_pending",
        "raw_ingestion_events",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_foreign_key(
        "raw_ingestion_events_source_id_fkey",
        "raw_ingestion_events",
        "sources",
        ["source_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Recreate articles table (empty — data is permanently lost)
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("sub_category", sa.String(50), nullable=True),
        sa.Column("importance_score", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_articles_published_at"), "articles", ["published_at"])
    op.create_index(op.f("ix_articles_source_id"), "articles", ["source_id"])
    op.create_index(op.f("ix_articles_title"), "articles", ["title"])
    op.create_index(op.f("ix_articles_url"), "articles", ["url"], unique=True)
    op.create_index("ix_articles_category", "articles", ["category"])
    op.create_index("ix_articles_region", "articles", ["region"])
