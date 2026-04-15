from datetime import datetime

from sqlalchemy import String, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin


class RefreshToken(Base, TimestampMixin):

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE")
    )

    token: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        unique=True,
        index=True
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )

    is_revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")