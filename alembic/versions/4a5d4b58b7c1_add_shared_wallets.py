"""add shared wallets

Revision ID: 4a5d4b58b7c1
Revises: 006e277d1355
Create Date: 2026-04-25 19:35:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a5d4b58b7c1"
down_revision: str | Sequence[str] | None = "006e277d1355"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shared_wallets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("total_balance_cents", sa.Integer(), nullable=True),
        sa.Column("spending_limit_cents", sa.Integer(), nullable=True),
        sa.Column("alert_threshold_percent", sa.Integer(), nullable=True),
        sa.Column("join_code", sa.String(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_shared_wallets_id"),
        "shared_wallets",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shared_wallets_join_code"),
        "shared_wallets",
        ["join_code"],
        unique=True,
    )
    op.create_index(
        op.f("ix_shared_wallets_name"), "shared_wallets", ["name"], unique=False
    )

    op.create_table(
        "wallet_members",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("contributed_cents", sa.Integer(), nullable=True),
        sa.Column("spent_cents", sa.Integer(), nullable=True),
        sa.Column("joined_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["wallet_id"], ["shared_wallets.id"]),
        sa.PrimaryKeyConstraint("user_id", "wallet_id"),
    )

    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("initiated_by", sa.Integer(), nullable=True),
        sa.Column("merchant", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["wallet_id"], ["shared_wallets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_wallet_transactions_id"),
        "wallet_transactions",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_wallet_transactions_id"), table_name="wallet_transactions")
    op.drop_table("wallet_transactions")
    op.drop_table("wallet_members")
    op.drop_index(op.f("ix_shared_wallets_name"), table_name="shared_wallets")
    op.drop_index(op.f("ix_shared_wallets_join_code"), table_name="shared_wallets")
    op.drop_index(op.f("ix_shared_wallets_id"), table_name="shared_wallets")
    op.drop_table("shared_wallets")
