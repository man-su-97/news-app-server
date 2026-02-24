"""
app/services/normalization/resolvers.py — FK Resolvers for AI Output
=====================================================================
Two resolver classes that translate AI free-text output into database FK ids.

Loaded ONCE per ingest run (not per article) to avoid N+1 DB queries:
  CategoryResolver  — maps AI sub_category string → master_sub_category.id
  LocationResolver  — maps AI location string → state.id (best-effort)

Usage pattern in IngestionService:
    cat_resolver, loc_resolver = await load_resolvers(db)
    for article in crime_articles:
        article["sub_category_id"] = cat_resolver.resolve(article.get("sub_category"))
        article["location_id"]     = loc_resolver.resolve(article.get("location"))

Why load once per ingest run?
  Taxonomy tables (master_sub_category, state) change rarely.
  Loading them once and resolving from an in-memory dict is:
    - Faster: 2 DB queries per run instead of 2 per article
    - Safe: resolvers are request-scoped; stale data is refreshed next run
"""

import logging
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AI sub_category string → master_sub_category.name mapping
# ---------------------------------------------------------------------------
# The AI is prompted to return exactly one of these 10 strings (lowercase).
# The DB stores human-readable names. This dict bridges the gap.
_AI_SUBCATEGORY_TO_NAME: dict[str, str] = {
    "murder":      "Murder",
    "violence":    "Violence",
    "terrorism":   "Terrorism",
    "fraud":       "Fraud",
    "corruption":  "Corruption",
    "cybercrime":  "Cybercrime",
    "drugs":       "Drug Trafficking",
    "theft":       "Theft",
    "trafficking": "Human Trafficking",
    "other":       "Other",
}

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
    """Maps the AI's sub_category string to a master_sub_category FK id.

    Loaded once from DB, then resolves from an in-memory dict.
    Logs a warning if an unrecognised AI string is encountered (future-proofing).
    """

    def __init__(self, name_to_id: dict[str, int]) -> None:
        # {sub_category_name_lower: id}  e.g. {"murder": 1, "cybercrime": 6}
        self._name_to_id = name_to_id

    def resolve(self, ai_sub_category: str | None) -> int | None:
        """Return master_sub_category.id for the given AI string, or None."""
        if not ai_sub_category:
            return None
        ai_str = ai_sub_category.lower().strip()
        db_name = _AI_SUBCATEGORY_TO_NAME.get(ai_str)
        if db_name is None:
            logger.warning("CategoryResolver: unknown AI sub_category %r", ai_sub_category)
            return None
        result = self._name_to_id.get(db_name.lower())
        if result is None:
            logger.warning("CategoryResolver: DB missing sub_category %r", db_name)
        return result

    def resolve_all(self, ai_sub_categories: list[str] | None) -> list[int]:
        """Resolve a multi-label list of AI sub_category strings to DB IDs.

        Used for the new sub_category_ids JSONB column in filter_articles.
        Silently drops any strings that cannot be resolved.

        Example:
          resolve_all(["murder", "terrorism"]) → [1, 3]
          resolve_all(["unknown_type"])        → []
        """
        if not ai_sub_categories:
            return []
        result = []
        seen: set[int] = set()
        for s in ai_sub_categories:
            resolved_id = self.resolve(s)
            if resolved_id is not None and resolved_id not in seen:
                result.append(resolved_id)
                seen.add(resolved_id)
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
    """Load both resolvers in two DB queries. Call once at ingest start.

    Returns:
        (CategoryResolver, LocationResolver) — both ready to use synchronously.
    """
    # Load sub_category lookup: {name_lower: id}
    sc_rows = await db.execute(
        text("SELECT id, name FROM master_sub_category WHERE is_active = true")
    )
    name_to_id = {row.name.lower(): row.id for row in sc_rows.all()}

    # Load state lookup: {name_lower: id}
    state_rows = await db.execute(
        text("SELECT id, name FROM state")
    )
    state_name_to_id = {row.name.lower(): row.id for row in state_rows.all()}

    logger.debug(
        "Resolvers loaded: %d sub_categories, %d states",
        len(name_to_id),
        len(state_name_to_id),
    )
    return CategoryResolver(name_to_id), LocationResolver(state_name_to_id)
