"""seed_master_data

Populates reference/lookup tables with initial data:

  master_category      — 8 top-level crime category types
  master_sub_category  — 10 sub-categories aligned to AI output strings
  country              — India + 9 other countries frequently in Indian crime news
  state                — 36 Indian states and union territories

AI sub_category string → master_sub_category.name mapping:
  murder       → Murder       (Violent Crime)
  violence     → Violence     (Violent Crime)
  trafficking  → Human Trafficking  (Sexual Crime)
  terrorism    → Terrorism    (Terrorism)
  fraud        → Fraud        (Financial Crime)
  corruption   → Corruption   (Financial Crime)
  cybercrime   → Cybercrime   (Cyber Crime)
  drugs        → Drug Trafficking   (Drug Crime)
  theft        → Theft        (Property Crime)
  other        → Other        (Other)

Downgrade removes all seeded rows (identified by name).

Revision ID: i5j6k7l8m901
Revises: h4i5j6k7l890
Create Date: 2026-02-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i5j6k7l8m901"
down_revision: Union[str, Sequence[str], None] = "h4i5j6k7l890"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # master_category — 8 top-level categories, ordered by priority_point
    # (lower number = shown first in UI; higher severity = lower number)
    # -----------------------------------------------------------------------
    op.execute(sa.text("""
        INSERT INTO master_category (id, name, description, priority_point, is_active, created_at)
        VALUES
          (1, 'Violent Crime',   'Crimes involving physical harm or threat to persons', 1, true, now()),
          (2, 'Terrorism',       'Acts of terrorism and extremist violence',             2, true, now()),
          (3, 'Financial Crime', 'Fraud, corruption, and money-related offences',        3, true, now()),
          (4, 'Cyber Crime',     'Crimes committed via digital networks or devices',     4, true, now()),
          (5, 'Drug Crime',      'Trafficking, possession, and distribution of narcotics',5, true, now()),
          (6, 'Property Crime',  'Theft, burglary, arson, and damage to property',       6, true, now()),
          (7, 'Sexual Crime',    'Sexual assault, trafficking, and exploitation',         7, true, now()),
          (8, 'Other',           'Crimes that do not fit the above categories',           8, true, now())
        ON CONFLICT (name) DO NOTHING
    """))

    # -----------------------------------------------------------------------
    # master_sub_category — one row per AI output value (plus extras)
    # The 'name' field is what the CategoryResolver matches against the AI string.
    # Mapping: ai_string.title() == name  (except special cases below)
    # Special cases stored in CategoryResolver._AI_SUBCATEGORY_MAP.
    # -----------------------------------------------------------------------
    op.execute(sa.text("""
        INSERT INTO master_sub_category (id, category_id, name, description, priority_point, is_active, created_at)
        VALUES
          -- Violent Crime (category 1)
          (1,  1, 'Murder',            'Intentional killing of a person',                        1, true, now()),
          (2,  1, 'Violence',          'Physical assault, battery, and non-lethal violence',      2, true, now()),
          -- Terrorism (category 2)
          (3,  2, 'Terrorism',         'Terrorist attacks and extremist activities',               1, true, now()),
          -- Financial Crime (category 3)
          (4,  3, 'Fraud',             'Deception for financial gain',                            1, true, now()),
          (5,  3, 'Corruption',        'Bribery, embezzlement, and abuse of public office',       2, true, now()),
          -- Cyber Crime (category 4)
          (6,  4, 'Cybercrime',        'Hacking, phishing, online scams, and data breaches',      1, true, now()),
          -- Drug Crime (category 5)
          (7,  5, 'Drug Trafficking',  'Narcotics trafficking, smuggling, and possession',        1, true, now()),
          -- Property Crime (category 6)
          (8,  6, 'Theft',             'Robbery, burglary, shoplifting, and vehicle theft',       1, true, now()),
          -- Sexual Crime (category 7)
          (9,  7, 'Human Trafficking', 'Trafficking of persons for exploitation',                 1, true, now()),
          -- Other (category 8)
          (10, 8, 'Other',             'Criminal activity not classified in other categories',    1, true, now())
        ON CONFLICT DO NOTHING
    """))

    # -----------------------------------------------------------------------
    # country — India is primary; others commonly appear in Indian news feeds
    # -----------------------------------------------------------------------
    op.execute(sa.text("""
        INSERT INTO country (id, name)
        VALUES
          (1,  'India'),
          (2,  'Pakistan'),
          (3,  'Bangladesh'),
          (4,  'Nepal'),
          (5,  'Sri Lanka'),
          (6,  'China'),
          (7,  'United States'),
          (8,  'United Kingdom'),
          (9,  'Afghanistan'),
          (10, 'Myanmar')
        ON CONFLICT (name) DO NOTHING
    """))

    # -----------------------------------------------------------------------
    # state — 28 Indian states + 8 union territories (all under country_id=1)
    # IDs 1-36 reserved for India. Other countries can use 37+.
    # -----------------------------------------------------------------------
    op.execute(sa.text("""
        INSERT INTO state (id, country_id, name)
        VALUES
          -- 28 States
          (1,  1, 'Andhra Pradesh'),
          (2,  1, 'Arunachal Pradesh'),
          (3,  1, 'Assam'),
          (4,  1, 'Bihar'),
          (5,  1, 'Chhattisgarh'),
          (6,  1, 'Goa'),
          (7,  1, 'Gujarat'),
          (8,  1, 'Haryana'),
          (9,  1, 'Himachal Pradesh'),
          (10, 1, 'Jharkhand'),
          (11, 1, 'Karnataka'),
          (12, 1, 'Kerala'),
          (13, 1, 'Madhya Pradesh'),
          (14, 1, 'Maharashtra'),
          (15, 1, 'Manipur'),
          (16, 1, 'Meghalaya'),
          (17, 1, 'Mizoram'),
          (18, 1, 'Nagaland'),
          (19, 1, 'Odisha'),
          (20, 1, 'Punjab'),
          (21, 1, 'Rajasthan'),
          (22, 1, 'Sikkim'),
          (23, 1, 'Tamil Nadu'),
          (24, 1, 'Telangana'),
          (25, 1, 'Tripura'),
          (26, 1, 'Uttar Pradesh'),
          (27, 1, 'Uttarakhand'),
          (28, 1, 'West Bengal'),
          -- 8 Union Territories
          (29, 1, 'Andaman and Nicobar Islands'),
          (30, 1, 'Chandigarh'),
          (31, 1, 'Dadra and Nagar Haveli and Daman and Diu'),
          (32, 1, 'Delhi'),
          (33, 1, 'Jammu and Kashmir'),
          (34, 1, 'Ladakh'),
          (35, 1, 'Lakshadweep'),
          (36, 1, 'Puducherry')
        ON CONFLICT DO NOTHING
    """))


def downgrade() -> None:
    # Remove seeded state rows (India only — id 1..36)
    op.execute(sa.text("DELETE FROM state WHERE id BETWEEN 1 AND 36"))
    # Remove seeded countries
    op.execute(sa.text(
        "DELETE FROM country WHERE name IN "
        "('India','Pakistan','Bangladesh','Nepal','Sri Lanka','China',"
        "'United States','United Kingdom','Afghanistan','Myanmar')"
    ))
    # Remove seeded sub_categories (id 1..10)
    op.execute(sa.text("DELETE FROM master_sub_category WHERE id BETWEEN 1 AND 10"))
    # Remove seeded categories (id 1..8)
    op.execute(sa.text("DELETE FROM master_category WHERE id BETWEEN 1 AND 8"))
