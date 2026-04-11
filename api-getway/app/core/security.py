from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, HTTPException, status

from app.core.config import settings

security = HTTPBearer()


def decode_access_token(token: str):
  try:
    payload = jwt.decode(
      token,
      settings.JWT_SECRET_KEY,
      algorithms=[settings.JWT_ALGORITHM],
    )
    return payload
  except JWTError:
    return None
  
async def get_token(
  credentials: HTTPAuthorizationCredentials = Depends(security)
):
  """
  Extract token from Authorization header
  """
  if not credentials:
      raise HTTPException(
          status_code=status.HTTP_401_UNAUTHORIZED,
          detail="Authorization token missing"
      )

  return credentials.credentials