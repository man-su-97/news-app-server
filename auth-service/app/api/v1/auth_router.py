from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

from app.services.auth_service import AuthService

from app.schemas.auth_schema import *


router = APIRouter()



# -----------------------
# REGISTER
# -----------------------

@router.post("/register")
async def register(
  data: RegisterRequest,
  background_tasks: BackgroundTasks,
  db: AsyncSession = Depends(get_db),
):
  service = AuthService(db)
  result = await service.register(
    email=data.email,
    password=data.password,
    full_name=data.full_name,
    role=data.role,
    background_tasks=background_tasks
  )
  return {
    "user": result[0],
    "message": "OTP sent to email"
  }



# -----------------------
# VERIFY EMAIL
# -----------------------

@router.post("/verify-email")
async def verify_email(
  data: VerifyEmailRequest,
  db: AsyncSession = Depends(get_db)
):
  service = AuthService(db)
  success = await service.verify_email(
    email=data.email,
    otp_code=data.otp_code
  )
  if success:
    return {"message": "Email verified"}
  return {"message": "Invalid OTP"}



# -----------------------
# RESEND OTP
# -----------------------

@router.post("/resend-verification-otp")
async def resend_verification_otp(
  data: ResendOTPRequest,
  background_tasks: BackgroundTasks,
  db: AsyncSession = Depends(get_db)
):
  service = AuthService(db)
  await service.resend_verification_otp(
    email=data.email,
    background_tasks=background_tasks
  )
  return {"message": "OTP resent"}



# -----------------------
# LOGIN
# -----------------------

@router.post("/login")
async def login(
  data: LoginRequest,
  request: Request,
  db: AsyncSession = Depends(get_db)
):
  service = AuthService(db)
  return await service.login(
    email=data.email,
    password=data.password,
    ip=request.client.host,
    user_agent=request.headers.get("user-agent")
  )



# -----------------------
# FORGOT PASSWORD
# -----------------------

@router.post("/forgot-password")
async def forgot_password(
  data: ForgotPasswordRequest,
  background_tasks: BackgroundTasks,
  db: AsyncSession = Depends(get_db)
):
  service = AuthService(db)
  await service.forgot_password(data.email, background_tasks=background_tasks)
  return {"message": "OTP sent"}


@router.post("/resend-reset-password-otp")
async def resend_reset_password_otp(
  data: ResendOTPRequest,
  background_tasks: BackgroundTasks,
  db: AsyncSession = Depends(get_db)
):
  service = AuthService(db)
  await service.resend_reset_password_otp(data.email, background_tasks=background_tasks)
  return {"message": "OTP resent"}



# -----------------------
# RESET PASSWORD
# -----------------------

@router.post("/reset-password")
async def reset_password(
  data: ResetPasswordRequest,
  db: AsyncSession = Depends(get_db)
):
  service = AuthService(db)
  await service.reset_password(
    email=data.email,
    otp_code=data.otp_code,
    new_password=data.new_password
  )
  return {"message": "Password reset"}



# -----------------------
# REFRESH TOKEN
# -----------------------

@router.post("/refresh-token")
async def refresh_token(
  data: RefreshTokenRequest,
  db: AsyncSession = Depends(get_db)
):
  service = AuthService(db)
  access_token = await service.refresh_token(
    data.refresh_token
  )
  return {"access_token": access_token}



# -----------------------
# LOGOUT
# -----------------------

@router.post("/logout")
async def logout(
  data: LogoutRequest,
  db: AsyncSession = Depends(get_db)
):
  service = AuthService(db)
  await service.logout(data.refresh_token)
  return {"message": "Logged out"}