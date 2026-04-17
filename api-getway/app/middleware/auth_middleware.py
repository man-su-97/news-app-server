from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import decode_access_token

PUBLIC_PATHS = [
  "/",
  "/health",

  # swagger
  "/docs",
  "/redoc",
  "/openapi.json",
  "/favicon.ico",

  # auth routes
  "/api/auth",
]


class AuthMiddleware(BaseHTTPMiddleware):
  async def dispatch(self, request: Request, call_next):

    path = request.url.path
    # public routes
    if path in PUBLIC_PATHS:
      return await call_next(request)

    # auth routes
    if path.startswith("/api/auth"):
      return await call_next(request)
    if path.startswith("/api/auth/oauth"):
      return await call_next(request)

    auth_header = request.headers.get("Authorization")

    if not auth_header:
      raise HTTPException(status_code=401, detail="Missing token")

    try:
      token = auth_header.split(" ")[1]

    except IndexError:
      raise HTTPException(status_code=401, detail="Invalid token")

    payload = decode_access_token(token)
    if not payload:
      raise HTTPException(status_code=401, detail="Invalid token")

    # attach user info in request state
    request.state.user_id = payload.get("sub")
    request.state.user_role = payload.get("role")
    request.state.user_email = payload.get("email")

    response = await call_next(request)

    return response