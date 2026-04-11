from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.core.security import (
  create_access_token,
  create_refresh_token
)
from app.core.config import settings
from app.models.users import User


class TokenService:

  def __init__(self, db: AsyncSession):
    self.refresh_repo = RefreshTokenRepository(db)


  async def generate_tokens(
    self,
    user: User
  ):
    access_token = create_access_token(user=user)
    refresh_token = create_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(
      days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    await self.refresh_repo.create(
      user_id=user.id,
      refresh_token=refresh_token,
      expires_at=expires_at
    )
    return access_token, refresh_token


  async def refresh_access_token(
    self,
    refresh_token: str
  ):
    token_obj = await self.refresh_repo.get_refresh_token(refresh_token)
    if not token_obj:
        return None
    return create_access_token(token_obj.user_id)


  async def revoke_refresh_token(
    self,
    refresh_token: str
  ):
    return await self.refresh_repo.revoke_refresh_token(
        refresh_token
    )