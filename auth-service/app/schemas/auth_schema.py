from pydantic import BaseModel, EmailStr, Field
from app.core.enums import UserRole


# -----------------------
# REGISTER
# -----------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str
    role: UserRole


class RegisterResponse(BaseModel):
    message: str



# -----------------------
# EMAIL VERIFICATION
# -----------------------

class VerifyEmailRequest(BaseModel):
    email: EmailStr
    otp_code: str = Field(min_length=4, max_length=6)


class ResendOTPRequest(BaseModel):
    email: EmailStr



# -----------------------
# LOGIN
# -----------------------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"



# -----------------------
# PASSWORD RESET
# -----------------------

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp_code: str
    new_password: str = Field(min_length=6)



# -----------------------
# TOKEN
# -----------------------

class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str