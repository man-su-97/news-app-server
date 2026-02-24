from datetime import datetime

from pydantic import BaseModel, Field


class SourceCreate(BaseModel):
    name: str = Field(..., description="Display name for this source", examples=["India News Crime RSS"])
    type: str = Field(..., description="`rss` for RSS/Atom feeds, `rest` for JSON APIs", examples=["rss"])
    url: str = Field(..., description="Feed URL", examples=["https://timesofindia.indiatimes.com/rssfeeds/7503091.cms"])
    config: dict | None = Field(
        default=None,
        description="Optional extra config, e.g. `{\"headers\": {\"Authorization\": \"Bearer TOKEN\"}}` for REST sources",
        examples=[None],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "RSS feed",
                    "value": {
                        "name": "Times of India Crime",
                        "type": "rss",
                        "url": "https://timesofindia.indiatimes.com/rssfeeds/7503091.cms",
                        "config": None,
                    },
                },
                {
                    "summary": "REST API with auth header",
                    "value": {
                        "name": "NewsAPI Crime",
                        "type": "rest",
                        "url": "https://newsapi.org/v2/top-headlines?category=crime",
                        "config": {"headers": {"Authorization": "Bearer YOUR_API_KEY"}},
                    },
                },
            ]
        }
    }


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, description="New display name")
    url: str | None = Field(default=None, description="New feed URL")
    is_active: bool | None = Field(default=None, description="`false` to pause, `true` to resume")
    config: dict | None = Field(default=None, description="Updated config")


class SourceResponse(BaseModel):
    id: int
    name: str
    type: str
    url: str
    config: dict | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
