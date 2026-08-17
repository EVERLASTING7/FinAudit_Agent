"""为风险解释和报告草稿增加可验证、可降级的持久事实。

Revision ID: 20260816_023
Revises: 20260816_022
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260816_023"
down_revision: str | None = "20260816_022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_ai_payload_columns(table_name: str, prefix: str) -> None:
    op.add_column(
        table_name,
        sa.Column(
            f"{prefix}_status",
            sa.String(length=30),
            nullable=False,
            server_default="disabled",
        ),
    )
    op.add_column(
        table_name,
        sa.Column(f"{prefix}_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column(f"{prefix}_sha256", sa.CHAR(length=64), nullable=True),
    )
    op.create_check_constraint(
        op.f(f"ck_{table_name}_{prefix}_status_allowed"),
        table_name,
        f"{prefix}_status IN ('disabled','succeeded','degraded')",
    )
    op.create_check_constraint(
        op.f(f"ck_{table_name}_{prefix}_object"),
        table_name,
        f"{prefix}_json IS NULL OR jsonb_typeof({prefix}_json)='object'",
    )
    op.create_check_constraint(
        op.f(f"ck_{table_name}_{prefix}_hash_format"),
        table_name,
        f"{prefix}_sha256 IS NULL OR {prefix}_sha256 ~ '^[0-9a-f]{{64}}$'",
    )
    op.create_check_constraint(
        op.f(f"ck_{table_name}_{prefix}_matrix"),
        table_name,
        f"({prefix}_status='succeeded' AND {prefix}_json IS NOT NULL "
        f"AND {prefix}_sha256 IS NOT NULL) OR "
        f"({prefix}_status IN ('disabled','degraded') AND {prefix}_json IS NULL "
        f"AND {prefix}_sha256 IS NULL)",
    )


def _drop_ai_payload_columns(table_name: str, prefix: str) -> None:
    for suffix in ("matrix", "hash_format", "object", "status_allowed"):
        op.drop_constraint(
            op.f(f"ck_{table_name}_{prefix}_{suffix}"),
            table_name,
            type_="check",
        )
    op.drop_column(table_name, f"{prefix}_sha256")
    op.drop_column(table_name, f"{prefix}_json")
    op.drop_column(table_name, f"{prefix}_status")


def _replace_report_state_trigger() -> None:
    op.execute(
        sa.text(
            r"""
            CREATE FUNCTION public.enforce_audit_report_runtime_v2()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,pg_temp
            AS $$
            DECLARE
                parent_org uuid;
                parent_task uuid;
                parent_status text;
            BEGIN
                SELECT organization_id,audit_task_id,status
                  INTO parent_org,parent_task,parent_status
                  FROM public.audit_task_executions
                 WHERE id=COALESCE(NEW.execution_id,OLD.execution_id) FOR UPDATE;
                IF TG_OP='DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='audit reports cannot be deleted';
                ELSIF TG_OP='INSERT' THEN
                    IF parent_org IS DISTINCT FROM NEW.organization_id
                       OR parent_task IS DISTINCT FROM NEW.audit_task_id
                       OR parent_status<>'completed' OR NEW.status<>'queued'
                       OR NEW.row_version<>1 OR NEW.ai_draft_status<>'disabled'
                       OR NEW.ai_draft_json IS NOT NULL OR NEW.ai_draft_sha256 IS NOT NULL THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='audit report parent invalid';
                    END IF;
                ELSE
                    IF ROW(NEW.id,NEW.organization_id,NEW.audit_task_id,NEW.execution_id,
                           NEW.report_version,NEW.payload_sha256,NEW.generator_version,
                           NEW.job_id,NEW.created_by,NEW.created_at,NEW.trace_id)
                       IS DISTINCT FROM
                       ROW(OLD.id,OLD.organization_id,OLD.audit_task_id,OLD.execution_id,
                           OLD.report_version,OLD.payload_sha256,OLD.generator_version,
                           OLD.job_id,OLD.created_by,OLD.created_at,OLD.trace_id)
                       OR NEW.row_version<>OLD.row_version+1 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='audit report transition invalid';
                    END IF;

                    IF OLD.status='generating' AND NEW.status='generating' THEN
                        IF OLD.ai_draft_status<>'disabled'
                           OR NEW.ai_draft_status NOT IN ('succeeded','degraded')
                           OR ROW(
                               NEW.status,NEW.pdf_bucket,NEW.pdf_object_key,NEW.pdf_sha256,
                               NEW.pdf_size_bytes,NEW.pdf_mime_type,NEW.xlsx_bucket,
                               NEW.xlsx_object_key,NEW.xlsx_sha256,NEW.xlsx_size_bytes,
                               NEW.xlsx_mime_type,NEW.failure_code,NEW.generated_at,
                               NEW.outdated_at,NEW.archived_at
                           ) IS DISTINCT FROM ROW(
                               OLD.status,OLD.pdf_bucket,OLD.pdf_object_key,OLD.pdf_sha256,
                               OLD.pdf_size_bytes,OLD.pdf_mime_type,OLD.xlsx_bucket,
                               OLD.xlsx_object_key,OLD.xlsx_sha256,OLD.xlsx_size_bytes,
                               OLD.xlsx_mime_type,OLD.failure_code,OLD.generated_at,
                               OLD.outdated_at,OLD.archived_at
                           ) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='audit report AI draft transition invalid';
                        END IF;
                    ELSIF NOT (
                           (OLD.status='queued' AND NEW.status IN ('generating','failed'))
                        OR (OLD.status='generating' AND NEW.status IN ('ready','failed'))
                        OR (OLD.status='failed' AND NEW.status='queued')
                        OR (OLD.status='ready' AND NEW.status IN ('outdated','archived'))
                        OR (OLD.status='outdated' AND NEW.status='archived')
                    ) OR ROW(
                        NEW.ai_draft_status,NEW.ai_draft_json,NEW.ai_draft_sha256
                    ) IS DISTINCT FROM ROW(
                        OLD.ai_draft_status,OLD.ai_draft_json,OLD.ai_draft_sha256
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='audit report transition invalid';
                    END IF;

                    IF OLD.status IN ('ready','outdated') AND ROW(
                        NEW.pdf_bucket,NEW.pdf_object_key,NEW.pdf_sha256,NEW.pdf_size_bytes,
                        NEW.xlsx_bucket,NEW.xlsx_object_key,NEW.xlsx_sha256,NEW.xlsx_size_bytes,
                        NEW.generated_at
                    ) IS DISTINCT FROM ROW(
                        OLD.pdf_bucket,OLD.pdf_object_key,OLD.pdf_sha256,OLD.pdf_size_bytes,
                        OLD.xlsx_bucket,OLD.xlsx_object_key,OLD.xlsx_sha256,OLD.xlsx_size_bytes,
                        OLD.generated_at
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='ready report artifacts are immutable';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$;
            REVOKE ALL ON FUNCTION public.enforce_audit_report_runtime_v2() FROM PUBLIC;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER trg_audit_reports_state_v1 ON public.audit_reports"))
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_audit_reports_state_v1 "
            "BEFORE INSERT OR UPDATE OR DELETE ON public.audit_reports "
            "FOR EACH ROW EXECUTE FUNCTION public.enforce_audit_report_runtime_v2()"
        )
    )


def _restore_report_state_trigger() -> None:
    op.execute(sa.text("DROP TRIGGER trg_audit_reports_state_v1 ON public.audit_reports"))
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_audit_reports_state_v1 "
            "BEFORE INSERT OR UPDATE OR DELETE ON public.audit_reports "
            "FOR EACH ROW EXECUTE FUNCTION public.enforce_audit_report_runtime_v1()"
        )
    )
    op.execute(sa.text("DROP FUNCTION public.enforce_audit_report_runtime_v2()"))


def upgrade() -> None:
    _add_ai_payload_columns("audit_risks", "ai_explanation")
    _add_ai_payload_columns("audit_reports", "ai_draft")
    _replace_report_state_trigger()


def downgrade() -> None:
    _restore_report_state_trigger()
    _drop_ai_payload_columns("audit_reports", "ai_draft")
    _drop_ai_payload_columns("audit_risks", "ai_explanation")
