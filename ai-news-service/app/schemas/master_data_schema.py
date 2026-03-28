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


class StateResponse(BaseModel):
    id: int
    country_id: int
    name: str

    model_config = {"from_attributes": True}
