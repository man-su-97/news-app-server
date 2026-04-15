import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from app.models.access_log import AccessLog
from app.core.enums import LogAction

logger = logging.getLogger(__name__)

class AccessLogRepository:
  def __init__(self, db: AsyncSession) -> None:
    self.db = db

  async def create_access_log(
    self, 
    action: LogAction, 
    user_id: int|None = None,
    ip_address: str|None = None,
    user_agent: str|None = None,
    description: str|None = None
  ):
    try:
      access_log = AccessLog(
        action=action,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        description=description
      )
      self.db.add(access_log)
      await self.db.commit()
      await self.db.refresh(access_log)
      return access_log
    except SQLAlchemyError:
      logger.exception("Database error occurred while creating access log.")
      raise
    except Exception as e:
      logger.exception(f"AN UNEXPECTED BUG OCCURRED in create_access_log!\n\n{e}")
      self.db.rollback()
      raise