"""
app/schemas/master_data_schema.py — Master Data API Response Schemas
====================================================================
Pydantic schemas for the reference/lookup tables:
  MasterCategory, MasterSubCategory, Country, State

Also includes RawIngestionResponse for the /raw-ingestion/ debug endpoint.
"""

from datetime import datetime

from pydantic import BaseModel


class MasterCategoryResponse(BaseModel):
    id: int
    name: str
    description: str | None
    priority_point: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MasterSubCategoryResponse(BaseModel):
    id: int
    category_id: int
    name: str
    description: str | None
    priority_point: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CountryResponse(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class StateResponse(BaseModel):
    id: int
    country_id: int
    name: str

    model_config = {"from_attributes": True}


class RawIngestionResponse(BaseModel):
    id: int
    source_id: int
    content_hash: str
    raw_payload: dict
    status: str
    normalized_by: str | None
    error_message: str | None
    retry_count: int
    created_at: datetime
    processed_at: datetime | None

    model_config = {"from_attributes": True}


class RawIngestionListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[RawIngestionResponse]
