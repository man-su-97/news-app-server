from sqlalchemy.ext.asyncio import AsyncSession

from app.services.user_service import UserService
from app.services.otp_service import OTPService
from app.services.token_service import TokenService
from app.services.access_log_service import AccessLogService

from app.core.security import hash_password, verify_password
from app.core.enums import OTPType


class AuthService:

  def __init__(self, db: AsyncSession):
    self.user_service = UserService(db)
    self.otp_service = OTPService(db)
    self.token_service = TokenService(db)
    self.log_service = AccessLogService(db)


  async def register(
    self,
    email: str,
    password: str,
    full_name: str,
    role: str
  ):
    password_hash = hash_password(password)
    user = await self.user_service.register_user(
      email=email,
      password_hash=password_hash,
      full_name=full_name,
      role=role
    )
    otp = await self.otp_service.create_otp(
      user_id=user.id,
      otp_type=OTPType.EMAIL_VERIFICATION
    )

    return user, otp


  async def verify_email(
    self,
    email: str,
    otp_code: str
  ):
    user = await self.user_service.get_user_by_email(email)
    if not user:
        return False

    valid = await self.otp_service.validate_otp(
      otp_code=otp_code,
      user_id=user.id,
      otp_type=OTPType.EMAIL
    )
    if not valid:
        return False
    await self.user_service.verify_user(user.id)

    return True
  
  async def resend_verification_otp(self, email: str):
    user = await self.user_service.get_user_by_email(email)
    if not user:
      return True
    return await self.otp_service.resend_otp(
      user.id,
      OTPType.EMAIL_VERIFICATION
    )


  async def login(
    self,
    email: str,
    password: str,
    ip: str,
    user_agent: str
  ):
    user = await self.user_service.get_user_by_email(email)
    if not user:
      return None
    if not verify_password(password, user.password_hash):
      return None
    access_token, refresh_token = await self.token_service.generate_tokens(user)

    await self.log_service.log_login(
      user_id=user.id,
      ip=ip,
      user_agent=user_agent
    )

    return access_token, refresh_token


  async def refresh_token(
    self,
    refresh_token: str
  ):
    return await self.token_service.refresh_access_token(refresh_token)


  async def logout(
    self,
    refresh_token: str
  ):
    return await self.token_service.revoke_refresh_token(refresh_token)
  

  async def forgot_password(self, email: str):
    user = await self.user_service.get_user_by_email(email)
    # do not reveal if email exists (security reason)
    if not user:
      return True
    await self.otp_service.create_otp(
      user_id=user.id,
      otp_type=OTPType.PASSWORD_RESET
    )
    return True
  
  
  async def resend_reset_password_otp(self, email: str):
    user = await self.user_service.get_user_by_email(email)
    if not user:
      return True

    return await self.otp_service.resend_otp(
      user.id,
      OTPType.PASSWORD_RESET
    )
  

  async def reset_password(
    self,
    email: str,
    otp_code: str,
    new_password: str
):
    user = await self.user_service.get_user_by_email(email)
    if not user:
      return False

    is_valid = await self.otp_service.validate_otp(
      user_id=user.id,
      otp_code=otp_code,
      otp_type=OTPType.PASSWORD_RESET
    )
    if not is_valid:
      return False

    new_password_hash = hash_password(new_password)

    await self.user_service.update_password(
      user_id=user.id,
      new_password_hash=new_password_hash
    )
    return True