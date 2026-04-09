"""add apartments

Revision ID: a1b2c3d4e5f6
Revises: ec6141f5fc09
Create Date: 2026-04-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'ec6141f5fc09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'apartments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('number', sa.String(length=32), nullable=False),
        sa.Column('call_code', sa.String(length=64), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('apartments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_apartments_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_apartments_number'), ['number'], unique=False)
        batch_op.create_index(batch_op.f('ix_apartments_call_code'), ['call_code'], unique=False)

    op.create_table(
        'apartment_monitors',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('apartment_id', sa.Integer(), nullable=False),
        sa.Column('sip_account', sa.String(length=128), nullable=False),
        sa.Column('label', sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(['apartment_id'], ['apartments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('apartment_monitors', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_apartment_monitors_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_apartment_monitors_apartment_id'), ['apartment_id'], unique=False)


def downgrade() -> None:
    op.drop_table('apartment_monitors')
    op.drop_table('apartments')
