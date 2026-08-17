"""强化供应商三态、来源候选唯一性与人工纠错类型。

Revision ID: 20260814_017
Revises: 20260814_016
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260814_017"
down_revision: str | None = "20260814_016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_invoice_state_function(*, allow_supplier_backfill: bool) -> None:
    supplier_guard = (
        "OR (NEW.supplier_id IS DISTINCT FROM OLD.supplier_id AND NOT "
        "(OLD.supplier_id IS NULL AND NEW.supplier_id IS NOT NULL))"
        if allow_supplier_backfill
        else "OR NEW.supplier_id IS DISTINCT FROM OLD.supplier_id"
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION public.enforce_invoices_state_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='invoice facts cannot be deleted';
                END IF;
                IF TG_OP = 'INSERT' THEN
                    IF NEW.row_version <> 1 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='invoice must start at row version one';
                    END IF;
                    RETURN NEW;
                END IF;

                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at
                   OR NEW.created_by IS DISTINCT FROM OLD.created_by
                   OR NEW.row_version <> OLD.row_version + 1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='invoice identity or row version is invalid';
                END IF;

                IF OLD.confirmation_status = 'unconfirmed' THEN
                    IF NOT (
                        (NEW.confirmation_status = 'unconfirmed' AND NEW.status = 'draft')
                        OR (NEW.confirmation_status = 'confirmed' AND NEW.status = 'confirmed')
                        OR (NEW.confirmation_status = 'rejected' AND NEW.status = 'draft')
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='invoice state transition is invalid';
                    END IF;
                ELSIF OLD.confirmation_status = 'rejected' THEN
                    IF NOT (
                        (NEW.confirmation_status = 'rejected' AND NEW.status = 'draft')
                        OR (NEW.confirmation_status = 'unconfirmed' AND NEW.status = 'draft')
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='invoice state transition is invalid';
                    END IF;
                ELSE
                    IF NEW.confirmation_status <> 'confirmed'
                       OR NOT (
                           (OLD.status = 'confirmed'
                            AND NEW.status IN ('confirmed','voided','archived'))
                           OR (OLD.status = 'voided'
                               AND NEW.status IN ('voided','archived'))
                           OR (OLD.status = 'archived' AND NEW.status = 'archived')
                       ) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='invoice confirmed state is immutable';
                    END IF;
                    IF NEW.invoice_code IS DISTINCT FROM OLD.invoice_code
                       OR NEW.invoice_number IS DISTINCT FROM OLD.invoice_number
                       OR NEW.invoice_type IS DISTINCT FROM OLD.invoice_type
                       OR NEW.invoice_date IS DISTINCT FROM OLD.invoice_date
                       OR NEW.buyer_name IS DISTINCT FROM OLD.buyer_name
                       OR NEW.buyer_tax_no IS DISTINCT FROM OLD.buyer_tax_no
                       OR NEW.seller_name IS DISTINCT FROM OLD.seller_name
                       OR NEW.seller_tax_no IS DISTINCT FROM OLD.seller_tax_no
                       {supplier_guard}
                       OR NEW.amount_excluding_tax IS DISTINCT FROM OLD.amount_excluding_tax
                       OR NEW.tax_amount IS DISTINCT FROM OLD.tax_amount
                       OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
                       OR NEW.currency IS DISTINCT FROM OLD.currency
                       OR NEW.field_evidence_json IS DISTINCT FROM OLD.field_evidence_json
                       OR NEW.critical_fact_hash IS DISTINCT FROM OLD.critical_fact_hash
                       OR NEW.confirmed_by IS DISTINCT FROM OLD.confirmed_by
                       OR NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='confirmed invoice facts are immutable';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE public.suppliers IN SHARE ROW EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE public.user_corrections IN SHARE ROW EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            r"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                      FROM public.suppliers
                     WHERE btrim(standard_name) = ''
                        OR standard_name <> btrim(standard_name)
                        OR standard_name ~ U&'[\0001-\001F\007F-\009F]'
                        OR row_version < 1
                        OR NOT (
                            (confirmation_status = 'unconfirmed' AND status = 'candidate'
                             AND confirmed_by IS NULL AND confirmed_at IS NULL)
                            OR
                            (confirmation_status = 'confirmed' AND status = 'active'
                             AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
                            OR
                            (confirmation_status = 'rejected' AND status = 'inactive'
                             AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
                        )
                ) OR EXISTS (
                    SELECT 1
                      FROM public.suppliers
                     WHERE status = 'candidate' AND deleted_at IS NULL
                     GROUP BY organization_id, source_contract_id
                    HAVING source_contract_id IS NOT NULL AND count(*) > 1
                ) OR EXISTS (
                    SELECT 1
                      FROM public.suppliers
                     WHERE status = 'candidate' AND deleted_at IS NULL
                     GROUP BY organization_id, source_invoice_id
                    HAVING source_invoice_id IS NOT NULL AND count(*) > 1
                ) OR EXISTS (
                    SELECT 1
                      FROM public.contracts AS source
                      LEFT JOIN public.suppliers AS supplier
                        ON supplier.id = source.supplier_id
                       AND supplier.organization_id = source.organization_id
                       AND supplier.confirmation_status = 'confirmed'
                       AND supplier.status = 'active'
                       AND supplier.deleted_at IS NULL
                     WHERE source.supplier_id IS NOT NULL AND supplier.id IS NULL
                ) OR EXISTS (
                    SELECT 1
                      FROM public.invoices AS source
                      LEFT JOIN public.suppliers AS supplier
                        ON supplier.id = source.supplier_id
                       AND supplier.organization_id = source.organization_id
                       AND supplier.confirmation_status = 'confirmed'
                       AND supplier.status = 'active'
                       AND supplier.deleted_at IS NULL
                     WHERE source.supplier_id IS NOT NULL AND supplier.id IS NULL
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='legacy supplier facts violate revision 017 invariants';
                END IF;
            END;
            $$
            """
        )
    )

    op.create_check_constraint(
        op.f("ck_suppliers_standard_name_normalized"),
        "suppliers",
        "btrim(standard_name) <> '' AND standard_name = btrim(standard_name) "
        "AND standard_name !~ U&'[\\0001-\\001F\\007F-\\009F]'",
        schema="public",
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_financial_supplier_binding_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                target_exists boolean;
            BEGIN
                IF TG_OP = 'UPDATE'
                   AND OLD.supplier_id IS NOT NULL
                   AND NEW.supplier_id IS DISTINCT FROM OLD.supplier_id THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='bound financial supplier cannot be replaced';
                END IF;
                IF NEW.supplier_id IS NULL THEN
                    RETURN NEW;
                END IF;
                SELECT true
                  INTO target_exists
                  FROM public.suppliers
                 WHERE id = NEW.supplier_id
                   AND organization_id = NEW.organization_id
                   AND confirmation_status = 'confirmed'
                   AND status = 'active'
                   AND deleted_at IS NULL
                 FOR KEY SHARE;
                IF target_exists IS DISTINCT FROM true THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='financial supplier binding target is invalid';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    for table_name in ("contracts", "invoices"):
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table_name}_supplier_binding_v1
                BEFORE INSERT OR UPDATE OF supplier_id, organization_id
                ON public.{table_name}
                FOR EACH ROW EXECUTE FUNCTION public.enforce_financial_supplier_binding_v1()
                """
            )
        )
    _replace_invoice_state_function(allow_supplier_backfill=True)
    op.create_check_constraint(
        op.f("ck_suppliers_row_version_positive"),
        "suppliers",
        "row_version > 0",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_suppliers_confirmation_matrix"),
        "suppliers",
        "(confirmation_status = 'unconfirmed' AND status = 'candidate' "
        "AND confirmed_by IS NULL AND confirmed_at IS NULL) OR "
        "(confirmation_status = 'confirmed' AND status = 'active' "
        "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL) OR "
        "(confirmation_status = 'rejected' AND status = 'inactive' "
        "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)",
        schema="public",
    )
    op.create_index(
        "uq_suppliers_organization_source_contract_candidate",
        "suppliers",
        ["organization_id", "source_contract_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text(
            "status = 'candidate' AND deleted_at IS NULL AND source_contract_id IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_suppliers_organization_source_invoice_candidate",
        "suppliers",
        ["organization_id", "source_invoice_id"],
        unique=True,
        schema="public",
        postgresql_where=sa.text(
            "status = 'candidate' AND deleted_at IS NULL AND source_invoice_id IS NOT NULL"
        ),
    )

    op.drop_constraint(
        op.f("ck_user_corrections_correction_type_allowed"),
        "user_corrections",
        schema="public",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_corrections_correction_type_allowed"),
        "user_corrections",
        "correction_type IN ('contract_field', 'supplementary_agreement_changes', "
        "'invoice_field', 'contract_invoice', 'supplier_field')",
        schema="public",
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE public.suppliers IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE public.user_corrections IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM public.user_corrections
                     WHERE correction_type = 'supplier_field' LIMIT 1
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='refusing to remove supplier correction contract '
                            || 'with business rows';
                END IF;
            END;
            $$
            """
        )
    )

    _replace_invoice_state_function(allow_supplier_backfill=False)
    for table_name in ("invoices", "contracts"):
        op.execute(
            sa.text(f"DROP TRIGGER trg_{table_name}_supplier_binding_v1 ON public.{table_name}")
        )
    op.execute(sa.text("DROP FUNCTION public.enforce_financial_supplier_binding_v1()"))

    op.drop_constraint(
        op.f("ck_user_corrections_correction_type_allowed"),
        "user_corrections",
        schema="public",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_corrections_correction_type_allowed"),
        "user_corrections",
        "correction_type IN ('contract_field', 'supplementary_agreement_changes', "
        "'invoice_field', 'contract_invoice')",
        schema="public",
    )
    op.drop_index(
        "uq_suppliers_organization_source_invoice_candidate",
        table_name="suppliers",
        schema="public",
    )
    op.drop_index(
        "uq_suppliers_organization_source_contract_candidate",
        table_name="suppliers",
        schema="public",
    )
    op.drop_constraint(
        op.f("ck_suppliers_confirmation_matrix"),
        "suppliers",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_suppliers_row_version_positive"),
        "suppliers",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_suppliers_standard_name_normalized"),
        "suppliers",
        schema="public",
        type_="check",
    )
