from datetime import datetime

from sqlalchemy import String, ForeignKey, DateTime, Boolean, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.models.base import Base
from app.models.mixins import TimestampMixin
from app.core.enums import OTPType


class OTP(Base, TimestampMixin):

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE")
    )

    otp_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False
    )

    otp_type: Mapped[OTPType] = mapped_column(
        Enum(OTPType),
        nullable=False
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )

    is_used: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    user: Mapped["User"] = relationship(back_populates="otps")