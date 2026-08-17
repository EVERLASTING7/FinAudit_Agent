"""创建合同、发票与供应商主数据空表。

Revision ID: 20260807_006
Revises: 20260807_005
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260807_006"
down_revision: str | None = "20260807_005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _require_utf8_server_encoding() -> None:
    if op.get_context().as_sql:
        op.execute(sa.text("SHOW server_encoding"))
        op.execute(
            sa.text(
                """
                DO $$
                BEGIN
                    IF (current_setting('server_encoding') COLLATE "C")
                        <> ('UTF8' COLLATE "C") THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '55000',
                            MESSAGE = 'PostgreSQL server_encoding must be UTF8';
                    END IF;
                END;
                $$
                """
            )
        )
        return

    server_encoding = op.get_bind().execute(sa.text("SHOW server_encoding")).scalar_one()
    if server_encoding != "UTF8":
        raise RuntimeError("PostgreSQL server_encoding must be UTF8")


def upgrade() -> None:
    _require_utf8_server_encoding()

    op.create_table(
        "contracts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_no", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("party_a_name", sa.String(length=300), nullable=True),
        sa.Column("party_a_tax_no", sa.String(length=32), nullable=True),
        sa.Column("party_b_name", sa.String(length=300), nullable=True),
        sa.Column("party_b_tax_no", sa.String(length=32), nullable=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), nullable=True),
        sa.Column("signed_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("payment_method", sa.String(length=100), nullable=True),
        sa.Column("payment_terms", sa.Text(), nullable=True),
        sa.Column("confirmation_status", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            """
            contract_no IS NULL OR (
                (contract_no COLLATE "C") <> ('' COLLATE "C")
                AND (contract_no COLLATE "C")
                    = (btrim(contract_no, ' ') COLLATE "C")
                AND (contract_no COLLATE "C")
                    !~ U&'[\\0001-\\001F\\007F-\\009F]'
            )
            """,
            name="contract_no_normalized",
        ),
        sa.CheckConstraint("amount IS NULL OR amount >= 0", name="amount_nonnegative"),
        sa.CheckConstraint(
            "expiry_date IS NULL OR effective_date IS NULL OR expiry_date >= effective_date",
            name="expiry_not_before_effective",
        ),
        sa.CheckConstraint(
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'expired', 'terminated', 'archived')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_contracts_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name="fk_contracts_confirmed_by_users"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_contracts_created_by_users"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name="fk_contracts_updated_by_users"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], name="fk_contracts_deleted_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_contracts"),
    )
    op.create_index(
        "uq_contracts_organization_contract_no",
        "contracts",
        ["organization_id", sa.text('(contract_no COLLATE "C")')],
        unique=True,
        postgresql_where=sa.text("contract_no IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "idx_contracts_org_status",
        "contracts",
        ["organization_id", "status", sa.text("updated_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_contracts_party_b_tax",
        "contracts",
        ["organization_id", "party_b_tax_no"],
        unique=False,
    )

    op.create_table(
        "invoices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_code", sa.String(length=50), nullable=True),
        sa.Column("invoice_number", sa.String(length=50), nullable=True),
        sa.Column("invoice_type", sa.String(length=40), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("buyer_name", sa.String(length=300), nullable=True),
        sa.Column("buyer_tax_no", sa.String(length=32), nullable=True),
        sa.Column("seller_name", sa.String(length=300), nullable=True),
        sa.Column("seller_tax_no", sa.String(length=32), nullable=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount_excluding_tax", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("tax_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "currency",
            sa.CHAR(length=3),
            nullable=False,
            server_default=sa.text("'CNY'"),
        ),
        sa.Column("confirmation_status", sa.String(length=20), nullable=False),
        sa.Column(
            "duplicate_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'not_checked'"),
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "field_evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        sa.CheckConstraint(
            "duplicate_status IN ('not_checked', 'unique', 'suspected', "
            "'confirmed_duplicate', 'exception_approved')",
            name="duplicate_status_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'voided', 'archived')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_invoices_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name="fk_invoices_confirmed_by_users"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_invoices_created_by_users"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name="fk_invoices_updated_by_users"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], name="fk_invoices_deleted_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_invoices"),
    )
    op.create_index(
        "idx_invoices_duplicate_lookup",
        "invoices",
        ["organization_id", "invoice_code", "invoice_number", "seller_tax_no"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL AND status <> 'voided'"),
    )
    op.create_index(
        "idx_invoices_org_date",
        "invoices",
        ["organization_id", sa.text("invoice_date DESC")],
        unique=False,
    )
    op.create_index(
        "idx_invoices_seller_tax",
        "invoices",
        ["organization_id", "seller_tax_no"],
        unique=False,
    )

    op.create_table(
        "suppliers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("standard_name", sa.String(length=300), nullable=False),
        sa.Column("unified_social_credit_code", sa.String(length=32), nullable=True),
        sa.Column("tax_number", sa.String(length=32), nullable=True),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_contract_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmation_status", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            """
            unified_social_credit_code IS NULL OR (
                (unified_social_credit_code COLLATE "C") <> ('' COLLATE "C")
                AND (unified_social_credit_code COLLATE "C")
                    = (btrim(unified_social_credit_code, ' ') COLLATE "C")
                AND (unified_social_credit_code COLLATE "C")
                    !~ U&'[\\0001-\\001F\\007F-\\009F]'
                AND (unified_social_credit_code COLLATE "C") ~ '^[0-9A-Z]+$'
            )
            """,
            name="unified_social_credit_code_normalized",
        ),
        sa.CheckConstraint(
            """
            tax_number IS NULL OR (
                (tax_number COLLATE "C") <> ('' COLLATE "C")
                AND (tax_number COLLATE "C") = (btrim(tax_number, ' ') COLLATE "C")
                AND (tax_number COLLATE "C")
                    !~ U&'[\\0001-\\001F\\007F-\\009F]'
            )
            """,
            name="tax_number_normalized",
        ),
        sa.CheckConstraint(
            "unified_social_credit_code IS NULL OR tax_number IS NULL OR "
            '(unified_social_credit_code COLLATE "C") '
            '= (tax_number COLLATE "C")',
            name="tax_identity_sources_equal",
        ),
        sa.CheckConstraint(
            "status <> 'active' OR COALESCE(unified_social_credit_code, tax_number) IS NOT NULL",
            name="active_tax_identity_required",
        ),
        sa.CheckConstraint(
            "source_type IN ('contract', 'invoice', 'manual')",
            name="source_type_allowed",
        ),
        sa.CheckConstraint(
            """
            (source_type = 'contract'
                AND source_contract_id IS NOT NULL
                AND source_invoice_id IS NULL)
            OR (source_type = 'invoice'
                AND source_contract_id IS NULL
                AND source_invoice_id IS NOT NULL)
            OR (source_type = 'manual'
                AND source_contract_id IS NULL
                AND source_invoice_id IS NULL)
            """,
            name="source_reference_matches_type",
        ),
        sa.CheckConstraint(
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'active', 'inactive')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_suppliers_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name="fk_suppliers_confirmed_by_users"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_suppliers_created_by_users"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name="fk_suppliers_updated_by_users"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], name="fk_suppliers_deleted_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_suppliers"),
    )
    op.create_index(
        "uq_suppliers_organization_tax_identity",
        "suppliers",
        [
            "organization_id",
            sa.text('(COALESCE(unified_social_credit_code, tax_number) COLLATE "C")'),
        ],
        unique=True,
        postgresql_where=sa.text(
            "status = 'active' AND deleted_at IS NULL AND "
            "COALESCE(unified_social_credit_code, tax_number) IS NOT NULL"
        ),
    )

    op.create_foreign_key(
        "fk_contracts_supplier_id_suppliers",
        "contracts",
        "suppliers",
        ["supplier_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_invoices_supplier_id_suppliers",
        "invoices",
        "suppliers",
        ["supplier_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_suppliers_source_contract_id_contracts",
        "suppliers",
        "contracts",
        ["source_contract_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_suppliers_source_invoice_id_invoices",
        "suppliers",
        "invoices",
        ["source_invoice_id"],
        ["id"],
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE contracts IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE invoices IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE suppliers IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM contracts LIMIT 1)
                    OR EXISTS (SELECT 1 FROM invoices LIMIT 1)
                    OR EXISTS (SELECT 1 FROM suppliers LIMIT 1) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'refusing to drop non-empty financial master tables';
                END IF;
            END;
            $$
            """
        )
    )

    op.drop_constraint("fk_suppliers_source_invoice_id_invoices", "suppliers", type_="foreignkey")
    op.drop_constraint("fk_suppliers_source_contract_id_contracts", "suppliers", type_="foreignkey")
    op.drop_constraint("fk_invoices_supplier_id_suppliers", "invoices", type_="foreignkey")
    op.drop_constraint("fk_contracts_supplier_id_suppliers", "contracts", type_="foreignkey")
    op.drop_table("suppliers")
    op.drop_table("invoices")
    op.drop_table("contracts")
