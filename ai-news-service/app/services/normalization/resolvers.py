"""
app/services/normalization/resolvers.py — FK Resolvers for AI Output
=====================================================================
Two resolver classes that translate AI free-text output into database FK ids.

  CategoryResolver  — maps AI sub_category string → master_sub_category.id
                      Uses IntEnum constants (app.core.enums) — NO DB query.
                      Sub_category→category parent lookup is also enum-based.

  LocationResolver  — maps AI location string → state.id (best-effort).
                      Still loaded from DB (state names are too many for hardcoding).

Usage pattern in IngestionService:
    cat_resolver, loc_resolver = await load_resolvers(db)
    for article in crime_articles:
        article["sub_category_ids"] = cat_resolver.resolve_all(article.get("sub_category_ids", []))
        article["category_ids"]     = cat_resolver.resolve_categories_from_ids(article["sub_category_ids"])
        article["sub_category_id"]  = cat_resolver.resolve(article.get("sub_category"))  # post_processed FK
        article["location_id"]      = loc_resolver.resolve(article.get("location"))

Why enums instead of DB lookups for categories?
  The seed migration (i5j6k7l8m901) hardcodes stable integer IDs for the 8
  categories and 10 sub-categories. The AI is constrained to exactly those 10
  sub_category strings. Using IntEnum:
    - Eliminates 1 DB query per ingest run (was SELECT from master_sub_category)
    - Reduces per-article work from 2 dict lookups to 1
    - Makes the mapping type-safe and self-documenting
"""

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    AI_STRING_TO_SUB_CATEGORY,
    SUB_CATEGORY_TO_CATEGORY,
    SubCategoryEnum,
    CategoryEnum,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# City / locality → Indian state name mapping
