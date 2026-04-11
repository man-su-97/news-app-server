import logging
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.users import User
from app.core.enums import UserStatus, UserRole

logger = logging.getLogger(__name__)

class UserRepository:
  def __init__(self, db: AsyncSession) -> None:
    self.db = db

  async def create(self,
    email: str,
    password_hash: str,
    full_name: str,
    is_verified: bool,
    status: str,
    role: UserRole = UserRole.USER
  ):
    try:
      user = User(
        email=email,
        password_hash=password_hash,
        full_name=full_name,
        is_verified=is_verified,
        role=role,
        status=status
      )
      self.db.add(user)
      await self.db.commit()
      await self.db.refresh(user)
      return user
    except SQLAlchemyError:
      logger.exception("Database error occurred while creating user.")
      raise
    except Exception as e:
      logger.error(f"Error creating user: {e}")
      self.db.rollback()
      raise
    
  async def get_by_email(self, email: str):
    try:
      result = await self.db.execute(select(User).where(User.email == email))
      return result.scalar_one_or_none()
    except SQLAlchemyError:
      logger.exception("Database error occurred while getting user by email.")
      raise
    except Exception as e:
      logger.error(f"Error getting user by email: {e}")
      self.db.rollback()
      raise
    
  async def get_by_id(self, user_id: int):
    try:
      result = await self.db.execute(select(User).where(User.id == user_id))
      return result.scalar_one_or_none()
    except SQLAlchemyError:
      logger.exception("Database error occurred while getting user by id.")
      raise
    except Exception as e:
      logger.error(f"Error getting user by id: {e}")
      self.db.rollback()
      raise
    
  async def update_user_password(self, user_id: int, password_hash: str):
    try:
      result = await self.db.execute(select(User).where(User.id == user_id))
      user = result.scalar_one_or_none()
      if not user:
        logger.error(f"User with id {user_id} not found")
        return None
      user.password_hash = password_hash
      await self.db.commit()
      await self.db.refresh(user)
      return user
    except SQLAlchemyError:
      logger.exception("Database error occurred while updating user password.")
      raise
    except Exception as e:
      logger.error(f"Error updating user password: {e}")
      self.db.rollback()
      raise
    
  async def mark_user_verified(self, user_id: int):
    try:
      result = await self.db.execute(select(User).where(User.id == user_id))
      user = result.scalar_one_or_none()
      if not user:
        logger.error(f"User with id {user_id} not found")
        return None
      user.is_verified = True
      await self.db.commit()
      await self.db.refresh(user)
      return user
    except SQLAlchemyError:
      logger.exception("Database error occurred while marking user as verified.")
      raise
    except Exception as e:
      logger.error(f"Error marking user as verified: {e}")
      self.db.rollback()
      raise
    
  async def update_user_status(self, user_id: int, status: UserStatus):
    try:
      result = await self.db.execute(select(User).where(User.id == user_id))
      user = result.scalar_one_or_none()
      if not user:
        logger.error(f"User with id {user_id} not found")
        return None
      user.status = status
      await self.db.commit()
      await self.db.refresh(user)
      return user
    except SQLAlchemyError:
      logger.exception("Database error occurred while updating user status.")
      raise
    except Exception as e:
      logger.error(f"Error updating user status: {e}")
      self.db.rollback()
      raise