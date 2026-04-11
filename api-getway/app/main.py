import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middleware.auth_middleware import AuthMiddleware
from app.routes.auth_proxy import router as auth_proxy
from app.routes.news_proxy import router as news_proxy

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(
  title="API Getway",
  version="1.0.0",
  description=("API Getway"),
)

app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_methods=["*"],
  allow_headers=["*"],
)

app.add_middleware(AuthMiddleware)

app.include_router(auth_proxy, prefix="/api")
app.include_router(news_proxy, prefix="/api")

@app.get("/health", tags=["Health"], include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.get("/", tags=["Health"], include_in_schema=False)
async def root():
    return {"message": "Getway API — see /docs"}