# Covers major cities that commonly appear in Indian crime news.
# Key: lowercase city name (or alias)
# Value: exact state name as seeded in the state table
# ---------------------------------------------------------------------------
_CITY_TO_STATE: dict[str, str] = {
    # Maharashtra
    "mumbai": "Maharashtra", "bombay": "Maharashtra",
    "pune": "Maharashtra", "nagpur": "Maharashtra",
    "nashik": "Maharashtra", "aurangabad": "Maharashtra",
    "thane": "Maharashtra", "navi mumbai": "Maharashtra",
    "solapur": "Maharashtra", "kolhapur": "Maharashtra",

    # Delhi
    "delhi": "Delhi", "new delhi": "Delhi",
    "noida": "Uttar Pradesh", "ghaziabad": "Uttar Pradesh",
    "gurugram": "Haryana", "gurgaon": "Haryana",
    "faridabad": "Haryana",

    # Karnataka
    "bengaluru": "Karnataka", "bangalore": "Karnataka",
    "mysuru": "Karnataka", "mysore": "Karnataka",
    "mangaluru": "Karnataka", "mangalore": "Karnataka",
    "hubli": "Karnataka", "belgaum": "Karnataka",

    # Tamil Nadu
    "chennai": "Tamil Nadu", "madras": "Tamil Nadu",
    "coimbatore": "Tamil Nadu", "madurai": "Tamil Nadu",
    "salem": "Tamil Nadu", "trichy": "Tamil Nadu",
    "tiruchirappalli": "Tamil Nadu",

    # Telangana
    "hyderabad": "Telangana", "secunderabad": "Telangana",
    "warangal": "Telangana",

    # West Bengal
    "kolkata": "West Bengal", "calcutta": "West Bengal",
    "howrah": "West Bengal", "durgapur": "West Bengal",
    "asansol": "West Bengal",

    # Gujarat
    "ahmedabad": "Gujarat", "surat": "Gujarat",
    "vadodara": "Gujarat", "baroda": "Gujarat",
    "rajkot": "Gujarat", "bhavnagar": "Gujarat",

    # Rajasthan
    "jaipur": "Rajasthan", "jodhpur": "Rajasthan",
    "udaipur": "Rajasthan", "kota": "Rajasthan",
    "ajmer": "Rajasthan", "bikaner": "Rajasthan",

    # Uttar Pradesh
    "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh",
    "varanasi": "Uttar Pradesh", "agra": "Uttar Pradesh",
    "meerut": "Uttar Pradesh", "allahabad": "Uttar Pradesh",
    "prayagraj": "Uttar Pradesh", "bareilly": "Uttar Pradesh",
    "aligarh": "Uttar Pradesh", "moradabad": "Uttar Pradesh",

    # Bihar
    "patna": "Bihar", "gaya": "Bihar",
    "muzaffarpur": "Bihar", "bhagalpur": "Bihar",

    # Madhya Pradesh
    "bhopal": "Madhya Pradesh", "indore": "Madhya Pradesh",
    "jabalpur": "Madhya Pradesh", "gwalior": "Madhya Pradesh",
    "ujjain": "Madhya Pradesh",

    # Andhra Pradesh
    "visakhapatnam": "Andhra Pradesh", "vizag": "Andhra Pradesh",
    "vijayawada": "Andhra Pradesh", "guntur": "Andhra Pradesh",
    "tirupati": "Andhra Pradesh",

    # Punjab
    "amritsar": "Punjab", "ludhiana": "Punjab",
    "jalandhar": "Punjab", "patiala": "Punjab",

    # Chandigarh
    "chandigarh": "Chandigarh",

    # Haryana
    "ambala": "Haryana", "hisar": "Haryana", "rohtak": "Haryana",

    # Himachal Pradesh
    "shimla": "Himachal Pradesh", "manali": "Himachal Pradesh",
    "dharamshala": "Himachal Pradesh",

    # Uttarakhand
    "dehradun": "Uttarakhand", "haridwar": "Uttarakhand",
    "rishikesh": "Uttarakhand",

    # Jharkhand
    "ranchi": "Jharkhand", "jamshedpur": "Jharkhand",
    "dhanbad": "Jharkhand",

    # Chhattisgarh
    "raipur": "Chhattisgarh", "bilaspur": "Chhattisgarh",

    # Odisha
    "bhubaneswar": "Odisha", "bhubaneshwar": "Odisha",
    "cuttack": "Odisha", "rourkela": "Odisha",

    # Assam
    "guwahati": "Assam", "dibrugarh": "Assam",
    "silchar": "Assam",

    # Kerala
    "thiruvananthapuram": "Kerala", "trivandrum": "Kerala",
    "kochi": "Kerala", "cochin": "Kerala",
    "kozhikode": "Kerala", "calicut": "Kerala",
    "thrissur": "Kerala",

    # Goa
    "panaji": "Goa", "panjim": "Goa",
    "margao": "Goa", "vasco": "Goa",

    # Jammu and Kashmir
    "srinagar": "Jammu and Kashmir", "jammu": "Jammu and Kashmir",

    # Puducherry
    "puducherry": "Puducherry", "pondicherry": "Puducherry",

    # Tripura
    "agartala": "Tripura",

    # Meghalaya
    "shillong": "Meghalaya",

    # Nagaland
    "kohima": "Nagaland", "dimapur": "Nagaland",

    # Manipur
    "imphal": "Manipur",

    # Mizoram
    "aizawl": "Mizoram",

    # Arunachal Pradesh
    "itanagar": "Arunachal Pradesh",

    # Sikkim
    "gangtok": "Sikkim",
}


