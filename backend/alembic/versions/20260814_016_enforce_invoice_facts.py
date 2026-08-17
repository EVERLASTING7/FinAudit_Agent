"""强化发票候选、确认事实和明细的数据库状态约束。

Revision ID: 20260814_016
Revises: 20260813_015
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260814_016"
down_revision: str | None = "20260813_015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE public.invoices IN SHARE ROW EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE public.invoice_items IN SHARE ROW EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                      FROM public.invoices
                     WHERE jsonb_typeof(field_evidence_json) IS DISTINCT FROM 'object'
                        OR critical_fact_hash !~ '^[0-9a-f]{64}$'
                        OR row_version < 1
                        OR NOT (
                            (confirmation_status = 'unconfirmed' AND status = 'draft'
                             AND confirmed_by IS NULL AND confirmed_at IS NULL)
                            OR
                            (confirmation_status = 'confirmed'
                             AND status IN ('confirmed','voided','archived')
                             AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
                            OR
                            (confirmation_status = 'rejected' AND status = 'draft'
                             AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
                        )
                ) OR EXISTS (
                    SELECT 1
                      FROM public.invoice_items
                     WHERE jsonb_typeof(evidence_json) IS DISTINCT FROM 'object'
                        OR row_version < 1
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='legacy invoice facts violate revision 016 invariants';
                END IF;
            END;
            $$
            """
        )
    )

    op.create_check_constraint(
        op.f("ck_invoices_field_evidence_object"),
        "invoices",
        "jsonb_typeof(field_evidence_json) = 'object'",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_invoices_critical_fact_hash_format"),
        "invoices",
        "critical_fact_hash ~ '^[0-9a-f]{64}$'",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_invoices_row_version_positive"),
        "invoices",
        "row_version > 0",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_invoices_confirmation_matrix"),
        "invoices",
        "(confirmation_status = 'unconfirmed' AND status = 'draft' "
        "AND confirmed_by IS NULL AND confirmed_at IS NULL) OR "
        "(confirmation_status = 'confirmed' AND status IN "
        "('confirmed', 'voided', 'archived') AND confirmed_by IS NOT NULL "
        "AND confirmed_at IS NOT NULL) OR "
        "(confirmation_status = 'rejected' AND status = 'draft' "
        "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_invoice_items_evidence_object"),
        "invoice_items",
        "jsonb_typeof(evidence_json) = 'object'",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_invoice_items_row_version_positive"),
        "invoice_items",
        "row_version > 0",
        schema="public",
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_invoices_state_v1()
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
                       OR NEW.supplier_id IS DISTINCT FROM OLD.supplier_id
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
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_invoice_items_state_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                parent_confirmation_status text;
                parent_status text;
            BEGIN
                SELECT confirmation_status, status
                  INTO parent_confirmation_status, parent_status
                  FROM public.invoices
                 WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.invoice_id ELSE NEW.invoice_id END
                 FOR KEY SHARE;
                IF parent_confirmation_status IS NULL THEN
                    IF TG_OP = 'DELETE' THEN
                        RETURN OLD;
                    END IF;
                    RETURN NEW;
                END IF;
                IF parent_confirmation_status NOT IN ('unconfirmed','rejected')
                   OR parent_status <> 'draft' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='confirmed invoice items are immutable';
                END IF;
                IF TG_OP = 'INSERT' AND NEW.row_version <> 1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='invoice item must start at row version one';
                ELSIF TG_OP = 'UPDATE' AND (
                    NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.invoice_id IS DISTINCT FROM OLD.invoice_id
                    OR NEW.row_version <> OLD.row_version + 1
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='invoice item identity or row version is invalid';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.prevent_invoice_fact_truncate_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE='invoice facts cannot be truncated';
            END;
            $$
            """
        )
    )
    for function_name in (
        "enforce_invoices_state_v1",
        "enforce_invoice_items_state_v1",
        "prevent_invoice_fact_truncate_v1",
    ):
        op.execute(sa.text(f"REVOKE ALL ON FUNCTION public.{function_name}() FROM PUBLIC"))
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_invoices_state_v1 "
            "BEFORE INSERT OR UPDATE OR DELETE ON public.invoices FOR EACH ROW "
            "EXECUTE FUNCTION public.enforce_invoices_state_v1()"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_invoice_items_state_v1 "
            "BEFORE INSERT OR UPDATE OR DELETE ON public.invoice_items FOR EACH ROW "
            "EXECUTE FUNCTION public.enforce_invoice_items_state_v1()"
        )
    )
    for table_name in ("invoices", "invoice_items"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table_name}_no_truncate_v1 "
                f"BEFORE TRUNCATE ON public.{table_name} FOR EACH STATEMENT "
                "EXECUTE FUNCTION public.prevent_invoice_fact_truncate_v1()"
            )
        )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE public.invoices IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE public.invoice_items IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM public.invoices LIMIT 1) "
            "OR EXISTS (SELECT 1 FROM public.invoice_items LIMIT 1) THEN "
            "RAISE EXCEPTION USING ERRCODE='55000', "
            "MESSAGE='refusing to remove invoice fact guards from non-empty data'; "
            "END IF; END; $$"
        )
    )
    op.execute(sa.text("DROP TRIGGER trg_invoice_items_no_truncate_v1 ON public.invoice_items"))
    op.execute(sa.text("DROP TRIGGER trg_invoices_no_truncate_v1 ON public.invoices"))
    op.execute(sa.text("DROP TRIGGER trg_invoice_items_state_v1 ON public.invoice_items"))
    op.execute(sa.text("DROP TRIGGER trg_invoices_state_v1 ON public.invoices"))
    op.execute(sa.text("DROP FUNCTION public.prevent_invoice_fact_truncate_v1()"))
    op.execute(sa.text("DROP FUNCTION public.enforce_invoice_items_state_v1()"))
    op.execute(sa.text("DROP FUNCTION public.enforce_invoices_state_v1()"))
    for constraint_name, table_name in (
        ("ck_invoice_items_row_version_positive", "invoice_items"),
        ("ck_invoice_items_evidence_object", "invoice_items"),
        ("ck_invoices_confirmation_matrix", "invoices"),
        ("ck_invoices_row_version_positive", "invoices"),
        ("ck_invoices_critical_fact_hash_format", "invoices"),
        ("ck_invoices_field_evidence_object", "invoices"),
    ):
        op.drop_constraint(
            op.f(constraint_name),
            table_name,
            type_="check",
            schema="public",
        )
