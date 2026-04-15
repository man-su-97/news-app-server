import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from app.models.refresh_token import RefreshToken
from sqlalchemy import select

logger = logging.getLogger(__name__)

class RefreshTokenRepository:
  def __init__(self, db: AsyncSession) -> None:
    self.db = db

  async def create(self, user_id: int, refresh_token: str, expires_at: datetime):
    try:
      refresh_token_obj = RefreshToken(
        user_id=user_id,
        token=refresh_token,
        expires_at=expires_at
      )
      self.db.add(refresh_token_obj)
      await self.db.commit()
      await self.db.refresh(refresh_token_obj)
      return refresh_token_obj
    except SQLAlchemyError:
      logger.exception("Database error occurred while creating refresh token.")
      raise
    except Exception as e:
      logger.exception(f"AN UNEXPECTED BUG OCCURRED in create_refresh_token!\n\n{e}")
      self.db.rollback()
      raise
    
  async def get_refresh_token(self, token: str):
    try:
      result = await self.db.execute(
        select(RefreshToken).where(
          RefreshToken.token == token,
          RefreshToken.is_revoked == False
        )
      )
      return result.scalar_one_or_none()
    except SQLAlchemyError:
      logger.exception("Database error occurred while fetching refresh token.")
      raise
    except Exception as e:
      logger.exception(f"AN UNEXPECTED BUG OCCURRED in get_refresh_token!\n\n{e}")
      self.db.rollback()
      raise

  async def revoke_refresh_token(self, token: str):
    try:
      result = await self.db.execute(
        select(RefreshToken).where(RefreshToken.token == token)
      )
      refresh_token = result.scalar_one_or_none()
      if not refresh_token:
        return None
      refresh_token.is_revoked = True
      await self.db.commit()
      await self.db.refresh(refresh_token)
      return refresh_token
    except SQLAlchemyError:
      logger.exception("Database error occurred while revoking refresh token.")
      raise
    except Exception as e:
      logger.exception(f"AN UNEXPECTED BUG OCCURRED in revoke_refresh_token!\n\n{e}")
      self.db.rollback()
      raise