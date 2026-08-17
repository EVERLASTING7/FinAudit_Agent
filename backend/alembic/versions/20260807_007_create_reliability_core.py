"""创建 Job、Step 与 Outbox 可靠性核心空表。

Revision ID: 20260807_007
Revises: 20260807_006
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260807_007"
down_revision: str | None = "20260807_006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "async_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=60), nullable=False),
        sa.Column("resource_type", sa.String(length=60), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("current_attempt_start_step_code", sa.String(length=80), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("input_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_schema_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("handler_registry_version", sa.String(length=80), nullable=False),
        sa.Column("handler_registry_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("retry_policy_version", sa.String(length=50), nullable=False),
        sa.Column("retry_policy_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("lease_policy_version", sa.String(length=50), nullable=False),
        sa.Column("lease_policy_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("lease_owner", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'cancel_requested', "
            "'succeeded', 'failed', 'cancelled')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "max_attempts >= 1 AND attempt_no >= 0 AND attempt_no <= max_attempts",
            name="attempt_bounds",
        ),
        sa.CheckConstraint("input_schema_version > 0", name="input_schema_version_positive"),
        sa.CheckConstraint("row_version > 0", name="row_version_positive"),
        sa.CheckConstraint(
            "(job_type COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'",
            name="job_type_format",
        ),
        sa.CheckConstraint(
            "(current_attempt_start_step_code COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'",
            name="current_attempt_start_step_code_format",
        ),
        sa.CheckConstraint(
            "stage IS NULL OR (stage COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'",
            name="stage_format",
        ),
        sa.CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$' "
            "AND handler_registry_hash ~ '^[0-9a-f]{64}$' "
            "AND retry_policy_hash ~ '^[0-9a-f]{64}$' "
            "AND lease_policy_hash ~ '^[0-9a-f]{64}$'",
            name="hashes_lower_hex",
        ),
        sa.CheckConstraint(
            '(handler_registry_version COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$' "
            'AND (retry_policy_version COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$' "
            'AND (lease_policy_version COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$'",
            name="version_formats",
        ),
        sa.CheckConstraint(
            "lease_owner IS NULL OR lease_owner ~ "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
            "[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="lease_owner_canonical_uuid_v4",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,79}$'",
            name="error_code_safe_format",
        ),
        sa.CheckConstraint(
            """
            (status = 'queued'
                AND attempt_no < max_attempts
                AND stage IS NULL
                AND next_retry_at IS NULL
                AND worker_id IS NULL
                AND started_at IS NULL
                AND finished_at IS NULL
                AND error_code IS NULL
                AND error_message IS NULL
                AND lease_owner IS NULL
                AND lease_expires_at IS NULL
                AND heartbeat_at IS NULL)
            OR (status IN ('running', 'cancel_requested')
                AND attempt_no >= 1
                AND stage IS NOT NULL
                AND next_retry_at IS NULL
                AND worker_id IS NOT NULL
                AND btrim(worker_id) <> ''
                AND started_at IS NOT NULL
                AND finished_at IS NULL
                AND error_code IS NULL
                AND error_message IS NULL
                AND lease_owner IS NOT NULL
                AND lease_expires_at IS NOT NULL
                AND heartbeat_at IS NOT NULL
                AND started_at <= heartbeat_at
                AND heartbeat_at < lease_expires_at)
            OR (status = 'succeeded'
                AND attempt_no >= 1
                AND stage IS NOT NULL
                AND next_retry_at IS NULL
                AND worker_id IS NULL
                AND started_at IS NOT NULL
                AND finished_at IS NOT NULL
                AND finished_at >= started_at
                AND error_code IS NULL
                AND error_message IS NULL
                AND lease_owner IS NULL
                AND lease_expires_at IS NULL
                AND heartbeat_at IS NULL)
            OR (status = 'failed'
                AND finished_at IS NOT NULL
                AND error_code IS NOT NULL
                AND worker_id IS NULL
                AND lease_owner IS NULL
                AND lease_expires_at IS NULL
                AND heartbeat_at IS NULL
                AND (
                    (started_at IS NULL
                        AND stage IS NULL
                        AND next_retry_at IS NULL
                        AND error_code IN (
                            'JOB_DISPATCH_FAILED',
                            'JOB_DISPATCH_OUTCOME_UNKNOWN'
                        ))
                    OR (attempt_no >= 1
                        AND started_at IS NOT NULL
                        AND stage IS NOT NULL
                        AND finished_at >= started_at
                        AND (
                            (error_code IN (
                                'DATABASE_TRANSIENT',
                                'DEPENDENCY_TIMEOUT',
                                'DEPENDENCY_UNAVAILABLE',
                                'RATE_LIMITED',
                                'STORAGE_TRANSIENT',
                                'WORKER_LOST'
                            ) AND attempt_no < max_attempts
                                AND next_retry_at = finished_at)
                            OR ((error_code NOT IN (
                                'DATABASE_TRANSIENT',
                                'DEPENDENCY_TIMEOUT',
                                'DEPENDENCY_UNAVAILABLE',
                                'RATE_LIMITED',
                                'STORAGE_TRANSIENT',
                                'WORKER_LOST'
                            ) OR attempt_no = max_attempts)
                                AND next_retry_at IS NULL)
                        ))
                ))
            OR (status = 'cancelled'
                AND finished_at IS NOT NULL
                AND error_code = 'JOB_CANCELLED'
                AND error_message IS NULL
                AND next_retry_at IS NULL
                AND worker_id IS NULL
                AND lease_owner IS NULL
                AND lease_expires_at IS NULL
                AND heartbeat_at IS NULL
                AND (
                    (started_at IS NULL AND stage IS NULL)
                    OR (attempt_no >= 1
                        AND started_at IS NOT NULL
                        AND stage IS NOT NULL
                        AND finished_at >= started_at)
                ))
            """,
            name="state_field_matrix",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_async_jobs_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["idempotency_record_id"],
            ["idempotency_records.id"],
            name="fk_async_jobs_idempotency_record_id_idempotency_records",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_async_jobs_created_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_async_jobs"),
    )
    op.create_index(
        "uq_async_jobs_active_resource_input",
        "async_jobs",
        ["organization_id", "job_type", "resource_type", "resource_id", "input_hash"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'cancel_requested')"),
    )
    op.create_index(
        "idx_async_jobs_claim",
        "async_jobs",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "idx_async_jobs_resource_created",
        "async_jobs",
        ["resource_type", "resource_id", sa.text("created_at DESC")],
        unique=False,
    )

    op.create_table(
        "async_job_steps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_seq", sa.Integer(), nullable=False),
        sa.Column("step_code", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("step_seq > 0", name="step_seq_positive"),
        sa.CheckConstraint("attempt_no > 0", name="attempt_no_positive"),
        sa.CheckConstraint(
            "(step_code COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'",
            name="step_code_format",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'cancelled', 'skipped')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,79}$'",
            name="error_code_safe_format",
        ),
        sa.CheckConstraint(
            """
            (status = 'running' AND finished_at IS NULL AND error_code IS NULL)
            OR (status = 'succeeded'
                AND finished_at IS NOT NULL
                AND finished_at >= started_at
                AND error_code IS NULL)
            OR (status = 'skipped'
                AND finished_at IS NOT NULL
                AND finished_at >= started_at
                AND error_code = 'STEP_SKIPPED')
            OR (status = 'failed'
                AND finished_at IS NOT NULL
                AND finished_at >= started_at
                AND error_code IS NOT NULL)
            OR (status = 'cancelled'
                AND finished_at IS NOT NULL
                AND finished_at >= started_at
                AND error_code = 'JOB_CANCELLED')
            """,
            name="state_field_matrix",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["async_jobs.id"], name="fk_async_job_steps_job_id_async_jobs"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_async_job_steps"),
        sa.UniqueConstraint(
            "job_id",
            "step_seq",
            "attempt_no",
            name="uq_async_job_steps_job_id_step_seq_attempt_no",
        ),
    )
    op.create_index(
        "uq_async_job_steps_one_running_per_attempt",
        "async_job_steps",
        ["job_id", "attempt_no"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "outbox_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("aggregate_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("event_version > 0", name="event_version_positive"),
        sa.CheckConstraint("event_sequence > 0", name="event_sequence_positive"),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 8", name="attempt_count_bounds"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'failed', 'published', 'dead_letter')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "btrim(aggregate_type) <> '' AND btrim(event_type) <> ''",
            name="identity_nonempty",
        ),
        sa.CheckConstraint(
            """
            (status = 'pending'
                AND attempt_count = 0
                AND next_attempt_at IS NULL
                AND published_at IS NULL
                AND last_error IS NULL)
            OR (status = 'processing'
                AND attempt_count BETWEEN 1 AND 8
                AND next_attempt_at IS NOT NULL
                AND published_at IS NULL
                AND last_error IS NULL)
            OR (status = 'failed'
                AND attempt_count BETWEEN 1 AND 7
                AND next_attempt_at IS NOT NULL
                AND published_at IS NULL
                AND last_error IN (
                    'BROKER_UNAVAILABLE',
                    'BROKER_TIMEOUT',
                    'PUBLISH_CONFIRM_UNKNOWN',
                    'PROCESSING_LEASE_EXPIRED'
                ))
            OR (status = 'published'
                AND attempt_count BETWEEN 1 AND 8
                AND next_attempt_at IS NULL
                AND published_at IS NOT NULL
                AND last_error IS NULL)
            OR (status = 'dead_letter'
                AND attempt_count BETWEEN 1 AND 8
                AND next_attempt_at IS NULL
                AND published_at IS NULL
                AND (
                    (attempt_count = 8
                        AND last_error = 'DELIVERY_ATTEMPTS_EXHAUSTED')
                    OR last_error IN (
                        'UNSUPPORTED_EVENT_VERSION',
                        'SERIALIZATION_FAILED',
                        'UNKNOWN_DELIVERY_ERROR'
                    )
                ))
            """,
            name="state_field_matrix",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.UniqueConstraint("event_id", "event_type", name="uq_outbox_events_event_id_event_type"),
        sa.UniqueConstraint(
            "aggregate_type",
            "aggregate_id",
            "event_sequence",
            name="uq_outbox_events_aggregate_type_aggregate_id_event_sequence",
        ),
    )
    op.create_index(
        "idx_outbox_events_claim",
        "outbox_events",
        ["status", "next_attempt_at", "created_at"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION enforce_async_jobs_state_v1()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                database_now timestamptz := clock_timestamp();
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    IF NEW.status <> 'queued'
                        OR NEW.attempt_no <> 0
                        OR NEW.row_version <> 1 THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid initial async job state';
                    END IF;
                    RETURN NEW;
                END IF;

                IF ROW(
                    NEW.id,
                    NEW.organization_id,
                    NEW.job_type,
                    NEW.resource_type,
                    NEW.resource_id,
                    NEW.max_attempts,
                    NEW.input_hash,
                    NEW.input_json,
                    NEW.input_schema_version,
                    NEW.idempotency_record_id,
                    NEW.handler_registry_version,
                    NEW.handler_registry_hash,
                    NEW.retry_policy_version,
                    NEW.retry_policy_hash,
                    NEW.lease_policy_version,
                    NEW.lease_policy_hash,
                    NEW.trace_id,
                    NEW.created_by,
                    NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.id,
                    OLD.organization_id,
                    OLD.job_type,
                    OLD.resource_type,
                    OLD.resource_id,
                    OLD.max_attempts,
                    OLD.input_hash,
                    OLD.input_json,
                    OLD.input_schema_version,
                    OLD.idempotency_record_id,
                    OLD.handler_registry_version,
                    OLD.handler_registry_hash,
                    OLD.retry_policy_version,
                    OLD.retry_policy_hash,
                    OLD.lease_policy_version,
                    OLD.lease_policy_hash,
                    OLD.trace_id,
                    OLD.created_by,
                    OLD.created_at
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'immutable async job fields cannot change';
                END IF;

                IF NEW.row_version <> OLD.row_version + 1 THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'async job row_version must increase by exactly one';
                END IF;

                IF (
                    (OLD.status = 'queued' AND NEW.status = 'running')
                    OR (OLD.status = 'running' AND NEW.status = 'running')
                    OR (OLD.status = 'cancel_requested'
                        AND NEW.status = 'cancel_requested')
                    OR (OLD.status = 'running'
                        AND NEW.status = 'failed'
                        AND NEW.error_code = 'WORKER_LOST'
                        AND database_now
                            >= OLD.lease_expires_at + interval '15 seconds')
                    OR (OLD.status = 'cancel_requested'
                        AND NEW.status = 'cancelled'
                        AND database_now
                            >= OLD.lease_expires_at + interval '15 seconds')
                ) AND (
                    OLD.lease_policy_version <> 'job-lease-v1'
                    OR OLD.lease_policy_hash
                        <> '50a6acee62769713152039af330cc4a779cc758ea36b97102308b1bc08564d00'
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'unsupported async job lease policy';
                END IF;

                IF OLD.status = 'queued' AND NEW.status = 'running' THEN
                    IF NEW.attempt_no <> OLD.attempt_no + 1
                        OR NEW.attempt_no > NEW.max_attempts
                        OR NEW.current_attempt_start_step_code
                            <> OLD.current_attempt_start_step_code
                        OR NEW.stage <> OLD.current_attempt_start_step_code
                        OR NEW.worker_id IS NULL
                        OR btrim(NEW.worker_id) = '' THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid async job claim';
                    END IF;
                    NEW.lease_owner := gen_random_uuid()::text;
                    NEW.started_at := database_now;
                    NEW.heartbeat_at := database_now;
                    NEW.lease_expires_at := database_now + interval '60 seconds';
                ELSIF OLD.status = 'queued' AND NEW.status = 'cancelled' THEN
                    IF NEW.attempt_no <> OLD.attempt_no
                        OR NEW.current_attempt_start_step_code
                            <> OLD.current_attempt_start_step_code
                        OR NEW.finished_at > database_now THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid queued async job cancellation';
                    END IF;
                ELSIF OLD.status = 'queued' AND NEW.status = 'failed' THEN
                    IF NEW.attempt_no <> OLD.attempt_no
                        OR NEW.current_attempt_start_step_code
                            <> OLD.current_attempt_start_step_code
                        OR NEW.finished_at > database_now
                        OR NEW.error_code NOT IN (
                            'JOB_DISPATCH_FAILED',
                            'JOB_DISPATCH_OUTCOME_UNKNOWN'
                        ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid pre-claim async job failure';
                    END IF;
                ELSIF OLD.status = 'running' AND NEW.status = 'running' THEN
                    IF NEW.current_attempt_start_step_code
                        <> OLD.current_attempt_start_step_code THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'active async job start step cannot change';
                    END IF;

                    IF NEW.attempt_no = OLD.attempt_no THEN
                        IF database_now >= OLD.lease_expires_at
                            OR NEW.worker_id IS DISTINCT FROM OLD.worker_id
                            OR NEW.lease_owner IS DISTINCT FROM OLD.lease_owner
                            OR NEW.started_at IS DISTINCT FROM OLD.started_at THEN
                            RAISE EXCEPTION USING
                                ERRCODE = '23514',
                                MESSAGE = 'invalid active async job update';
                        END IF;

                        IF NEW.stage IS NOT DISTINCT FROM OLD.stage THEN
                            IF NEW.heartbeat_at IS NOT DISTINCT FROM OLD.heartbeat_at
                                AND NEW.lease_expires_at
                                    IS NOT DISTINCT FROM OLD.lease_expires_at THEN
                                RAISE EXCEPTION USING
                                    ERRCODE = '23514',
                                    MESSAGE = 'async job heartbeat must change lease time';
                            END IF;
                            NEW.heartbeat_at := database_now;
                            NEW.lease_expires_at := database_now + interval '60 seconds';
                        ELSIF NEW.heartbeat_at IS DISTINCT FROM OLD.heartbeat_at
                            OR NEW.lease_expires_at
                                IS DISTINCT FROM OLD.lease_expires_at THEN
                            IF NEW.heartbeat_at IS NOT DISTINCT FROM OLD.heartbeat_at
                                OR NEW.lease_expires_at
                                    IS NOT DISTINCT FROM OLD.lease_expires_at
                                OR NEW.heartbeat_at > database_now
                                OR NEW.heartbeat_at >= OLD.lease_expires_at
                                OR NEW.lease_expires_at IS DISTINCT FROM
                                    NEW.heartbeat_at + interval '60 seconds' THEN
                                RAISE EXCEPTION USING
                                    ERRCODE = '23514',
                                    MESSAGE = 'invalid async job stage transition time';
                            END IF;
                        END IF;
                    ELSIF NEW.attempt_no = OLD.attempt_no + 1 THEN
                        IF database_now < OLD.lease_expires_at + interval '15 seconds'
                            OR OLD.attempt_no >= OLD.max_attempts
                            OR NEW.stage <> OLD.current_attempt_start_step_code
                            OR NEW.worker_id IS NULL
                            OR btrim(NEW.worker_id) = ''
                            OR NEW.started_at IS DISTINCT FROM NEW.heartbeat_at
                            OR NEW.lease_expires_at IS DISTINCT FROM
                                NEW.started_at + interval '60 seconds'
                            OR NEW.started_at
                                < OLD.lease_expires_at + interval '15 seconds'
                            OR NEW.started_at > database_now THEN
                            RAISE EXCEPTION USING
                                ERRCODE = '23514',
                                MESSAGE = 'invalid async job lease recovery';
                        END IF;
                        NEW.lease_owner := gen_random_uuid()::text;
                    ELSE
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid async job attempt change';
                    END IF;
                ELSIF OLD.status = 'running' AND NEW.status = 'cancel_requested' THEN
                    IF NEW.attempt_no <> OLD.attempt_no
                        OR NEW.current_attempt_start_step_code
                            <> OLD.current_attempt_start_step_code
                        OR NEW.stage IS DISTINCT FROM OLD.stage
                        OR ROW(
                            NEW.worker_id,
                            NEW.started_at,
                            NEW.lease_owner,
                            NEW.lease_expires_at,
                            NEW.heartbeat_at
                        ) IS DISTINCT FROM ROW(
                            OLD.worker_id,
                            OLD.started_at,
                            OLD.lease_owner,
                            OLD.lease_expires_at,
                            OLD.heartbeat_at
                        ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'cancel request must preserve async job fencing';
                    END IF;
                ELSIF OLD.status = 'running'
                    AND NEW.status IN ('succeeded', 'failed') THEN
                    IF NEW.attempt_no <> OLD.attempt_no
                        OR NEW.current_attempt_start_step_code
                            <> OLD.current_attempt_start_step_code
                        OR NEW.stage IS DISTINCT FROM OLD.stage
                        OR NEW.started_at IS DISTINCT FROM OLD.started_at
                        OR NEW.finished_at > database_now
                        OR NOT (
                            (
                                NEW.status = 'failed'
                                AND NEW.error_code = 'WORKER_LOST'
                                AND OLD.attempt_no = OLD.max_attempts
                                AND database_now
                                    >= OLD.lease_expires_at + interval '15 seconds'
                            )
                            OR (
                                NOT (
                                    NEW.status = 'failed'
                                    AND NEW.error_code = 'WORKER_LOST'
                                )
                                AND database_now < OLD.lease_expires_at
                            )
                        ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid running async job transition';
                    END IF;
                ELSIF OLD.status = 'cancel_requested'
                    AND NEW.status = 'cancel_requested' THEN
                    IF database_now >= OLD.lease_expires_at
                        OR NEW.attempt_no <> OLD.attempt_no
                        OR NEW.current_attempt_start_step_code
                            <> OLD.current_attempt_start_step_code
                        OR NEW.stage IS DISTINCT FROM OLD.stage
                        OR NEW.worker_id IS DISTINCT FROM OLD.worker_id
                        OR NEW.lease_owner IS DISTINCT FROM OLD.lease_owner
                        OR NEW.started_at IS DISTINCT FROM OLD.started_at
                        OR (
                            NEW.heartbeat_at IS NOT DISTINCT FROM OLD.heartbeat_at
                            AND NEW.lease_expires_at IS NOT DISTINCT FROM OLD.lease_expires_at
                        ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid cancel-requested heartbeat';
                    END IF;
                    NEW.heartbeat_at := database_now;
                    NEW.lease_expires_at := database_now + interval '60 seconds';
                ELSIF OLD.status = 'cancel_requested' AND NEW.status = 'cancelled' THEN
                    IF NEW.attempt_no <> OLD.attempt_no
                        OR NEW.current_attempt_start_step_code
                            <> OLD.current_attempt_start_step_code
                        OR NEW.stage IS DISTINCT FROM OLD.stage
                        OR NEW.started_at IS DISTINCT FROM OLD.started_at
                        OR NEW.finished_at > database_now
                        OR NOT (
                            database_now < OLD.lease_expires_at
                            OR database_now >= OLD.lease_expires_at + interval '15 seconds'
                        ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid active async job cancellation';
                    END IF;
                ELSIF OLD.status = 'failed' AND NEW.status = 'queued' THEN
                    IF NEW.attempt_no <> OLD.attempt_no
                        OR OLD.started_at IS NULL
                        OR OLD.attempt_no >= OLD.max_attempts
                        OR OLD.next_retry_at IS NULL
                        OR OLD.next_retry_at > database_now
                        OR OLD.error_code NOT IN (
                            'DATABASE_TRANSIENT',
                            'DEPENDENCY_TIMEOUT',
                            'DEPENDENCY_UNAVAILABLE',
                            'RATE_LIMITED',
                            'STORAGE_TRANSIENT',
                            'WORKER_LOST'
                        )
                        OR OLD.retry_policy_version <> 'job-retry-policy-v1'
                        OR OLD.retry_policy_hash
                            <> '9cdb2a30bba1e39155adcb3bcb55fe6465811b63290d249ccbfac4f976cdbba7'
                        OR OLD.lease_policy_version <> 'job-lease-v1'
                        OR OLD.lease_policy_hash
                            <> '50a6acee62769713152039af330cc4a779cc758ea36b97102308b1bc08564d00'
                    THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid async job retry transition';
                    END IF;
                    -- Registry membership remains a fail-closed Loader gate. The approved
                    -- bundle is intentionally not synthesized by this schema revision.
                ELSE
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'invalid async job status transition';
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
            CREATE FUNCTION enforce_async_job_steps_state_v1()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                database_now timestamptz := clock_timestamp();
                job_record async_jobs%ROWTYPE;
            BEGIN
                IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'async job steps cannot be deleted or truncated';
                END IF;

                SELECT * INTO job_record
                FROM async_jobs
                WHERE id = NEW.job_id;

                IF NOT FOUND THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23503',
                        MESSAGE = 'async job step references an unknown job';
                END IF;

                IF TG_OP = 'INSERT' THEN
                    IF NEW.status <> 'running'
                        OR NEW.started_at > database_now
                        OR NOT (
                            (job_record.status = 'running'
                                AND NEW.attempt_no = job_record.attempt_no
                                AND NEW.step_code = job_record.stage
                                AND database_now < job_record.lease_expires_at)
                            OR (job_record.status = 'queued'
                                AND NEW.attempt_no = job_record.attempt_no + 1
                                AND NEW.step_code
                                    = job_record.current_attempt_start_step_code)
                            OR (job_record.status = 'running'
                                AND job_record.attempt_no < job_record.max_attempts
                                AND NEW.attempt_no = job_record.attempt_no + 1
                                AND NEW.step_code
                                    = job_record.current_attempt_start_step_code
                                AND database_now
                                    >= job_record.lease_expires_at + interval '15 seconds'
                                AND NEW.started_at
                                    >= job_record.lease_expires_at + interval '15 seconds')
                        ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid initial async job step state';
                    END IF;
                    RETURN NEW;
                END IF;

                IF OLD.status <> 'running'
                    OR NEW.status NOT IN ('succeeded', 'failed', 'cancelled', 'skipped') THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'async job step can enter a terminal state only once';
                END IF;

                IF ROW(
                    NEW.id,
                    NEW.job_id,
                    NEW.step_seq,
                    NEW.step_code,
                    NEW.attempt_no,
                    NEW.started_at,
                    NEW.trace_id
                ) IS DISTINCT FROM ROW(
                    OLD.id,
                    OLD.job_id,
                    OLD.step_seq,
                    OLD.step_code,
                    OLD.attempt_no,
                    OLD.started_at,
                    OLD.trace_id
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'immutable async job step fields cannot change';
                END IF;

                IF OLD.job_id <> job_record.id
                    OR OLD.attempt_no <> job_record.attempt_no
                    OR OLD.step_code <> job_record.stage
                    OR job_record.status NOT IN ('running', 'cancel_requested') THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'async job step is not the current fenced step';
                END IF;

                IF NEW.finished_at > database_now THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'async job step cannot finish in the future';
                END IF;

                IF database_now < job_record.lease_expires_at THEN
                    IF NEW.error_code IN ('LEASE_EXPIRED', 'WORKER_LOST') THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'lease recovery error cannot be written before expiry';
                    END IF;
                ELSIF database_now
                    < job_record.lease_expires_at + interval '15 seconds' THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'async job step write is outside the lease boundary';
                ELSIF NOT (
                    (job_record.status = 'running'
                        AND job_record.attempt_no < job_record.max_attempts
                        AND NEW.status = 'failed'
                        AND NEW.error_code = 'LEASE_EXPIRED'
                        AND NEW.finished_at
                            >= job_record.lease_expires_at + interval '15 seconds')
                    OR (job_record.status = 'running'
                        AND job_record.attempt_no = job_record.max_attempts
                        AND NEW.status = 'failed'
                        AND NEW.error_code = 'WORKER_LOST'
                        AND NEW.finished_at
                            >= job_record.lease_expires_at + interval '15 seconds')
                    OR (job_record.status = 'cancel_requested'
                        AND NEW.status = 'cancelled'
                        AND NEW.error_code = 'JOB_CANCELLED'
                        AND NEW.finished_at
                            >= job_record.lease_expires_at + interval '15 seconds')
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'invalid async job step lease recovery terminal';
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
            CREATE FUNCTION enforce_job_step_consistency_v1()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                target_job_id uuid;
                job_record async_jobs%ROWTYPE;
                running_count integer;
                current_first async_job_steps%ROWTYPE;
                current_last async_job_steps%ROWTYPE;
                previous_last async_job_steps%ROWTYPE;
            BEGIN
                IF TG_TABLE_NAME = 'async_jobs' THEN
                    target_job_id := NEW.id;
                ELSE
                    target_job_id := COALESCE(NEW.job_id, OLD.job_id);
                END IF;

                SELECT * INTO job_record
                FROM async_jobs
                WHERE id = target_job_id;

                IF NOT FOUND THEN
                    RETURN NULL;
                END IF;

                IF TG_TABLE_NAME = 'async_jobs' AND TG_OP = 'UPDATE' THEN
                    IF OLD.status = 'running'
                        AND NEW.status = 'running'
                        AND NEW.attempt_no = OLD.attempt_no + 1 THEN
                        SELECT * INTO previous_last
                        FROM async_job_steps
                        WHERE job_id = target_job_id
                            AND attempt_no = OLD.attempt_no
                        ORDER BY step_seq DESC
                        LIMIT 1;

                        IF previous_last.id IS NULL
                            OR previous_last.status <> 'failed'
                            OR previous_last.error_code <> 'LEASE_EXPIRED'
                            OR previous_last.finished_at
                                IS DISTINCT FROM job_record.started_at THEN
                            RAISE EXCEPTION USING
                                ERRCODE = '23514',
                                MESSAGE = 'lease recovery must share one database timestamp';
                        END IF;
                    END IF;

                    IF OLD.status = 'running'
                        AND NEW.status = 'running'
                        AND NEW.attempt_no = OLD.attempt_no
                        AND NEW.stage IS DISTINCT FROM OLD.stage
                        AND (
                            NEW.heartbeat_at IS DISTINCT FROM OLD.heartbeat_at
                            OR NEW.lease_expires_at
                                IS DISTINCT FROM OLD.lease_expires_at
                        ) THEN
                        SELECT * INTO current_last
                        FROM async_job_steps
                        WHERE job_id = target_job_id
                            AND attempt_no = NEW.attempt_no
                        ORDER BY step_seq DESC
                        LIMIT 1;

                        IF current_last.id IS NULL
                            OR current_last.started_at
                                IS DISTINCT FROM job_record.heartbeat_at THEN
                            RAISE EXCEPTION USING
                                ERRCODE = '23514',
                                MESSAGE = 'stage transition must share one database timestamp';
                        END IF;
                    END IF;
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM async_job_steps
                    WHERE job_id = target_job_id
                        AND attempt_no > job_record.attempt_no
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'async job step attempt exceeds job attempt';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM (
                        SELECT
                            attempt_no,
                            min(step_seq) AS first_seq,
                            max(step_seq) AS last_seq,
                            count(*) AS step_count
                        FROM async_job_steps
                        WHERE job_id = target_job_id
                        GROUP BY attempt_no
                    ) AS fragments
                    WHERE fragments.step_count
                        <> fragments.last_seq - fragments.first_seq + 1
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'async job attempt steps must form a continuous fragment';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM async_job_steps AS next_step
                    JOIN async_job_steps AS previous_step
                        ON previous_step.job_id = next_step.job_id
                        AND previous_step.attempt_no = next_step.attempt_no
                        AND previous_step.step_seq = next_step.step_seq - 1
                    WHERE next_step.job_id = target_job_id
                        AND previous_step.finished_at
                            IS DISTINCT FROM next_step.started_at
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'adjacent async job steps must share one database timestamp';
                END IF;

                SELECT count(*) INTO running_count
                FROM async_job_steps
                WHERE job_id = target_job_id AND status = 'running';

                IF job_record.status IN ('running', 'cancel_requested') THEN
                    IF running_count <> 1 THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'active async job requires exactly one running step';
                    END IF;

                    SELECT * INTO current_first
                    FROM async_job_steps
                    WHERE job_id = target_job_id
                        AND attempt_no = job_record.attempt_no
                    ORDER BY step_seq ASC
                    LIMIT 1;

                    SELECT * INTO current_last
                    FROM async_job_steps
                    WHERE job_id = target_job_id
                        AND attempt_no = job_record.attempt_no
                    ORDER BY step_seq DESC
                    LIMIT 1;

                    IF EXISTS (
                        SELECT 1
                        FROM async_job_steps
                        WHERE job_id = target_job_id
                            AND attempt_no = job_record.attempt_no
                            AND step_seq < current_last.step_seq
                            AND status NOT IN ('succeeded', 'skipped')
                    ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'active attempt contains an invalid prior terminal step';
                    END IF;

                    IF current_first.id IS NULL
                        OR current_first.step_code
                            <> job_record.current_attempt_start_step_code
                        OR current_first.started_at IS DISTINCT FROM job_record.started_at
                        OR current_last.status <> 'running'
                        OR current_last.step_code <> job_record.stage THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'active async job and current step are inconsistent';
                    END IF;

                ELSE
                    IF running_count <> 0 THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'inactive async job cannot retain a running step';
                    END IF;

                    IF job_record.status IN ('queued')
                        OR (job_record.status IN ('failed', 'cancelled')
                            AND job_record.started_at IS NULL) THEN
                        IF EXISTS (
                            SELECT 1
                            FROM async_job_steps
                            WHERE job_id = target_job_id
                                AND attempt_no = job_record.attempt_no + 1
                        ) THEN
                            RAISE EXCEPTION USING
                                ERRCODE = '23514',
                                MESSAGE = 'unclaimed async job attempt cannot have steps';
                        END IF;
                    ELSIF job_record.status IN ('succeeded', 'failed', 'cancelled') THEN
                        SELECT * INTO current_first
                        FROM async_job_steps
                        WHERE job_id = target_job_id
                            AND attempt_no = job_record.attempt_no
                        ORDER BY step_seq ASC
                        LIMIT 1;

                        SELECT * INTO current_last
                        FROM async_job_steps
                        WHERE job_id = target_job_id
                            AND attempt_no = job_record.attempt_no
                        ORDER BY step_seq DESC
                        LIMIT 1;

                        IF EXISTS (
                            SELECT 1
                            FROM async_job_steps
                            WHERE job_id = target_job_id
                                AND attempt_no = job_record.attempt_no
                                AND step_seq < current_last.step_seq
                                AND status NOT IN ('succeeded', 'skipped')
                        ) THEN
                            RAISE EXCEPTION USING
                                ERRCODE = '23514',
                                MESSAGE = 'terminal attempt contains an invalid prior step';
                        END IF;

                        IF current_first.id IS NULL
                            OR current_first.step_code
                                <> job_record.current_attempt_start_step_code
                            OR current_first.started_at
                                IS DISTINCT FROM job_record.started_at
                            OR current_last.step_code <> job_record.stage
                            OR current_last.finished_at IS DISTINCT FROM job_record.finished_at
                            OR (
                                job_record.status = 'succeeded'
                                AND (
                                    current_last.status <> 'succeeded'
                                    OR current_last.error_code IS NOT NULL
                                )
                            )
                            OR (
                                job_record.status = 'failed'
                                AND (
                                    current_last.status <> 'failed'
                                    OR current_last.error_code
                                        IS DISTINCT FROM job_record.error_code
                                )
                            )
                            OR (
                                job_record.status = 'cancelled'
                                AND (
                                    current_last.status <> 'cancelled'
                                    OR current_last.error_code <> 'JOB_CANCELLED'
                                )
                            ) THEN
                            RAISE EXCEPTION USING
                                ERRCODE = '23514',
                                MESSAGE = 'terminal async job and final step are inconsistent';
                        END IF;

                    END IF;
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
            CREATE FUNCTION enforce_outbox_events_state_v1()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                database_now timestamptz := clock_timestamp();
                jitter_digest bytea;
                jitter_milliseconds integer;
                retry_seconds integer;
            BEGIN
                IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'outbox events cannot be deleted or truncated';
                END IF;

                IF TG_OP = 'INSERT' THEN
                    IF NEW.status <> 'pending'
                        OR NEW.attempt_count <> 0 THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid initial outbox event state';
                    END IF;
                    IF NEW.event_type = 'job.dispatch.requested'
                        AND (
                            NEW.aggregate_type <> 'async_job'
                            OR NEW.event_version <> 1
                            OR NEW.payload_json
                                <> jsonb_build_object('job_id', NEW.aggregate_id::text)
                            OR NOT EXISTS (
                                SELECT 1
                                FROM async_jobs
                                WHERE id = NEW.aggregate_id
                                    AND status = 'queued'
                                    AND NEW.event_sequence = attempt_no + 1
                            )
                        ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid job dispatch outbox identity';
                    END IF;
                    RETURN NEW;
                END IF;

                IF ROW(
                    NEW.id,
                    NEW.aggregate_type,
                    NEW.aggregate_id,
                    NEW.event_id,
                    NEW.event_type,
                    NEW.event_version,
                    NEW.event_sequence,
                    NEW.payload_json,
                    NEW.trace_id,
                    NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.id,
                    OLD.aggregate_type,
                    OLD.aggregate_id,
                    OLD.event_id,
                    OLD.event_type,
                    OLD.event_version,
                    OLD.event_sequence,
                    OLD.payload_json,
                    OLD.trace_id,
                    OLD.created_at
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'immutable outbox event fields cannot change';
                END IF;

                IF OLD.status IN ('published', 'dead_letter') THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'terminal outbox event cannot change';
                END IF;

                IF (OLD.status = 'pending' AND NEW.status = 'processing')
                    OR (OLD.status = 'failed' AND NEW.status = 'processing') THEN
                    IF OLD.attempt_count >= 8
                        OR (OLD.status = 'failed' AND OLD.next_attempt_at > database_now) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'outbox event is not claimable';
                    END IF;
                    NEW.attempt_count := OLD.attempt_count + 1;
                    NEW.next_attempt_at := database_now + interval '60 seconds';
                    NEW.published_at := NULL;
                    NEW.last_error := NULL;
                ELSIF OLD.status = 'processing' AND NEW.status = 'published' THEN
                    IF NEW.attempt_count <> OLD.attempt_count THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'outbox fencing attempt cannot change on publish';
                    END IF;
                    NEW.next_attempt_at := NULL;
                    NEW.published_at := database_now;
                    NEW.last_error := NULL;
                ELSIF OLD.status = 'processing' AND NEW.status = 'failed' THEN
                    IF NEW.attempt_count <> OLD.attempt_count
                        OR OLD.attempt_count >= 8
                        OR NEW.last_error NOT IN (
                            'BROKER_UNAVAILABLE',
                            'BROKER_TIMEOUT',
                            'PUBLISH_CONFIRM_UNKNOWN',
                            'PROCESSING_LEASE_EXPIRED'
                        )
                        OR (
                            NEW.last_error = 'PROCESSING_LEASE_EXPIRED'
                            AND database_now < OLD.next_attempt_at
                        ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid recoverable outbox failure';
                    END IF;
                    retry_seconds := (ARRAY[1, 2, 4, 8, 16, 32, 60])[OLD.attempt_count];
                    jitter_digest := digest(
                        convert_to(lower(NEW.id::text) || ':' || NEW.attempt_count::text, 'UTF8'),
                        'sha256'
                    );
                    jitter_milliseconds := (
                        get_byte(jitter_digest, 0)::numeric * 72057594037927936
                        + get_byte(jitter_digest, 1)::numeric * 281474976710656
                        + get_byte(jitter_digest, 2)::numeric * 1099511627776
                        + get_byte(jitter_digest, 3)::numeric * 4294967296
                        + get_byte(jitter_digest, 4)::numeric * 16777216
                        + get_byte(jitter_digest, 5)::numeric * 65536
                        + get_byte(jitter_digest, 6)::numeric * 256
                        + get_byte(jitter_digest, 7)::numeric
                    )::numeric % 1000;
                    NEW.next_attempt_at := database_now
                        + make_interval(secs => retry_seconds)
                        + jitter_milliseconds * interval '1 millisecond';
                    NEW.published_at := NULL;
                ELSIF OLD.status IN ('processing', 'failed')
                    AND NEW.status = 'dead_letter' THEN
                    IF NEW.attempt_count <> OLD.attempt_count THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'outbox fencing attempt cannot change on dead-letter';
                    END IF;
                    IF NEW.last_error IN (
                        'BROKER_UNAVAILABLE',
                        'BROKER_TIMEOUT',
                        'PUBLISH_CONFIRM_UNKNOWN',
                        'PROCESSING_LEASE_EXPIRED'
                    ) THEN
                        IF OLD.attempt_count < 8 THEN
                            RAISE EXCEPTION USING
                                ERRCODE = '23514',
                                MESSAGE = 'recoverable outbox failure cannot dead-letter early';
                        END IF;
                        IF NEW.last_error = 'PROCESSING_LEASE_EXPIRED'
                            AND (
                                OLD.status <> 'processing'
                                OR database_now < OLD.next_attempt_at
                            ) THEN
                            RAISE EXCEPTION USING
                                ERRCODE = '23514',
                                MESSAGE = 'outbox processing lease has not expired';
                        END IF;
                        NEW.last_error := 'DELIVERY_ATTEMPTS_EXHAUSTED';
                    ELSIF NEW.last_error = 'DELIVERY_ATTEMPTS_EXHAUSTED'
                        AND OLD.attempt_count <> 8 THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'outbox delivery attempts are not exhausted';
                    ELSIF NEW.last_error IS NULL
                        OR NEW.last_error NOT IN (
                            'UNSUPPORTED_EVENT_VERSION',
                            'SERIALIZATION_FAILED',
                            'DELIVERY_ATTEMPTS_EXHAUSTED'
                        ) THEN
                        NEW.last_error := 'UNKNOWN_DELIVERY_ERROR';
                    END IF;
                    NEW.next_attempt_at := NULL;
                    NEW.published_at := NULL;
                ELSE
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'invalid outbox event status transition';
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
            CREATE TRIGGER trg_async_jobs_state_v1
            BEFORE INSERT OR UPDATE ON async_jobs
            FOR EACH ROW EXECUTE FUNCTION enforce_async_jobs_state_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER trg_async_jobs_consistency_v1
            AFTER INSERT OR UPDATE ON async_jobs
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION enforce_job_step_consistency_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_async_job_steps_state_v1
            BEFORE INSERT OR UPDATE OR DELETE ON async_job_steps
            FOR EACH ROW EXECUTE FUNCTION enforce_async_job_steps_state_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_async_job_steps_no_truncate_v1
            BEFORE TRUNCATE ON async_job_steps
            FOR EACH STATEMENT EXECUTE FUNCTION enforce_async_job_steps_state_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER trg_async_job_steps_consistency_v1
            AFTER INSERT OR UPDATE OR DELETE ON async_job_steps
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION enforce_job_step_consistency_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_outbox_events_state_v1
            BEFORE INSERT OR UPDATE OR DELETE ON outbox_events
            FOR EACH ROW EXECUTE FUNCTION enforce_outbox_events_state_v1()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_outbox_events_no_truncate_v1
            BEFORE TRUNCATE ON outbox_events
            FOR EACH STATEMENT EXECUTE FUNCTION enforce_outbox_events_state_v1()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE async_jobs IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE async_job_steps IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE outbox_events IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM async_jobs LIMIT 1)
                    OR EXISTS (SELECT 1 FROM async_job_steps LIMIT 1)
                    OR EXISTS (SELECT 1 FROM outbox_events LIMIT 1) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'refusing to drop non-empty reliability core tables';
                END IF;
            END;
            $$
            """
        )
    )

    op.drop_table("outbox_events")
    op.drop_table("async_job_steps")
    op.drop_table("async_jobs")
    op.execute(sa.text("DROP FUNCTION enforce_job_step_consistency_v1()"))
    op.execute(sa.text("DROP FUNCTION enforce_outbox_events_state_v1()"))
    op.execute(sa.text("DROP FUNCTION enforce_async_job_steps_state_v1()"))
    op.execute(sa.text("DROP FUNCTION enforce_async_jobs_state_v1()"))
