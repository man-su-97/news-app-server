# app/core/enums.py

from enum import Enum


class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DELETED = "deleted"
    PENDING = "pending"


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"
    SERVICE = "service"


class OTPType(str, Enum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"
    LOGIN = "login"


class LogAction(str, Enum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    TOKEN_REFRESH = "token_refresh"
    OTP_SENT = "otp_sent"
    OTP_VERIFIED = "otp_verified"