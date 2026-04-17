from sqlalchemy import String, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.models.base import Base
from app.models.mixins import TimestampMixin
from app.core.enums import LogAction


class AccessLog(Base, TimestampMixin):

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True
    )

    action: Mapped[LogAction] = mapped_column(
        Enum(LogAction),
        nullable=False
    )

    ip_address: Mapped[str] = mapped_column(
        String(50),
        nullable=True
    )

    user_agent: Mapped[str] = mapped_column(
        String(500),
        nullable=True
    )

    description: Mapped[str] = mapped_column(
        String(500),
        nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="logs")