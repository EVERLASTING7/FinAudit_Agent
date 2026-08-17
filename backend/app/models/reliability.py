"""BASE-005 幂等记录模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

ASYNC_JOB_STATUSES = (
    "queued",
    "running",
    "cancel_requested",
    "succeeded",
    "failed",
    "cancelled",
)
ASYNC_JOB_STEP_STATUSES = ("running", "succeeded", "failed", "cancelled", "skipped")
OUTBOX_EVENT_STATUSES = ("pending", "processing", "failed", "published", "dead_letter")
JOB_RETRY_POLICY_VERSION = "job-retry-policy-v1"
JOB_RETRY_POLICY_HASH = "9cdb2a30bba1e39155adcb3bcb55fe6465811b63290d249ccbfac4f976cdbba7"
JOB_LEASE_POLICY_VERSION = "job-lease-v1"
JOB_LEASE_POLICY_HASH = "50a6acee62769713152039af330cc4a779cc758ea36b97102308b1bc08564d00"


class IdempotencyRecord(Base):
    """API 写请求的幂等键、请求哈希与脱敏响应快照。"""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        UniqueConstraint(
            "organization_id",
            "user_id",
            "idempotency_key",
            name="uq_idempotency_records_organization_user_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            name="fk_idempotency_records_organization_id_organizations",
        ),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_idempotency_records_user_id_users"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_method: Mapped[str] = mapped_column(String(10), nullable=False)
    request_path: Mapped[str] = mapped_column(String(500), nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AsyncJob(Base):
    """PostgreSQL 权威的可恢复长任务状态；具体 Handler 由后续批准制品提供。"""

    __tablename__ = "async_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'cancel_requested', "
            "'succeeded', 'failed', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint(
            "max_attempts >= 1 AND attempt_no >= 0 AND attempt_no <= max_attempts",
            name="attempt_bounds",
        ),
        CheckConstraint("input_schema_version > 0", name="input_schema_version_positive"),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        CheckConstraint(
            "(job_type COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'",
            name="job_type_format",
        ),
        CheckConstraint(
            "(current_attempt_start_step_code COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'",
            name="current_attempt_start_step_code_format",
        ),
        CheckConstraint(
            "stage IS NULL OR (stage COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'",
            name="stage_format",
        ),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$' "
            "AND handler_registry_hash ~ '^[0-9a-f]{64}$' "
            "AND retry_policy_hash ~ '^[0-9a-f]{64}$' "
            "AND lease_policy_hash ~ '^[0-9a-f]{64}$'",
            name="hashes_lower_hex",
        ),
        CheckConstraint(
            '(handler_registry_version COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$' "
            'AND (retry_policy_version COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$' "
            'AND (lease_policy_version COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$'",
            name="version_formats",
        ),
        CheckConstraint(
            "lease_owner IS NULL OR lease_owner ~ "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
            "[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="lease_owner_canonical_uuid_v4",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,79}$'",
            name="error_code_safe_format",
        ),
        CheckConstraint(
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
        Index(
            "uq_async_jobs_active_resource_input",
            "organization_id",
            "job_type",
            "resource_type",
            "resource_id",
            "input_hash",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'cancel_requested')"),
        ),
        Index("idx_async_jobs_claim", "status", "next_retry_at"),
        Index(
            "idx_async_jobs_resource_created",
            "resource_type",
            "resource_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_async_jobs_organization_id_organizations"),
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(80))
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    current_attempt_start_step_code: Mapped[str] = mapped_column(String(80), nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    input_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    input_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    input_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_record_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "idempotency_records.id",
            name="fk_async_jobs_idempotency_record_id_idempotency_records",
        ),
    )
    handler_registry_version: Mapped[str] = mapped_column(String(80), nullable=False)
    handler_registry_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    retry_policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    retry_policy_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    lease_policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    lease_policy_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_async_jobs_created_by_users"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AsyncJobStep(Base):
    """单个 Job attempt 的追加式绝对步骤历史。"""

    __tablename__ = "async_job_steps"
    __table_args__ = (
        CheckConstraint("step_seq > 0", name="step_seq_positive"),
        CheckConstraint("attempt_no > 0", name="attempt_no_positive"),
        CheckConstraint(
            "(step_code COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'",
            name="step_code_format",
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'cancelled', 'skipped')",
            name="status_allowed",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,79}$'",
            name="error_code_safe_format",
        ),
        CheckConstraint(
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
        UniqueConstraint(
            "job_id",
            "step_seq",
            "attempt_no",
            name="uq_async_job_steps_job_id_step_seq_attempt_no",
        ),
        Index(
            "uq_async_job_steps_one_running_per_attempt",
            "job_id",
            "attempt_no",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("async_jobs.id", name="fk_async_job_steps_job_id_async_jobs"),
        nullable=False,
    )
    step_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    step_code: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class OutboxEvent(Base):
    """身份不可变、仅允许投递状态推进的可靠事件。"""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("event_version > 0", name="event_version_positive"),
        CheckConstraint("event_sequence > 0", name="event_sequence_positive"),
        CheckConstraint("attempt_count BETWEEN 0 AND 8", name="attempt_count_bounds"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'failed', 'published', 'dead_letter')",
            name="status_allowed",
        ),
        CheckConstraint(
            "btrim(aggregate_type) <> '' AND btrim(event_type) <> ''",
            name="identity_nonempty",
        ),
        CheckConstraint(
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
        UniqueConstraint("event_id", "event_type", name="uq_outbox_events_event_id_event_type"),
        UniqueConstraint(
            "aggregate_type",
            "aggregate_id",
            "event_sequence",
            name="uq_outbox_events_aggregate_type_aggregate_id_event_sequence",
        ),
        Index("idx_outbox_events_claim", "status", "next_attempt_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
