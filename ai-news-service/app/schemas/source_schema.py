from datetime import datetime

from pydantic import BaseModel, Field


class SourceCreate(BaseModel):
    name: str = Field(..., description="Display name for this source")
    type: str = Field(..., description="`rss` for RSS/Atom feeds, `rest` for JSON APIs")
    url: str = Field(..., description="Feed URL")
    config: dict | None = Field(
        default=None,
        description="Optional extra config, e.g. `{\"headers\": {\"Authorization\": \"Bearer TOKEN\"}}` for REST sources",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "India News Crime",
                "type": "rss",
                "url": "https://www.indiatoday.in/rss/1206514",
                "config": None,
            }
        }
    }


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, description="New display name")
    url: str | None = Field(default=None, description="New feed URL")
    is_active: bool | None = Field(default=None, description="`false` to pause, `true` to resume")
    config: dict | None = Field(default=None, description="Updated config")

    model_config = {
        "json_schema_extra": {
            "example": {
                "is_active": False
            }
        }
    }


class SourceResponse(BaseModel):
    id: int
    name: str
    type: str
    url: str
    config: dict | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
