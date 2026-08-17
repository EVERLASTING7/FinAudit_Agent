"""允许未确认发票缺少币种，并移除无证据的 CNY 默认值。

Revision ID: 20260816_022
Revises: 20260815_021
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260816_022"
down_revision: str | None = "20260815_021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.alter_column(
        "invoices",
        "currency",
        existing_type=sa.CHAR(length=3),
        nullable=True,
        server_default=None,
    )
    op.create_check_constraint(
        op.f("ck_invoices_confirmed_currency_required"),
        "invoices",
        "confirmation_status <> 'confirmed' OR currency IS NOT NULL",
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.drop_constraint(
        op.f("ck_invoices_confirmed_currency_required"),
        "invoices",
        type_="check",
    )
    op.execute(sa.text("UPDATE invoices SET currency = 'CNY' WHERE currency IS NULL"))
    op.alter_column(
        "invoices",
        "currency",
        existing_type=sa.CHAR(length=3),
        nullable=False,
        server_default=sa.text("'CNY'"),
    )
