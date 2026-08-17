"""创建补充协议、发票明细与合同发票关系核心空表。

Revision ID: 20260807_009
Revises: 20260807_008
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260807_009"
down_revision: str | None = "20260807_008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplementary_agreements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agreement_no", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("signed_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("confirmation_status", sa.String(length=20), nullable=False),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmation_reason", sa.Text(), nullable=True),
        sa.Column("critical_fact_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("delete_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_confirmation', 'confirmed', 'rejected', 'archived')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        sa.CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["public.organizations.id"],
            name="fk_supplementary_agreements_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["public.contracts.id"],
            name="fk_supplementary_agreements_contract_id_contracts",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["public.users.id"],
            name="fk_supplementary_agreements_confirmed_by_users",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["public.users.id"],
            name="fk_supplementary_agreements_created_by_users",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["public.users.id"],
            name="fk_supplementary_agreements_updated_by_users",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by"],
            ["public.users.id"],
            name="fk_supplementary_agreements_deleted_by_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supplementary_agreements"),
        schema="public",
    )
    op.create_index(
        "idx_supplementary_agreements_contract_effective_status",
        "supplementary_agreements",
        ["contract_id", "effective_date", "status"],
        unique=False,
        schema="public",
    )

    op.create_table(
        "invoice_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("item_name", sa.String(length=500), nullable=True),
        sa.Column("specification", sa.String(length=300), nullable=True),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("amount_excluding_tax", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("tax_rate", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("tax_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.CheckConstraint("line_no > 0", name="line_no_positive"),
        sa.CheckConstraint(
            "tax_rate IS NULL OR tax_rate BETWEEN 0 AND 1",
            name="tax_rate_bounds",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["public.invoices.id"],
            name="fk_invoice_items_invoice_id_invoices",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_invoice_items"),
        sa.UniqueConstraint(
            "invoice_id",
            "line_no",
            name="uq_invoice_items_invoice_id_line_no",
        ),
        schema="public",
    )

    op.create_table(
        "contract_invoices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "match_reasons_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("suggested_by", sa.String(length=20), nullable=True),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('candidate', 'suggested', 'confirmed_primary', 'cancelled')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "suggested_by IS NULL OR suggested_by IN ('system', 'user')",
            name="suggested_by_allowed",
        ),
        sa.CheckConstraint(
            "status <> 'cancelled' OR (cancel_reason IS NOT NULL AND btrim(cancel_reason) <> '')",
            name="cancel_reason_required",
        ),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["public.contracts.id"],
            name="fk_contract_invoices_contract_id_contracts",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["public.invoices.id"],
            name="fk_contract_invoices_invoice_id_invoices",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["public.users.id"],
            name="fk_contract_invoices_confirmed_by_users",
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by"],
            ["public.users.id"],
            name="fk_contract_invoices_cancelled_by_users",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["public.users.id"],
            name="fk_contract_invoices_created_by_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_contract_invoices"),
        schema="public",
    )
    op.create_index(
        "uq_contract_invoice_pair_active",
        "contract_invoices",
        ["contract_id", "invoice_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("deleted_at IS NULL AND status <> 'cancelled'"),
    )
    op.create_index(
        "uq_invoice_confirmed_primary_contract",
        "contract_invoices",
        ["invoice_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("status = 'confirmed_primary' AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE public.contract_invoices IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE public.invoice_items IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE public.supplementary_agreements IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM public.contract_invoices LIMIT 1)
                    OR EXISTS (SELECT 1 FROM public.invoice_items LIMIT 1)
                    OR EXISTS (SELECT 1 FROM public.supplementary_agreements LIMIT 1) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'refusing to drop non-empty financial relationship tables';
                END IF;
            END;
            $$
            """
        )
    )
    op.drop_table("contract_invoices", schema="public")
    op.drop_table("invoice_items", schema="public")
    op.drop_table("supplementary_agreements", schema="public")
