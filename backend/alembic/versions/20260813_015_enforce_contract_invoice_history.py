"""强化合同发票关系的状态、组织边界与历史不可变约束。

Revision ID: 20260813_015
Revises: 20260813_014
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_015"
down_revision: str | None = "20260813_014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE public.contract_invoices IN SHARE ROW EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                      FROM public.contract_invoices AS relation
                      LEFT JOIN public.contracts AS contract
                        ON contract.id = relation.contract_id
                      LEFT JOIN public.invoices AS invoice
                        ON invoice.id = relation.invoice_id
                     WHERE contract.id IS NULL
                        OR invoice.id IS NULL
                        OR contract.organization_id IS DISTINCT FROM invoice.organization_id
                        OR (
                            relation.status <> 'cancelled'
                            AND (contract.deleted_at IS NOT NULL OR invoice.deleted_at IS NOT NULL)
                        )
                        OR (
                            relation.status IN ('candidate','suggested','confirmed_primary')
                            AND (
                                contract.confirmation_status IS DISTINCT FROM 'confirmed'
                                OR contract.status IS NOT DISTINCT FROM 'draft'
                            )
                        )
                        OR relation.row_version < 1
                        OR jsonb_typeof(relation.match_reasons_json) IS DISTINCT FROM 'object'
                        OR NOT (
                            relation.match_reasons_json ?& ARRAY['tax_no','name','date']
                        )
                        OR (
                            relation.match_reasons_json - ARRAY['tax_no','name','date']
                        ) <> '{}'::jsonb
                        OR EXISTS (
                            SELECT 1
                              FROM jsonb_each(
                                  CASE
                                      WHEN jsonb_typeof(relation.match_reasons_json) = 'object'
                                      THEN relation.match_reasons_json
                                      ELSE '{}'::jsonb
                                  END
                              ) AS reason(key, value)
                             WHERE jsonb_typeof(reason.value) IS DISTINCT FROM 'object'
                                OR NOT (reason.value ?& ARRAY['status','code'])
                                OR (reason.value - ARRAY['status','code']) <> '{}'::jsonb
                                OR (reason.key, reason.value->>'status', reason.value->>'code')
                                   NOT IN (
                                       ('tax_no','matched','tax_no_matched'),
                                       ('tax_no','mismatched','tax_no_mismatched'),
                                       ('tax_no','unavailable','tax_no_unavailable'),
                                       ('name','matched','name_matched'),
                                       ('name','mismatched','name_mismatched'),
                                       ('name','unavailable','name_unavailable'),
                                       ('date','matched','date_in_range'),
                                       ('date','mismatched','date_out_of_range'),
                                       ('date','unavailable','date_unavailable')
                                   )
                        )
                        OR (
                            relation.status = 'candidate'
                            AND (
                                relation.suggested_by IS DISTINCT FROM 'system'
                                OR relation.confirmed_by IS NOT NULL
                                OR relation.confirmed_at IS NOT NULL
                                OR relation.cancelled_by IS NOT NULL
                                OR relation.cancelled_at IS NOT NULL
                                OR relation.cancel_reason IS NOT NULL
                            )
                        )
                        OR (
                            relation.status = 'suggested'
                            AND (
                                relation.suggested_by IS NULL
                                OR relation.confirmed_by IS NOT NULL
                                OR relation.confirmed_at IS NOT NULL
                                OR relation.cancelled_by IS NOT NULL
                                OR relation.cancelled_at IS NOT NULL
                                OR relation.cancel_reason IS NOT NULL
                            )
                        )
                        OR (
                            relation.status = 'confirmed_primary'
                            AND (
                                relation.confirmed_by IS NULL
                                OR relation.confirmed_at IS NULL
                                OR relation.cancelled_by IS NOT NULL
                                OR relation.cancelled_at IS NOT NULL
                                OR relation.cancel_reason IS NOT NULL
                            )
                        )
                        OR (
                            relation.status = 'cancelled'
                            AND (
                                relation.cancelled_by IS NULL
                                OR relation.cancelled_at IS NULL
                                OR relation.cancel_reason IS NULL
                                OR btrim(relation.cancel_reason) = ''
                            )
                        )
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='legacy contract invoice rows violate revision 015 invariants';
                END IF;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_contract_invoice_history_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                contract_organization_id uuid;
                invoice_organization_id uuid;
                contract_deleted_at timestamptz;
                invoice_deleted_at timestamptz;
                contract_confirmation_status text;
                contract_status text;
            BEGIN
                IF TG_OP = 'TRUNCATE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='contract invoice history cannot be truncated';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='contract invoice history is append-only';
                END IF;

                SELECT organization_id, deleted_at, confirmation_status, status
                  INTO contract_organization_id, contract_deleted_at,
                       contract_confirmation_status, contract_status
                  FROM public.contracts WHERE id = NEW.contract_id FOR KEY SHARE;
                SELECT organization_id, deleted_at
                  INTO invoice_organization_id, invoice_deleted_at
                  FROM public.invoices WHERE id = NEW.invoice_id FOR KEY SHARE;
                IF contract_organization_id IS NOT NULL
                   AND invoice_organization_id IS NOT NULL
                   AND contract_organization_id IS DISTINCT FROM invoice_organization_id THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='contract invoice organization mismatch';
                END IF;
                IF NEW.status <> 'cancelled'
                   AND (contract_deleted_at IS NOT NULL OR invoice_deleted_at IS NOT NULL) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='contract invoice visibility mismatch';
                END IF;
                IF NEW.status IN ('candidate','suggested','confirmed_primary')
                   AND contract_organization_id IS NOT NULL
                   AND (contract_confirmation_status IS DISTINCT FROM 'confirmed'
                        OR contract_status IS NOT DISTINCT FROM 'draft') THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='contract invoice target contract is not linkable';
                END IF;
                IF jsonb_typeof(NEW.match_reasons_json) IS DISTINCT FROM 'object' THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='contract invoice match reasons are invalid';
                END IF;
                IF NOT (NEW.match_reasons_json ?& ARRAY['tax_no','name','date'])
                   OR (NEW.match_reasons_json - ARRAY['tax_no','name','date']) <> '{}'::jsonb
                   OR EXISTS (
                       SELECT 1
                         FROM jsonb_each(NEW.match_reasons_json) AS reason(key, value)
                        WHERE jsonb_typeof(reason.value) IS DISTINCT FROM 'object'
                           OR NOT (reason.value ?& ARRAY['status','code'])
                           OR (reason.value - ARRAY['status','code']) <> '{}'::jsonb
                           OR (reason.key, reason.value->>'status', reason.value->>'code')
                              NOT IN (
                                  ('tax_no','matched','tax_no_matched'),
                                  ('tax_no','mismatched','tax_no_mismatched'),
                                  ('tax_no','unavailable','tax_no_unavailable'),
                                  ('name','matched','name_matched'),
                                  ('name','mismatched','name_mismatched'),
                                  ('name','unavailable','name_unavailable'),
                                  ('date','matched','date_in_range'),
                                  ('date','mismatched','date_out_of_range'),
                                  ('date','unavailable','date_unavailable')
                              )
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='contract invoice match reasons are invalid';
                END IF;
                IF NEW.row_version < 1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='contract invoice row version is invalid';
                END IF;

                IF TG_OP = 'INSERT' AND NEW.status NOT IN ('candidate','suggested') THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='contract invoice history must start as candidate or suggested';
                END IF;
                IF TG_OP = 'INSERT' AND NEW.deleted_at IS NOT NULL THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='contract invoice history cannot start soft deleted';
                END IF;

                IF NEW.status = 'candidate' AND NEW.suggested_by IS DISTINCT FROM 'system' THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='candidate contract invoice must be system suggested';
                END IF;

                IF TG_OP = 'UPDATE' THEN
                    IF NEW.contract_id IS DISTINCT FROM OLD.contract_id
                       OR NEW.invoice_id IS DISTINCT FROM OLD.invoice_id
                       OR NEW.match_reasons_json IS DISTINCT FROM OLD.match_reasons_json
                       OR NEW.suggested_by IS DISTINCT FROM OLD.suggested_by
                       OR NEW.created_at IS DISTINCT FROM OLD.created_at
                       OR NEW.created_by IS DISTINCT FROM OLD.created_by
                       OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at
                       OR NEW.row_version <> OLD.row_version + 1 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='contract invoice identity or row version is invalid';
                    END IF;
                    IF NOT (
                        (OLD.status = 'candidate' AND NEW.status IN ('suggested','cancelled'))
                        OR (OLD.status = 'suggested'
                            AND NEW.status IN ('confirmed_primary','cancelled'))
                        OR (OLD.status = 'confirmed_primary' AND NEW.status = 'cancelled')
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='contract invoice state transition is invalid';
                    END IF;
                    IF OLD.status = 'confirmed_primary' AND (
                        NEW.confirmed_by IS DISTINCT FROM OLD.confirmed_by
                        OR NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='contract invoice confirmation history is immutable';
                    END IF;
                    IF OLD.status IN ('candidate','suggested')
                       AND NEW.status = 'cancelled'
                       AND (NEW.confirmed_by IS NOT NULL OR NEW.confirmed_at IS NOT NULL) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='unconfirmed contract invoice cannot gain confirmation history';
                    END IF;
                END IF;

                IF NEW.status IN ('candidate','suggested') AND (
                    NEW.confirmed_by IS NOT NULL OR NEW.confirmed_at IS NOT NULL
                    OR NEW.cancelled_by IS NOT NULL OR NEW.cancelled_at IS NOT NULL
                    OR NEW.cancel_reason IS NOT NULL
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='contract invoice pending state shape is invalid';
                END IF;
                IF NEW.status = 'suggested' AND NEW.suggested_by IS NULL THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='contract invoice suggestion source is required';
                ELSIF NEW.status = 'confirmed_primary' AND (
                    NEW.confirmed_by IS NULL OR NEW.confirmed_at IS NULL
                    OR NEW.cancelled_by IS NOT NULL OR NEW.cancelled_at IS NOT NULL
                    OR NEW.cancel_reason IS NOT NULL
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='contract invoice confirmation shape is invalid';
                ELSIF NEW.status = 'cancelled' AND (
                    NEW.cancelled_by IS NULL OR NEW.cancelled_at IS NULL
                    OR NEW.cancel_reason IS NULL OR btrim(NEW.cancel_reason) = ''
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='contract invoice cancellation shape is invalid';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text("REVOKE ALL ON FUNCTION public.enforce_contract_invoice_history_v1() FROM PUBLIC")
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_contract_invoices_history_v1 "
            "BEFORE INSERT OR UPDATE OR DELETE ON public.contract_invoices FOR EACH ROW "
            "EXECUTE FUNCTION public.enforce_contract_invoice_history_v1()"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_contract_invoices_no_truncate_v1 "
            "BEFORE TRUNCATE ON public.contract_invoices FOR EACH STATEMENT "
            "EXECUTE FUNCTION public.enforce_contract_invoice_history_v1()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE public.contract_invoices IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM public.contract_invoices LIMIT 1) THEN "
            "RAISE EXCEPTION USING ERRCODE='55000', "
            "MESSAGE='refusing to remove contract invoice history guards from non-empty data'; "
            "END IF; END; $$"
        )
    )
    op.execute(
        sa.text("DROP TRIGGER trg_contract_invoices_no_truncate_v1 ON public.contract_invoices")
    )
    op.execute(sa.text("DROP TRIGGER trg_contract_invoices_history_v1 ON public.contract_invoices"))
    op.execute(sa.text("DROP FUNCTION public.enforce_contract_invoice_history_v1()"))
