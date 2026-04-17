"""All tables fk modified related to user

Revision ID: d6a7d7c23666
Revises: 7f634735328f
Create Date: 2026-04-16 10:47:56.492944

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6a7d7c23666'
down_revision: Union[str, Sequence[str], None] = '7f634735328f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # 1. DROP EXISTING FOREIGN KEYS FIRST
    op.drop_constraint('fk_accesslog_user_id_user', 'accesslog', type_='foreignkey')
    op.drop_constraint('fk_otp_user_id_user', 'otp', type_='foreignkey')
    op.drop_constraint('fk_refreshtoken_user_id_user', 'refreshtoken', type_='foreignkey')

    # 2. DROP THE INTEGER SEQUENCE DEFAULT 
    # This prevents the "default cannot be cast to uuid" error
    op.alter_column('user', 'id', server_default=None)

    # 3. ALTER COLUMNS TO UUID
    op.alter_column('user', 'id',
               existing_type=sa.INTEGER(),
               type_=sa.UUID(),
               existing_nullable=False,
               postgresql_using="lpad(id::text, 32, '0')::uuid")

    op.alter_column('accesslog', 'user_id',
               existing_type=sa.INTEGER(),
               type_=sa.UUID(),
               existing_nullable=True,
               postgresql_using="lpad(user_id::text, 32, '0')::uuid")
               
    op.alter_column('otp', 'user_id',
               existing_type=sa.INTEGER(),
               type_=sa.UUID(),
               existing_nullable=False,
               postgresql_using="lpad(user_id::text, 32, '0')::uuid")
               
    op.alter_column('refreshtoken', 'user_id',
               existing_type=sa.INTEGER(),
               type_=sa.UUID(),
               existing_nullable=False,
               postgresql_using="lpad(user_id::text, 32, '0')::uuid")
               
    # ADD NEW COLUMNS & ALTER OTHERS
    op.add_column('user', sa.Column('dob', sa.DateTime(timezone=True), nullable=True))
    op.add_column('user', sa.Column('gender', sa.String(length=255), nullable=True))
    op.add_column('user', sa.Column('provider', sa.String(length=255), nullable=True))
    op.add_column('user', sa.Column('provider_id', sa.String(length=255), nullable=True))
               
    op.alter_column('user', 'password_hash',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)

    # 4. RECREATE FOREIGN KEYS
    op.create_foreign_key('fk_accesslog_user_id_user', 'accesslog', 'user', ['user_id'], ['id'])
    op.create_foreign_key('fk_otp_user_id_user', 'otp', 'user', ['user_id'], ['id'])
    op.create_foreign_key('fk_refreshtoken_user_id_user', 'refreshtoken', 'user', ['user_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    
    # 1. DROP UUID FOREIGN KEYS
    op.drop_constraint('fk_accesslog_user_id_user', 'accesslog', type_='foreignkey')
    op.drop_constraint('fk_otp_user_id_user', 'otp', type_='foreignkey')
    op.drop_constraint('fk_refreshtoken_user_id_user', 'refreshtoken', type_='foreignkey')

    # 2. REVERT COLUMNS TO INTEGER
    op.alter_column('user', 'id',
               existing_type=sa.UUID(),
               type_=sa.INTEGER(),
               existing_nullable=False)

    op.alter_column('refreshtoken', 'user_id',
               existing_type=sa.UUID(),
               type_=sa.INTEGER(),
               existing_nullable=False)
               
    op.alter_column('otp', 'user_id',
               existing_type=sa.UUID(),
               type_=sa.INTEGER(),
               existing_nullable=False)
               
    op.alter_column('accesslog', 'user_id',
               existing_type=sa.UUID(),
               type_=sa.INTEGER(),
               existing_nullable=True)

    # REVERT OTHER COLUMNS
    op.alter_column('user', 'password_hash',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)
    op.drop_column('user', 'provider_id')
    op.drop_column('user', 'provider')
    op.drop_column('user', 'gender')
    op.drop_column('user', 'dob')

    # 3. RECREATE INTEGER FOREIGN KEYS
    op.create_foreign_key('fk_accesslog_user_id_user', 'accesslog', 'user', ['user_id'], ['id'])
    op.create_foreign_key('fk_otp_user_id_user', 'otp', 'user', ['user_id'], ['id'])
    op.create_foreign_key('fk_refreshtoken_user_id_user', 'refreshtoken', 'user', ['user_id'], ['id'])