# app/oauth/google.py

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.oauth.oauth import oauth
from app.core.database import get_db
from app.models.users import User
from app.core.security import create_access_token
from app.services.token_service import TokenService

router = APIRouter()


# -------------------------------
# STEP 1: Redirect to Google Login
# -------------------------------
@router.get("/login")
async def google_login(request: Request):
    # redirect_uri = request.url_for("google_callback")
    redirect_uri = "http://localhost:8001/auth/oauth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


# -------------------------------
# STEP 2: Google Callback
# -------------------------------
@router.get("/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    try:
      # Get token from Google
      token = await oauth.google.authorize_access_token(request)

      print(token)

      # Extract user info
      # user_info = await oauth.google.parse_id_token(request, token)
      resp = await oauth.google.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        token=token
      )
      user_info = resp.json()

      if not user_info:
        raise HTTPException(status_code=400, detail="Failed to fetch user info")

      email = user_info.get("email")
      provider_id = user_info.get("sub")  # unique Google ID
      name = user_info.get("name")

      if not email:
        raise HTTPException(status_code=400, detail="Email not available from Google")

      # -------------------------------
      # STEP 3: Check if user exists
      # -------------------------------
      result = await db.execute(select(User).where(User.email == email))
      user = result.scalar_one_or_none()

      if user:
        # -------------------------------
        # STEP 4: Link account if needed
        # -------------------------------
        if not user.provider:
          user.provider = "google"
          user.provider_id = provider_id
          await db.commit()
          await db.refresh(user)
      else:
        # -------------------------------
        # STEP 5: Create new user
        # -------------------------------
        user_obj = User(
          email=email,
          full_name=name,
          provider="google",
          provider_id=provider_id,
          is_verified=True,  # Google already verifies email
        )
        db.add(user_obj)
        await db.commit()
        await db.refresh(user_obj)

        user = user_obj

      # -------------------------------
      # STEP 6: Generate YOUR JWT (SSO)
      # -------------------------------
      # access_token = create_access_token(user=user)
      access_token, refresh_token = await TokenService.generate_tokens(user)

      # -------------------------------
      # STEP 7: Return token
      # -------------------------------
      return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
        "user": {
          "id": str(user.id),
          "email": user.email,
          "name": user.full_name
        }
      }

    except Exception as e:
      await db.rollback()
      raise HTTPException(status_code=400, detail=str(e))