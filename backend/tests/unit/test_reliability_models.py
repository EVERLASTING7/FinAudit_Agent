from typing import cast

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import DefaultClause

from app.models import (
    ASYNC_JOB_STATUSES,
    ASYNC_JOB_STEP_STATUSES,
    JOB_LEASE_POLICY_HASH,
    JOB_LEASE_POLICY_VERSION,
    JOB_RETRY_POLICY_HASH,
    JOB_RETRY_POLICY_VERSION,
    OUTBOX_EVENT_STATUSES,
    Base,
)

CURRENT_HEAD_TABLES = {
    "async_job_steps",
    "async_jobs",
    "ai_call_logs",
    "audit_reports",
    "audit_risks",
    "audit_rules",
    "audit_task_executions",
    "audit_task_items",
    "audit_task_snapshots",
    "audit_tasks",
    "break_glass_requests",
    "chunking_configs",
    "contract_documents",
    "contract_fields",
    "contract_invoices",
    "contracts",
    "document_assets",
    "document_block_corrections",
    "document_blocks",
    "document_chunk_sets",
    "document_chunk_sources",
    "document_chunks",
    "document_content_exclusions",
    "document_index_items",
    "document_index_versions",
    "document_markdown_versions",
    "document_pages",
    "document_parse_versions",
    "files",
    "file_primary_business_objects",
    "idempotency_records",
    "invoice_items",
    "invoices",
    "knowledge_bases",
    "markdown_source_mappings",
    "markdown_validation_results",
    "organizations",
    "operation_logs",
    "outbox_events",
    "policy_approval_records",
    "policy_documents",
    "qa_feedback",
    "qa_queries",
    "retrieval_eval_cases",
    "retrieval_eval_datasets",
    "retrieval_eval_results",
    "retrieval_eval_runs",
    "risk_citations",
    "roles",
    "rule_executions",
    "scanner_registry_profiles",
    "supplementary_agreements",
    "supplementary_agreement_changes",
    "suppliers",
    "token_sessions",
    "user_roles",
    "user_corrections",
    "users",
}

RELIABILITY_COLUMN_CONTRACT: dict[str, tuple[tuple[str, str, bool, str | None], ...]] = {
    "async_jobs": (
        ("id", "UUID", False, "gen_random_uuid()"),
        ("organization_id", "UUID", False, None),
        ("job_type", "VARCHAR(60)", False, None),
        ("resource_type", "VARCHAR(60)", False, None),
        ("resource_id", "UUID", False, None),
        ("status", "VARCHAR(30)", False, None),
        ("stage", "VARCHAR(80)", True, None),
        ("attempt_no", "INTEGER", False, "0"),
        ("max_attempts", "INTEGER", False, None),
        ("current_attempt_start_step_code", "VARCHAR(80)", False, None),
        ("next_retry_at", "TIMESTAMP WITH TIME ZONE", True, None),
        ("worker_id", "VARCHAR(100)", True, None),
        ("started_at", "TIMESTAMP WITH TIME ZONE", True, None),
        ("finished_at", "TIMESTAMP WITH TIME ZONE", True, None),
        ("error_code", "VARCHAR(80)", True, None),
        ("error_message", "TEXT", True, None),
        ("input_hash", "CHAR(64)", False, None),
        ("input_json", "JSONB", False, None),
        ("input_schema_version", "INTEGER", False, None),
        ("idempotency_record_id", "UUID", True, None),
        ("handler_registry_version", "VARCHAR(80)", False, None),
        ("handler_registry_hash", "CHAR(64)", False, None),
        ("retry_policy_version", "VARCHAR(50)", False, None),
        ("retry_policy_hash", "CHAR(64)", False, None),
        ("lease_policy_version", "VARCHAR(50)", False, None),
        ("lease_policy_hash", "CHAR(64)", False, None),
        ("lease_owner", "VARCHAR(100)", True, None),
        ("lease_expires_at", "TIMESTAMP WITH TIME ZONE", True, None),
        ("heartbeat_at", "TIMESTAMP WITH TIME ZONE", True, None),
        ("row_version", "BIGINT", False, "1"),
        ("trace_id", "UUID", False, None),
        ("created_by", "UUID", True, None),
        ("created_at", "TIMESTAMP WITH TIME ZONE", False, "now()"),
    ),
    "async_job_steps": (
        ("id", "UUID", False, "gen_random_uuid()"),
        ("job_id", "UUID", False, None),
        ("step_seq", "INTEGER", False, None),
        ("step_code", "VARCHAR(80)", False, None),
        ("status", "VARCHAR(30)", False, None),
        ("attempt_no", "INTEGER", False, None),
        ("started_at", "TIMESTAMP WITH TIME ZONE", False, None),
        ("finished_at", "TIMESTAMP WITH TIME ZONE", True, None),
        ("summary_json", "JSONB", False, "'{}'::jsonb"),
        ("error_code", "VARCHAR(80)", True, None),
        ("trace_id", "UUID", False, None),
    ),
    "outbox_events": (
        ("id", "UUID", False, "gen_random_uuid()"),
        ("aggregate_type", "VARCHAR(80)", False, None),
        ("aggregate_id", "UUID", False, None),
        ("event_id", "UUID", False, None),
        ("event_type", "VARCHAR(100)", False, None),
        ("event_version", "INTEGER", False, None),
        ("event_sequence", "INTEGER", False, None),
        ("payload_json", "JSONB", False, None),
        ("status", "VARCHAR(30)", False, None),
        ("attempt_count", "INTEGER", False, "0"),
        ("next_attempt_at", "TIMESTAMP WITH TIME ZONE", True, None),
        ("published_at", "TIMESTAMP WITH TIME ZONE", True, None),
        ("last_error", "TEXT", True, None),
        ("trace_id", "UUID", False, None),
        ("created_at", "TIMESTAMP WITH TIME ZONE", False, "now()"),
    ),
}


