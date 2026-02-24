"""
app/api/routes_master_data.py — Master Data Read Endpoints
==========================================================
HTTP API for the four reference/lookup tables:
  GET /categories/                    → list all crime categories
  GET /categories/{id}                → get one category
  GET /sub-categories/                → list all crime sub-categories
  GET /sub-categories/{id}            → get one sub-category
  GET /countries/                     → list all countries
  GET /countries/{id}                 → get one country
  GET /states/                        → list all states (optionally filter by country)
  GET /states/{id}                    → get one state

These tables are seeded via Alembic data migration and rarely change.
Useful during demo to show what categories/locations the AI resolves articles into.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import (
    get_category_repo,
    get_country_repo,
    get_state_repo,
    get_sub_category_repo,
)
from app.repositories.master_data_repo import (
    CountryRepository,
    MasterCategoryRepository,
    MasterSubCategoryRepository,
    StateRepository,
)
from app.schemas.master_data_schema import (
    CountryResponse,
    MasterCategoryResponse,
    MasterSubCategoryResponse,
    StateResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Crime Categories
# ---------------------------------------------------------------------------

@router.get(
    "/categories/",
    response_model=list[MasterCategoryResponse],
    summary="List all crime categories",
)
async def list_categories(
    active_only: bool = Query(False, description="When true, return only is_active=true rows"),
    repo: MasterCategoryRepository = Depends(get_category_repo),
):
    """List all master crime categories ordered by priority_point.

    Examples: Violent Crime, Financial Crime, Cyber Crime, Drug-Related Crime.
    These are the top-level classification labels the AI assigns to articles.
    """
    return await repo.get_all(active_only=active_only)


@router.get(
    "/categories/{category_id}",
    response_model=MasterCategoryResponse,
    summary="Get crime category by ID",
)
async def get_category(
    category_id: int,
    repo: MasterCategoryRepository = Depends(get_category_repo),
):
    """Get a single master crime category by its ID."""
    item = await repo.get_by_id(category_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return item


# ---------------------------------------------------------------------------
# Crime Sub-Categories
# ---------------------------------------------------------------------------

@router.get(
    "/sub-categories/",
    response_model=list[MasterSubCategoryResponse],
    summary="List all crime sub-categories",
)
async def list_sub_categories(
    category_id: int | None = Query(None, description="Filter by parent category ID"),
    active_only: bool = Query(False, description="When true, return only is_active=true rows"),
    repo: MasterSubCategoryRepository = Depends(get_sub_category_repo),
):
    """List all crime sub-categories ordered by category and priority_point.

    Examples: Murder, Assault, Robbery, Cybercrime, Fraud, Corruption.
    The AI assigns sub_category_ids[] (multi-label) from this list to each article.

    Use category_id to show only sub-categories for one parent category.
    """
    return await repo.get_all(category_id=category_id, active_only=active_only)


@router.get(
    "/sub-categories/{sub_category_id}",
    response_model=MasterSubCategoryResponse,
    summary="Get crime sub-category by ID",
)
async def get_sub_category(
    sub_category_id: int,
    repo: MasterSubCategoryRepository = Depends(get_sub_category_repo),
):
    """Get a single crime sub-category by its ID."""
    item = await repo.get_by_id(sub_category_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Sub-category not found")
    return item


# ---------------------------------------------------------------------------
# Countries
# ---------------------------------------------------------------------------

@router.get(
    "/countries/",
    response_model=list[CountryResponse],
    summary="List all countries",
)
async def list_countries(
    repo: CountryRepository = Depends(get_country_repo),
):
    """List all countries in the reference table, ordered alphabetically."""
    return await repo.get_all()


@router.get(
    "/countries/{country_id}",
    response_model=CountryResponse,
    summary="Get country by ID",
)
async def get_country(
    country_id: int,
    repo: CountryRepository = Depends(get_country_repo),
):
    """Get a single country by its ID."""
    item = await repo.get_by_id(country_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Country not found")
    return item


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

@router.get(
    "/states/",
    response_model=list[StateResponse],
    summary="List all states",
)
async def list_states(
    country_id: int | None = Query(None, description="Filter states by country ID"),
    repo: StateRepository = Depends(get_state_repo),
):
    """List all states/provinces ordered alphabetically.

    Use country_id to show states for one specific country only.
    The AI resolves article locations (e.g. 'Mumbai, India') to a state ID
    which is stored in filter_articles.location_state_id.
    """
    return await repo.get_all(country_id=country_id)


@router.get(
    "/states/{state_id}",
    response_model=StateResponse,
    summary="Get state by ID",
)
async def get_state(
    state_id: int,
    repo: StateRepository = Depends(get_state_repo),
):
    """Get a single state/province by its ID."""
    item = await repo.get_by_id(state_id)
    if item is None:
        raise HTTPException(status_code=404, detail="State not found")
    return item
