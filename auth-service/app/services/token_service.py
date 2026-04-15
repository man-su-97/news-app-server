from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.refresh_token_repo import RefreshTokenRepository
from app.repositories.user_repo import UserRepository
from app.core.security import (
  create_access_token,
  create_refresh_token
)
from app.core.config import settings
from app.models.users import User


class TokenService:

  def __init__(self, db: AsyncSession):
    self.refresh_repo = RefreshTokenRepository(db)
    self.user_repo = UserRepository(db)


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
      raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"message":"Invalid refresh token"}
      )
    
    user_obj = await self.user_repo.get_by_id(token_obj.user_id)
    if not user_obj:
      raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"message":"User not found"}
      )
    
    return create_access_token(user=user_obj)


  async def revoke_refresh_token(
    self,
    refresh_token: str
  ):
    return await self.refresh_repo.revoke_refresh_token(
        refresh_token
    )