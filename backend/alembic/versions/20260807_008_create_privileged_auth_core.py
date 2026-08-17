"""创建特权授权请求与角色分配核心空表。

Revision ID: 20260807_008
Revises: 20260807_007
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260807_008"
down_revision: str | None = "20260807_007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 008 不拥有角色种子；任何漂移都必须在首个 DDL 前失败。
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF (SELECT count(*) FROM public.roles) <> 5
                    OR (SELECT count(*) FROM public.roles
                        WHERE code IN (
                            'audit_reviewer', 'contract_admin', 'finance_reviewer',
                            'read_only', 'system_admin'
                        )) <> 5
                    OR (SELECT count(DISTINCT code) FROM public.roles) <> 5
                    OR EXISTS (
                        SELECT 1 FROM public.roles
                        WHERE is_system_role IS DISTINCT FROM TRUE
                    ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'fixed privileged-auth role preflight failed';
                END IF;
            END;
            $$
            """
        )
    )

    op.create_table(
        "break_glass_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_role_code", sa.String(length=40), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "target_role_code IN ('system_admin', 'finance_reviewer', "
            "'audit_reviewer', 'contract_admin')",
            name="target_role_code_allowed",
        ),
        sa.CheckConstraint(
            "requested_duration_seconds BETWEEN 1 AND 14400",
            name="requested_duration_bounds",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'revoked', 'expired')",
            name="status_allowed",
        ),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason_nonempty"),
        sa.CheckConstraint(
            "decision_reason IS NULL OR length(btrim(decision_reason)) > 0",
            name="decision_reason_nonempty",
        ),
        sa.CheckConstraint(
            "revoke_reason IS NULL OR length(btrim(revoke_reason)) > 0",
            name="revoke_reason_nonempty",
        ),
        sa.CheckConstraint("row_version > 0", name="row_version_positive"),
        sa.CheckConstraint(
            """
            (status = 'pending'
                AND effective_from IS NULL AND expires_at IS NULL
                AND decided_by IS NULL AND decision_at IS NULL
                AND decision_reason IS NULL AND revoked_by IS NULL
                AND revoked_at IS NULL AND revoke_reason IS NULL)
            OR (status = 'approved'
                AND effective_from IS NOT NULL AND expires_at IS NOT NULL
                AND decided_by IS NOT NULL AND decision_at IS NOT NULL
                AND decision_reason IS NOT NULL AND revoked_by IS NULL
                AND revoked_at IS NULL AND revoke_reason IS NULL)
            OR (status = 'rejected'
                AND effective_from IS NULL AND expires_at IS NULL
                AND decided_by IS NOT NULL AND decision_at IS NOT NULL
                AND decision_reason IS NOT NULL AND revoked_by IS NULL
                AND revoked_at IS NULL AND revoke_reason IS NULL)
            OR (status = 'revoked'
                AND effective_from IS NOT NULL AND expires_at IS NOT NULL
                AND decided_by IS NOT NULL AND decision_at IS NOT NULL
                AND decision_reason IS NOT NULL AND revoked_by IS NOT NULL
                AND revoked_at IS NOT NULL AND revoke_reason IS NOT NULL)
            OR (status = 'expired'
                AND effective_from IS NOT NULL AND expires_at IS NOT NULL
                AND decided_by IS NOT NULL AND decision_at IS NOT NULL
                AND decision_reason IS NOT NULL AND revoked_by IS NULL
                AND revoked_at IS NULL AND revoke_reason IS NULL)
            """,
            name="state_field_matrix",
        ),
        sa.CheckConstraint(
            """
            created_at <= updated_at AND (
                (status = 'pending' AND updated_at = created_at)
                OR (status = 'approved'
                    AND created_at <= decision_at
                    AND decision_at = effective_from
                    AND effective_from < expires_at
                    AND expires_at = effective_from
                        + requested_duration_seconds * interval '1 second'
                    AND updated_at = decision_at)
                OR (status = 'rejected'
                    AND created_at <= decision_at
                    AND updated_at = decision_at)
                OR (status = 'revoked'
                    AND created_at <= decision_at
                    AND decision_at = effective_from
                    AND effective_from < expires_at
                    AND expires_at = effective_from
                        + requested_duration_seconds * interval '1 second'
                    AND effective_from <= revoked_at
                    AND revoked_at < expires_at
                    AND updated_at = revoked_at)
                OR (status = 'expired'
                    AND created_at <= decision_at
                    AND decision_at = effective_from
                    AND effective_from < expires_at
                    AND expires_at = effective_from
                        + requested_duration_seconds * interval '1 second'
                    AND updated_at >= expires_at)
            )
            """,
            name="time_matrix",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["public.organizations.id"],
            name="fk_break_glass_requests_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["public.users.id"],
            name="fk_break_glass_requests_target_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["public.users.id"],
            name="fk_break_glass_requests_requested_by_users",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["public.users.id"],
            name="fk_break_glass_requests_decided_by_users",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["public.users.id"],
            name="fk_break_glass_requests_revoked_by_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_break_glass_requests"),
        schema="public",
    )

    op.create_table(
        "user_roles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assignment_source", sa.String(length=20), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("break_glass_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assignment_reason", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "assignment_source IN ('bootstrap', 'user', 'break_glass')",
            name="assignment_source_allowed",
        ),
        sa.CheckConstraint(
            """
            (assignment_source = 'bootstrap'
                AND assigned_by IS NULL AND expires_at IS NULL
                AND break_glass_request_id IS NULL
                AND assignment_reason = 'system_bootstrap')
            OR (assignment_source = 'user'
                AND assigned_by IS NOT NULL AND expires_at IS NULL
                AND break_glass_request_id IS NULL)
            OR (assignment_source = 'break_glass'
                AND assigned_by IS NOT NULL AND expires_at IS NOT NULL
                AND break_glass_request_id IS NOT NULL)
            """,
            name="assignment_source_matrix",
        ),
        sa.CheckConstraint(
            "length(btrim(assignment_reason)) > 0 "
            "AND (assignment_source <> 'user' "
            "OR assignment_reason = btrim(assignment_reason))",
            name="assignment_reason_nonempty",
        ),
        sa.CheckConstraint(
            """
            (revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason IS NULL)
            OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL
                AND revoke_reason IS NOT NULL AND length(btrim(revoke_reason)) > 0
                AND (assignment_source = 'break_glass'
                    OR revoke_reason = btrim(revoke_reason)))
            """,
            name="revocation_matrix",
        ),
        sa.CheckConstraint(
            "(expires_at IS NULL OR assigned_at < expires_at) "
            "AND (revoked_at IS NULL OR revoked_at >= assigned_at)",
            name="time_order",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["public.users.id"], name="fk_user_roles_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["public.roles.id"], name="fk_user_roles_role_id_roles"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"], ["public.users.id"], name="fk_user_roles_assigned_by_users"
        ),
        sa.ForeignKeyConstraint(
            ["break_glass_request_id"],
            ["public.break_glass_requests.id"],
            name="fk_user_roles_break_glass_request_id_break_glass_requests",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"], ["public.users.id"], name="fk_user_roles_revoked_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_roles"),
        sa.UniqueConstraint(
            "break_glass_request_id",
            name="uq_user_roles_break_glass_request_id",
        ),
        schema="public",
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE public.user_roles
            ADD CONSTRAINT ex_user_roles_effective_range_no_overlap
            EXCLUDE USING gist (
                user_id WITH =,
                role_id WITH =,
                tstzrange(
                    assigned_at,
                    COALESCE(expires_at, 'infinity'::timestamptz),
                    '[)'
                ) WITH &&
            ) WHERE (revoked_at IS NULL)
            """
        )
    )
    op.execute(sa.text("REVOKE ALL ON TABLE public.break_glass_requests FROM PUBLIC"))
    op.execute(sa.text("REVOKE ALL ON TABLE public.user_roles FROM PUBLIC"))

    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_break_glass_requests_state_v1()
            RETURNS trigger
            LANGUAGE plpgsql
            VOLATILE
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                database_now timestamptz;
            BEGIN
                IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'break-glass requests cannot be deleted or truncated';
                END IF;

                IF TG_OP = 'INSERT' THEN
                    IF NEW.status <> 'pending' OR NEW.row_version <> 1 THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid initial break-glass request state';
                    END IF;
                    database_now := pg_catalog.clock_timestamp();
                    IF NOT EXISTS (
                        SELECT 1
                        FROM public.users AS actor
                        JOIN public.user_roles AS actor_assignment
                            ON actor_assignment.user_id = actor.id
                        JOIN public.roles AS actor_role
                            ON actor_role.id = actor_assignment.role_id
                        WHERE actor.id = NEW.requested_by
                            AND actor.organization_id = NEW.organization_id
                            AND actor.status = 'active' AND actor.deleted_at IS NULL
                            AND actor_role.code = 'system_admin'
                            AND actor_role.is_enabled = TRUE
                            AND actor_assignment.assignment_source IN ('bootstrap', 'user')
                            AND actor_assignment.assigned_at <= database_now
                            AND actor_assignment.expires_at IS NULL
                            AND actor_assignment.revoked_at IS NULL
                    ) OR NOT EXISTS (
                        SELECT 1 FROM public.users AS target_user
                        WHERE target_user.id = NEW.target_user_id
                            AND target_user.organization_id = NEW.organization_id
                            AND target_user.status = 'active'
                            AND target_user.deleted_at IS NULL
                    ) OR NOT EXISTS (
                        SELECT 1 FROM public.roles AS target_role
                        WHERE target_role.code = NEW.target_role_code
                    ) OR EXISTS (
                        SELECT 1
                        FROM public.user_roles AS target_assignment
                        JOIN public.roles AS target_role
                            ON target_role.id = target_assignment.role_id
                        WHERE target_assignment.user_id = NEW.target_user_id
                            AND target_role.code = NEW.target_role_code
                            AND target_role.is_enabled = TRUE
                            AND target_assignment.assigned_at <= database_now
                            AND (target_assignment.expires_at IS NULL
                                OR database_now < target_assignment.expires_at)
                            AND target_assignment.revoked_at IS NULL
                    ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'break-glass requester or target is not eligible';
                    END IF;
                    NEW.created_at := database_now;
                    NEW.updated_at := database_now;
                    RETURN NEW;
                END IF;

                IF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
                    OR NEW.target_user_id IS DISTINCT FROM OLD.target_user_id
                    OR NEW.target_role_code IS DISTINCT FROM OLD.target_role_code
                    OR NEW.requested_by IS DISTINCT FROM OLD.requested_by
                    OR NEW.reason IS DISTINCT FROM OLD.reason
                    OR NEW.requested_duration_seconds
                        IS DISTINCT FROM OLD.requested_duration_seconds
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                    OR NEW.trace_id IS DISTINCT FROM OLD.trace_id
                    OR NEW.row_version <> OLD.row_version + 1 THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'immutable request fields or row_version are invalid';
                END IF;

                IF OLD.status = 'pending' AND NEW.status = 'approved' THEN
                    database_now := pg_catalog.clock_timestamp();
                    IF NEW.decided_by IS NULL
                        OR NEW.decided_by = OLD.requested_by
                        OR NEW.decided_by = OLD.target_user_id
                        OR NOT EXISTS (
                            SELECT 1
                            FROM public.users AS actor
                            JOIN public.user_roles AS actor_assignment
                                ON actor_assignment.user_id = actor.id
                            JOIN public.roles AS actor_role
                                ON actor_role.id = actor_assignment.role_id
                            WHERE actor.id = NEW.decided_by
                                AND actor.organization_id = OLD.organization_id
                                AND actor.status = 'active' AND actor.deleted_at IS NULL
                                AND actor_role.code = 'system_admin'
                                AND actor_role.is_enabled = TRUE
                                AND actor_assignment.assignment_source IN ('bootstrap', 'user')
                                AND actor_assignment.assigned_at <= database_now
                                AND actor_assignment.expires_at IS NULL
                                AND actor_assignment.revoked_at IS NULL
                        ) OR NOT EXISTS (
                            SELECT 1 FROM public.users AS requester
                            WHERE requester.id = OLD.requested_by
                                AND requester.organization_id = OLD.organization_id
                                AND requester.status = 'active'
                                AND requester.deleted_at IS NULL
                        ) OR NOT EXISTS (
                            SELECT 1 FROM public.users AS target_user
                            WHERE target_user.id = OLD.target_user_id
                                AND target_user.organization_id = OLD.organization_id
                                AND target_user.status = 'active'
                                AND target_user.deleted_at IS NULL
                        ) OR NOT EXISTS (
                            SELECT 1 FROM public.roles AS target_role
                            WHERE target_role.code = OLD.target_role_code
                                AND target_role.is_enabled = TRUE
                        ) OR EXISTS (
                            SELECT 1
                            FROM public.user_roles AS target_assignment
                            JOIN public.roles AS target_role
                                ON target_role.id = target_assignment.role_id
                            WHERE target_assignment.user_id = OLD.target_user_id
                                AND target_role.code = OLD.target_role_code
                                AND target_role.is_enabled = TRUE
                                AND target_assignment.assigned_at <= database_now
                                AND (target_assignment.expires_at IS NULL
                                    OR database_now < target_assignment.expires_at)
                                AND target_assignment.revoked_at IS NULL
                        ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'break-glass approval is not eligible';
                    END IF;
                    NEW.decision_at := database_now;
                    NEW.effective_from := database_now;
                    NEW.expires_at := database_now
                        + OLD.requested_duration_seconds * interval '1 second';
                    NEW.updated_at := database_now;
                ELSIF OLD.status = 'pending' AND NEW.status = 'rejected' THEN
                    database_now := pg_catalog.clock_timestamp();
                    IF NEW.decided_by IS NULL
                        OR NEW.decided_by = OLD.requested_by
                        OR NEW.decided_by = OLD.target_user_id
                        OR NOT EXISTS (
                            SELECT 1
                            FROM public.users AS actor
                            JOIN public.user_roles AS actor_assignment
                                ON actor_assignment.user_id = actor.id
                            JOIN public.roles AS actor_role
                                ON actor_role.id = actor_assignment.role_id
                            WHERE actor.id = NEW.decided_by
                                AND actor.organization_id = OLD.organization_id
                                AND actor.status = 'active' AND actor.deleted_at IS NULL
                                AND actor_role.code = 'system_admin'
                                AND actor_role.is_enabled = TRUE
                                AND actor_assignment.assignment_source IN ('bootstrap', 'user')
                                AND actor_assignment.assigned_at <= database_now
                                AND actor_assignment.expires_at IS NULL
                                AND actor_assignment.revoked_at IS NULL
                        ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'break-glass rejection actor is not eligible';
                    END IF;
                    NEW.decision_at := database_now;
                    NEW.updated_at := database_now;
                ELSIF OLD.status = 'approved' AND NEW.status = 'revoked' THEN
                    database_now := pg_catalog.clock_timestamp();
                    IF NEW.decided_by IS DISTINCT FROM OLD.decided_by
                        OR NEW.decision_at IS DISTINCT FROM OLD.decision_at
                        OR NEW.decision_reason IS DISTINCT FROM OLD.decision_reason
                        OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
                        OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
                        OR NEW.revoked_by IS NULL
                        OR database_now >= OLD.expires_at
                        OR NOT EXISTS (
                            SELECT 1
                            FROM public.users AS actor
                            JOIN public.user_roles AS actor_assignment
                                ON actor_assignment.user_id = actor.id
                            JOIN public.roles AS actor_role
                                ON actor_role.id = actor_assignment.role_id
                            WHERE actor.id = NEW.revoked_by
                                AND actor.organization_id = OLD.organization_id
                                AND actor.status = 'active' AND actor.deleted_at IS NULL
                                AND actor_role.code = 'system_admin'
                                AND actor_role.is_enabled = TRUE
                                AND actor_assignment.assignment_source IN ('bootstrap', 'user')
                                AND actor_assignment.assigned_at <= database_now
                                AND actor_assignment.expires_at IS NULL
                                AND actor_assignment.revoked_at IS NULL
                        ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'break-glass revocation is not eligible';
                    END IF;
                    NEW.revoked_at := database_now;
                    NEW.updated_at := database_now;
                ELSIF OLD.status = 'approved' AND NEW.status = 'expired' THEN
                    database_now := pg_catalog.clock_timestamp();
                    IF NEW.decided_by IS DISTINCT FROM OLD.decided_by
                        OR NEW.decision_at IS DISTINCT FROM OLD.decision_at
                        OR NEW.decision_reason IS DISTINCT FROM OLD.decision_reason
                        OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
                        OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
                        OR NEW.revoked_by IS DISTINCT FROM OLD.revoked_by
                        OR NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
                        OR NEW.revoke_reason IS DISTINCT FROM OLD.revoke_reason
                        OR database_now < OLD.expires_at THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'break-glass request is not expirable';
                    END IF;
                    NEW.updated_at := database_now;
                ELSE
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'invalid break-glass request status transition';
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
            CREATE FUNCTION public.enforce_user_roles_state_v1()
            RETURNS trigger
            LANGUAGE plpgsql
            VOLATILE
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                database_now timestamptz;
                request_record public.break_glass_requests%ROWTYPE;
                selected_role_code varchar(40);
            BEGIN
                IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'user roles cannot be deleted or truncated';
                END IF;

                IF TG_OP = 'INSERT' THEN
                    IF NEW.revoked_at IS NOT NULL
                        OR NEW.revoked_by IS NOT NULL
                        OR NEW.revoke_reason IS NOT NULL THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'new user role cannot be pre-revoked';
                    END IF;
                    IF NEW.assignment_source IN ('bootstrap', 'user') THEN
                        database_now := pg_catalog.clock_timestamp();
                        NEW.assigned_at := database_now;
                    ELSIF NEW.assignment_source = 'break_glass' THEN
                        SELECT * INTO request_record
                        FROM public.break_glass_requests
                        WHERE id = NEW.break_glass_request_id;
                        SELECT code INTO selected_role_code
                        FROM public.roles WHERE id = NEW.role_id;
                        IF request_record.id IS NULL OR selected_role_code IS NULL
                            OR request_record.status <> 'approved'
                            OR NEW.user_id IS DISTINCT FROM request_record.target_user_id
                            OR selected_role_code IS DISTINCT FROM request_record.target_role_code
                            OR NEW.assigned_by IS DISTINCT FROM request_record.decided_by
                            OR NEW.assigned_at IS DISTINCT FROM request_record.effective_from
                            OR NEW.expires_at IS DISTINCT FROM request_record.expires_at
                            OR NEW.assignment_reason
                                IS DISTINCT FROM request_record.decision_reason THEN
                            RAISE EXCEPTION USING
                                ERRCODE = '23514',
                                MESSAGE = 'break-glass role assignment does not match request';
                        END IF;
                    ELSE
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'unknown user role assignment source';
                    END IF;
                    RETURN NEW;
                END IF;

                IF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.user_id IS DISTINCT FROM OLD.user_id
                    OR NEW.role_id IS DISTINCT FROM OLD.role_id
                    OR NEW.assigned_by IS DISTINCT FROM OLD.assigned_by
                    OR NEW.assignment_source IS DISTINCT FROM OLD.assignment_source
                    OR NEW.assigned_at IS DISTINCT FROM OLD.assigned_at
                    OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
                    OR NEW.break_glass_request_id
                        IS DISTINCT FROM OLD.break_glass_request_id
                    OR NEW.assignment_reason IS DISTINCT FROM OLD.assignment_reason
                    OR OLD.revoked_at IS NOT NULL OR OLD.revoked_by IS NOT NULL
                    OR OLD.revoke_reason IS NOT NULL
                    OR NEW.revoked_by IS NULL OR NEW.revoke_reason IS NULL THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'immutable or revocation user role fields are invalid';
                END IF;

                IF OLD.assignment_source = 'break_glass' THEN
                    SELECT * INTO request_record
                    FROM public.break_glass_requests
                    WHERE id = OLD.break_glass_request_id;
                    IF request_record.id IS NULL OR request_record.status <> 'revoked'
                        OR NEW.revoked_by IS DISTINCT FROM request_record.revoked_by
                        OR NEW.revoked_at IS DISTINCT FROM request_record.revoked_at
                        OR NEW.revoke_reason IS DISTINCT FROM request_record.revoke_reason THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'break-glass role revocation does not match request';
                    END IF;
                ELSE
                    database_now := pg_catalog.clock_timestamp();
                    NEW.revoked_at := database_now;
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
            CREATE FUNCTION public.enforce_break_glass_role_consistency_v1()
            RETURNS trigger
            LANGUAGE plpgsql
            VOLATILE
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                selected_request_id uuid;
                request_record public.break_glass_requests%ROWTYPE;
                assignment_record public.user_roles%ROWTYPE;
                selected_role_code varchar(40);
            BEGIN
                IF TG_TABLE_NAME = 'break_glass_requests' THEN
                    IF TG_OP = 'DELETE' THEN
                        selected_request_id := OLD.id;
                    ELSE
                        selected_request_id := NEW.id;
                    END IF;
                ELSE
                    IF TG_OP = 'DELETE' THEN
                        selected_request_id := OLD.break_glass_request_id;
                    ELSE
                        selected_request_id := NEW.break_glass_request_id;
                    END IF;
                    IF selected_request_id IS NULL THEN
                        RETURN NULL;
                    END IF;
                END IF;

                SELECT * INTO request_record
                FROM public.break_glass_requests
                WHERE id = selected_request_id;
                IF request_record.id IS NULL THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'break-glass request consistency target is missing';
                END IF;

                IF request_record.status = 'pending' THEN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM public.users AS requester
                        JOIN public.user_roles AS requester_assignment
                            ON requester_assignment.user_id = requester.id
                        JOIN public.roles AS requester_role
                            ON requester_role.id = requester_assignment.role_id
                        WHERE requester.id = request_record.requested_by
                            AND requester.organization_id = request_record.organization_id
                            AND requester.status = 'active'
                            AND requester.deleted_at IS NULL
                            AND requester_role.code = 'system_admin'
                            AND requester_role.is_enabled = TRUE
                            AND requester_assignment.assignment_source
                                IN ('bootstrap', 'user')
                            AND requester_assignment.assigned_at
                                <= request_record.created_at
                            AND requester_assignment.expires_at IS NULL
                            AND requester_assignment.revoked_at IS NULL
                    ) OR NOT EXISTS (
                        SELECT 1 FROM public.users AS target_user
                        WHERE target_user.id = request_record.target_user_id
                            AND target_user.organization_id
                                = request_record.organization_id
                            AND target_user.status = 'active'
                            AND target_user.deleted_at IS NULL
                    ) OR EXISTS (
                        SELECT 1
                        FROM public.user_roles AS target_assignment
                        JOIN public.roles AS target_role
                            ON target_role.id = target_assignment.role_id
                        WHERE target_assignment.user_id = request_record.target_user_id
                            AND target_role.code = request_record.target_role_code
                            AND target_role.is_enabled = TRUE
                            AND target_assignment.assigned_at
                                <= request_record.created_at
                            AND (target_assignment.expires_at IS NULL
                                OR request_record.created_at
                                    < target_assignment.expires_at)
                            AND target_assignment.revoked_at IS NULL
                    ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'pending request final eligibility is invalid';
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM public.user_roles
                        WHERE break_glass_request_id = selected_request_id
                    ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'pending or rejected request cannot have a role';
                    END IF;
                    RETURN NULL;
                ELSIF request_record.status = 'rejected' THEN
                    IF EXISTS (
                        SELECT 1 FROM public.user_roles
                        WHERE break_glass_request_id = selected_request_id
                    ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'rejected request cannot have a role';
                    END IF;
                    RETURN NULL;
                END IF;

                SELECT * INTO assignment_record
                FROM public.user_roles
                WHERE break_glass_request_id = selected_request_id;
                IF assignment_record.id IS NULL THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'decided request requires one role assignment';
                END IF;
                SELECT code INTO selected_role_code
                FROM public.roles WHERE id = assignment_record.role_id;
                IF selected_role_code IS NULL
                    OR assignment_record.assignment_source <> 'break_glass'
                    OR assignment_record.user_id
                        IS DISTINCT FROM request_record.target_user_id
                    OR selected_role_code IS DISTINCT FROM request_record.target_role_code
                    OR assignment_record.assigned_by
                        IS DISTINCT FROM request_record.decided_by
                    OR assignment_record.assigned_at
                        IS DISTINCT FROM request_record.effective_from
                    OR assignment_record.expires_at
                        IS DISTINCT FROM request_record.expires_at
                    OR assignment_record.assignment_reason
                        IS DISTINCT FROM request_record.decision_reason
                    OR (request_record.status = 'approved' AND (
                        NOT EXISTS (
                            SELECT 1
                            FROM public.users AS requester
                            WHERE requester.id = request_record.requested_by
                                AND requester.organization_id
                                    = request_record.organization_id
                                AND requester.status = 'active'
                                AND requester.deleted_at IS NULL
                        )
                        OR NOT EXISTS (
                            SELECT 1
                            FROM public.users AS target_user
                            WHERE target_user.id = request_record.target_user_id
                                AND target_user.organization_id
                                    = request_record.organization_id
                                AND target_user.status = 'active'
                                AND target_user.deleted_at IS NULL
                        )
                        OR NOT EXISTS (
                            SELECT 1
                            FROM public.users AS decider
                            JOIN public.user_roles AS decider_assignment
                                ON decider_assignment.user_id = decider.id
                            JOIN public.roles AS decider_role
                                ON decider_role.id = decider_assignment.role_id
                            WHERE decider.id = request_record.decided_by
                                AND decider.organization_id
                                    = request_record.organization_id
                                AND decider.status = 'active'
                                AND decider.deleted_at IS NULL
                                AND decider_role.code = 'system_admin'
                                AND decider_role.is_enabled = TRUE
                                AND decider_assignment.assignment_source
                                    IN ('bootstrap', 'user')
                                AND decider_assignment.assigned_at
                                    <= request_record.decision_at
                                AND decider_assignment.expires_at IS NULL
                                AND decider_assignment.revoked_at IS NULL
                        )
                        OR NOT EXISTS (
                            SELECT 1 FROM public.roles AS target_role
                            WHERE target_role.code = request_record.target_role_code
                                AND target_role.is_enabled = TRUE
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM public.user_roles AS target_assignment
                            JOIN public.roles AS target_role
                                ON target_role.id = target_assignment.role_id
                            WHERE target_assignment.user_id
                                = request_record.target_user_id
                                AND target_role.code = request_record.target_role_code
                                AND target_role.is_enabled = TRUE
                                AND target_assignment.break_glass_request_id
                                    IS DISTINCT FROM request_record.id
                                AND target_assignment.assigned_at
                                    <= request_record.decision_at
                                AND (target_assignment.expires_at IS NULL
                                    OR request_record.decision_at
                                        < target_assignment.expires_at)
                                AND target_assignment.revoked_at IS NULL
                        )
                    ))
                    OR (request_record.status IN ('approved', 'expired') AND (
                        assignment_record.revoked_by IS NOT NULL
                        OR assignment_record.revoked_at IS NOT NULL
                        OR assignment_record.revoke_reason IS NOT NULL
                    ))
                    OR (request_record.status = 'revoked' AND (
                        assignment_record.revoked_by
                            IS DISTINCT FROM request_record.revoked_by
                        OR assignment_record.revoked_at
                            IS DISTINCT FROM request_record.revoked_at
                        OR assignment_record.revoke_reason
                            IS DISTINCT FROM request_record.revoke_reason
                    )) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'break-glass request and role assignment are inconsistent';
                END IF;
                RETURN NULL;
            END;
            $$
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_long_term_role_separation_v1()
            RETURNS trigger
            LANGUAGE plpgsql
            VOLATILE
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                affected_user_id uuid;
                database_now timestamptz;
            BEGIN
                IF TG_TABLE_NAME = 'user_roles' THEN
                    IF TG_OP = 'DELETE' THEN
                        RETURN NULL;
                    END IF;
                    IF NEW.assignment_source = 'break_glass' THEN
                        RETURN NULL;
                    END IF;
                    affected_user_id := NEW.user_id;
                    IF TG_OP = 'INSERT' THEN
                        database_now := NEW.assigned_at;
                    ELSE
                        database_now := NEW.revoked_at;
                    END IF;
                ELSIF TG_TABLE_NAME = 'users' THEN
                    affected_user_id := NEW.id;
                    database_now := pg_catalog.clock_timestamp();
                ELSE
                    affected_user_id := NULL;
                    database_now := pg_catalog.clock_timestamp();
                END IF;

                IF database_now IS NULL THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'long-term role mutation time is missing';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM public.users AS target_user
                    JOIN public.user_roles AS admin_assignment
                        ON admin_assignment.user_id = target_user.id
                    JOIN public.roles AS admin_role
                        ON admin_role.id = admin_assignment.role_id
                    JOIN public.user_roles AS reviewer_assignment
                        ON reviewer_assignment.user_id = target_user.id
                    JOIN public.roles AS reviewer_role
                        ON reviewer_role.id = reviewer_assignment.role_id
                    WHERE (affected_user_id IS NULL
                            OR target_user.id = affected_user_id)
                        AND target_user.status = 'active'
                        AND target_user.deleted_at IS NULL
                        AND admin_role.code = 'system_admin'
                        AND admin_role.is_enabled = TRUE
                        AND reviewer_role.code IN ('finance_reviewer', 'audit_reviewer')
                        AND reviewer_role.is_enabled = TRUE
                        AND admin_assignment.assignment_source IN ('bootstrap', 'user')
                        AND reviewer_assignment.assignment_source IN ('bootstrap', 'user')
                        AND admin_assignment.assigned_at <= database_now
                        AND reviewer_assignment.assigned_at <= database_now
                        AND admin_assignment.expires_at IS NULL
                        AND reviewer_assignment.expires_at IS NULL
                        AND admin_assignment.revoked_at IS NULL
                        AND reviewer_assignment.revoked_at IS NULL
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'long-term system admin and reviewer roles conflict';
                END IF;
                RETURN NULL;
            END;
            $$
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_roles_invariants_v1()
            RETURNS trigger
            LANGUAGE plpgsql
            VOLATILE
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'fixed roles cannot be deleted';
                ELSIF TG_OP = 'INSERT' THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'fixed roles cannot be inserted';
                ELSIF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.code IS DISTINCT FROM OLD.code
                    OR NEW.is_system_role IS DISTINCT FROM OLD.is_system_role
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'fixed role identity cannot change';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )

    for function_name in (
        "enforce_break_glass_requests_state_v1",
        "enforce_user_roles_state_v1",
        "enforce_break_glass_role_consistency_v1",
        "enforce_long_term_role_separation_v1",
        "enforce_roles_invariants_v1",
    ):
        op.execute(sa.text(f"REVOKE ALL ON FUNCTION public.{function_name}() FROM PUBLIC"))

    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_break_glass_requests_state_v1
            BEFORE INSERT OR UPDATE OR DELETE ON public.break_glass_requests
            FOR EACH ROW EXECUTE FUNCTION public.enforce_break_glass_requests_state_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_break_glass_requests_no_truncate_v1
            BEFORE TRUNCATE ON public.break_glass_requests
            FOR EACH STATEMENT EXECUTE FUNCTION public.enforce_break_glass_requests_state_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER trg_break_glass_requests_consistency_v1
            AFTER INSERT OR UPDATE OR DELETE ON public.break_glass_requests
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION public.enforce_break_glass_role_consistency_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_user_roles_state_v1
            BEFORE INSERT OR UPDATE OR DELETE ON public.user_roles
            FOR EACH ROW EXECUTE FUNCTION public.enforce_user_roles_state_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_user_roles_no_truncate_v1
            BEFORE TRUNCATE ON public.user_roles
            FOR EACH STATEMENT EXECUTE FUNCTION public.enforce_user_roles_state_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER trg_user_roles_consistency_v1
            AFTER INSERT OR UPDATE OR DELETE ON public.user_roles
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION public.enforce_break_glass_role_consistency_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER trg_user_roles_sod_v1
            AFTER INSERT OR UPDATE OR DELETE ON public.user_roles
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION public.enforce_long_term_role_separation_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER trg_users_role_sod_v1
            AFTER INSERT OR UPDATE OF organization_id, status, deleted_at ON public.users
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION public.enforce_long_term_role_separation_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_roles_invariants_v1
            BEFORE INSERT OR UPDATE OR DELETE ON public.roles
            FOR EACH ROW EXECUTE FUNCTION public.enforce_roles_invariants_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER trg_roles_role_sod_v1
            AFTER UPDATE OF is_enabled ON public.roles
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION public.enforce_long_term_role_separation_v1()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE public.break_glass_requests IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE public.user_roles IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM public.break_glass_requests LIMIT 1)
                    OR EXISTS (SELECT 1 FROM public.user_roles LIMIT 1) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'refusing to drop non-empty privileged-auth tables';
                END IF;
            END;
            $$
            """
        )
    )
    op.execute(sa.text("LOCK TABLE public.users IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE public.roles IN ACCESS EXCLUSIVE MODE"))

    op.execute(sa.text("DROP TRIGGER trg_users_role_sod_v1 ON public.users"))
    op.execute(sa.text("DROP TRIGGER trg_roles_role_sod_v1 ON public.roles"))
    op.execute(sa.text("DROP TRIGGER trg_roles_invariants_v1 ON public.roles"))
    op.execute(sa.text("DROP TRIGGER trg_user_roles_sod_v1 ON public.user_roles"))
    op.execute(sa.text("DROP TRIGGER trg_user_roles_consistency_v1 ON public.user_roles"))
    op.execute(sa.text("DROP TRIGGER trg_user_roles_no_truncate_v1 ON public.user_roles"))
    op.execute(sa.text("DROP TRIGGER trg_user_roles_state_v1 ON public.user_roles"))
    op.execute(
        sa.text(
            "DROP TRIGGER trg_break_glass_requests_consistency_v1 ON public.break_glass_requests"
        )
    )
    op.execute(
        sa.text(
            "DROP TRIGGER trg_break_glass_requests_no_truncate_v1 ON public.break_glass_requests"
        )
    )
    op.execute(
        sa.text("DROP TRIGGER trg_break_glass_requests_state_v1 ON public.break_glass_requests")
    )
    op.drop_table("user_roles", schema="public")
    op.drop_table("break_glass_requests", schema="public")
    op.execute(sa.text("DROP FUNCTION public.enforce_roles_invariants_v1()"))
    op.execute(sa.text("DROP FUNCTION public.enforce_long_term_role_separation_v1()"))
    op.execute(sa.text("DROP FUNCTION public.enforce_break_glass_role_consistency_v1()"))
    op.execute(sa.text("DROP FUNCTION public.enforce_user_roles_state_v1()"))
    op.execute(sa.text("DROP FUNCTION public.enforce_break_glass_requests_state_v1()"))
