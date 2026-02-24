from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import (
    get_category_repo,
    get_state_repo,
    get_sub_category_repo,
)
from app.repositories.master_data_repo import (
    MasterCategoryRepository,
    MasterSubCategoryRepository,
    StateRepository,
)
from app.schemas.master_data_schema import (
    MasterCategoryResponse,
    MasterSubCategoryResponse,
    StateResponse,
)

router = APIRouter()


@router.get(
    "/categories/",
    response_model=list[MasterCategoryResponse],
    summary="List crime categories",
)
async def list_categories(
    active_only: bool = Query(False, description="Return only active categories"),
    repo: MasterCategoryRepository = Depends(get_category_repo),
):
    """Returns all top-level crime categories ordered by priority.

    Use these IDs to filter the news feed by broad crime type
    (e.g. Violent Crime, Financial Crime, Cyber Crime).
    """
    return await repo.get_all(active_only=active_only)


@router.get(
    "/categories/{category_id}",
    response_model=MasterCategoryResponse,
    summary="Get a crime category by ID",
    responses={404: {"description": "Category not found"}},
)
async def get_category(
    category_id: int,
    repo: MasterCategoryRepository = Depends(get_category_repo),
):
    """Returns a single crime category by its ID."""
    item = await repo.get_by_id(category_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return item


@router.get(
    "/sub-categories/",
    response_model=list[MasterSubCategoryResponse],
    summary="List crime sub-categories",
)
async def list_sub_categories(
    category_id: int | None = Query(None, description="Filter by parent category ID"),
    active_only: bool = Query(False, description="Return only active sub-categories"),
    repo: MasterSubCategoryRepository = Depends(get_sub_category_repo),
):
    """Returns all crime sub-categories ordered by category and priority.

    Pass `sub_category_id` to `GET /final-articles/` to filter the feed
    by a specific crime type (e.g. Murder, Fraud, Cybercrime).
    """
    return await repo.get_all(category_id=category_id, active_only=active_only)


@router.get(
    "/sub-categories/{sub_category_id}",
    response_model=MasterSubCategoryResponse,
    summary="Get a crime sub-category by ID",
    responses={404: {"description": "Sub-category not found"}},
)
async def get_sub_category(
    sub_category_id: int,
    repo: MasterSubCategoryRepository = Depends(get_sub_category_repo),
):
    """Returns a single crime sub-category by its ID."""
    item = await repo.get_by_id(sub_category_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Sub-category not found")
    return item


@router.get(
    "/states/",
    response_model=list[StateResponse],
    summary="List states",
)
async def list_states(
    country_id: int | None = Query(None, description="Filter by country ID"),
    repo: StateRepository = Depends(get_state_repo),
):
    """Returns all states/provinces ordered alphabetically.

    Use the state `id` to filter the news feed by location.
    """
    return await repo.get_all(country_id=country_id)


@router.get(
    "/states/{state_id}",
    response_model=StateResponse,
    summary="Get a state by ID",
    responses={404: {"description": "State not found"}},
)
async def get_state(
    state_id: int,
    repo: StateRepository = Depends(get_state_repo),
):
    """Returns a single state by its ID."""
    item = await repo.get_by_id(state_id)
    if item is None:
        raise HTTPException(status_code=404, detail="State not found")
    return item
