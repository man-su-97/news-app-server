"""
app/main.py — Application Entry Point
======================================
This is the FIRST file FastAPI reads when the server starts.
Think of it as the "reception desk" of the entire application:
  - It creates the FastAPI app object
  - Configures global settings (CORS, logging)
  - Registers all URL route groups (sources, articles, ingest, AI providers)
  - Starts/stops the background scheduler (auto-fetch news every 5 minutes)

Architecture decision: All routers live in separate files (routes_*.py) and are
"included" here. This keeps main.py small and each feature self-contained.
"""

import logging                           # Python's built-in logging library
from contextlib import asynccontextmanager  # Needed for the lifespan context manager

from fastapi import FastAPI              # The main FastAPI class — creates the web server
from fastapi.middleware.cors import CORSMiddleware  # Handles browser cross-origin requests

# Register ALL ORM models with SQLAlchemy's mapper registry at startup.
# This must happen before any query runs so relationship() string targets
# (e.g. "MasterSubCategory") can be resolved. The package __init__.py
# imports every model in dependency order.
import app.models  # noqa: F401

# Import each route group from its own file.
# Each router is a mini "sub-app" that handles a specific area of functionality.
from app.api.routes_ai_providers import router as ai_provider_router          # /ai-providers endpoints
from app.api.routes_articles import router as article_router                  # /articles endpoints
from app.api.routes_filter_articles import router as filter_article_router    # /filter-articles endpoints
from app.api.routes_final_articles import router as final_article_router      # /final-articles endpoints
from app.api.routes_ingest import router as ingest_router                     # /ingest endpoints
from app.api.routes_master_data import router as master_data_router           # /categories, /sub-categories, /countries, /states
from app.api.routes_raw_ingestion import router as raw_ingestion_router       # /raw-ingestion endpoints
from app.api.routes_sources import router as source_router                    # /sources endpoints

# The scheduler runs background jobs (fetch news every 5 minutes)
from app.services.scheduler import start_scheduler, stop_scheduler

# Configure Python's logging system.
# Every module that calls logging.getLogger(__name__) will output in this format:
#   "2026-01-15 10:30:00 INFO app.services.ingestion_service — Ingestion complete: 10 written"
# level=INFO means we see INFO, WARNING, ERROR but not DEBUG messages.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


# lifespan is FastAPI's lifecycle hook — code before `yield` runs on server START,
# code after `yield` runs on server STOP.
# Architecture decision: We use lifespan instead of the older @app.on_event("startup")
# because lifespan is the modern FastAPI pattern and supports async cleanup properly.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # SERVER START: kick off the background scheduler that fetches news every 5 min
    start_scheduler()
    yield                    # <-- server is running and handling requests here
    # SERVER STOP: shut down the scheduler gracefully so no jobs are left hanging
    stop_scheduler()


# Create the FastAPI application instance.
# title and version appear in the auto-generated /docs Swagger UI.
# lifespan= wires up our startup/shutdown hook above.
app = FastAPI(title="News Aggregator API", version="0.2.0", lifespan=lifespan)

# CORS (Cross-Origin Resource Sharing) middleware.
# Browsers block requests from one domain to another by default (security policy).
# This middleware tells browsers: "it's OK to call this API from any origin".
# Architecture decision: allow_origins=["*"] is fine for development and internal
# APIs. For production, restrict to your frontend domain:
#   allow_origins=["https://your-frontend.com"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Accept requests from any domain
    allow_methods=["*"],   # Allow GET, POST, DELETE, PATCH, etc.
    allow_headers=["*"],   # Allow any request headers
    # allow_credentials is intentionally omitted (default False).
    # Combining allow_credentials=True with allow_origins=["*"] is rejected
    # by all browsers per the CORS spec. This API uses no cookies or sessions,
    # so credentials are not needed. If auth is added later, set
    # allow_origins to specific domains and re-enable allow_credentials.
)

# Register route groups with URL prefixes.
# prefix="/sources" means all routes inside routes_sources.py get /sources prepended.
# tags=["Sources"] groups them together in the Swagger UI (/docs).
app.include_router(source_router, prefix="/sources", tags=["Sources"])
app.include_router(raw_ingestion_router, prefix="/raw-ingestion", tags=["Raw Ingestion"])
app.include_router(filter_article_router, prefix="/filter-articles", tags=["Filter Articles"])
app.include_router(article_router, prefix="/articles", tags=["Articles"])
app.include_router(final_article_router, prefix="/final-articles", tags=["Final Feed"])
app.include_router(ingest_router, prefix="/ingest", tags=["Ingestion"])
app.include_router(ai_provider_router, prefix="/ai-providers", tags=["AI Providers"])
app.include_router(master_data_router, prefix="/master", tags=["Master Data"])


# Simple health check endpoint.
# Used by Docker health checks, Kubernetes liveness probes, uptime monitors, etc.
# If the server is running, this returns 200 OK with {"status": "ok"}.
@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}


# Root endpoint — confirms the API is reachable.
# Useful for a quick sanity check: curl http://localhost:8000/
@app.get("/", tags=["Root"])
async def root():
    return {"message": "Welcome to the News Aggregator API!"}
