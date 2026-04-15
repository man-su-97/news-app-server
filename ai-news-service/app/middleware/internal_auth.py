from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings


PUBLIC_PATHS = [
    "/",
    "/health",

    # swagger
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
]

class InternalServiceMiddleware(BaseHTTPMiddleware):
  async def dispatch(self, request: Request, call_next):
    path = request.url.path
    # public routes
    if path in PUBLIC_PATHS:
      return await call_next(request)
    
    secret = request.headers.get("x-internal-secret")
    if secret != settings.INTERNAL_SERVICE_SECRET:
      raise HTTPException(
        status_code=403,
        detail="Forbidden direct access",
      )
    response = await call_next(request)
    return response