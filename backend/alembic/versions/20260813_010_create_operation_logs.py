"""创建安全操作日志追加式存储。

Revision ID: 20260813_010
Revises: 20260807_009
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_010"
down_revision: str | None = "20260807_009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operation_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_kind", sa.String(length=20), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_code", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "change_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "(action_code COLLATE \"C\") ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$'",
            name="action_code_format",
        ),
        sa.CheckConstraint(
            "(actor_kind = 'user' AND organization_id IS NOT NULL "
            "AND actor_id IS NOT NULL) OR "
            "(actor_kind IN ('anonymous', 'system') AND actor_id IS NULL)",
            name="actor_matrix",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(change_summary_json) = 'object' "
            "AND octet_length(change_summary_json::text) <= 16384",
            name="change_summary_object",
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'denied', 'failed')",
            name="outcome_allowed",
        ),
        sa.CheckConstraint(
            "(resource_type IS NULL AND resource_id IS NULL) OR "
            "(resource_type IS NOT NULL AND resource_id IS NOT NULL)",
            name="resource_matrix",
        ),
        sa.CheckConstraint(
            "resource_type IS NULL OR (resource_type COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'",
            name="resource_type_format",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["public.organizations.id"],
            name="fk_operation_logs_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["public.users.id"],
            name="fk_operation_logs_actor_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_operation_logs"),
        schema="public",
    )
    op.create_index(
        "idx_operation_logs_actor_created",
        "operation_logs",
        ["actor_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
        schema="public",
    )
    op.create_index(
        "idx_operation_logs_organization_created",
        "operation_logs",
        ["organization_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
        schema="public",
    )
    op.create_index(
        "idx_operation_logs_resource_created",
        "operation_logs",
        [
            "resource_type",
            "resource_id",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
        unique=False,
        schema="public",
    )
    op.create_index(
        "idx_operation_logs_trace",
        "operation_logs",
        ["trace_id"],
        unique=False,
        schema="public",
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_operation_logs_append_only_v1()
            RETURNS trigger
            LANGUAGE plpgsql
            VOLATILE
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                RAISE EXCEPTION USING
                    ERRCODE = '55000',
                    MESSAGE = 'operation logs are append-only';
                RETURN NULL;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text("REVOKE ALL ON FUNCTION public.enforce_operation_logs_append_only_v1() FROM PUBLIC")
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_operation_logs_append_only_v1
            BEFORE UPDATE OR DELETE ON public.operation_logs
            FOR EACH ROW
            EXECUTE FUNCTION public.enforce_operation_logs_append_only_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_operation_logs_no_truncate_v1
            BEFORE TRUNCATE ON public.operation_logs
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.enforce_operation_logs_append_only_v1()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE public.operation_logs IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM public.operation_logs LIMIT 1) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'refusing to drop non-empty operation logs';
                END IF;
            END;
            $$
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER trg_operation_logs_no_truncate_v1 ON public.operation_logs"))
    op.execute(sa.text("DROP TRIGGER trg_operation_logs_append_only_v1 ON public.operation_logs"))
    op.drop_table("operation_logs", schema="public")
    op.execute(sa.text("DROP FUNCTION public.enforce_operation_logs_append_only_v1()"))