def _normalize_sql(value: object) -> str:
    return " ".join(str(value).split())


RELIABILITY_CHECK_CONTRACT = {
    "async_jobs": {
        "ck_async_jobs_attempt_bounds": (
            "max_attempts >= 1 AND attempt_no >= 0 AND attempt_no <= max_attempts"
        ),
        "ck_async_jobs_current_attempt_start_step_code_format": (
            "(current_attempt_start_step_code COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'"
        ),
        "ck_async_jobs_error_code_safe_format": (
            "error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,79}$'"
        ),
        "ck_async_jobs_hashes_lower_hex": (
            "input_hash ~ '^[0-9a-f]{64}$' "
            "AND handler_registry_hash ~ '^[0-9a-f]{64}$' "
            "AND retry_policy_hash ~ '^[0-9a-f]{64}$' "
            "AND lease_policy_hash ~ '^[0-9a-f]{64}$'"
        ),
        "ck_async_jobs_input_schema_version_positive": "input_schema_version > 0",
        "ck_async_jobs_job_type_format": ("(job_type COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'"),
        "ck_async_jobs_lease_owner_canonical_uuid_v4": (
            "lease_owner IS NULL OR lease_owner ~ "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
            "[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"
        ),
        "ck_async_jobs_row_version_positive": "row_version > 0",
        "ck_async_jobs_stage_format": (
            "stage IS NULL OR (stage COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'"
        ),
        "ck_async_jobs_state_field_matrix": """
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
        "ck_async_jobs_status_allowed": (
            "status IN ('queued', 'running', 'cancel_requested', "
            "'succeeded', 'failed', 'cancelled')"
        ),
        "ck_async_jobs_version_formats": (
            '(handler_registry_version COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$' "
            'AND (retry_policy_version COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$' "
            'AND (lease_policy_version COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$'"
        ),
    },
    "async_job_steps": {
        "ck_async_job_steps_attempt_no_positive": "attempt_no > 0",
        "ck_async_job_steps_error_code_safe_format": (
            "error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,79}$'"
        ),
        "ck_async_job_steps_state_field_matrix": """
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
        "ck_async_job_steps_status_allowed": (
            "status IN ('running', 'succeeded', 'failed', 'cancelled', 'skipped')"
        ),
        "ck_async_job_steps_step_code_format": ("(step_code COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'"),
        "ck_async_job_steps_step_seq_positive": "step_seq > 0",
    },
    "outbox_events": {
        "ck_outbox_events_attempt_count_bounds": "attempt_count BETWEEN 0 AND 8",
        "ck_outbox_events_event_sequence_positive": "event_sequence > 0",
        "ck_outbox_events_event_version_positive": "event_version > 0",
        "ck_outbox_events_identity_nonempty": (
            "btrim(aggregate_type) <> '' AND btrim(event_type) <> ''"
        ),
        "ck_outbox_events_state_field_matrix": """
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
        "ck_outbox_events_status_allowed": (
            "status IN ('pending', 'processing', 'failed', 'published', 'dead_letter')"
        ),
    },
}

RELIABILITY_FOREIGN_KEY_CONTRACT = {
    "async_jobs": {
        "fk_async_jobs_created_by_users": (
            ("created_by",),
            ("users.id",),
            None,
            None,
        ),
        "fk_async_jobs_idempotency_record_id_idempotency_records": (
            ("idempotency_record_id",),
            ("idempotency_records.id",),
            None,
            None,
        ),
        "fk_async_jobs_organization_id_organizations": (
            ("organization_id",),
            ("organizations.id",),
            None,
            None,
        ),
    },
    "async_job_steps": {
        "fk_async_job_steps_job_id_async_jobs": (
            ("job_id",),
            ("async_jobs.id",),
            None,
            None,
        )
    },
    "outbox_events": {},
}

RELIABILITY_UNIQUE_CONTRACT = {
    "async_jobs": {},
    "async_job_steps": {
        "uq_async_job_steps_job_id_step_seq_attempt_no": (
            "job_id",
            "step_seq",
            "attempt_no",
        )
    },
    "outbox_events": {
        "uq_outbox_events_aggregate_type_aggregate_id_event_sequence": (
            "aggregate_type",
            "aggregate_id",
            "event_sequence",
        ),
        "uq_outbox_events_event_id_event_type": ("event_id", "event_type"),
    },
}


def _column_contract(table: Table) -> tuple[tuple[str, str, bool, str | None], ...]:
    result: list[tuple[str, str, bool, str | None]] = []
    for column in table.c:
        nullable = column.nullable
        assert nullable is not None
        column_type = (
            "TIMESTAMP WITH TIME ZONE"
            if isinstance(column.type, DateTime) and column.type.timezone
            else str(column.type)
        )
        default = column.server_default
        default_sql = None if default is None else str(cast(DefaultClause, default).arg)
        result.append((column.name, column_type, nullable, default_sql))
    return tuple(result)


def _check_contract(table: Table) -> dict[str, str]:
    return {
        str(constraint.name): _normalize_sql(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def _foreign_key_contract(
    table: Table,
) -> dict[str, tuple[tuple[str, ...], tuple[str, ...], str | None, str | None]]:
    return {
        str(constraint.name): (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.onupdate,
            constraint.ondelete,
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name is not None
    }


def _unique_contract(table: Table) -> dict[str, tuple[str, ...]]:
    return {
        str(constraint.name): tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name is not None
    }


def _index_contract(table_name: str) -> dict[str, tuple[bool, tuple[str, ...], str | None]]:
    table = Base.metadata.tables[table_name]
    return {
        str(index.name): (
            index.unique,
            tuple(str(expression) for expression in index.expressions),
            (
                None
                if index.dialect_options["postgresql"]["where"] is None
                else str(index.dialect_options["postgresql"]["where"])
            ),
        )
        for index in table.indexes
        if index.name is not None
    }


def test_current_metadata_contains_exactly_fifty_seven_tables() -> None:
    assert set(Base.metadata.tables) == CURRENT_HEAD_TABLES
    assert sum(len(columns) for columns in RELIABILITY_COLUMN_CONTRACT.values()) == 59


def test_idempotency_record_contract_is_exact() -> None:
    table = Base.metadata.tables["idempotency_records"]

    assert list(table.c.keys()) == [
        "id",
        "organization_id",
        "user_id",
        "idempotency_key",
        "request_method",
        "request_path",
        "request_hash",
        "response_status",
        "response_body_json",
        "resource_type",
        "resource_id",
        "expires_at",
        "created_at",
    ]
    assert isinstance(table.c.request_hash.type, CHAR)
    assert table.c.request_hash.type.length == 64
    assert isinstance(table.c.response_body_json.type, JSONB)

    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    uniques = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert checks == {"ck_idempotency_records_expires_after_creation"}
    assert uniques == {"uq_idempotency_records_organization_user_key"}


def test_reliability_constants_are_exact() -> None:
    assert ASYNC_JOB_STATUSES == (
        "queued",
        "running",
        "cancel_requested",
        "succeeded",
        "failed",
        "cancelled",
    )
    assert ASYNC_JOB_STEP_STATUSES == (
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "skipped",
    )
    assert OUTBOX_EVENT_STATUSES == (
        "pending",
        "processing",
        "failed",
        "published",
        "dead_letter",
    )
    assert JOB_RETRY_POLICY_VERSION == "job-retry-policy-v1"
    assert JOB_RETRY_POLICY_HASH == (
        "9cdb2a30bba1e39155adcb3bcb55fe6465811b63290d249ccbfac4f976cdbba7"
    )
    assert JOB_LEASE_POLICY_VERSION == "job-lease-v1"
    assert JOB_LEASE_POLICY_HASH == (
        "50a6acee62769713152039af330cc4a779cc758ea36b97102308b1bc08564d00"
    )


def test_async_jobs_model_contract_is_exact() -> None:
    table = Base.metadata.tables["async_jobs"]

    assert _column_contract(table) == RELIABILITY_COLUMN_CONTRACT["async_jobs"]
    assert "retryable" not in table.c
    assert "idempotency_key" not in table.c
    assert isinstance(table.c.input_json.type, JSONB)
    for column_name in (
        "input_hash",
        "handler_registry_hash",
        "retry_policy_hash",
        "lease_policy_hash",
    ):
        column = table.c[column_name]
        assert isinstance(column.type, CHAR)
        assert column.type.length == 64
    assert _check_contract(table) == {
        name: _normalize_sql(definition)
        for name, definition in RELIABILITY_CHECK_CONTRACT["async_jobs"].items()
    }
    assert _foreign_key_contract(table) == RELIABILITY_FOREIGN_KEY_CONTRACT["async_jobs"]
    assert _unique_contract(table) == RELIABILITY_UNIQUE_CONTRACT["async_jobs"]
    assert _index_contract("async_jobs") == {
        "idx_async_jobs_claim": (
            False,
            ("async_jobs.status", "async_jobs.next_retry_at"),
            None,
        ),
        "idx_async_jobs_resource_created": (
            False,
            (
                "async_jobs.resource_type",
                "async_jobs.resource_id",
                "created_at DESC",
            ),
            None,
        ),
        "uq_async_jobs_active_resource_input": (
            True,
            (
                "async_jobs.organization_id",
                "async_jobs.job_type",
                "async_jobs.resource_type",
                "async_jobs.resource_id",
                "async_jobs.input_hash",
            ),
            "status IN ('queued', 'running', 'cancel_requested')",
        ),
    }


def test_async_job_steps_model_contract_is_exact() -> None:
    table = Base.metadata.tables["async_job_steps"]

    assert _column_contract(table) == RELIABILITY_COLUMN_CONTRACT["async_job_steps"]
    assert isinstance(table.c.summary_json.type, JSONB)
    assert _check_contract(table) == {
        name: _normalize_sql(definition)
        for name, definition in RELIABILITY_CHECK_CONTRACT["async_job_steps"].items()
    }
    assert _foreign_key_contract(table) == RELIABILITY_FOREIGN_KEY_CONTRACT["async_job_steps"]
    assert _unique_contract(table) == RELIABILITY_UNIQUE_CONTRACT["async_job_steps"]
    assert _index_contract("async_job_steps") == {
        "uq_async_job_steps_one_running_per_attempt": (
            True,
            ("async_job_steps.job_id", "async_job_steps.attempt_no"),
            "status = 'running'",
        )
    }


def test_outbox_events_model_contract_is_exact() -> None:
    table = Base.metadata.tables["outbox_events"]

    assert _column_contract(table) == RELIABILITY_COLUMN_CONTRACT["outbox_events"]
    assert isinstance(table.c.payload_json.type, JSONB)
    assert _check_contract(table) == {
        name: _normalize_sql(definition)
        for name, definition in RELIABILITY_CHECK_CONTRACT["outbox_events"].items()
    }
    assert _foreign_key_contract(table) == RELIABILITY_FOREIGN_KEY_CONTRACT["outbox_events"]
    assert _unique_contract(table) == RELIABILITY_UNIQUE_CONTRACT["outbox_events"]
    assert _index_contract("outbox_events") == {
        "idx_outbox_events_claim": (
            False,
            (
                "outbox_events.status",
                "outbox_events.next_attempt_at",
                "outbox_events.created_at",
            ),
            None,
        )
    }