class CategoryResolver:
    """Resolves AI sub_category strings to DB IDs using IntEnum constants.

    No DB query required — IDs are fixed by the seed migration (i5j6k7l8m901)
    and the AI is constrained to exactly 10 sub_category strings.

    Methods:
      resolve(ai_str)                 → sub_category int ID (or None)
      resolve_all(ai_str_list)        → list of sub_category int IDs
      resolve_categories_from_ids(ids) → list of parent category int IDs
    """

    def resolve(self, ai_sub_category: str | None) -> int | None:
        """Return master_sub_category.id for the given AI string, or None.

        Example: resolve("murder") → 1
        """
        if not ai_sub_category:
            return None
        enum_val = AI_STRING_TO_SUB_CATEGORY.get(ai_sub_category.lower().strip())
        if enum_val is None:
            logger.warning("CategoryResolver: unknown AI sub_category %r", ai_sub_category)
            return None
        return int(enum_val)

    def resolve_all(self, ai_sub_categories: list[str] | None) -> list[int]:
        """Resolve a multi-label list of AI strings to sub_category DB IDs (deduplicated).

        Used for filtered_articles.sub_category_ids JSONB column.

        Example: resolve_all(["murder", "terrorism"]) → [1, 3]
        """
        if not ai_sub_categories:
            return []
        result: list[int] = []
        seen: set[int] = set()
        for s in ai_sub_categories:
            sc_id = self.resolve(s)
            if sc_id is not None and sc_id not in seen:
                result.append(sc_id)
                seen.add(sc_id)
        return result

    def resolve_categories_from_ids(self, sub_cat_ids: list[int] | None) -> list[int]:
        """Map sub_category DB IDs → parent category DB IDs (deduplicated).

        Used for filtered_articles.category_ids JSONB column.

        Example:
          [1, 2]  (Murder + Violence, both Violent Crime) → [1]
          [1, 4]  (Murder + Fraud) → [1, 3]  (Violent Crime + Financial Crime)
        """
        if not sub_cat_ids:
            return []
        result: list[int] = []
        seen: set[int] = set()
        for sc_id in sub_cat_ids:
            try:
                cat_id = int(SUB_CATEGORY_TO_CATEGORY[SubCategoryEnum(sc_id)])
            except (ValueError, KeyError):
                logger.warning("CategoryResolver: unknown sub_category_id %d", sc_id)
                continue
            if cat_id not in seen:
                result.append(cat_id)
                seen.add(cat_id)
        return result


class LocationResolver:
    """Maps the AI's free-text location string to a state FK id (best-effort).

    Strategy (tried in order):
      1. Direct state name match — "Maharashtra" found in location string
      2. City alias match      — "Mumbai" → Maharashtra → state_id
      3. Return None           — location is too vague or outside seeded states

    Case-insensitive throughout.
    """

    def __init__(self, state_name_to_id: dict[str, int]) -> None:
        # {state_name_lower: id}  e.g. {"maharashtra": 14, "delhi": 32}
        self._state_map = state_name_to_id

    def resolve(self, location: str | None) -> int | None:
        """Return state.id for the given location string, or None."""
        if not location:
            return None
        loc_lower = location.lower().strip()

        # Pass 1: direct substring match against state names
        # e.g. "Mumbai, Maharashtra, India" → "maharashtra" found → id 14
        for state_name_lower, state_id in self._state_map.items():
            if state_name_lower in loc_lower:
                return state_id

        # Pass 2: city alias lookup
        # e.g. "Mumbai" → "Maharashtra" → id 14
        for city, state_name in _CITY_TO_STATE.items():
            if city in loc_lower:
                return self._state_map.get(state_name.lower())

        return None


async def load_resolvers(
    db: AsyncSession,
) -> tuple[CategoryResolver, LocationResolver]:
    """Load both resolvers. CategoryResolver needs no DB query (uses enums).
    LocationResolver loads state names from DB (36 states — not hardcoded).

    Returns:
        (CategoryResolver, LocationResolver) — both ready to use synchronously.
    """
    # State lookup only — sub_category lookup is now enum-based (no DB query)
    state_rows = await db.execute(
        text("SELECT id, name FROM state")
    )
    state_name_to_id = {row.name.lower(): row.id for row in state_rows.all()}

    logger.debug(
        "Resolvers loaded: sub_categories=enum-based, states=%d",
        len(state_name_to_id),
    )
    return CategoryResolver(), LocationResolver(state_name_to_id)
