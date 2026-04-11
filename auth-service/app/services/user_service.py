import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user_repo import UserRepository
from app.core.enums import UserStatus, UserRole

logger = logging.getLogger(__name__)

class UserService:

  def __init__(self, db: AsyncSession):
    self.user_repo = UserRepository(db)

  async def register_user(
    self,
    email: str,
    password_hash: str,
    full_name: str,
    role: UserRole
  ):
    existing_user = await self.user_repo.get_by_email(email)

    if existing_user:
      raise ValueError("User already exists")

    user = await self.user_repo.create(
      email=email,
      password_hash=password_hash,
      full_name=full_name,
      is_verified=False,
      status=UserStatus.PENDING,
      role=role
    )

    return user
  

  async def get_user_by_email(self, email: str):
    return await self.user_repo.get_by_email(email)


  async def verify_user(self, user_id: int):
    return await self.user_repo.mark_user_verified(user_id)


  async def update_password(
    self,
    user_id: int,
    new_password_hash: str
  ):
    return await self.user_repo.update_user_password(
      user_id=user_id,
      password_hash=new_password_hash
    )
  

  async def update_status(
    self,
    user_id: int,
    status: UserStatus
  ):
    return await self.user_repo.update_user_status(
      user_id=user_id,
      status=status
    )