import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.api.v1.auth_router import router as auth_router
from app.oauth.google import router as google_router
from app.core.config import settings

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(
  title="Auth Service API",
  version="1.0.0",
  description=("Auth Service API"),
)

app.add_middleware(
  SessionMiddleware, 
  secret_key=settings.SESSION_SECRET_KEY,
  same_site="lax",     # allow OAuth redirect
  https_only=False     # for localhost
)

app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_methods=["*"],
  allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(google_router, prefix="/auth/oauth/google", tags=["Google Auth"])

@app.get("/health", tags=["Health"], include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.get("/", tags=["Health"], include_in_schema=False)
async def root():
    return {"message": "Auth Service API — see /docs"}