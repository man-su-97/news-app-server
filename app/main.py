import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_ai_providers import router as ai_provider_router
from app.api.routes_articles import router as article_router
from app.api.routes_ingest import router as ingest_router
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
()


app = FastAPI(title="News Aggregator API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(source_router, prefix="/sources", tags=["Sources"])
app.include_router(article_router, prefix="/articles", tags=["Articles"])
app.include_router(ingest_router, prefix="/ingest", tags=["Ingestion"])
app.include_router(ai_provider_router,
                   prefix="/ai-providers", tags=["AI Providers"])


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}


@app.get("/", tags=["Root"])
async def root():
    return {"message": "Welcome to the News Aggregator API!"}
