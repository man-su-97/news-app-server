from sqlalchemy import String, Boolean, Enum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from typing import List

from app.models.base import Base
from app.models.mixins import TimestampMixin
from app.core.enums import UserRole, UserStatus


class User(Base, TimestampMixin):

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=True
    )

    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=True
    )

    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole),
        default=UserRole.USER
    )

    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus),
        default=UserStatus.PENDING
    )

    dob: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    gender: Mapped[str] = mapped_column(
        String(255),
        nullable=True
    )

    provider: Mapped[str] = mapped_column(
        String(255),
        nullable=True
    )

    provider_id: Mapped[str] = mapped_column(
        String(255),
        nullable=True
    )

    # relationships
    otps: Mapped[List["OTP"]] = relationship(back_populates="user")

    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(
        back_populates="user"
    )

    logs: Mapped[List["AccessLog"]] = relationship(
        back_populates="user"
    )