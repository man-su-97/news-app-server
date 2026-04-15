import httpx

from fastapi import APIRouter, Request

from app.core.config import settings


router = APIRouter()


@router.api_route("/news/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_news(request: Request, path: str):
  url = f"{settings.AI_NEWS_SERVICE_URL}/{path}"
  headers = dict(request.headers)
  # forward user context
  headers["x-user-id"] = str(request.state.user_id)
  headers["x-user-role"] = str(request.state.user_role)
  headers["x-user-email"] = str(request.state.user_email)
  headers["x-internal-secret"] = settings.INTERNAL_SERVICE_SECRET

  async with httpx.AsyncClient() as client:
    response = await client.request(
      method=request.method,
      url=url,
      headers=headers,
      content=await request.body(),
    )
  return response.json()