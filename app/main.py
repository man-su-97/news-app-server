import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.models  # noqa: F401  — registers all ORM models before any query runs

from app.api.routes_ai_providers import router as ai_provider_router
from app.api.routes_filter_articles import router as filter_article_router
from app.api.routes_final_articles import router as final_article_router
from app.api.routes_ingest import router as ingest_router
from app.api.routes_raw_ingestion import router as raw_ingestion_router
from app.api.routes_master_data import router as master_data_router
from app.api.routes_post_processed import router as post_processed_router
from app.api.routes_sources import router as source_router
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Crime News API",
    version="1.0.0",
    description=(
        "AI-powered crime news aggregator for India.\n\n"
        "**Pipeline:** RSS/REST sources → AI classification & scoring → ranked news feed.\n\n"
        "**Public endpoint:** `GET /final-articles/` — ranked, deduplicated feed updated every 5 minutes.\n\n"
        "**Admin endpoints:** `/sources/`, `/ingest/`, `/ai-providers/` — manage sources and AI config."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(final_article_router, prefix="/final-articles", tags=["Feed"])
app.include_router(filter_article_router, prefix="/filter-articles", tags=["Pipeline"])
app.include_router(post_processed_router, prefix="/post-processed", tags=["Pipeline"])
app.include_router(master_data_router, prefix="/master", tags=["Master Data"])
app.include_router(source_router, prefix="/sources", tags=["Admin"])
app.include_router(ingest_router, prefix="/ingest", tags=["Admin"])
app.include_router(raw_ingestion_router, prefix="/raw-ingestion", tags=["Pipeline"])
app.include_router(ai_provider_router, prefix="/ai-providers", tags=["Admin"])


@app.get("/health", tags=["Health"], include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.get("/", tags=["Health"], include_in_schema=False)
async def root():
    return {"message": "Crime News API — see /docs"}
