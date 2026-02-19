from datetime import datetime

from pydantic import BaseModel


class SourceCreate(BaseModel):
    name: str
    type: str  # "rss" | "rest"
    url: str
    config: dict | None = None


class SourceResponse(BaseModel):
    id: int
    name: str
    type: str
    url: str
    config: dict | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
