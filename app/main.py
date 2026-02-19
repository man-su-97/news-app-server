import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_articles import router as article_router
from app.api.routes_ingest import router as ingest_router
from app.api.routes_sources import router as source_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(title="News Aggregator API", version="0.1.0")

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


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}
