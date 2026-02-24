"""
app/core/enums.py — Crime Taxonomy Enums
=========================================
IntEnum classes that mirror the master_category and master_sub_category seed data.

IDs are hardcoded to match the values inserted in migration i5j6k7l8m901.
Using IntEnum instead of DB string lookups gives:
  - Zero DB queries for category resolution (was 1 query per ingest run)
  - Single dict lookup per article (was 2 dict lookups + a DB round-trip)
  - Type-safe code — comparisons, switches, and set operations work naturally

IMPORTANT: If you add a new category or sub_category to the DB, you MUST
also add the corresponding enum member here with the correct integer ID.
"""

from enum import IntEnum


class CategoryEnum(IntEnum):
    """Top-level crime categories (maps to master_category.id)."""
    VIOLENT_CRIME   = 1
    TERRORISM       = 2
    FINANCIAL_CRIME = 3
    CYBER_CRIME     = 4
    DRUG_CRIME      = 5
    PROPERTY_CRIME  = 6
    SEXUAL_CRIME    = 7
    OTHER           = 8


class SubCategoryEnum(IntEnum):
    """Crime sub-categories (maps to master_sub_category.id)."""
    MURDER            = 1   # → CategoryEnum.VIOLENT_CRIME
    VIOLENCE          = 2   # → CategoryEnum.VIOLENT_CRIME
    TERRORISM         = 3   # → CategoryEnum.TERRORISM
    FRAUD             = 4   # → CategoryEnum.FINANCIAL_CRIME
    CORRUPTION        = 5   # → CategoryEnum.FINANCIAL_CRIME
    CYBERCRIME        = 6   # → CategoryEnum.CYBER_CRIME
    DRUG_TRAFFICKING  = 7   # → CategoryEnum.DRUG_CRIME
    THEFT             = 8   # → CategoryEnum.PROPERTY_CRIME
    HUMAN_TRAFFICKING = 9   # → CategoryEnum.SEXUAL_CRIME
    OTHER             = 10  # → CategoryEnum.OTHER


# ---------------------------------------------------------------------------
# AI string → SubCategoryEnum
# The AI is prompted to return exactly these lowercase strings.
# One dict lookup replaces the old two-step _AI_SUBCATEGORY_TO_NAME + name_to_id chain.
# ---------------------------------------------------------------------------
AI_STRING_TO_SUB_CATEGORY: dict[str, SubCategoryEnum] = {
    "murder":      SubCategoryEnum.MURDER,
    "violence":    SubCategoryEnum.VIOLENCE,
    "terrorism":   SubCategoryEnum.TERRORISM,
    "fraud":       SubCategoryEnum.FRAUD,
    "corruption":  SubCategoryEnum.CORRUPTION,
    "cybercrime":  SubCategoryEnum.CYBERCRIME,
    "drugs":       SubCategoryEnum.DRUG_TRAFFICKING,   # AI says "drugs" → Drug Trafficking
    "theft":       SubCategoryEnum.THEFT,
    "trafficking": SubCategoryEnum.HUMAN_TRAFFICKING,  # AI says "trafficking" → Human Trafficking
    "other":       SubCategoryEnum.OTHER,
}

# ---------------------------------------------------------------------------
# SubCategoryEnum → CategoryEnum  (parent lookup)
# Used to derive category_ids from sub_category_ids — no DB join needed.
# ---------------------------------------------------------------------------
SUB_CATEGORY_TO_CATEGORY: dict[SubCategoryEnum, CategoryEnum] = {
    SubCategoryEnum.MURDER:            CategoryEnum.VIOLENT_CRIME,
    SubCategoryEnum.VIOLENCE:          CategoryEnum.VIOLENT_CRIME,
    SubCategoryEnum.TERRORISM:         CategoryEnum.TERRORISM,
    SubCategoryEnum.FRAUD:             CategoryEnum.FINANCIAL_CRIME,
    SubCategoryEnum.CORRUPTION:        CategoryEnum.FINANCIAL_CRIME,
    SubCategoryEnum.CYBERCRIME:        CategoryEnum.CYBER_CRIME,
    SubCategoryEnum.DRUG_TRAFFICKING:  CategoryEnum.DRUG_CRIME,
    SubCategoryEnum.THEFT:             CategoryEnum.PROPERTY_CRIME,
    SubCategoryEnum.HUMAN_TRAFFICKING: CategoryEnum.SEXUAL_CRIME,
    SubCategoryEnum.OTHER:             CategoryEnum.OTHER,
}
