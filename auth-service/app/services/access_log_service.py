from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.access_logs_repo import AccessLogRepository
from app.core.enums import LogAction


class AccessLogService:

  def __init__(self, db: AsyncSession):
    self.log_repo = AccessLogRepository(db)


  async def log_login(
    self,
    user_id: int,
    ip: str,
    user_agent: str
  ):
    await self.log_repo.create_access_log(
      action=LogAction.LOGIN_SUCCESS,
      user_id=user_id,
      ip_address=ip,
      user_agent=user_agent,
      description="User logged in"
    )