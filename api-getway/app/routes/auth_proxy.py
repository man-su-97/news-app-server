import httpx

from fastapi import APIRouter, Request, Response

from app.core.config import settings


router = APIRouter()


@router.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_auth(request: Request, path: str):
  url = f"{settings.AUTH_SERVICE_URL}/auth/{path}"
  async with httpx.AsyncClient(follow_redirects=False) as client:
    response = await client.request(
      method=request.method,
      url=url,
      headers=request.headers.raw,
      content=await request.body(),
      cookies=request.cookies
    )
  # RETURN RAW RESPONSE
    return Response(
      content=response.content,
      status_code=response.status_code,
      headers=dict(response.headers),
    )