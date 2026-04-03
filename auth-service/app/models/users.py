from sqlalchemy import String, Boolean, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List

from app.models.base import Base
from app.models.mixins import TimestampMixin
from app.core.enums import UserRole, UserStatus


class User(Base, TimestampMixin):

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False
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
        default=UserStatus.ACTIVE
    )

    # relationships
    otps: Mapped[List["OTP"]] = relationship(back_populates="user")

    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(
        back_populates="user"
    )

    logs: Mapped[List["AccessLog"]] = relationship(
        back_populates="user"
    )