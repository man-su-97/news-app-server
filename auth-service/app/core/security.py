from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from jose import jwt
from app.core.config import settings
from app.models.users import User

pwd_context = CryptContext(
  schemes=["bcrypt"], 
  deprecated="auto"
)

def hash_password(password: str) -> str:
  """
  Hash a password using the best available password hashing algorithm.

  :param password: The password to hash.
  :return: The hashed password.
  """
  return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
  """
  Verify that a plain password matches a hashed password.

  :param plain_password: The plain password to verify.
  :param hashed_password: The hashed password to verify against.
  :return: Whether the plain password matches the hashed password.
  """
  return pwd_context.verify(plain_password, hashed_password)

def create_access_token(user: User, expires_minutes: int = 30):
  """
  Create an access token for a user.

  :param user_id: The ID of the user to create an access token for.
  :param expires_minutes: The number of minutes until the access token expires. Defaults to 30 minutes.
  :return: The generated access token.
  """
  expire = datetime.now(tz=timezone.utc) + timedelta(minutes=expires_minutes)
  payload = {
    "user_id": user.id,
    "email": user.email,
    "role": user.role, 
    "exp": expire
  }
  return jwt.encode(payload, key=settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def create_refresh_token():
  """
  Generates a secure, URL-safe, random token for use as a refresh token.

  :return: A secure, URL-safe, random token.
  """
  import secrets
  return secrets.token_urlsafe(32)