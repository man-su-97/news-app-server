import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from app.models.otp import OTP
from app.core.enums import OTPType

logger = logging.getLogger(__name__)

class OTPRepository:
  def __init__(self, db: AsyncSession) -> None:
    self.db = db

  async def create_otp(self, user_id: int, otp_code:str, otp_type: OTPType, expires_at: datetime):
    try:
      otp_obj = OTP(
        user_id=user_id,
        otp_code=otp_code,
        otp_type=otp_type,
        expires_at=expires_at
      )
      self.db.add(otp_obj)
      await self.db.commit()
      await self.db.refresh(otp_obj)
      return otp_obj
    except SQLAlchemyError:
      logger.exception("Database error occurred while creating otp.")
      raise
    except Exception as e:
      logger.exception(f"AN UNEXPECTED BUG OCCURRED in create_otp!\n\n{e}")
      self.db.rollback()
      raise

  async def get_valid_otp(self, user_id: int, otp_code: str, otp_type: OTPType):
    try:
      result = await self.db.execute(
        select(OTP).where(
          OTP.user_id == user_id,
          OTP.otp_code == otp_code,
          OTP.otp_type == otp_type,
          OTP.is_used == False,
          OTP.expires_at > datetime.now(timezone.utc)
        )
      )
      return result.scalar_one_or_none()
    except SQLAlchemyError:
      logger.exception("Database error occurred while fetching otp.")
      raise
    except Exception as e:
      logger.exception(f"AN UNEXPECTED BUG OCCURRED in get_valid_otp!\n\n{e}")
      self.db.rollback()
      raise

  async def mark_otp_used(self, otp_id: int):
    try:
      result = await self.db.execute(select(OTP).where(OTP.id == otp_id))
      otp = result.scalar_one_or_none()
      if not otp:
        return False
      otp.is_used = True
      await self.db.commit()
      await self.db.refresh(otp)
      return True
    except SQLAlchemyError:
      logger.exception("Database error occurred while marking otp as used.")
      raise
    except Exception as e:
      logger.exception(f"AN UNEXPECTED BUG OCCURRED in mark_otp_used!\n\n{e}")
      self.db.rollback()
      raise

  async def get_latest_otp(self, user_id: int, otp_type: OTPType):
    try:
      result = await self.db.execute(
        select(OTP).where(
          OTP.user_id == user_id,
          OTP.otp_type == otp_type
        ).order_by(OTP.created_at.desc()).limit(1)
      )
      return result.scalar_one_or_none()
    except SQLAlchemyError:
      logger.exception("Database error occurred while fetching latest otp.")
      raise
    except Exception as e:
      logger.exception(f"AN UNEXPECTED BUG OCCURRED in get_latest_otp!\n\n{e}")
      self.db.rollback()
      raise