from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.otp_repo import OTPRepository
from app.core.enums import OTPType
from app.core.config import settings
from app.core.otp import generate_otp


class OTPService:

  def __init__(self, db: AsyncSession):
    self.otp_repo = OTPRepository(db)


  async def create_otp(
    self,
    user_id: int,
    otp_type: OTPType,
    expiry_minutes: int = 10
  ):
    otp_code = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(
      minutes=expiry_minutes
    )
    return await self.otp_repo.create_otp(
      user_id=user_id,
      otp_code=otp_code,
      otp_type=otp_type,
      expires_at=expires_at
    )


  async def validate_otp(
    self,
    user_id: int,
    otp_code: str,
    otp_type: OTPType
  ):

    otp = await self.otp_repo.get_valid_otp(
      user_id=user_id,
      otp_code=otp_code,
      otp_type=otp_type
    )

    if not otp:
      return False
    await self.otp_repo.mark_otp_used(otp.id)
    return True
  

  async def resend_otp(
    self,
    user_id: int,
    otp_type: OTPType
):
    latest_otp = await self.otp_repo.get_latest_otp(user_id, otp_type)
    # prevent spam
    if latest_otp:
      diff = datetime.now(timezone.utc) - latest_otp.created_at
      if diff.total_seconds() < settings.RESEND_COOL_DOWN_SECONDS:
        raise ValueError("OTP recently sent. Please wait.")

    otp_code = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    return await self.otp_repo.create_otp(
      user_id=user_id,
      otp_code=otp_code,
      otp_type=otp_type,
      expires_at=expires_at
    )