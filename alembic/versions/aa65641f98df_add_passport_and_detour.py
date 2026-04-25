"""add passport and detour

Revision ID: aa65641f98df
Revises: 9c5be7474007
Create Date: 2026-04-25 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'aa65641f98df'
down_revision: str | Sequence[str] | None = '9c5be7474007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # event_attendance association table
    op.create_table(
        'event_attendance',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('user_id', 'event_id')
    )

    # detours table
    op.create_table(
        'detours',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_detours_id'), 'detours', ['id'], unique=False)
    op.create_index(op.f('ix_detours_name'), 'detours', ['name'], unique=False)

    # detour_events association table (with order)
    op.create_table(
        'detour_events',
        sa.Column('detour_id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['detour_id'], ['detours.id'], ),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
        sa.PrimaryKeyConstraint('detour_id', 'event_id', 'order')
    )

    # detour_shares association table
    op.create_table(
        'detour_shares',
        sa.Column('detour_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['detour_id'], ['detours.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('detour_id', 'user_id')
    )

    # Add research_count to users
    op.add_column(
        "users",
        sa.Column("research_count", sa.Integer(), nullable=True, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table('detour_shares')
    op.drop_table('detour_events')
    op.drop_index(op.f('ix_detours_name'), table_name='detours')
    op.drop_index(op.f('ix_detours_id'), table_name='detours')
    op.drop_table('detours')
    op.drop_table('event_attendance')
