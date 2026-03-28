"""
app/models/__init__.py — Central Model Registration
=====================================================
Importing this package guarantees every SQLAlchemy model is registered with
Base.metadata and the mapper registry BEFORE any query runs.

Why this matters:
  SQLAlchemy resolves relationship() string targets (e.g. "MasterSubCategory")
  lazily at first query time by searching its internal class registry.
  If a model module was never imported, the class is not in the registry and
  SQLAlchemy raises:
      InvalidRequestError: expression 'MasterSubCategory' failed to locate a name

  Import order must respect relationships:
    - Base models (no FKs to others) first
    - Then models that FK into base models
    - Then models that FK into those, etc.

  Any code that triggers a query (services, repos, tests) should import
  this package or import app.main (which includes this via the router chain).
"""

from app.models.base import Base            # noqa: F401 — must be first
from app.models.ai_provider import AIProviderConfig  # noqa: F401
from app.models.source import Source        # noqa: F401
from app.models.category import MasterCategory, MasterSubCategory  # noqa: F401
from app.models.location import Country, State  # noqa: F401
from app.models.raw_event import RawIngestion   # noqa: F401  (FK → news_sources)
from app.models.filter_article import FilterArticle  # noqa: F401  (FK → raw_ingestion, master_sub_category)
from app.models.post_processed_article import PostProcessedArticle  # noqa: F401  (FK → filter_articles, master_sub_category, state)
from app.models.final_article import FinalArticle  # noqa: F401  (FK → post_processed_articles)

__all__ = [
    "Base",
    "AIProviderConfig",
    "Source",
    "MasterCategory",
    "MasterSubCategory",
    "Country",
    "State",
    "RawIngestion",
    "FilterArticle",
    "PostProcessedArticle",
    "FinalArticle",
]
