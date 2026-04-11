"""add pending to userstatus enum

Revision ID: 7f634735328f
Revises: 9d0afd75cbd5
Create Date: 2026-04-09 12:48:22.904428

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f634735328f'
down_revision: Union[str, Sequence[str], None] = '9d0afd75cbd5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE userstatus ADD VALUE 'PENDING'")
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
