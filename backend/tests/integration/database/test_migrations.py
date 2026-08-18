import os
import re
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from threading import Barrier
from time import monotonic
from typing import cast
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import URL, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, StatementError

from alembic import command
from alembic import op as alembic_op
from app.db.migration import create_migration_engine

EXPECTED_EXTENSIONS = {"btree_gist", "citext", "pgcrypto"}
TABLES_AT_006 = {
    "audit_rules",
    "audit_tasks",
    "contracts",
    "invoices",
    "organizations",
    "suppliers",
    "users",
    "roles",
    "token_sessions",
    "idempotency_records",
}
RELIABILITY_TABLES = ("async_jobs", "async_job_steps", "outbox_events")
PRIVILEGED_AUTH_TABLES = ("break_glass_requests", "user_roles")
FINANCIAL_RELATIONSHIP_TABLES = (
    "supplementary_agreements",
    "invoice_items",
    "contract_invoices",
)
OPERATION_LOG_TABLES = ("operation_logs",)
FILE_INTAKE_TABLES = ("knowledge_bases", "files")
DOCUMENT_PROCESSING_TABLES = (
    "document_parse_versions",
    "document_pages",
    "document_assets",
    "document_blocks",
    "document_content_exclusions",
)
FINANCIAL_FACT_DETAIL_TABLES = (
    "file_primary_business_objects",
    "contract_fields",
    "supplementary_agreement_changes",
    "user_corrections",
)
MARKDOWN_KNOWLEDGE_TABLES = (
    "document_block_corrections",
    "document_markdown_versions",
    "markdown_source_mappings",
    "markdown_validation_results",
    "policy_documents",
    "policy_approval_records",
    "chunking_configs",
    "document_chunk_sets",
    "document_chunks",
    "document_chunk_sources",
    "contract_documents",
)
RETRIEVAL_RUNTIME_TABLES = (
    "document_index_versions",
    "document_index_items",
    "retrieval_eval_datasets",
    "retrieval_eval_cases",
    "retrieval_eval_runs",
    "retrieval_eval_results",
    "qa_queries",
    "qa_feedback",
)
AUDIT_REPORT_RUNTIME_TABLES = (
    "audit_task_items",
    "audit_task_executions",
    "audit_task_snapshots",
    "rule_executions",
    "audit_risks",
    "risk_citations",
    "audit_reports",
    "ai_call_logs",
)
TABLES_AT_007 = TABLES_AT_006 | set(RELIABILITY_TABLES)
TABLES_AT_008 = TABLES_AT_007 | set(PRIVILEGED_AUTH_TABLES)
TABLES_AT_009 = TABLES_AT_008 | set(FINANCIAL_RELATIONSHIP_TABLES)
TABLES_AT_010 = TABLES_AT_009 | set(OPERATION_LOG_TABLES)
TABLES_AT_011 = TABLES_AT_010 | set(FILE_INTAKE_TABLES)
TABLES_AT_013 = TABLES_AT_011 | set(DOCUMENT_PROCESSING_TABLES)
TABLES_AT_014 = TABLES_AT_013 | set(FINANCIAL_FACT_DETAIL_TABLES)
TABLES_AT_015 = TABLES_AT_014
TABLES_AT_016 = TABLES_AT_015
TABLES_AT_017 = TABLES_AT_016
TABLES_AT_018 = TABLES_AT_017 | set(MARKDOWN_KNOWLEDGE_TABLES)
TABLES_AT_019 = TABLES_AT_018 | set(RETRIEVAL_RUNTIME_TABLES)
TABLES_AT_020 = TABLES_AT_019 | set(AUDIT_REPORT_RUNTIME_TABLES)
TABLES_AT_021 = TABLES_AT_020
TABLES_AT_022 = TABLES_AT_021
TABLES_AT_023 = TABLES_AT_022
TABLES_AT_024 = TABLES_AT_023
CURRENT_HEAD_TABLES = TABLES_AT_024
EXPECTED_ROLE_CODES = {
    "system_admin",
    "finance_reviewer",
    "audit_reviewer",
    "contract_admin",
    "read_only",
}
BACKEND_ROOT = Path(__file__).resolve().parents[3]
DESTRUCTIVE_CONFIRMATION_ENV = "FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS"
DESTRUCTIVE_CONFIRMATION_VALUE = "RESET_DISPOSABLE_FINAUDIT_TEST_DATABASE"
DISPOSABLE_DATABASE_COMMENT = "finaudit:disposable-migration-test"
SAFE_DATABASE_NAME = re.compile(r"^finaudit_[a-z0-9_]+_test$")
FINANCIAL_TABLES = ("contracts", "invoices", "suppliers")
FINANCIAL_ORGANIZATION_ID = "61111111-1111-4111-8111-111111111111"
FINANCIAL_ACTOR_ID = "61111111-1111-4111-8111-111111111112"
FINANCIAL_REVISION = "20260807_006"
PREVIOUS_FINANCIAL_REVISION = "20260807_005"
RELIABILITY_REVISION = "20260807_007"
PRIVILEGED_AUTH_REVISION = "20260807_008"
FINANCIAL_RELATIONSHIP_REVISION = "20260807_009"
OPERATION_LOG_REVISION = "20260813_010"
FILE_INTAKE_REVISION = "20260813_011"
FILE_ORIGINAL_LOCATOR_REVISION = "20260813_012"
DOCUMENT_PROCESSING_REVISION = "20260813_013"
FINANCIAL_FACT_DETAIL_REVISION = "20260813_014"
CONTRACT_INVOICE_HISTORY_REVISION = "20260813_015"
INVOICE_FACTS_REVISION = "20260814_016"
SUPPLIER_RUNTIME_REVISION = "20260814_017"
MARKDOWN_KNOWLEDGE_REVISION = "20260814_018"
RETRIEVAL_RUNTIME_REVISION = "20260814_019"
AUDIT_REPORT_RUNTIME_REVISION = "20260814_020"
RETRIEVAL_INITIAL_STATE_REVISION = "20260815_021"
INVOICE_NULL_CURRENCY_REVISION = "20260816_022"
AI_GENERATED_FACTS_REVISION = "20260816_023"
CURRENCY_NEUTRAL_AI_COST_REVISION = "20260817_024"
CURRENT_REVISION = CURRENCY_NEUTRAL_AI_COST_REVISION
PRIVILEGED_AUTH_FUNCTIONS = {
    "enforce_break_glass_requests_state_v1",
    "enforce_user_roles_state_v1",
    "enforce_break_glass_role_consistency_v1",
    "enforce_long_term_role_separation_v1",
    "enforce_roles_invariants_v1",
}
PRIVILEGED_AUTH_TRIGGERS = {
    "break_glass_requests": {
        "trg_break_glass_requests_state_v1",
        "trg_break_glass_requests_no_truncate_v1",
        "trg_break_glass_requests_consistency_v1",
    },
    "user_roles": {
        "trg_user_roles_state_v1",
        "trg_user_roles_no_truncate_v1",
        "trg_user_roles_consistency_v1",
        "trg_user_roles_sod_v1",
    },
    "users": {"trg_users_role_sod_v1"},
    "roles": {"trg_roles_invariants_v1", "trg_roles_role_sod_v1"},
}
RELIABILITY_ORGANIZATION_ID = "62222222-2222-4222-8222-222222222222"
LEASE_POLICY_VERSION = "job-lease-v1"
LEASE_POLICY_HASH = "50a6acee62769713152039af330cc4a779cc758ea36b97102308b1bc08564d00"
RETRY_POLICY_VERSION = "job-retry-policy-v1"
RETRY_POLICY_HASH = "9cdb2a30bba1e39155adcb3bcb55fe6465811b63290d249ccbfac4f976cdbba7"
RELIABILITY_COLUMN_CONTRACT = {
    "async_jobs": (
        ("id", "uuid", "NO", None),
        ("organization_id", "uuid", "NO", None),
        ("job_type", "varchar", "NO", 60),
        ("resource_type", "varchar", "NO", 60),
        ("resource_id", "uuid", "NO", None),
        ("status", "varchar", "NO", 30),
        ("stage", "varchar", "YES", 80),
        ("attempt_no", "int4", "NO", None),
        ("max_attempts", "int4", "NO", None),
        ("current_attempt_start_step_code", "varchar", "NO", 80),
        ("next_retry_at", "timestamptz", "YES", None),
        ("worker_id", "varchar", "YES", 100),
        ("started_at", "timestamptz", "YES", None),
        ("finished_at", "timestamptz", "YES", None),
        ("error_code", "varchar", "YES", 80),
        ("error_message", "text", "YES", None),
        ("input_hash", "bpchar", "NO", 64),
        ("input_json", "jsonb", "NO", None),
        ("input_schema_version", "int4", "NO", None),
        ("idempotency_record_id", "uuid", "YES", None),
        ("handler_registry_version", "varchar", "NO", 80),
        ("handler_registry_hash", "bpchar", "NO", 64),
        ("retry_policy_version", "varchar", "NO", 50),
        ("retry_policy_hash", "bpchar", "NO", 64),
        ("lease_policy_version", "varchar", "NO", 50),
        ("lease_policy_hash", "bpchar", "NO", 64),
        ("lease_owner", "varchar", "YES", 100),
        ("lease_expires_at", "timestamptz", "YES", None),
        ("heartbeat_at", "timestamptz", "YES", None),
        ("row_version", "int8", "NO", None),
        ("trace_id", "uuid", "NO", None),
        ("created_by", "uuid", "YES", None),
        ("created_at", "timestamptz", "NO", None),
    ),
    "async_job_steps": (
        ("id", "uuid", "NO", None),
        ("job_id", "uuid", "NO", None),
        ("step_seq", "int4", "NO", None),
        ("step_code", "varchar", "NO", 80),
        ("status", "varchar", "NO", 30),
        ("attempt_no", "int4", "NO", None),
        ("started_at", "timestamptz", "NO", None),
        ("finished_at", "timestamptz", "YES", None),
        ("summary_json", "jsonb", "NO", None),
        ("error_code", "varchar", "YES", 80),
        ("trace_id", "uuid", "NO", None),
    ),
    "outbox_events": (
        ("id", "uuid", "NO", None),
        ("aggregate_type", "varchar", "NO", 80),
        ("aggregate_id", "uuid", "NO", None),
        ("event_id", "uuid", "NO", None),
        ("event_type", "varchar", "NO", 100),
        ("event_version", "int4", "NO", None),
        ("event_sequence", "int4", "NO", None),
        ("payload_json", "jsonb", "NO", None),
        ("status", "varchar", "NO", 30),
        ("attempt_count", "int4", "NO", None),
        ("next_attempt_at", "timestamptz", "YES", None),
        ("published_at", "timestamptz", "YES", None),
        ("last_error", "text", "YES", None),
        ("trace_id", "uuid", "NO", None),
        ("created_at", "timestamptz", "NO", None),
    ),
}
RELIABILITY_CONSTRAINTS = {
    "async_jobs": {
        "ck_async_jobs_attempt_bounds": (
            "c",
            "CHECK (max_attempts >= 1 AND attempt_no >= 0 AND attempt_no <= max_attempts)",
        ),
        "ck_async_jobs_current_attempt_start_step_code_format": (
            "c",
            'CHECK ((current_attempt_start_step_code::text COLLATE "C") '
            "~ '^[a-z][a-z0-9_]*$'::text)",
        ),
        "ck_async_jobs_error_code_safe_format": (
            "c",
            "CHECK (error_code IS NULL OR error_code::text ~ '^[A-Z][A-Z0-9_]{0,79}$'::text)",
        ),
        "ck_async_jobs_hashes_lower_hex": (
            "c",
            "CHECK (input_hash ~ '^[0-9a-f]{64}$'::text "
            "AND handler_registry_hash ~ '^[0-9a-f]{64}$'::text "
            "AND retry_policy_hash ~ '^[0-9a-f]{64}$'::text "
            "AND lease_policy_hash ~ '^[0-9a-f]{64}$'::text)",
        ),
        "ck_async_jobs_input_schema_version_positive": (
            "c",
            "CHECK (input_schema_version > 0)",
        ),
        "ck_async_jobs_job_type_format": (
            "c",
            "CHECK ((job_type::text COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'::text)",
        ),
        "ck_async_jobs_lease_owner_canonical_uuid_v4": (
            "c",
            "CHECK (lease_owner IS NULL OR lease_owner::text ~ "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
            "[89ab][0-9a-f]{3}-[0-9a-f]{12}$'::text)",
        ),
        "ck_async_jobs_row_version_positive": ("c", "CHECK (row_version > 0)"),
        "ck_async_jobs_stage_format": (
            "c",
            "CHECK (stage IS NULL OR (stage::text COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'::text)",
        ),
        "ck_async_jobs_state_field_matrix": (
            "c",
            "CHECK (status::text = 'queued'::text AND attempt_no < max_attempts "
            "AND stage IS NULL AND next_retry_at IS NULL AND worker_id IS NULL "
            "AND started_at IS NULL AND finished_at IS NULL AND error_code IS NULL "
            "AND error_message IS NULL AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND heartbeat_at IS NULL "
            "OR (status::text = ANY (ARRAY['running'::character varying, "
            "'cancel_requested'::character varying]::text[])) AND attempt_no >= 1 "
            "AND stage IS NOT NULL AND next_retry_at IS NULL AND worker_id IS NOT NULL "
            "AND btrim(worker_id::text) <> ''::text AND started_at IS NOT NULL "
            "AND finished_at IS NULL AND error_code IS NULL AND error_message IS NULL "
            "AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND heartbeat_at IS NOT NULL AND started_at <= heartbeat_at "
            "AND heartbeat_at < lease_expires_at OR status::text = 'succeeded'::text "
            "AND attempt_no >= 1 AND stage IS NOT NULL AND next_retry_at IS NULL "
            "AND worker_id IS NULL AND started_at IS NOT NULL AND finished_at IS NOT NULL "
            "AND finished_at >= started_at AND error_code IS NULL "
            "AND error_message IS NULL AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND heartbeat_at IS NULL "
            "OR status::text = 'failed'::text AND finished_at IS NOT NULL "
            "AND error_code IS NOT NULL AND worker_id IS NULL AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND heartbeat_at IS NULL "
            "AND (started_at IS NULL AND stage IS NULL AND next_retry_at IS NULL "
            "AND (error_code::text = ANY (ARRAY['JOB_DISPATCH_FAILED'::character varying, "
            "'JOB_DISPATCH_OUTCOME_UNKNOWN'::character varying]::text[])) "
            "OR attempt_no >= 1 AND started_at IS NOT NULL AND stage IS NOT NULL "
            "AND finished_at >= started_at AND ((error_code::text = ANY "
            "(ARRAY['DATABASE_TRANSIENT'::character varying, "
            "'DEPENDENCY_TIMEOUT'::character varying, "
            "'DEPENDENCY_UNAVAILABLE'::character varying, "
            "'RATE_LIMITED'::character varying, 'STORAGE_TRANSIENT'::character varying, "
            "'WORKER_LOST'::character varying]::text[])) AND attempt_no < max_attempts "
            "AND next_retry_at = finished_at OR ((error_code::text <> ALL "
            "(ARRAY['DATABASE_TRANSIENT'::character varying, "
            "'DEPENDENCY_TIMEOUT'::character varying, "
            "'DEPENDENCY_UNAVAILABLE'::character varying, "
            "'RATE_LIMITED'::character varying, 'STORAGE_TRANSIENT'::character varying, "
            "'WORKER_LOST'::character varying]::text[])) OR attempt_no = max_attempts) "
            "AND next_retry_at IS NULL)) OR status::text = 'cancelled'::text "
            "AND finished_at IS NOT NULL AND error_code::text = 'JOB_CANCELLED'::text "
            "AND error_message IS NULL AND next_retry_at IS NULL AND worker_id IS NULL "
            "AND lease_owner IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL "
            "AND (started_at IS NULL AND stage IS NULL OR attempt_no >= 1 "
            "AND started_at IS NOT NULL AND stage IS NOT NULL "
            "AND finished_at >= started_at))",
        ),
        "ck_async_jobs_status_allowed": (
            "c",
            "CHECK (status::text = ANY (ARRAY['queued'::character varying, "
            "'running'::character varying, 'cancel_requested'::character varying, "
            "'succeeded'::character varying, 'failed'::character varying, "
            "'cancelled'::character varying]::text[]))",
        ),
        "ck_async_jobs_version_formats": (
            "c",
            'CHECK ((handler_registry_version::text COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$'::text "
            'AND (retry_policy_version::text COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$'::text "
            'AND (lease_policy_version::text COLLATE "C") '
            "~ '^[a-z0-9][a-z0-9._-]*$'::text)",
        ),
        "fk_async_jobs_created_by_users": (
            "f",
            "FOREIGN KEY (created_by) REFERENCES users(id)",
        ),
        "fk_async_jobs_idempotency_record_id_idempotency_records": (
            "f",
            "FOREIGN KEY (idempotency_record_id) REFERENCES idempotency_records(id)",
        ),
        "fk_async_jobs_organization_id_organizations": (
            "f",
            "FOREIGN KEY (organization_id) REFERENCES organizations(id)",
        ),
        "pk_async_jobs": ("p", "PRIMARY KEY (id)"),
    },
    "async_job_steps": {
        "ck_async_job_steps_attempt_no_positive": ("c", "CHECK (attempt_no > 0)"),
        "ck_async_job_steps_error_code_safe_format": (
            "c",
            "CHECK (error_code IS NULL OR error_code::text ~ '^[A-Z][A-Z0-9_]{0,79}$'::text)",
        ),
        "ck_async_job_steps_state_field_matrix": (
            "c",
            "CHECK (status::text = 'running'::text AND finished_at IS NULL "
            "AND error_code IS NULL OR status::text = 'succeeded'::text "
            "AND finished_at IS NOT NULL AND finished_at >= started_at "
            "AND error_code IS NULL OR status::text = 'skipped'::text "
            "AND finished_at IS NOT NULL AND finished_at >= started_at "
            "AND error_code::text = 'STEP_SKIPPED'::text "
            "OR status::text = 'failed'::text AND finished_at IS NOT NULL "
            "AND finished_at >= started_at AND error_code IS NOT NULL "
            "OR status::text = 'cancelled'::text AND finished_at IS NOT NULL "
            "AND finished_at >= started_at "
            "AND error_code::text = 'JOB_CANCELLED'::text)",
        ),
        "ck_async_job_steps_status_allowed": (
            "c",
            "CHECK (status::text = ANY (ARRAY['running'::character varying, "
            "'succeeded'::character varying, 'failed'::character varying, "
            "'cancelled'::character varying, 'skipped'::character varying]::text[]))",
        ),
        "ck_async_job_steps_step_code_format": (
            "c",
            "CHECK ((step_code::text COLLATE \"C\") ~ '^[a-z][a-z0-9_]*$'::text)",
        ),
        "ck_async_job_steps_step_seq_positive": ("c", "CHECK (step_seq > 0)"),
        "fk_async_job_steps_job_id_async_jobs": (
            "f",
            "FOREIGN KEY (job_id) REFERENCES async_jobs(id)",
        ),
        "pk_async_job_steps": ("p", "PRIMARY KEY (id)"),
        "uq_async_job_steps_job_id_step_seq_attempt_no": (
            "u",
            "UNIQUE (job_id, step_seq, attempt_no)",
        ),
    },
    "outbox_events": {
        "ck_outbox_events_attempt_count_bounds": (
            "c",
            "CHECK (attempt_count >= 0 AND attempt_count <= 8)",
        ),
        "ck_outbox_events_event_sequence_positive": (
            "c",
            "CHECK (event_sequence > 0)",
        ),
        "ck_outbox_events_event_version_positive": (
            "c",
            "CHECK (event_version > 0)",
        ),
        "ck_outbox_events_identity_nonempty": (
            "c",
            "CHECK (btrim(aggregate_type::text) <> ''::text "
            "AND btrim(event_type::text) <> ''::text)",
        ),
        "ck_outbox_events_state_field_matrix": (
            "c",
            "CHECK (status::text = 'pending'::text AND attempt_count = 0 "
            "AND next_attempt_at IS NULL AND published_at IS NULL AND last_error IS NULL "
            "OR status::text = 'processing'::text AND attempt_count >= 1 "
            "AND attempt_count <= 8 AND next_attempt_at IS NOT NULL "
            "AND published_at IS NULL AND last_error IS NULL "
            "OR status::text = 'failed'::text AND attempt_count >= 1 "
            "AND attempt_count <= 7 AND next_attempt_at IS NOT NULL "
            "AND published_at IS NULL AND (last_error = ANY "
            "(ARRAY['BROKER_UNAVAILABLE'::text, 'BROKER_TIMEOUT'::text, "
            "'PUBLISH_CONFIRM_UNKNOWN'::text, 'PROCESSING_LEASE_EXPIRED'::text])) "
            "OR status::text = 'published'::text AND attempt_count >= 1 "
            "AND attempt_count <= 8 AND next_attempt_at IS NULL "
            "AND published_at IS NOT NULL AND last_error IS NULL "
            "OR status::text = 'dead_letter'::text AND attempt_count >= 1 "
            "AND attempt_count <= 8 AND next_attempt_at IS NULL "
            "AND published_at IS NULL AND (attempt_count = 8 "
            "AND last_error = 'DELIVERY_ATTEMPTS_EXHAUSTED'::text OR (last_error = ANY "
            "(ARRAY['UNSUPPORTED_EVENT_VERSION'::text, 'SERIALIZATION_FAILED'::text, "
            "'UNKNOWN_DELIVERY_ERROR'::text]))))",
        ),
        "ck_outbox_events_status_allowed": (
            "c",
            "CHECK (status::text = ANY (ARRAY['pending'::character varying, "
            "'processing'::character varying, 'failed'::character varying, "
            "'published'::character varying, 'dead_letter'::character varying]::text[]))",
        ),
        "pk_outbox_events": ("p", "PRIMARY KEY (id)"),
        "uq_outbox_events_aggregate_type_aggregate_id_event_sequence": (
            "u",
            "UNIQUE (aggregate_type, aggregate_id, event_sequence)",
        ),
        "uq_outbox_events_event_id_event_type": (
            "u",
            "UNIQUE (event_id, event_type)",
        ),
    },
}
RELIABILITY_FUNCTIONS = {
    "enforce_async_jobs_state_v1",
    "enforce_async_job_steps_state_v1",
    "enforce_job_step_consistency_v1",
    "enforce_outbox_events_state_v1",
}
RELIABILITY_FUNCTION_IDENTITIES = {f"{name}()" for name in RELIABILITY_FUNCTIONS}
RELIABILITY_TRIGGERS = {
    "async_jobs": {"trg_async_jobs_state_v1", "trg_async_jobs_consistency_v1"},
    "async_job_steps": {
        "trg_async_job_steps_state_v1",
        "trg_async_job_steps_no_truncate_v1",
        "trg_async_job_steps_consistency_v1",
    },
    "outbox_events": {"trg_outbox_events_state_v1", "trg_outbox_events_no_truncate_v1"},
}
RELIABILITY_TRIGGER_CONTRACT = {
    "async_jobs": {
        "trg_async_jobs_state_v1": (
            "CREATE TRIGGER trg_async_jobs_state_v1 BEFORE INSERT OR UPDATE ON async_jobs "
            "FOR EACH ROW EXECUTE FUNCTION enforce_async_jobs_state_v1()",
            False,
            False,
            "O",
            "enforce_async_jobs_state_v1",
        ),
        "trg_async_jobs_consistency_v1": (
            "CREATE CONSTRAINT TRIGGER trg_async_jobs_consistency_v1 "
            "AFTER INSERT OR UPDATE ON async_jobs DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION enforce_job_step_consistency_v1()",
            True,
            True,
            "O",
            "enforce_job_step_consistency_v1",
        ),
    },
    "async_job_steps": {
        "trg_async_job_steps_state_v1": (
            "CREATE TRIGGER trg_async_job_steps_state_v1 "
            "BEFORE INSERT OR DELETE OR UPDATE ON async_job_steps "
            "FOR EACH ROW EXECUTE FUNCTION enforce_async_job_steps_state_v1()",
            False,
            False,
            "O",
            "enforce_async_job_steps_state_v1",
        ),
        "trg_async_job_steps_no_truncate_v1": (
            "CREATE TRIGGER trg_async_job_steps_no_truncate_v1 "
            "BEFORE TRUNCATE ON async_job_steps "
            "FOR EACH STATEMENT EXECUTE FUNCTION enforce_async_job_steps_state_v1()",
            False,
            False,
            "O",
            "enforce_async_job_steps_state_v1",
        ),
        "trg_async_job_steps_consistency_v1": (
            "CREATE CONSTRAINT TRIGGER trg_async_job_steps_consistency_v1 "
            "AFTER INSERT OR DELETE OR UPDATE ON async_job_steps "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "EXECUTE FUNCTION enforce_job_step_consistency_v1()",
            True,
            True,
            "O",
            "enforce_job_step_consistency_v1",
        ),
    },
    "outbox_events": {
        "trg_outbox_events_state_v1": (
            "CREATE TRIGGER trg_outbox_events_state_v1 "
            "BEFORE INSERT OR DELETE OR UPDATE ON outbox_events "
            "FOR EACH ROW EXECUTE FUNCTION enforce_outbox_events_state_v1()",
            False,
            False,
            "O",
            "enforce_outbox_events_state_v1",
        ),
        "trg_outbox_events_no_truncate_v1": (
            "CREATE TRIGGER trg_outbox_events_no_truncate_v1 "
            "BEFORE TRUNCATE ON outbox_events "
            "FOR EACH STATEMENT EXECUTE FUNCTION enforce_outbox_events_state_v1()",
            False,
            False,
            "O",
            "enforce_outbox_events_state_v1",
        ),
    },
}
RELIABILITY_INDEX_CONTRACT = {
    "async_jobs": {
        "idx_async_jobs_claim": (
            False,
            "CREATE INDEX idx_async_jobs_claim ON async_jobs USING btree (status, next_retry_at)",
            None,
            ("status", "next_retry_at"),
            (0, 0),
        ),
        "idx_async_jobs_resource_created": (
            False,
            "CREATE INDEX idx_async_jobs_resource_created ON async_jobs USING btree "
            "(resource_type, resource_id, created_at DESC)",
            None,
            ("resource_type", "resource_id", "created_at"),
            (0, 0, 3),
        ),
        "pk_async_jobs": (
            True,
            "CREATE UNIQUE INDEX pk_async_jobs ON async_jobs USING btree (id)",
            None,
            ("id",),
            (0,),
        ),
        "uq_async_jobs_active_resource_input": (
            True,
            "CREATE UNIQUE INDEX uq_async_jobs_active_resource_input ON async_jobs "
            "USING btree (organization_id, job_type, resource_type, resource_id, input_hash) "
            "WHERE status::text = ANY (ARRAY['queued'::character varying, "
            "'running'::character varying, "
            "'cancel_requested'::character varying]::text[])",
            "status::text = ANY (ARRAY['queued'::character varying, "
            "'running'::character varying, "
            "'cancel_requested'::character varying]::text[])",
            ("organization_id", "job_type", "resource_type", "resource_id", "input_hash"),
            (0, 0, 0, 0, 0),
        ),
        "uq_async_jobs_file_job_type_lifetime": (
            True,
            "CREATE UNIQUE INDEX uq_async_jobs_file_job_type_lifetime ON async_jobs "
            "USING btree (resource_type, resource_id, job_type) "
            "WHERE resource_type::text = 'file'::text AND (job_type::text = ANY "
            "(ARRAY['file_scan'::character varying, "
            "'file_process'::character varying]::text[]))",
            "resource_type::text = 'file'::text AND (job_type::text = ANY "
            "(ARRAY['file_scan'::character varying, "
            "'file_process'::character varying]::text[]))",
            ("resource_type", "resource_id", "job_type"),
            (0, 0, 0),
        ),
    },
    "async_job_steps": {
        "pk_async_job_steps": (
            True,
            "CREATE UNIQUE INDEX pk_async_job_steps ON async_job_steps USING btree (id)",
            None,
            ("id",),
            (0,),
        ),
        "uq_async_job_steps_job_id_step_seq_attempt_no": (
            True,
            "CREATE UNIQUE INDEX uq_async_job_steps_job_id_step_seq_attempt_no "
            "ON async_job_steps USING btree (job_id, step_seq, attempt_no)",
            None,
            ("job_id", "step_seq", "attempt_no"),
            (0, 0, 0),
        ),
        "uq_async_job_steps_one_running_per_attempt": (
            True,
            "CREATE UNIQUE INDEX uq_async_job_steps_one_running_per_attempt "
            "ON async_job_steps USING btree (job_id, attempt_no) "
            "WHERE status::text = 'running'::text",
            "status::text = 'running'::text",
            ("job_id", "attempt_no"),
            (0, 0),
        ),
    },
    "outbox_events": {
        "idx_outbox_events_claim": (
            False,
            "CREATE INDEX idx_outbox_events_claim ON outbox_events USING btree "
            "(status, next_attempt_at, created_at)",
            None,
            ("status", "next_attempt_at", "created_at"),
            (0, 0, 0),
        ),
        "pk_outbox_events": (
            True,
            "CREATE UNIQUE INDEX pk_outbox_events ON outbox_events USING btree (id)",
            None,
            ("id",),
            (0,),
        ),
        "uq_outbox_events_aggregate_type_aggregate_id_event_sequence": (
            True,
            "CREATE UNIQUE INDEX "
            "uq_outbox_events_aggregate_type_aggregate_id_event_sequence "
            "ON outbox_events USING btree (aggregate_type, aggregate_id, event_sequence)",
            None,
            ("aggregate_type", "aggregate_id", "event_sequence"),
            (0, 0, 0),
        ),
        "uq_outbox_events_event_id_event_type": (
            True,
            "CREATE UNIQUE INDEX uq_outbox_events_event_id_event_type "
            "ON outbox_events USING btree (event_id, event_type)",
            None,
            ("event_id", "event_type"),
            (0, 0),
        ),
    },
}
CIRCULAR_FINANCIAL_FOREIGN_KEYS = {
    "fk_contracts_supplier_id_suppliers",
    "fk_invoices_supplier_id_suppliers",
    "fk_suppliers_source_contract_id_contracts",
    "fk_suppliers_source_invoice_id_invoices",
}

pytestmark = pytest.mark.integration


class UnsafeMigrationTargetError(RuntimeError):
    """测试目标未满足全部可丢弃数据库门禁。"""


class InjectedMigrationFailure(RuntimeError):
    """测试在目标 DDL 已执行后中断当前 Alembic 事务。"""


def read_safe_test_database_url() -> URL:
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if raw_url is None or not raw_url.strip():
        pytest.skip("未设置 TEST_DATABASE_URL，跳过 PostgreSQL 迁移集成测试")

    database_url_text = raw_url.strip()
    # SQLAlchemy 会丢弃空值 query，因此必须在归一化前检查原始 URL。
    has_query_component = "?" in database_url_text

    try:
        database_url = make_url(database_url_text)
    except (ArgumentError, ValueError):
        database_url = None

    if database_url is None:
        pytest.fail("TEST_DATABASE_URL 不是有效的 SQLAlchemy URL", pytrace=False)

    database_name = database_url.database or ""
    if (
        database_url.drivername != "postgresql+psycopg"
        or database_url.host not in {"localhost", "127.0.0.1"}
        or SAFE_DATABASE_NAME.fullmatch(database_name.lower()) is None
        or has_query_component
        or os.environ.get(DESTRUCTIVE_CONFIRMATION_ENV) != DESTRUCTIVE_CONFIRMATION_VALUE
    ):
        raise UnsafeMigrationTargetError(
            "拒绝不安全的迁移目标：需要 psycopg、本机专用命名、无查询参数和显式重置确认"
        )
    return database_url


def assert_disposable_database_marker(database_url: URL) -> None:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            marker = connection.execute(
                text(
                    "SELECT shobj_description(oid, 'pg_database') "
                    "FROM pg_database WHERE datname = current_database()"
                )
            ).scalar_one()
    finally:
        engine.dispose()

    if marker != DISPOSABLE_DATABASE_COMMENT:
        raise UnsafeMigrationTargetError("拒绝重置未标记为可丢弃的测试数据库")


def current_revision(database_url: URL) -> str | None:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
            return revision
    finally:
        engine.dispose()


def current_head_revision() -> str:
    scripts = ScriptDirectory.from_config(Config(str(BACKEND_ROOT / "alembic.ini")))
    head = scripts.get_current_head()
    if head is None:
        raise AssertionError("Alembic 迁移图缺少 head")
    return head


def installed_extensions(database_url: URL) -> set[str]:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT extname FROM pg_extension WHERE extname = ANY(:extensions)"),
                {"extensions": sorted(EXPECTED_EXTENSIONS)},
            )
            return set(rows.scalars())
    finally:
        engine.dispose()


def installed_baseline_tables(database_url: URL) -> set[str]:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = current_schema() "
                    "AND tablename <> 'alembic_version'"
                )
            )
            return set(rows.scalars())
    finally:
        engine.dispose()


def seeded_role_codes(database_url: URL) -> set[str]:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            return set(connection.execute(text("SELECT code FROM roles")).scalars())
    finally:
        engine.dispose()


def table_row_count(database_url: URL, table_name: str) -> int:
    if table_name not in CURRENT_HEAD_TABLES:
        raise AssertionError("测试只允许查询当前 BASE-005 表")
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            return int(connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one())
    finally:
        engine.dispose()


def user_trigger_names(database_url: URL, table_name: str) -> set[str]:
    if table_name not in CURRENT_HEAD_TABLES:
        raise AssertionError("测试只允许查询当前 BASE-005 表")
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            # information_schema.triggers omits PostgreSQL TRUNCATE triggers.
            rows = connection.execute(
                text(
                    "SELECT trigger_catalog.tgname "
                    "FROM pg_trigger AS trigger_catalog "
                    "JOIN pg_class AS table_catalog "
                    "ON table_catalog.oid = trigger_catalog.tgrelid "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = table_catalog.relnamespace "
                    "WHERE schema_catalog.nspname = current_schema() "
                    "AND table_catalog.relname = :table_name "
                    "AND NOT trigger_catalog.tgisinternal"
                ),
                {"table_name": table_name},
            )
            return set(rows.scalars())
    finally:
        engine.dispose()


def audit_task_column_contract(
    database_url: URL,
) -> list[tuple[str, str, str, int | None, str | None]]:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT column_name, udt_name, is_nullable, "
                    "character_maximum_length, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'audit_tasks' "
                    "ORDER BY ordinal_position"
                )
            )
            return [
                (
                    str(row.column_name),
                    str(row.udt_name),
                    str(row.is_nullable),
                    row.character_maximum_length,
                    row.column_default,
                )
                for row in rows
            ]
    finally:
        engine.dispose()


def audit_task_constraint_contract(database_url: URL) -> dict[str, tuple[str, str]]:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT conname, contype, pg_get_constraintdef(oid, true) AS definition "
                    "FROM pg_constraint "
                    "WHERE conrelid = 'audit_tasks'::regclass"
                )
            )
            return {str(row.conname): (str(row.contype), str(row.definition)) for row in rows}
    finally:
        engine.dispose()


def financial_column_contract(
    database_url: URL,
    table_name: str,
) -> list[tuple[str, str, str, int | None, int | None, int | None, str | None]]:
    if table_name not in FINANCIAL_TABLES:
        raise AssertionError("测试只允许检查 CR-012-R3 三表")
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT column_name, udt_name, is_nullable, "
                    "character_maximum_length, numeric_precision, numeric_scale, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = :table_name "
                    "ORDER BY ordinal_position"
                ),
                {"table_name": table_name},
            )
            return [
                (
                    str(row.column_name),
                    str(row.udt_name),
                    str(row.is_nullable),
                    row.character_maximum_length,
                    row.numeric_precision,
                    row.numeric_scale,
                    row.column_default,
                )
                for row in rows
            ]
    finally:
        engine.dispose()


def financial_constraint_contract(
    database_url: URL,
    table_name: str,
) -> dict[str, tuple[str, str]]:
    if table_name not in FINANCIAL_TABLES:
        raise AssertionError("测试只允许检查 CR-012-R3 三表")
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT conname, contype, pg_get_constraintdef(constraint_catalog.oid, true) "
                    "AS definition FROM pg_constraint AS constraint_catalog "
                    "JOIN pg_class AS table_catalog "
                    "ON table_catalog.oid = constraint_catalog.conrelid "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = table_catalog.relnamespace "
                    "WHERE schema_catalog.nspname = current_schema() "
                    "AND table_catalog.relname = :table_name"
                ),
                {"table_name": table_name},
            )
            return {str(row.conname): (str(row.contype), str(row.definition)) for row in rows}
    finally:
        engine.dispose()


def financial_index_contract(
    database_url: URL,
    table_name: str,
) -> dict[str, tuple[bool, str, str | None, tuple[str, ...]]]:
    if table_name not in FINANCIAL_TABLES:
        raise AssertionError("测试只允许检查 CR-012-R3 三表")
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT index_catalog.relname AS index_name, index_state.indisunique, "
                    "pg_get_indexdef(index_catalog.oid, 0, true) AS definition, "
                    "pg_get_expr(index_state.indpred, index_state.indrelid, true) AS predicate, "
                    "ARRAY(SELECT pg_get_indexdef(index_state.indexrelid, key_position, true) "
                    "FROM generate_series(1, index_state.indnkeyatts) AS key_position "
                    "ORDER BY key_position) AS key_columns "
                    "FROM pg_index AS index_state "
                    "JOIN pg_class AS index_catalog ON index_catalog.oid = index_state.indexrelid "
                    "JOIN pg_class AS table_catalog ON table_catalog.oid = index_state.indrelid "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = table_catalog.relnamespace "
                    "WHERE schema_catalog.nspname = current_schema() "
                    "AND table_catalog.relname = :table_name"
                ),
                {"table_name": table_name},
            )
            return {
                str(row.index_name): (
                    bool(row.indisunique),
                    str(row.definition),
                    None if row.predicate is None else str(row.predicate),
                    tuple(str(column) for column in row.key_columns),
                )
                for row in rows
            }
    finally:
        engine.dispose()


def financial_foreign_key_actions(database_url: URL) -> dict[str, tuple[str, str]]:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT constraint_catalog.conname, constraint_catalog.confupdtype::text "
                    "AS update_action, constraint_catalog.confdeltype::text AS delete_action "
                    "FROM pg_constraint AS constraint_catalog "
                    "JOIN pg_class AS table_catalog "
                    "ON table_catalog.oid = constraint_catalog.conrelid "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = table_catalog.relnamespace "
                    "WHERE schema_catalog.nspname = current_schema() "
                    "AND table_catalog.relname::text = ANY(CAST(:table_names AS text[])) "
                    "AND constraint_catalog.contype = 'f'"
                ),
                {"table_names": list(FINANCIAL_TABLES)},
            )
            return {
                str(row.conname): (str(row.update_action), str(row.delete_action)) for row in rows
            }
    finally:
        engine.dispose()


def reliability_column_contract(
    database_url: URL,
    table_name: str,
) -> list[tuple[str, str, str, int | None, str | None]]:
    if table_name not in RELIABILITY_TABLES:
        raise AssertionError("test may inspect only CR-004 reliability tables")
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT column_name, udt_name, is_nullable, "
                    "character_maximum_length, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = :table_name "
                    "ORDER BY ordinal_position"
                ),
                {"table_name": table_name},
            )
            return [
                (
                    str(row.column_name),
                    str(row.udt_name),
                    str(row.is_nullable),
                    row.character_maximum_length,
                    None if row.column_default is None else str(row.column_default),
                )
                for row in rows
            ]
    finally:
        engine.dispose()


def reliability_constraint_contract(
    database_url: URL,
    table_name: str,
) -> dict[str, tuple[str, bool, bool, bool, str]]:
    if table_name not in RELIABILITY_TABLES:
        raise AssertionError("test may inspect only CR-004 reliability tables")
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT constraint_catalog.conname, constraint_catalog.contype, "
                    "constraint_catalog.convalidated, constraint_catalog.condeferrable, "
                    "constraint_catalog.condeferred, "
                    "pg_get_constraintdef(constraint_catalog.oid, true) AS definition "
                    "FROM pg_constraint AS constraint_catalog "
                    "JOIN pg_class AS table_catalog "
                    "ON table_catalog.oid = constraint_catalog.conrelid "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = table_catalog.relnamespace "
                    "WHERE schema_catalog.nspname = current_schema() "
                    "AND table_catalog.relname = :table_name "
                    "AND constraint_catalog.contype <> 't'"
                ),
                {"table_name": table_name},
            )
            return {
                str(row.conname): (
                    str(row.contype),
                    bool(row.convalidated),
                    bool(row.condeferrable),
                    bool(row.condeferred),
                    str(row.definition),
                )
                for row in rows
            }
    finally:
        engine.dispose()


def reliability_index_contract(
    database_url: URL,
    table_name: str,
) -> dict[str, tuple[bool, str, str | None, tuple[str, ...], tuple[int, ...]]]:
    if table_name not in RELIABILITY_TABLES:
        raise AssertionError("test may inspect only CR-004 reliability tables")
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT index_catalog.relname AS index_name, index_state.indisunique, "
                    "pg_get_indexdef(index_catalog.oid, 0, true) AS definition, "
                    "pg_get_expr(index_state.indpred, index_state.indrelid, true) AS predicate, "
                    "index_state.indoption::text AS key_options, "
                    "ARRAY(SELECT pg_get_indexdef(index_state.indexrelid, key_position, true) "
                    "FROM generate_series(1, index_state.indnkeyatts) AS key_position "
                    "ORDER BY key_position) AS key_columns "
                    "FROM pg_index index_state "
                    "JOIN pg_class index_catalog ON index_catalog.oid = index_state.indexrelid "
                    "JOIN pg_class table_catalog ON table_catalog.oid = index_state.indrelid "
                    "JOIN pg_namespace schema_catalog "
                    "ON schema_catalog.oid = table_catalog.relnamespace "
                    "WHERE schema_catalog.nspname = current_schema() "
                    "AND table_catalog.relname = :table_name"
                ),
                {"table_name": table_name},
            )
            return {
                str(row.index_name): (
                    bool(row.indisunique),
                    str(row.definition),
                    None if row.predicate is None else str(row.predicate),
                    tuple(str(column) for column in row.key_columns),
                    tuple(int(option) for option in str(row.key_options).split()),
                )
                for row in rows
            }
    finally:
        engine.dispose()


def reliability_function_contract(
    database_url: URL,
) -> dict[str, tuple[int, str, str, bool, str, str, str]]:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT DISTINCT function_catalog.oid::regprocedure::text AS identity, "
                    "function_catalog.pronargs, "
                    "function_catalog.prorettype::regtype::text AS return_type, "
                    "language_catalog.lanname, function_catalog.prosecdef, "
                    "function_catalog.provolatile, function_catalog.prokind, "
                    "pg_get_functiondef(function_catalog.oid) AS definition "
                    "FROM pg_proc function_catalog "
                    "JOIN pg_namespace schema_catalog "
                    "ON schema_catalog.oid = function_catalog.pronamespace "
                    "JOIN pg_language language_catalog "
                    "ON language_catalog.oid = function_catalog.prolang "
                    "JOIN pg_trigger trigger_catalog "
                    "ON trigger_catalog.tgfoid = function_catalog.oid "
                    "JOIN pg_class table_catalog "
                    "ON table_catalog.oid = trigger_catalog.tgrelid "
                    "WHERE schema_catalog.nspname = current_schema() "
                    "AND table_catalog.relname = ANY(CAST(:table_names AS text[])) "
                    "AND NOT trigger_catalog.tgisinternal"
                ),
                {"table_names": list(RELIABILITY_TABLES)},
            )
            return {
                str(row.identity): (
                    int(row.pronargs),
                    str(row.return_type),
                    str(row.lanname),
                    bool(row.prosecdef),
                    str(row.provolatile),
                    str(row.prokind),
                    str(row.definition),
                )
                for row in rows
            }
    finally:
        engine.dispose()


def reliability_trigger_contract(
    database_url: URL,
) -> dict[str, dict[str, tuple[str, bool, bool, str, str]]]:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT table_catalog.relname AS table_name, trigger_catalog.tgname, "
                    "pg_get_triggerdef(trigger_catalog.oid, true) AS definition, "
                    "trigger_catalog.tgdeferrable, trigger_catalog.tginitdeferred, "
                    "trigger_catalog.tgenabled, "
                    "function_catalog.proname AS function_name "
                    "FROM pg_trigger trigger_catalog "
                    "JOIN pg_class table_catalog ON table_catalog.oid = trigger_catalog.tgrelid "
                    "JOIN pg_namespace schema_catalog "
                    "ON schema_catalog.oid = table_catalog.relnamespace "
                    "JOIN pg_proc function_catalog "
                    "ON function_catalog.oid = trigger_catalog.tgfoid "
                    "WHERE schema_catalog.nspname = current_schema() "
                    "AND table_catalog.relname = ANY(CAST(:table_names AS text[])) "
                    "AND NOT trigger_catalog.tgisinternal"
                ),
                {"table_names": list(RELIABILITY_TABLES)},
            )
            result: dict[str, dict[str, tuple[str, bool, bool, str, str]]] = {
                table_name: {} for table_name in RELIABILITY_TABLES
            }
            for row in rows:
                result[str(row.table_name)][str(row.tgname)] = (
                    str(row.definition),
                    bool(row.tgdeferrable),
                    bool(row.tginitdeferred),
                    str(row.tgenabled),
                    str(row.function_name),
                )
            return result
    finally:
        engine.dispose()


def safe_database_error_signature(error: DBAPIError) -> tuple[str | None, str | None]:
    original = error.orig
    sqlstate = getattr(original, "sqlstate", None)
    diagnostic = getattr(original, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    return (
        sqlstate if isinstance(sqlstate, str) else None,
        constraint_name if isinstance(constraint_name, str) else None,
    )


def audit_task_runtime_defaults(database_url: URL) -> tuple[int, bool, bool]:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT row_version, created_at IS NOT NULL AS has_created_at, "
                    "updated_at IS NOT NULL AS has_updated_at "
                    "FROM audit_tasks WHERE task_no = 'AUDIT-MIGRATION-001'"
                )
            ).one()
            return int(row.row_version), bool(row.has_created_at), bool(row.has_updated_at)
    finally:
        engine.dispose()


def execute_database_statement(
    database_url: URL,
    statement: str,
    parameters: Mapping[str, object] | None = None,
) -> None:
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(statement), parameters or {})
    finally:
        engine.dispose()


def execute_expect_database_error(
    database_url: URL,
    statement: str,
    parameters: Mapping[str, object] | None = None,
) -> tuple[str | None, str | None]:
    try:
        execute_database_statement(database_url, statement, parameters)
    except DBAPIError as error:
        return safe_database_error_signature(error)
    raise AssertionError("预期 PostgreSQL 拒绝该写入")


def call_expect_database_error(action: Callable[[], object]) -> tuple[str | None, str | None]:
    try:
        action()
    except DBAPIError as error:
        return safe_database_error_signature(error)
    raise AssertionError("预期 PostgreSQL 拒绝该写入")


def fail_outbox_and_observe_retry(
    database_url: URL,
    event_id: str,
) -> tuple[int, datetime, datetime, datetime]:
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "WITH transition_start AS MATERIALIZED ("
                    "SELECT clock_timestamp() AS t), "
                    "failed AS ("
                    "UPDATE outbox_events SET status = 'failed', "
                    "last_error = 'BROKER_TIMEOUT' FROM transition_start "
                    "WHERE id = :id RETURNING attempt_count, next_attempt_at) "
                    "SELECT failed.attempt_count, failed.next_attempt_at, "
                    "transition_start.t AS transition_before, "
                    "clock_timestamp() AS transition_after "
                    "FROM failed CROSS JOIN transition_start"
                ),
                {"id": event_id},
            ).one()
            return (
                int(row.attempt_count),
                cast(datetime, row.next_attempt_at),
                cast(datetime, row.transition_before),
                cast(datetime, row.transition_after),
            )
    finally:
        engine.dispose()


def outbox_retry_jitter_milliseconds(event_id: str, attempt_count: int) -> int:
    retry_identity = f"{event_id.lower()}:{attempt_count}".encode()
    return int.from_bytes(sha256(retry_identity).digest()[:8], "big") % 1000


def configure_disposable_database(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[URL, Config]:
    database_url = read_safe_test_database_url()
    assert_disposable_database_marker(database_url)
    monkeypatch.setenv("DATABASE_URL", database_url.render_as_string(hide_password=False))
    return database_url, Config(str(BACKEND_ROOT / "alembic.ini"))


def reset_disposable_database_to_head(database_url: URL, alembic_config: Config) -> None:
    command.downgrade(alembic_config, "base")
    assert current_revision(database_url) is None
    command.upgrade(alembic_config, "head")
    assert current_revision(database_url) == CURRENT_REVISION


def reset_disposable_database_to_privileged_auth_revision(
    database_url: URL,
    alembic_config: Config,
) -> None:
    command.downgrade(alembic_config, "base")
    assert current_revision(database_url) is None
    command.upgrade(alembic_config, PRIVILEGED_AUTH_REVISION)
    assert current_revision(database_url) == PRIVILEGED_AUTH_REVISION


def seed_reliability_organization(database_url: URL) -> None:
    execute_database_statement(
        database_url,
        """
        INSERT INTO organizations (
            id, name, unified_social_credit_code, tax_number, status
        ) VALUES (
            :id, 'reliability migration organization',
            'SYNTHETIC-RELIABILITY-USCC', 'SYNTHETIC-RELIABILITY-TAX', 'active'
        )
        """,
        {"id": RELIABILITY_ORGANIZATION_ID},
    )


def clear_reliability_test_data(database_url: URL) -> None:
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            for table_name in RELIABILITY_TABLES:
                connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
            connection.execute(text("DELETE FROM outbox_events"))
            connection.execute(text("DELETE FROM async_job_steps"))
            connection.execute(text("DELETE FROM async_jobs"))
            for table_name in reversed(RELIABILITY_TABLES):
                connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))
            connection.execute(
                text("DELETE FROM organizations WHERE id = :organization_id"),
                {"organization_id": RELIABILITY_ORGANIZATION_ID},
            )
    finally:
        engine.dispose()


def insert_queued_job(
    database_url: URL,
    *,
    job_id: str | None = None,
    resource_id: str | None = None,
    input_hash: str = "a" * 64,
    max_attempts: int = 2,
    lease_policy_version: str = LEASE_POLICY_VERSION,
    lease_policy_hash: str = LEASE_POLICY_HASH,
) -> str:
    actual_job_id = job_id or str(uuid4())
    execute_database_statement(
        database_url,
        """
        INSERT INTO async_jobs (
            id, organization_id, job_type, resource_type, resource_id,
            status, max_attempts, current_attempt_start_step_code,
            input_hash, input_json, input_schema_version,
            handler_registry_version, handler_registry_hash,
            retry_policy_version, retry_policy_hash,
            lease_policy_version, lease_policy_hash, trace_id
        ) VALUES (
            :id, :organization_id, 'audit_pipeline', 'audit_task', :resource_id,
            'queued', :max_attempts, 'prepare',
            :input_hash, jsonb_build_object('synthetic', true), 1,
            'pending', repeat('b', 64),
            :retry_policy_version, :retry_policy_hash,
            :lease_policy_version, :lease_policy_hash, :trace_id
        )
        """,
        {
            "id": actual_job_id,
            "organization_id": RELIABILITY_ORGANIZATION_ID,
            "resource_id": resource_id or str(uuid4()),
            "input_hash": input_hash,
            "max_attempts": max_attempts,
            "retry_policy_version": RETRY_POLICY_VERSION,
            "retry_policy_hash": RETRY_POLICY_HASH,
            "lease_policy_version": lease_policy_version,
            "lease_policy_hash": lease_policy_hash,
            "trace_id": str(uuid4()),
        },
    )
    return actual_job_id


def claim_job_with_step(database_url: URL, job_id: str, *, worker_id: str = "worker-1") -> str:
    step_id = str(uuid4())
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            job = connection.execute(
                text(
                    "UPDATE async_jobs SET status = 'running', stage = "
                    "current_attempt_start_step_code, attempt_no = attempt_no + 1, "
                    "worker_id = :worker_id, row_version = row_version + 1 "
                    "WHERE id = :job_id RETURNING attempt_no, stage, started_at, trace_id"
                ),
                {"job_id": job_id, "worker_id": worker_id},
            ).one()
            connection.execute(
                text(
                    "INSERT INTO async_job_steps ("
                    "id, job_id, step_seq, step_code, status, attempt_no, started_at, trace_id"
                    ") VALUES ("
                    ":id, :job_id, 1, :step_code, 'running', :attempt_no, :started_at, :trace_id"
                    ")"
                ),
                {
                    "id": step_id,
                    "job_id": job_id,
                    "step_code": job.stage,
                    "attempt_no": job.attempt_no,
                    "started_at": job.started_at,
                    "trace_id": job.trace_id,
                },
            )
    finally:
        engine.dispose()
    return step_id


def claim_job_with_step_atomic(
    database_url: URL,
    job_id: str,
) -> tuple[datetime, datetime, datetime, datetime]:
    step_id = str(uuid4())
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "WITH claimed AS ("
                    "UPDATE async_jobs SET status = 'running', "
                    "stage = current_attempt_start_step_code, attempt_no = attempt_no + 1, "
                    "worker_id = 'atomic-claim-worker', row_version = row_version + 1 "
                    "WHERE id = :job_id RETURNING id, attempt_no, stage, started_at, "
                    "heartbeat_at, lease_expires_at, trace_id), "
                    "created_step AS ("
                    "INSERT INTO async_job_steps ("
                    "id, job_id, step_seq, step_code, status, attempt_no, started_at, trace_id) "
                    "SELECT :step_id, id, 1, stage, 'running', attempt_no, started_at, trace_id "
                    "FROM claimed RETURNING started_at) "
                    "SELECT claimed.started_at, claimed.heartbeat_at, "
                    "claimed.lease_expires_at, created_step.started_at AS step_started_at "
                    "FROM claimed CROSS JOIN created_step"
                ),
                {"job_id": job_id, "step_id": step_id},
            ).one()
            return (
                cast(datetime, row.started_at),
                cast(datetime, row.heartbeat_at),
                cast(datetime, row.lease_expires_at),
                cast(datetime, row.step_started_at),
            )
    finally:
        engine.dispose()


def recover_job_with_step_atomic(
    database_url: URL,
    job_id: str,
    old_step_id: str,
) -> tuple[datetime, datetime, datetime, datetime, datetime]:
    new_step_id = str(uuid4())
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "WITH recovery_clock AS MATERIALIZED ("
                    "SELECT clock_timestamp() AS t), "
                    "finished_previous AS ("
                    "UPDATE async_job_steps SET status = 'failed', "
                    "finished_at = recovery_clock.t, error_code = 'LEASE_EXPIRED' "
                    "FROM recovery_clock WHERE id = :old_step_id "
                    "RETURNING job_id, finished_at), "
                    "reclaimed AS ("
                    "UPDATE async_jobs SET attempt_no = attempt_no + 1, "
                    "stage = current_attempt_start_step_code, "
                    "worker_id = 'atomic-recovery-worker', "
                    "started_at = recovery_clock.t, heartbeat_at = recovery_clock.t, "
                    "lease_expires_at = recovery_clock.t + interval '60 seconds', "
                    "row_version = row_version + 1 "
                    "FROM recovery_clock, finished_previous "
                    "WHERE async_jobs.id = :job_id "
                    "AND finished_previous.job_id = async_jobs.id "
                    "RETURNING async_jobs.id, async_jobs.attempt_no, async_jobs.stage, "
                    "async_jobs.started_at, async_jobs.heartbeat_at, "
                    "async_jobs.lease_expires_at, async_jobs.trace_id), "
                    "created_step AS ("
                    "INSERT INTO async_job_steps ("
                    "id, job_id, step_seq, step_code, status, attempt_no, started_at, trace_id) "
                    "SELECT :new_step_id, reclaimed.id, 1, reclaimed.stage, 'running', "
                    "reclaimed.attempt_no, recovery_clock.t, reclaimed.trace_id "
                    "FROM reclaimed CROSS JOIN recovery_clock RETURNING started_at) "
                    "SELECT recovery_clock.t AS recovery_timestamp, "
                    "finished_previous.finished_at, "
                    "reclaimed.started_at, reclaimed.heartbeat_at, "
                    "reclaimed.lease_expires_at, created_step.started_at AS step_started_at "
                    "FROM recovery_clock CROSS JOIN finished_previous "
                    "CROSS JOIN reclaimed CROSS JOIN created_step"
                ),
                {
                    "job_id": job_id,
                    "new_step_id": new_step_id,
                    "old_step_id": old_step_id,
                },
            ).one()
            assert row.recovery_timestamp == row.finished_at == row.started_at == row.heartbeat_at
            return (
                cast(datetime, row.recovery_timestamp),
                cast(datetime, row.finished_at),
                cast(datetime, row.started_at),
                cast(datetime, row.lease_expires_at),
                cast(datetime, row.step_started_at),
            )
    finally:
        engine.dispose()


def attempt_atomic_recovery_with_invalid_clock(
    database_url: URL,
    job_id: str,
    old_step_id: str,
    *,
    future_clock: bool,
) -> None:
    old_step_clock = (
        "recovery_clock.t + interval '1 hour'"
        if future_clock
        else "recovery_clock.t - interval '1 millisecond'"
    )
    job_clock = "recovery_clock.t + interval '1 hour'" if future_clock else "recovery_clock.t"
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "WITH recovery_clock AS MATERIALIZED ("
                    "SELECT clock_timestamp() AS t), "
                    "finished_previous AS ("
                    "UPDATE async_job_steps SET status = 'failed', "
                    f"finished_at = {old_step_clock}, error_code = 'LEASE_EXPIRED' "
                    "FROM recovery_clock WHERE id = :old_step_id RETURNING job_id), "
                    "reclaimed AS ("
                    "UPDATE async_jobs SET attempt_no = attempt_no + 1, "
                    "stage = current_attempt_start_step_code, worker_id = 'invalid-clock-worker', "
                    f"started_at = {job_clock}, heartbeat_at = {job_clock}, "
                    f"lease_expires_at = {job_clock} + interval '60 seconds', "
                    "row_version = row_version + 1 FROM recovery_clock, finished_previous "
                    "WHERE async_jobs.id = :job_id "
                    "AND finished_previous.job_id = async_jobs.id RETURNING async_jobs.id) "
                    "SELECT id FROM reclaimed"
                ),
                {"job_id": job_id, "old_step_id": old_step_id},
            ).one()
    finally:
        engine.dispose()


def expire_active_job_lease(database_url: URL, job_id: str) -> None:
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE async_jobs DISABLE TRIGGER USER"))
            connection.execute(text("ALTER TABLE async_job_steps DISABLE TRIGGER USER"))
            connection.execute(
                text(
                    "WITH expiry_clock AS MATERIALIZED ("
                    "SELECT clock_timestamp() AS t), expired_job AS ("
                    "UPDATE async_jobs SET started_at = "
                    "expiry_clock.t - interval '120 seconds', "
                    "heartbeat_at = expiry_clock.t - interval '90 seconds', "
                    "lease_expires_at = expiry_clock.t - interval '30 seconds' "
                    "FROM expiry_clock WHERE id = :job_id RETURNING id, attempt_no) "
                    "UPDATE async_job_steps SET started_at = "
                    "expiry_clock.t - interval '120 seconds' "
                    "FROM expiry_clock, expired_job WHERE job_id = expired_job.id "
                    "AND async_job_steps.attempt_no = expired_job.attempt_no "
                    "AND async_job_steps.status = 'running'"
                ),
                {"job_id": job_id},
            )
            connection.execute(text("ALTER TABLE async_job_steps ENABLE TRIGGER USER"))
            connection.execute(text("ALTER TABLE async_jobs ENABLE TRIGGER USER"))
    finally:
        engine.dispose()


def move_active_job_lease_into_recovery_grace(database_url: URL, job_id: str) -> None:
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE async_jobs DISABLE TRIGGER USER"))
            connection.execute(text("ALTER TABLE async_job_steps DISABLE TRIGGER USER"))
            connection.execute(
                text(
                    "WITH grace_clock AS MATERIALIZED ("
                    "SELECT clock_timestamp() AS t), grace_job AS ("
                    "UPDATE async_jobs SET started_at = "
                    "grace_clock.t - interval '120 seconds', "
                    "heartbeat_at = grace_clock.t - interval '2 seconds', "
                    "lease_expires_at = grace_clock.t - interval '1 second' "
                    "FROM grace_clock WHERE id = :job_id RETURNING id, attempt_no) "
                    "UPDATE async_job_steps SET started_at = "
                    "grace_clock.t - interval '120 seconds' "
                    "FROM grace_clock, grace_job WHERE job_id = grace_job.id "
                    "AND async_job_steps.attempt_no = grace_job.attempt_no "
                    "AND async_job_steps.status = 'running'"
                ),
                {"job_id": job_id},
            )
            connection.execute(text("ALTER TABLE async_job_steps ENABLE TRIGGER USER"))
            connection.execute(text("ALTER TABLE async_jobs ENABLE TRIGGER USER"))
    finally:
        engine.dispose()


def replace_active_job_policy_with_unknown(database_url: URL, job_id: str) -> None:
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE async_jobs DISABLE TRIGGER USER"))
            connection.execute(
                text(
                    "UPDATE async_jobs SET lease_policy_version = 'unknown-policy', "
                    "lease_policy_hash = repeat('f', 64) WHERE id = :job_id"
                ),
                {"job_id": job_id},
            )
            connection.execute(text("ALTER TABLE async_jobs ENABLE TRIGGER USER"))
    finally:
        engine.dispose()


def seed_financial_organization(database_url: URL) -> None:
    execute_database_statement(
        database_url,
        """
        INSERT INTO organizations (
            id, name, unified_social_credit_code, tax_number, status
        ) VALUES (
            :id, 'financial migration organization',
            'SYNTHETIC-ORG-USCC', 'SYNTHETIC-ORG-TAX', 'active'
        )
        """,
        {"id": FINANCIAL_ORGANIZATION_ID},
    )
    execute_database_statement(
        database_url,
        "INSERT INTO users (id, organization_id, username, display_name, password_hash, "
        "status, password_changed_at, token_invalid_before) VALUES "
        "(:id, :organization_id, 'financial.migration.actor', 'financial migration actor', "
        "'synthetic-password-hash', 'active', now(), now())",
        {"id": FINANCIAL_ACTOR_ID, "organization_id": FINANCIAL_ORGANIZATION_ID},
    )


def clear_financial_test_data(database_url: URL) -> None:
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            parameters = {"organization_id": FINANCIAL_ORGANIZATION_ID}
            trigger_tables = ("contracts", "invoices")
            for table_name in trigger_tables:
                connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
            connection.execute(
                text(
                    "UPDATE contracts SET supplier_id = NULL "
                    "WHERE organization_id = :organization_id"
                ),
                parameters,
            )
            connection.execute(
                text(
                    "UPDATE invoices SET supplier_id = NULL "
                    "WHERE organization_id = :organization_id"
                ),
                parameters,
            )
            for table_name in ("suppliers", "invoices", "contracts"):
                connection.execute(
                    text(f"DELETE FROM {table_name} WHERE organization_id = :organization_id"),
                    parameters,
                )
            connection.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": FINANCIAL_ACTOR_ID},
            )
            connection.execute(
                text("DELETE FROM organizations WHERE id = :organization_id"),
                parameters,
            )
            for table_name in reversed(trigger_tables):
                connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))
    finally:
        engine.dispose()


def insert_contract(
    database_url: URL,
    *,
    record_id: str,
    contract_no: str | None,
    status: str = "draft",
    amount: str | None = None,
    effective_date: str | None = None,
    expiry_date: str | None = None,
    deleted: bool = False,
) -> None:
    execute_database_statement(
        database_url,
        """
        INSERT INTO contracts (
            id, organization_id, contract_no, name, amount,
            effective_date, expiry_date, confirmation_status, status,
            critical_fact_hash, deleted_at, delete_reason
        ) VALUES (
            :id, :organization_id, :contract_no, 'synthetic contract', :amount,
            :effective_date, :expiry_date, 'unconfirmed', :status,
            repeat('a', 64),
            CASE WHEN :deleted THEN now() ELSE NULL END,
            CASE WHEN :deleted THEN 'synthetic cleanup' ELSE NULL END
        )
        """,
        {
            "id": record_id,
            "organization_id": FINANCIAL_ORGANIZATION_ID,
            "contract_no": contract_no,
            "amount": amount,
            "effective_date": effective_date,
            "expiry_date": expiry_date,
            "status": status,
            "deleted": deleted,
        },
    )


def insert_invoice(
    database_url: URL,
    *,
    record_id: str,
    invoice_code: str = "INV-CODE",
    invoice_number: str = "INV-NUMBER",
    seller_tax_no: str = "SYNTHETIC-INVOICE-TAX",
    status: str = "draft",
) -> None:
    execute_database_statement(
        database_url,
        """
        INSERT INTO invoices (
            id, organization_id, invoice_code, invoice_number, seller_tax_no,
            confirmation_status, status, critical_fact_hash
        ) VALUES (
            :id, :organization_id, :invoice_code, :invoice_number, :seller_tax_no,
            'unconfirmed', :status, repeat('b', 64)
        )
        """,
        {
            "id": record_id,
            "organization_id": FINANCIAL_ORGANIZATION_ID,
            "invoice_code": invoice_code,
            "invoice_number": invoice_number,
            "seller_tax_no": seller_tax_no,
            "status": status,
        },
    )


def insert_supplier(
    database_url: URL,
    *,
    record_id: str,
    standard_name: str = "synthetic supplier",
    unified_social_credit_code: str | None = None,
    tax_number: str | None = None,
    source_type: str = "manual",
    source_contract_id: str | None = None,
    source_invoice_id: str | None = None,
    confirmation_status: str = "unconfirmed",
    status: str = "candidate",
    deleted: bool = False,
) -> None:
    resolved_confirmation_status = confirmation_status
    if confirmation_status == "unconfirmed" and status == "active":
        resolved_confirmation_status = "confirmed"
    elif confirmation_status == "unconfirmed" and status == "inactive":
        resolved_confirmation_status = "rejected"
    execute_database_statement(
        database_url,
        """
        INSERT INTO suppliers (
            id, organization_id, standard_name,
            unified_social_credit_code, tax_number,
            source_type, source_contract_id, source_invoice_id,
            confirmation_status, status, confirmed_by, confirmed_at,
            deleted_at, delete_reason
        ) VALUES (
            :id, :organization_id, :standard_name,
            :unified_social_credit_code, :tax_number,
            :source_type, :source_contract_id, :source_invoice_id,
            :confirmation_status, :status,
            CASE WHEN :is_confirmed THEN CAST(:confirmed_by AS uuid) ELSE NULL END,
            CASE WHEN :is_confirmed THEN now() ELSE NULL END,
            CASE WHEN :deleted THEN now() ELSE NULL END,
            CASE WHEN :deleted THEN 'synthetic cleanup' ELSE NULL END
        )
        """,
        {
            "id": record_id,
            "organization_id": FINANCIAL_ORGANIZATION_ID,
            "standard_name": standard_name,
            "unified_social_credit_code": unified_social_credit_code,
            "tax_number": tax_number,
            "source_type": source_type,
            "source_contract_id": source_contract_id,
            "source_invoice_id": source_invoice_id,
            "confirmation_status": resolved_confirmation_status,
            "is_confirmed": resolved_confirmation_status != "unconfirmed",
            "confirmed_by": FINANCIAL_ACTOR_ID,
            "status": status,
            "deleted": deleted,
        },
    )


def count_financial_rows(database_url: URL, table_name: str) -> int:
    if table_name not in FINANCIAL_TABLES:
        raise AssertionError("测试只允许统计 CR-012-R3 三表")
    return table_row_count(database_url, table_name)


def query_plan_uses_index(plan: object, index_name: str) -> bool:
    if isinstance(plan, dict):
        return plan.get("Index Name") == index_name or any(
            query_plan_uses_index(value, index_name) for value in plan.values()
        )
    if isinstance(plan, list):
        return any(query_plan_uses_index(value, index_name) for value in plan)
    return False


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/contest",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_test_backup",
        "postgresql+psycopg://migration:safe-test-value@database/finaudit_base005_test",
        "postgresql://migration:safe-test-value@127.0.0.1/finaudit_base005_test",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_base005_test?host=database",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_base005_test?hostaddr=203.0.113.10",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_base005_test?dbname=postgres",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_base005_test?service=production",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_base005_test?application_name=finaudit-tests",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_base005_test?application_name=",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_base005_test?host=",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_base005_test?service",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_base005_test?host=&host=",
    ],
)
def test_unsafe_database_target_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_url: str,
) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", unsafe_url)
    monkeypatch.setenv(DESTRUCTIVE_CONFIRMATION_ENV, DESTRUCTIVE_CONFIRMATION_VALUE)

    with pytest.raises(UnsafeMigrationTargetError):
        read_safe_test_database_url()


def test_safe_database_target_without_query_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_base005_test",
    )
    monkeypatch.setenv(DESTRUCTIVE_CONFIRMATION_ENV, DESTRUCTIVE_CONFIRMATION_VALUE)

    database_url = read_safe_test_database_url()

    assert database_url.host == "127.0.0.1"
    assert database_url.database == "finaudit_base005_test"
    assert not database_url.query


def test_missing_destructive_confirmation_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://migration:safe-test-value@127.0.0.1/finaudit_base005_test",
    )
    monkeypatch.delenv(DESTRUCTIVE_CONFIRMATION_ENV, raising=False)

    with pytest.raises(UnsafeMigrationTargetError):
        read_safe_test_database_url()


def test_financial_upgrade_rejects_disposable_sql_ascii_database_atomically(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url = read_safe_test_database_url()
    assert_disposable_database_marker(database_url)
    assert database_url.drivername == "postgresql+psycopg"
    assert database_url.host in {"localhost", "127.0.0.1"}
    assert database_url.database is not None
    assert SAFE_DATABASE_NAME.fullmatch(database_url.database.lower()) is not None
    assert not database_url.query

    sql_ascii_database_name = f"finaudit_sql_ascii_{uuid4().hex}_test"
    assert SAFE_DATABASE_NAME.fullmatch(sql_ascii_database_name) is not None
    admin_engine = create_migration_engine(database_url.set(database="postgres")).execution_options(
        isolation_level="AUTOCOMMIT"
    )
    quoted_database_name = admin_engine.dialect.identifier_preparer.quote_identifier(
        sql_ascii_database_name
    )
    sql_ascii_url = database_url.set(database=sql_ascii_database_name)
    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))

    try:
        try:
            with admin_engine.connect() as connection:
                is_superuser = bool(
                    connection.execute(
                        text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                    ).scalar_one()
                )
                if not is_superuser:
                    pytest.fail(
                        "SQL_ASCII 迁移门禁要求 disposable PostgreSQL 超级用户",
                        pytrace=False,
                    )
                connection.execute(
                    text(
                        f"CREATE DATABASE {quoted_database_name} TEMPLATE template0 "
                        "ENCODING 'SQL_ASCII' LC_COLLATE 'C' LC_CTYPE 'C'"
                    )
                )
                connection.execute(
                    text(
                        f"COMMENT ON DATABASE {quoted_database_name} "
                        f"IS '{DISPOSABLE_DATABASE_COMMENT}'"
                    )
                )

            assert_disposable_database_marker(sql_ascii_url)
            encoding_engine = create_migration_engine(sql_ascii_url)
            try:
                with encoding_engine.connect() as connection:
                    assert (
                        connection.execute(text("SHOW server_encoding")).scalar_one() == "SQL_ASCII"
                    )
                    assert connection.execute(text("SHOW client_encoding")).scalar_one() == "UTF8"
            finally:
                encoding_engine.dispose()

            monkeypatch.setenv(
                "DATABASE_URL",
                sql_ascii_url.render_as_string(hide_password=False),
            )
            command.upgrade(alembic_config, PREVIOUS_FINANCIAL_REVISION)
            assert current_revision(sql_ascii_url) == PREVIOUS_FINANCIAL_REVISION

            with pytest.raises(RuntimeError, match="server_encoding must be UTF8"):
                command.upgrade(alembic_config, FINANCIAL_REVISION)

            assert current_revision(sql_ascii_url) == PREVIOUS_FINANCIAL_REVISION
            assert installed_baseline_tables(sql_ascii_url) == (
                TABLES_AT_006 - set(FINANCIAL_TABLES)
            )
        finally:
            monkeypatch.setenv(
                "DATABASE_URL",
                database_url.render_as_string(hide_password=False),
            )
            with admin_engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": sql_ascii_database_name},
                )
                connection.execute(text(f"DROP DATABASE IF EXISTS {quoted_database_name}"))
                assert not bool(
                    connection.execute(
                        text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :name)"),
                        {"name": sql_ascii_database_name},
                    ).scalar_one()
                )
    except DBAPIError as error:
        sqlstate, _ = safe_database_error_signature(error)
        pytest.fail(
            f"SQL_ASCII disposable 数据库生命周期失败，SQLSTATE={sqlstate or 'unknown'}",
            pytrace=False,
        )
    finally:
        admin_engine.dispose()

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}\n{caplog.text}"
    if database_url.password and database_url.password in rendered_output:
        pytest.fail("SQL_ASCII 门禁输出包含数据库密码", pytrace=False)
    if (
        "postgresql+psycopg://" in rendered_output
        or sql_ascii_database_name in rendered_output
        or "PostgreSQL server_encoding must be UTF8" in rendered_output
        or "Traceback" in rendered_output
    ):
        pytest.fail("SQL_ASCII 门禁输出包含连接信息或原始异常", pytrace=False)


def test_current_base005_migration_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url = read_safe_test_database_url()
    assert_disposable_database_marker(database_url)
    monkeypatch.setenv("DATABASE_URL", database_url.render_as_string(hide_password=False))
    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))

    command.downgrade(alembic_config, "base")
    assert current_revision(database_url) is None

    command.upgrade(alembic_config, "head")
    assert current_revision(database_url) == current_head_revision()
    assert installed_extensions(database_url) == EXPECTED_EXTENSIONS
    assert installed_baseline_tables(database_url) == CURRENT_HEAD_TABLES
    assert seeded_role_codes(database_url) == EXPECTED_ROLE_CODES
    assert table_row_count(database_url, "organizations") == 0
    assert table_row_count(database_url, "users") == 0
    assert table_row_count(database_url, "token_sessions") == 0
    assert table_row_count(database_url, "idempotency_records") == 0
    assert table_row_count(database_url, "audit_rules") == 0
    assert table_row_count(database_url, "audit_tasks") == 0
    assert table_row_count(database_url, "contracts") == 0
    assert table_row_count(database_url, "invoices") == 0
    assert table_row_count(database_url, "suppliers") == 0
    assert user_trigger_names(database_url, "audit_rules") == {
        "trg_audit_rules_immutable",
        "trg_audit_rules_no_truncate",
    }
    assert user_trigger_names(database_url, "audit_tasks") == {"trg_audit_tasks_runtime_v1"}
    assert user_trigger_names(database_url, "document_index_versions") == {
        "trg_document_index_versions_initial_state_v1",
        "trg_document_index_versions_no_truncate_v1",
        "trg_document_index_versions_state_v1",
    }
    assert user_trigger_names(database_url, "retrieval_eval_datasets") == {
        "trg_retrieval_eval_datasets_initial_state_v1",
        "trg_retrieval_eval_datasets_no_truncate_v1",
        "trg_retrieval_eval_datasets_state_v1",
    }
    assert user_trigger_names(database_url, "retrieval_eval_runs") == {
        "trg_retrieval_eval_runs_initial_state_v1",
        "trg_retrieval_eval_runs_no_truncate_v1",
        "trg_retrieval_eval_runs_state_v1",
    }
    columns = audit_task_column_contract(database_url)
    assert [
        (name, data_type, nullable, length) for name, data_type, nullable, length, _ in columns
    ] == [
        ("id", "uuid", "NO", None),
        ("organization_id", "uuid", "NO", None),
        ("task_no", "varchar", "NO", 80),
        ("name", "varchar", "NO", 300),
        ("owner_id", "uuid", "NO", None),
        ("current_execution_id", "uuid", "YES", None),
        ("status", "varchar", "NO", 30),
        ("description", "text", "YES", None),
        ("row_version", "int8", "NO", None),
        ("created_at", "timestamptz", "NO", None),
        ("created_by", "uuid", "YES", None),
        ("updated_at", "timestamptz", "NO", None),
        ("updated_by", "uuid", "YES", None),
        ("deleted_at", "timestamptz", "YES", None),
        ("deleted_by", "uuid", "YES", None),
        ("delete_reason", "text", "YES", None),
    ]
    defaults = {name: default for name, _, _, _, default in columns if default is not None}
    assert defaults == {
        "id": "gen_random_uuid()",
        "row_version": "'1'::bigint",
        "created_at": "now()",
        "updated_at": "now()",
    }
    constraints = audit_task_constraint_contract(database_url)
    assert {name: kind for name, (kind, _) in constraints.items()} == {
        "ck_audit_tasks_soft_delete_reason_required": "c",
        "ck_audit_tasks_status_allowed": "c",
        "fk_audit_tasks_created_by_users": "f",
        "fk_audit_tasks_current_execution_id_audit_task_executions": "f",
        "fk_audit_tasks_deleted_by_users": "f",
        "fk_audit_tasks_organization_id_organizations": "f",
        "fk_audit_tasks_owner_id_users": "f",
        "fk_audit_tasks_updated_by_users": "f",
        "pk_audit_tasks": "p",
        "uq_audit_tasks_organization_id_task_no": "u",
    }
    assert "current_execution_id" in "\n".join(definition for _, definition in constraints.values())

    execute_database_statement(
        database_url,
        """
        INSERT INTO organizations (
            id,
            name,
            unified_social_credit_code,
            tax_number,
            status
        ) VALUES (
            '11111111-1111-4111-8111-111111111111',
            'migration guard organization',
            'TEST-USCC-001',
            'TEST-TAX-001',
            'active'
        )
        """,
    )
    execute_database_statement(
        database_url,
        """
        INSERT INTO users (
            id,
            organization_id,
            username,
            display_name,
            password_hash,
            status,
            password_changed_at
        ) VALUES (
            '22222222-2222-4222-8222-222222222222',
            '11111111-1111-4111-8111-111111111111',
            'migration_guard_user',
            'migration guard user',
            'synthetic-test-hash',
            'active',
            now()
        )
        """,
    )
    execute_database_statement(
        database_url,
        """
        INSERT INTO audit_tasks (
            organization_id,
            task_no,
            name,
            owner_id,
            status
        ) VALUES (
            '11111111-1111-4111-8111-111111111111',
            'AUDIT-MIGRATION-001',
            'migration guard task',
            '22222222-2222-4222-8222-222222222222',
            'open'
        )
        """,
    )
    assert table_row_count(database_url, "audit_tasks") == 1
    assert audit_task_runtime_defaults(database_url) == (1, True, True)
    for invalid_statement in (
        """
        INSERT INTO audit_tasks (organization_id, task_no, name, owner_id, status)
        VALUES (
            '11111111-1111-4111-8111-111111111111',
            'AUDIT-MIGRATION-001',
            'duplicate task number',
            '22222222-2222-4222-8222-222222222222',
            'open'
        )
        """,
        """
        INSERT INTO audit_tasks (
            organization_id, task_no, name, owner_id, current_execution_id, status
        ) VALUES (
            '11111111-1111-4111-8111-111111111111',
            'AUDIT-MIGRATION-BAD-EXECUTION',
            'invalid current execution',
            '22222222-2222-4222-8222-222222222222',
            '33333333-3333-4333-8333-333333333333',
            'open'
        )
        """,
        """
        INSERT INTO audit_tasks (organization_id, task_no, name, owner_id, status)
        VALUES (
            '11111111-1111-4111-8111-111111111111',
            'AUDIT-MIGRATION-BAD-STATUS',
            'invalid status',
            '22222222-2222-4222-8222-222222222222',
            'running'
        )
        """,
        """
        INSERT INTO audit_tasks (
            organization_id, task_no, name, owner_id, status, deleted_at
        ) VALUES (
            '11111111-1111-4111-8111-111111111111',
            'AUDIT-MIGRATION-NO-DELETE-REASON',
            'invalid soft delete',
            '22222222-2222-4222-8222-222222222222',
            'open',
            now()
        )
        """,
        """
        INSERT INTO audit_tasks (organization_id, task_no, name, owner_id, status)
        VALUES (
            '44444444-4444-4444-8444-444444444444',
            'AUDIT-MIGRATION-BAD-ORG',
            'invalid organization',
            '22222222-2222-4222-8222-222222222222',
            'open'
        )
        """,
        """
        INSERT INTO audit_tasks (organization_id, task_no, name, owner_id, status)
        VALUES (
            '11111111-1111-4111-8111-111111111111',
            'AUDIT-MIGRATION-BAD-OWNER',
            'invalid owner',
            '44444444-4444-4444-8444-444444444444',
            'open'
        )
        """,
    ):
        with pytest.raises(DBAPIError):
            execute_database_statement(database_url, invalid_statement)
        assert table_row_count(database_url, "audit_tasks") == 1

    with pytest.raises(DBAPIError):
        command.downgrade(alembic_config, "20260807_004")
    assert current_revision(database_url) == current_head_revision()
    assert table_row_count(database_url, "audit_tasks") == 1
    execute_database_statement(database_url, "DELETE FROM audit_tasks")
    assert table_row_count(database_url, "audit_tasks") == 0

    execute_database_statement(
        database_url,
        """
        INSERT INTO audit_rules (
            rule_code,
            version,
            name,
            category,
            input_schema_json,
            implementation_key,
            implementation_hash,
            application_release,
            catalog_manifest_sha256,
            default_risk_level,
            explanation_template,
            published_at,
            change_reason
        ) VALUES (
            'RULE-TEST',
            1,
            'migration guard test',
            'test',
            '{}'::jsonb,
            'tests.audit.rule',
            repeat('a', 64),
            'test-release',
            repeat('b', 64),
            'notice',
            'test only',
            now(),
            'verify immutable migration behavior'
        )
        """,
    )
    for forbidden_statement in (
        "UPDATE audit_rules SET name = 'changed' WHERE rule_code = 'RULE-TEST'",
        "DELETE FROM audit_rules WHERE rule_code = 'RULE-TEST'",
        "TRUNCATE audit_rules",
    ):
        with pytest.raises(DBAPIError):
            execute_database_statement(database_url, forbidden_statement)
        assert table_row_count(database_url, "audit_rules") == 1

    with pytest.raises(DBAPIError):
        command.downgrade(alembic_config, "20260807_003")
    assert current_revision(database_url) == current_head_revision()
    assert table_row_count(database_url, "audit_rules") == 1

    cleanup_engine = create_migration_engine(database_url)
    try:
        with cleanup_engine.begin() as connection:
            connection.execute(text("ALTER TABLE audit_rules DISABLE TRIGGER USER"))
            connection.execute(text("DELETE FROM audit_rules"))
            connection.execute(text("ALTER TABLE audit_rules ENABLE TRIGGER USER"))
    finally:
        cleanup_engine.dispose()
    assert table_row_count(database_url, "audit_rules") == 0

    command.downgrade(alembic_config, "base")
    assert current_revision(database_url) is None
    assert installed_extensions(database_url) == EXPECTED_EXTENSIONS
    assert installed_baseline_tables(database_url) == set()

    command.upgrade(alembic_config, "head")
    assert current_revision(database_url) == current_head_revision()
    assert installed_extensions(database_url) == EXPECTED_EXTENSIONS
    assert installed_baseline_tables(database_url) == CURRENT_HEAD_TABLES
    assert seeded_role_codes(database_url) == EXPECTED_ROLE_CODES

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}\n{caplog.text}"
    if database_url.password and database_url.password in rendered_output:
        pytest.fail("迁移输出包含连接密码，输出内容已隐藏", pytrace=False)


def test_ai_generated_fact_columns_and_constraints_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)

    expected_prefixes = {
        "audit_risks": "ai_explanation",
        "audit_reports": "ai_draft",
    }

    def contract(table_name: str, prefix: str) -> tuple[list[tuple[object, ...]], set[str]]:
        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                columns = connection.execute(
                    text(
                        "SELECT column_name, udt_name, is_nullable, "
                        "character_maximum_length, column_default "
                        "FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = :table_name "
                        "AND column_name LIKE :prefix ORDER BY ordinal_position"
                    ),
                    {"table_name": table_name, "prefix": f"{prefix}%"},
                ).all()
                constraints = set(
                    connection.execute(
                        text(
                            "SELECT constraint_catalog.conname FROM pg_constraint "
                            "AS constraint_catalog JOIN pg_class AS table_catalog "
                            "ON table_catalog.oid = constraint_catalog.conrelid "
                            "JOIN pg_namespace AS schema_catalog "
                            "ON schema_catalog.oid = table_catalog.relnamespace "
                            "WHERE schema_catalog.nspname = current_schema() "
                            "AND table_catalog.relname = :table_name"
                        ),
                        {"table_name": table_name},
                    ).scalars()
                )
                return [tuple(row) for row in columns], {
                    name for name in constraints if prefix in name
                }
        finally:
            engine.dispose()

    for table_name, prefix in expected_prefixes.items():
        columns, constraints = contract(table_name, prefix)
        assert [row[:4] for row in columns] == [
            (f"{prefix}_status", "varchar", "NO", 30),
            (f"{prefix}_json", "jsonb", "YES", None),
            (f"{prefix}_sha256", "bpchar", "YES", 64),
        ]
        assert columns[0][4] == "'disabled'::character varying"
        assert columns[1][4] is None
        assert columns[2][4] is None
        assert constraints == {
            f"ck_{table_name}_{prefix}_status_allowed",
            f"ck_{table_name}_{prefix}_object",
            f"ck_{table_name}_{prefix}_hash_format",
            f"ck_{table_name}_{prefix}_matrix",
        }

    command.downgrade(alembic_config, INVOICE_NULL_CURRENCY_REVISION)
    assert current_revision(database_url) == INVOICE_NULL_CURRENCY_REVISION
    for table_name, prefix in expected_prefixes.items():
        assert contract(table_name, prefix) == ([], set())

    command.upgrade(alembic_config, AI_GENERATED_FACTS_REVISION)
    assert current_revision(database_url) == AI_GENERATED_FACTS_REVISION
    for table_name, prefix in expected_prefixes.items():
        assert len(contract(table_name, prefix)[0]) == 3


def test_currency_neutral_ai_cost_migration_preserves_v1_and_guards_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    organization_id = "6a73eb80-fde4-4be2-9679-37168dbe8f01"
    operation_id = "4b625e5c-eef9-4e65-a9d0-6ed64870e766"
    trace_id = "cd1d35d7-e014-43b8-b267-36268e1092dd"
    v1_event_id = "876c4f10-50d8-4c1c-aeb4-6b6ba9799f01"
    pending_event_id = "876c4f10-50d8-4c1c-aeb4-6b6ba9799f02"
    v2_event_id = "876c4f10-50d8-4c1c-aeb4-6b6ba9799f03"
    mixed_event_id = "876c4f10-50d8-4c1c-aeb4-6b6ba9799f04"

    command.downgrade(alembic_config, AI_GENERATED_FACTS_REVISION)
    execute_database_statement(
        database_url,
        """
        INSERT INTO organizations (
            id, name, unified_social_credit_code, tax_number, status
        ) VALUES (
            :organization_id, 'currency migration test',
            'SYNTH-CURRENCY-MIGRATION-USCC', 'SYNTH-CURRENCY-MIGRATION-TAX', 'active'
        )
        """,
        {"organization_id": organization_id},
    )

    def insert_ai_call(
        event_id: str,
        *,
        event_version: int,
        status: str,
        legacy_cost: int | None,
        currency: str | None = None,
        reserved_cost: int | None = None,
        actual_cost: int | None = None,
    ) -> None:
        columns = ""
        values = ""
        parameters: dict[str, object] = {
            "event_id": event_id,
            "event_version": event_version,
            "organization_id": organization_id,
            "operation_id": operation_id,
            "trace_id": trace_id,
            "status": status,
            "event_sequence": 1 if status == "pending" else 2,
            "legacy_cost": legacy_cost,
        }
        if event_version == 2:
            columns = ", cost_currency, reserved_cost_microunits, actual_cost_microunits"
            values = ", :currency, :reserved_cost, :actual_cost"
            parameters.update(
                {
                    "currency": currency,
                    "reserved_cost": reserved_cost,
                    "actual_cost": actual_cost,
                }
            )
        execute_database_statement(
            database_url,
            f"""
            INSERT INTO ai_call_logs (
                id, event_version, event_sequence, organization_id,
                business_operation_id, trace_id, call_type, logical_generation_no,
                provider_attempt_no, adapter_id, endpoint_id, model_id,
                policy_version, policy_hash, pricing_version, input_hash,
                output_hash, reserved_input_tokens, reserved_output_tokens,
                reserved_cost_micro_usd, input_tokens, output_tokens, vector_count,
                attempt_count, is_fallback, status, started_at, completed_at, duration_ms
                {columns}
            ) VALUES (
                :event_id, :event_version, :event_sequence, :organization_id,
                :operation_id, :trace_id, 'embedding', 1,
                1, 'openai_embeddings_v1', 'synthetic-endpoint', 'synthetic-model',
                '2', repeat('a',64), 'synthetic-pricing-v2', repeat('b',64),
                CASE WHEN :status='pending' THEN NULL ELSE repeat('c',64) END,
                10, 0, :legacy_cost,
                CASE WHEN :status='pending' THEN NULL ELSE 7 END,
                CASE WHEN :status='pending' THEN NULL ELSE 0 END,
                CASE WHEN :status='pending' THEN NULL ELSE 1 END,
                1, false, :status, clock_timestamp() - interval '1 second',
                CASE WHEN :status='pending' THEN NULL ELSE clock_timestamp() END,
                CASE WHEN :status='pending' THEN NULL ELSE 1000 END
                {values}
            )
            """,
            parameters,
        )

    def delete_ai_call(event_id: str) -> None:
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE ai_call_logs DISABLE TRIGGER USER")
                connection.execute(
                    text("DELETE FROM ai_call_logs WHERE id=:event_id"),
                    {"event_id": event_id},
                )
                connection.exec_driver_sql("ALTER TABLE ai_call_logs ENABLE TRIGGER USER")
        finally:
            engine.dispose()

    insert_ai_call(
        v1_event_id,
        event_version=1,
        status="succeeded",
        legacy_cost=23,
    )
    command.upgrade(alembic_config, CURRENCY_NEUTRAL_AI_COST_REVISION)
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT event_version, reserved_cost_micro_usd, cost_currency, "
                    "reserved_cost_microunits, actual_cost_microunits "
                    "FROM ai_call_logs WHERE id=:event_id"
                ),
                {"event_id": v1_event_id},
            ).one()
            assert tuple(row) == (1, 23, None, None, None)
    finally:
        engine.dispose()

    command.downgrade(alembic_config, AI_GENERATED_FACTS_REVISION)
    delete_ai_call(v1_event_id)
    insert_ai_call(
        pending_event_id,
        event_version=1,
        status="pending",
        legacy_cost=0,
    )
    assert (
        call_expect_database_error(
            lambda: command.upgrade(alembic_config, CURRENCY_NEUTRAL_AI_COST_REVISION)
        )[0]
        == "55000"
    )
    assert current_revision(database_url) == AI_GENERATED_FACTS_REVISION
    delete_ai_call(pending_event_id)

    command.upgrade(alembic_config, CURRENCY_NEUTRAL_AI_COST_REVISION)
    insert_ai_call(
        v2_event_id,
        event_version=2,
        status="succeeded",
        legacy_cost=None,
        currency="CNY",
        reserved_cost=5,
        actual_cost=4,
    )
    assert execute_expect_database_error(
        database_url,
        """
        INSERT INTO ai_call_logs (
            id, event_version, event_sequence, organization_id,
            business_operation_id, trace_id, call_type, logical_generation_no,
            provider_attempt_no, adapter_id, endpoint_id, model_id,
            policy_version, policy_hash, pricing_version, input_hash,
            output_hash, reserved_input_tokens, reserved_output_tokens,
            reserved_cost_micro_usd, cost_currency, reserved_cost_microunits,
            actual_cost_microunits, input_tokens, output_tokens, vector_count,
            attempt_count, is_fallback, status, started_at, completed_at, duration_ms
        ) VALUES (
            :event_id, 2, 2, :organization_id, :operation_id, :trace_id,
            'embedding', 1, 1, 'openai_embeddings_v1', 'synthetic-endpoint',
            'synthetic-model', '2', repeat('a',64), 'synthetic-pricing-v2',
            repeat('b',64), repeat('c',64), 10, 0, 1, 'CNY', 5, 4,
            7, 0, 1, 1, false, 'succeeded', clock_timestamp() - interval '1 second',
            clock_timestamp(), 1000
        )
        """,
        {
            "event_id": mixed_event_id,
            "organization_id": organization_id,
            "operation_id": operation_id,
            "trace_id": trace_id,
        },
    ) == ("23514", "ck_ai_call_logs_cost_version_matrix")
    assert (
        call_expect_database_error(
            lambda: command.downgrade(alembic_config, AI_GENERATED_FACTS_REVISION)
        )[0]
        == "55000"
    )
    assert current_revision(database_url) == CURRENCY_NEUTRAL_AI_COST_REVISION

    delete_ai_call(v2_event_id)
    execute_database_statement(
        database_url,
        "DELETE FROM organizations WHERE id=:organization_id",
        {"organization_id": organization_id},
    )
    command.downgrade(alembic_config, AI_GENERATED_FACTS_REVISION)
    command.upgrade(alembic_config, CURRENCY_NEUTRAL_AI_COST_REVISION)
    assert current_revision(database_url) == CURRENCY_NEUTRAL_AI_COST_REVISION


def test_financial_master_postgresql_catalog_is_exact_and_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)

    expected_columns = {
        "contracts": [
            ("id", "uuid", "NO", None),
            ("organization_id", "uuid", "NO", None),
            ("contract_no", "varchar", "YES", 100),
            ("name", "varchar", "NO", 300),
            ("party_a_name", "varchar", "YES", 300),
            ("party_a_tax_no", "varchar", "YES", 32),
            ("party_b_name", "varchar", "YES", 300),
            ("party_b_tax_no", "varchar", "YES", 32),
            ("supplier_id", "uuid", "YES", None),
            ("amount", "numeric", "YES", None),
            ("currency", "bpchar", "YES", 3),
            ("signed_date", "date", "YES", None),
            ("effective_date", "date", "YES", None),
            ("expiry_date", "date", "YES", None),
            ("payment_method", "varchar", "YES", 100),
            ("payment_terms", "text", "YES", None),
            ("confirmation_status", "varchar", "NO", 20),
            ("status", "varchar", "NO", 20),
            ("confirmed_by", "uuid", "YES", None),
            ("confirmed_at", "timestamptz", "YES", None),
            ("critical_fact_hash", "bpchar", "NO", 64),
            ("row_version", "int8", "NO", None),
            ("created_at", "timestamptz", "NO", None),
            ("created_by", "uuid", "YES", None),
            ("updated_at", "timestamptz", "NO", None),
            ("updated_by", "uuid", "YES", None),
            ("deleted_at", "timestamptz", "YES", None),
            ("deleted_by", "uuid", "YES", None),
            ("delete_reason", "text", "YES", None),
        ],
        "invoices": [
            ("id", "uuid", "NO", None),
            ("organization_id", "uuid", "NO", None),
            ("invoice_code", "varchar", "YES", 50),
            ("invoice_number", "varchar", "YES", 50),
            ("invoice_type", "varchar", "YES", 40),
            ("invoice_date", "date", "YES", None),
            ("buyer_name", "varchar", "YES", 300),
            ("buyer_tax_no", "varchar", "YES", 32),
            ("seller_name", "varchar", "YES", 300),
            ("seller_tax_no", "varchar", "YES", 32),
            ("supplier_id", "uuid", "YES", None),
            ("amount_excluding_tax", "numeric", "YES", None),
            ("tax_amount", "numeric", "YES", None),
            ("total_amount", "numeric", "YES", None),
            ("currency", "bpchar", "YES", 3),
            ("confirmation_status", "varchar", "NO", 20),
            ("duplicate_status", "varchar", "NO", 30),
            ("status", "varchar", "NO", 20),
            ("field_evidence_json", "jsonb", "NO", None),
            ("confirmed_by", "uuid", "YES", None),
            ("confirmed_at", "timestamptz", "YES", None),
            ("critical_fact_hash", "bpchar", "NO", 64),
            ("row_version", "int8", "NO", None),
            ("created_at", "timestamptz", "NO", None),
            ("created_by", "uuid", "YES", None),
            ("updated_at", "timestamptz", "NO", None),
            ("updated_by", "uuid", "YES", None),
            ("deleted_at", "timestamptz", "YES", None),
            ("deleted_by", "uuid", "YES", None),
            ("delete_reason", "text", "YES", None),
            ("is_red_invoice", "bool", "YES", None),
        ],
        "suppliers": [
            ("id", "uuid", "NO", None),
            ("organization_id", "uuid", "NO", None),
            ("standard_name", "varchar", "NO", 300),
            ("unified_social_credit_code", "varchar", "YES", 32),
            ("tax_number", "varchar", "YES", 32),
            ("source_type", "varchar", "NO", 30),
            ("source_contract_id", "uuid", "YES", None),
            ("source_invoice_id", "uuid", "YES", None),
            ("confirmation_status", "varchar", "NO", 20),
            ("status", "varchar", "NO", 20),
            ("confirmed_by", "uuid", "YES", None),
            ("confirmed_at", "timestamptz", "YES", None),
            ("row_version", "int8", "NO", None),
            ("created_at", "timestamptz", "NO", None),
            ("created_by", "uuid", "YES", None),
            ("updated_at", "timestamptz", "NO", None),
            ("updated_by", "uuid", "YES", None),
            ("deleted_at", "timestamptz", "YES", None),
            ("deleted_by", "uuid", "YES", None),
            ("delete_reason", "text", "YES", None),
        ],
    }
    expected_constraint_types = {
        "contracts": {
            "ck_contracts_amount_nonnegative": "c",
            "ck_contracts_confirmation_status_allowed": "c",
            "ck_contracts_contract_no_normalized": "c",
            "ck_contracts_expiry_not_before_effective": "c",
            "ck_contracts_soft_delete_reason_required": "c",
            "ck_contracts_status_allowed": "c",
            "fk_contracts_confirmed_by_users": "f",
            "fk_contracts_created_by_users": "f",
            "fk_contracts_deleted_by_users": "f",
            "fk_contracts_organization_id_organizations": "f",
            "fk_contracts_supplier_id_suppliers": "f",
            "fk_contracts_updated_by_users": "f",
            "pk_contracts": "p",
        },
        "invoices": {
            "ck_invoices_confirmed_currency_required": "c",
            "ck_invoices_confirmation_matrix": "c",
            "ck_invoices_confirmation_status_allowed": "c",
            "ck_invoices_critical_fact_hash_format": "c",
            "ck_invoices_duplicate_status_allowed": "c",
            "ck_invoices_field_evidence_object": "c",
            "ck_invoices_row_version_positive": "c",
            "ck_invoices_soft_delete_reason_required": "c",
            "ck_invoices_status_allowed": "c",
            "fk_invoices_confirmed_by_users": "f",
            "fk_invoices_created_by_users": "f",
            "fk_invoices_deleted_by_users": "f",
            "fk_invoices_organization_id_organizations": "f",
            "fk_invoices_supplier_id_suppliers": "f",
            "fk_invoices_updated_by_users": "f",
            "pk_invoices": "p",
        },
        "suppliers": {
            "ck_suppliers_active_tax_identity_required": "c",
            "ck_suppliers_confirmation_matrix": "c",
            "ck_suppliers_confirmation_status_allowed": "c",
            "ck_suppliers_row_version_positive": "c",
            "ck_suppliers_soft_delete_reason_required": "c",
            "ck_suppliers_source_reference_matches_type": "c",
            "ck_suppliers_source_type_allowed": "c",
            "ck_suppliers_standard_name_normalized": "c",
            "ck_suppliers_status_allowed": "c",
            "ck_suppliers_tax_identity_sources_equal": "c",
            "ck_suppliers_tax_number_normalized": "c",
            "ck_suppliers_unified_social_credit_code_normalized": "c",
            "fk_suppliers_confirmed_by_users": "f",
            "fk_suppliers_created_by_users": "f",
            "fk_suppliers_deleted_by_users": "f",
            "fk_suppliers_organization_id_organizations": "f",
            "fk_suppliers_source_contract_id_contracts": "f",
            "fk_suppliers_source_invoice_id_invoices": "f",
            "fk_suppliers_updated_by_users": "f",
            "pk_suppliers": "p",
        },
    }
    control_range = "[\x01-\x1f\x7f-\x9f]"
    confirmation_check = (
        "CHECK (confirmation_status::text = ANY (ARRAY["
        "'unconfirmed'::character varying, 'confirmed'::character varying, "
        "'rejected'::character varying]::text[]))"
    )
    soft_delete_check = (
        "CHECK (deleted_at IS NULL OR delete_reason IS NOT NULL "
        "AND btrim(delete_reason) <> ''::text)"
    )
    expected_check_definitions = {
        "contracts": {
            "ck_contracts_amount_nonnegative": ("CHECK (amount IS NULL OR amount >= 0::numeric)"),
            "ck_contracts_confirmation_status_allowed": confirmation_check,
            "ck_contracts_contract_no_normalized": (
                'CHECK (contract_no IS NULL OR (contract_no::text COLLATE "C") '
                '<> (\'\'::text COLLATE "C") AND (contract_no::text COLLATE "C") '
                "= (btrim(contract_no::text, ' '::text) COLLATE \"C\") AND "
                f"(contract_no::text COLLATE \"C\") !~ '{control_range}'::text)"
            ),
            "ck_contracts_expiry_not_before_effective": (
                "CHECK (expiry_date IS NULL OR effective_date IS NULL "
                "OR expiry_date >= effective_date)"
            ),
            "ck_contracts_soft_delete_reason_required": soft_delete_check,
            "ck_contracts_status_allowed": (
                "CHECK (status::text = ANY (ARRAY['draft'::character varying, "
                "'active'::character varying, 'expired'::character varying, "
                "'terminated'::character varying, "
                "'archived'::character varying]::text[]))"
            ),
        },
        "invoices": {
            "ck_invoices_confirmed_currency_required": (
                "CHECK (confirmation_status::text <> 'confirmed'::text OR currency IS NOT NULL)"
            ),
            "ck_invoices_confirmation_matrix": (
                "CHECK (confirmation_status::text = 'unconfirmed'::text "
                "AND status::text = 'draft'::text AND confirmed_by IS NULL "
                "AND confirmed_at IS NULL OR confirmation_status::text = "
                "'confirmed'::text AND (status::text = ANY (ARRAY["
                "'confirmed'::character varying, 'voided'::character varying, "
                "'archived'::character varying]::text[])) AND confirmed_by IS NOT NULL "
                "AND confirmed_at IS NOT NULL OR confirmation_status::text = "
                "'rejected'::text AND status::text = 'draft'::text "
                "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)"
            ),
            "ck_invoices_confirmation_status_allowed": confirmation_check,
            "ck_invoices_critical_fact_hash_format": (
                "CHECK (critical_fact_hash ~ '^[0-9a-f]{64}$'::text)"
            ),
            "ck_invoices_duplicate_status_allowed": (
                "CHECK (duplicate_status::text = ANY (ARRAY["
                "'not_checked'::character varying, 'unique'::character varying, "
                "'suspected'::character varying, "
                "'confirmed_duplicate'::character varying, "
                "'exception_approved'::character varying]::text[]))"
            ),
            "ck_invoices_field_evidence_object": (
                "CHECK (jsonb_typeof(field_evidence_json) = 'object'::text)"
            ),
            "ck_invoices_row_version_positive": "CHECK (row_version > 0)",
            "ck_invoices_soft_delete_reason_required": soft_delete_check,
            "ck_invoices_status_allowed": (
                "CHECK (status::text = ANY (ARRAY['draft'::character varying, "
                "'confirmed'::character varying, 'voided'::character varying, "
                "'archived'::character varying]::text[]))"
            ),
        },
        "suppliers": {
            "ck_suppliers_active_tax_identity_required": (
                "CHECK (status::text <> 'active'::text OR "
                "COALESCE(unified_social_credit_code, tax_number) IS NOT NULL)"
            ),
            "ck_suppliers_confirmation_matrix": (
                "CHECK (confirmation_status::text = 'unconfirmed'::text "
                "AND status::text = 'candidate'::text AND confirmed_by IS NULL "
                "AND confirmed_at IS NULL OR confirmation_status::text = "
                "'confirmed'::text AND status::text = 'active'::text "
                "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL OR "
                "confirmation_status::text = 'rejected'::text "
                "AND status::text = 'inactive'::text AND confirmed_by IS NOT NULL "
                "AND confirmed_at IS NOT NULL)"
            ),
            "ck_suppliers_confirmation_status_allowed": confirmation_check,
            "ck_suppliers_row_version_positive": "CHECK (row_version > 0)",
            "ck_suppliers_soft_delete_reason_required": soft_delete_check,
            "ck_suppliers_source_reference_matches_type": (
                "CHECK (source_type::text = 'contract'::text "
                "AND source_contract_id IS NOT NULL AND source_invoice_id IS NULL "
                "OR source_type::text = 'invoice'::text "
                "AND source_contract_id IS NULL AND source_invoice_id IS NOT NULL "
                "OR source_type::text = 'manual'::text "
                "AND source_contract_id IS NULL AND source_invoice_id IS NULL)"
            ),
            "ck_suppliers_source_type_allowed": (
                "CHECK (source_type::text = ANY (ARRAY['contract'::character varying, "
                "'invoice'::character varying, 'manual'::character varying]::text[]))"
            ),
            "ck_suppliers_standard_name_normalized": (
                "CHECK (btrim(standard_name::text) <> ''::text "
                "AND standard_name::text = btrim(standard_name::text) "
                f"AND standard_name::text !~ '{control_range}'::text)"
            ),
            "ck_suppliers_status_allowed": (
                "CHECK (status::text = ANY (ARRAY['candidate'::character varying, "
                "'active'::character varying, 'inactive'::character varying]::text[]))"
            ),
            "ck_suppliers_tax_identity_sources_equal": (
                "CHECK (unified_social_credit_code IS NULL OR tax_number IS NULL OR "
                '(unified_social_credit_code::text COLLATE "C") '
                '= (tax_number::text COLLATE "C"))'
            ),
            "ck_suppliers_tax_number_normalized": (
                'CHECK (tax_number IS NULL OR (tax_number::text COLLATE "C") '
                '<> (\'\'::text COLLATE "C") AND (tax_number::text COLLATE "C") '
                "= (btrim(tax_number::text, ' '::text) COLLATE \"C\") AND "
                f"(tax_number::text COLLATE \"C\") !~ '{control_range}'::text)"
            ),
            "ck_suppliers_unified_social_credit_code_normalized": (
                "CHECK (unified_social_credit_code IS NULL OR "
                '(unified_social_credit_code::text COLLATE "C") '
                "<> (''::text COLLATE \"C\") AND "
                '(unified_social_credit_code::text COLLATE "C") = '
                "(btrim(unified_social_credit_code::text, ' '::text) COLLATE \"C\") "
                'AND (unified_social_credit_code::text COLLATE "C") '
                f"!~ '{control_range}'::text AND "
                '(unified_social_credit_code::text COLLATE "C") '
                "~ '^[0-9A-Z]+$'::text)"
            ),
        },
    }
    expected_indexes = {
        "contracts": {
            "idx_contracts_org_status",
            "idx_contracts_party_b_tax",
            "pk_contracts",
            "uq_contracts_organization_contract_no",
        },
        "invoices": {
            "idx_invoices_duplicate_lookup",
            "idx_invoices_org_date",
            "idx_invoices_seller_tax",
            "pk_invoices",
        },
        "suppliers": {
            "pk_suppliers",
            "uq_suppliers_organization_source_contract_candidate",
            "uq_suppliers_organization_source_invoice_candidate",
            "uq_suppliers_organization_tax_identity",
        },
    }
    expected_business_indexes = {
        "contracts": {
            "idx_contracts_org_status": (
                False,
                "CREATE INDEX idx_contracts_org_status ON contracts USING btree "
                "(organization_id, status, updated_at DESC)",
                None,
                ("organization_id", "status", "updated_at"),
            ),
            "idx_contracts_party_b_tax": (
                False,
                "CREATE INDEX idx_contracts_party_b_tax ON contracts USING btree "
                "(organization_id, party_b_tax_no)",
                None,
                ("organization_id", "party_b_tax_no"),
            ),
            "uq_contracts_organization_contract_no": (
                True,
                "CREATE UNIQUE INDEX uq_contracts_organization_contract_no ON "
                'contracts USING btree (organization_id, contract_no COLLATE "C") '
                "WHERE contract_no IS NOT NULL AND deleted_at IS NULL",
                "contract_no IS NOT NULL AND deleted_at IS NULL",
                ("organization_id", "contract_no"),
            ),
        },
        "invoices": {
            "idx_invoices_duplicate_lookup": (
                False,
                "CREATE INDEX idx_invoices_duplicate_lookup ON invoices USING btree "
                "(organization_id, invoice_code, invoice_number, seller_tax_no) "
                "WHERE deleted_at IS NULL AND status::text <> 'voided'::text",
                "deleted_at IS NULL AND status::text <> 'voided'::text",
                (
                    "organization_id",
                    "invoice_code",
                    "invoice_number",
                    "seller_tax_no",
                ),
            ),
            "idx_invoices_org_date": (
                False,
                "CREATE INDEX idx_invoices_org_date ON invoices USING btree "
                "(organization_id, invoice_date DESC)",
                None,
                ("organization_id", "invoice_date"),
            ),
            "idx_invoices_seller_tax": (
                False,
                "CREATE INDEX idx_invoices_seller_tax ON invoices USING btree "
                "(organization_id, seller_tax_no)",
                None,
                ("organization_id", "seller_tax_no"),
            ),
        },
        "suppliers": {
            "uq_suppliers_organization_source_contract_candidate": (
                True,
                "CREATE UNIQUE INDEX uq_suppliers_organization_source_contract_candidate "
                "ON suppliers USING btree (organization_id, source_contract_id) "
                "WHERE status::text = 'candidate'::text AND deleted_at IS NULL "
                "AND source_contract_id IS NOT NULL",
                "status::text = 'candidate'::text AND deleted_at IS NULL "
                "AND source_contract_id IS NOT NULL",
                ("organization_id", "source_contract_id"),
            ),
            "uq_suppliers_organization_source_invoice_candidate": (
                True,
                "CREATE UNIQUE INDEX uq_suppliers_organization_source_invoice_candidate "
                "ON suppliers USING btree (organization_id, source_invoice_id) "
                "WHERE status::text = 'candidate'::text AND deleted_at IS NULL "
                "AND source_invoice_id IS NOT NULL",
                "status::text = 'candidate'::text AND deleted_at IS NULL "
                "AND source_invoice_id IS NOT NULL",
                ("organization_id", "source_invoice_id"),
            ),
            "uq_suppliers_organization_tax_identity": (
                True,
                "CREATE UNIQUE INDEX uq_suppliers_organization_tax_identity ON "
                "suppliers USING btree (organization_id, "
                'COALESCE(unified_social_credit_code, tax_number) COLLATE "C") '
                "WHERE status::text = 'active'::text AND deleted_at IS NULL AND "
                "COALESCE(unified_social_credit_code, tax_number) IS NOT NULL",
                "status::text = 'active'::text AND deleted_at IS NULL AND "
                "COALESCE(unified_social_credit_code, tax_number) IS NOT NULL",
                (
                    "organization_id",
                    "COALESCE(unified_social_credit_code, tax_number)",
                ),
            ),
        },
    }

    for table_name in FINANCIAL_TABLES:
        columns = financial_column_contract(database_url, table_name)
        observed_columns = [
            (name, data_type, nullable, length) for name, data_type, nullable, length, *_ in columns
        ]
        assert observed_columns == expected_columns[table_name]
        constraints = financial_constraint_contract(database_url, table_name)
        assert {name: kind for name, (kind, _) in constraints.items()} == expected_constraint_types[
            table_name
        ]
        assert {
            name: definition for name, (kind, definition) in constraints.items() if kind == "c"
        } == expected_check_definitions[table_name]
        indexes = financial_index_contract(database_url, table_name)
        assert set(indexes) == expected_indexes[table_name]
        assert {
            name: definition for name, definition in indexes.items() if not name.startswith("pk_")
        } == expected_business_indexes[table_name]
        assert count_financial_rows(database_url, table_name) == 0

    expected_foreign_key_targets = {
        "contracts": {
            "fk_contracts_organization_id_organizations": "organizations(id)",
            "fk_contracts_supplier_id_suppliers": "suppliers(id)",
            "fk_contracts_confirmed_by_users": "users(id)",
            "fk_contracts_created_by_users": "users(id)",
            "fk_contracts_updated_by_users": "users(id)",
            "fk_contracts_deleted_by_users": "users(id)",
        },
        "invoices": {
            "fk_invoices_organization_id_organizations": "organizations(id)",
            "fk_invoices_supplier_id_suppliers": "suppliers(id)",
            "fk_invoices_confirmed_by_users": "users(id)",
            "fk_invoices_created_by_users": "users(id)",
            "fk_invoices_updated_by_users": "users(id)",
            "fk_invoices_deleted_by_users": "users(id)",
        },
        "suppliers": {
            "fk_suppliers_organization_id_organizations": "organizations(id)",
            "fk_suppliers_source_contract_id_contracts": "contracts(id)",
            "fk_suppliers_source_invoice_id_invoices": "invoices(id)",
            "fk_suppliers_confirmed_by_users": "users(id)",
            "fk_suppliers_created_by_users": "users(id)",
            "fk_suppliers_updated_by_users": "users(id)",
            "fk_suppliers_deleted_by_users": "users(id)",
        },
    }
    for table_name, expected_targets in expected_foreign_key_targets.items():
        constraints = financial_constraint_contract(database_url, table_name)
        for constraint_name, target in expected_targets.items():
            normalized_definition = constraints[constraint_name][1].replace(" ", "")
            assert f"REFERENCES{target}" in normalized_definition

    contract_columns = financial_column_contract(database_url, "contracts")
    contract_by_name = {row[0]: row for row in contract_columns}
    assert contract_by_name["amount"][4:6] == (18, 2)
    invoice_columns = financial_column_contract(database_url, "invoices")
    invoice_by_name = {row[0]: row for row in invoice_columns}
    for column_name in ("amount_excluding_tax", "tax_amount", "total_amount"):
        assert invoice_by_name[column_name][4:6] == (18, 2)

    contract_defaults = {row[0]: row[6] for row in contract_columns if row[6] is not None}
    assert contract_defaults == {
        "id": "gen_random_uuid()",
        "row_version": "'1'::bigint",
        "created_at": "now()",
        "updated_at": "now()",
    }
    invoice_defaults = {row[0]: row[6] for row in invoice_columns if row[6] is not None}
    assert invoice_defaults == {
        "id": "gen_random_uuid()",
        "duplicate_status": "'not_checked'::character varying",
        "field_evidence_json": "'{}'::jsonb",
        "row_version": "'1'::bigint",
        "created_at": "now()",
        "updated_at": "now()",
    }
    supplier_defaults = {
        row[0]: row[6]
        for row in financial_column_contract(database_url, "suppliers")
        if row[6] is not None
    }
    assert supplier_defaults == {
        "id": "gen_random_uuid()",
        "row_version": "'1'::bigint",
        "created_at": "now()",
        "updated_at": "now()",
    }

    foreign_key_actions = financial_foreign_key_actions(database_url)
    assert set(foreign_key_actions) == {
        name
        for table_name in FINANCIAL_TABLES
        for name, (kind, _) in financial_constraint_contract(database_url, table_name).items()
        if kind == "f"
    }
    assert set(foreign_key_actions.values()) == {("a", "a")}


def test_financial_master_postgresql_constraints_and_indexes_behave_exactly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_financial_organization(database_url)
    sensitive_values = {
        "SYNTHETIC-CONTRACT-CONFLICT",
        "SYNTHETIC-ACTIVE-TAX-9001",
        "SYNTHETICUSCC9002",
        "合成税号甲乙",
    }
    try:
        insert_contract(
            database_url,
            record_id="62000000-0000-4000-8000-000000000001",
            contract_no=None,
        )
        insert_contract(
            database_url,
            record_id="62000000-0000-4000-8000-000000000002",
            contract_no=None,
        )
        for sequence, contract_no in enumerate(
            ("Case-Key", "case-key", "é", "e\u0301", "内部 空格", "\u00a0边界\u00a0"),
            start=3,
        ):
            insert_contract(
                database_url,
                record_id=f"62000000-0000-4000-8000-{sequence:012d}",
                contract_no=contract_no,
            )
        insert_contract(
            database_url,
            record_id="62000000-0000-4000-8000-000000000020",
            contract_no="SYNTHETIC-CONTRACT-CONFLICT",
            status="draft",
        )
        for sequence, duplicate_status in enumerate(
            ("active", "expired", "terminated", "archived"),
            start=21,
        ):

            def insert_duplicate_contract(
                status: str = duplicate_status,
                number: int = sequence,
            ) -> None:
                insert_contract(
                    database_url,
                    record_id=f"62000000-0000-4000-8000-{number:012d}",
                    contract_no="SYNTHETIC-CONTRACT-CONFLICT",
                    status=status,
                )

            assert call_expect_database_error(insert_duplicate_contract) == (
                "23505",
                "uq_contracts_organization_contract_no",
            )
        insert_contract(
            database_url,
            record_id="62000000-0000-4000-8000-000000000022",
            contract_no="SYNTHETIC-CONTRACT-REUSE",
            deleted=True,
        )
        insert_contract(
            database_url,
            record_id="62000000-0000-4000-8000-000000000023",
            contract_no="SYNTHETIC-CONTRACT-REUSE",
            status="active",
        )
        for sequence, invalid_contract_no in enumerate(
            ("", " ", " leading", "trailing ", "bad\x01value", "bad\x7fvalue", "bad\x9fvalue"),
            start=30,
        ):

            def insert_invalid_contract(
                value: str = invalid_contract_no,
                number: int = sequence,
            ) -> None:
                insert_contract(
                    database_url,
                    record_id=f"62000000-0000-4000-8000-{number:012d}",
                    contract_no=value,
                )

            assert call_expect_database_error(insert_invalid_contract) == (
                "23514",
                "ck_contracts_contract_no_normalized",
            )
        with pytest.raises((StatementError, ValueError)):
            insert_contract(
                database_url,
                record_id="62000000-0000-4000-8000-000000000039",
                contract_no="bad\x00value",
            )
        assert call_expect_database_error(
            lambda: insert_contract(
                database_url,
                record_id="62000000-0000-4000-8000-000000000040",
                contract_no="SYNTHETIC-NEGATIVE-AMOUNT",
                amount="-0.01",
            )
        ) == ("23514", "ck_contracts_amount_nonnegative")
        assert call_expect_database_error(
            lambda: insert_contract(
                database_url,
                record_id="62000000-0000-4000-8000-000000000041",
                contract_no="SYNTHETIC-BAD-DATES",
                effective_date="2026-08-10",
                expiry_date="2026-08-09",
            )
        ) == ("23514", "ck_contracts_expiry_not_before_effective")
        insert_contract(
            database_url,
            record_id="62000000-0000-4000-8000-000000000042",
            contract_no="SYNTHETIC-EQUAL-DATES",
            amount="0.00",
            effective_date="2026-08-09",
            expiry_date="2026-08-09",
        )

        source_contract_id = "62000000-0000-4000-8000-000000000050"
        source_invoice_id = "63000000-0000-4000-8000-000000000050"
        insert_contract(
            database_url,
            record_id=source_contract_id,
            contract_no="SYNTHETIC-SOURCE-CONTRACT",
        )
        insert_invoice(database_url, record_id=source_invoice_id)
        source_combinations = (
            (None, None),
            (source_contract_id, None),
            (None, source_invoice_id),
            (source_contract_id, source_invoice_id),
        )
        allowed_source_combinations = {
            ("contract", source_contract_id, None),
            ("invoice", None, source_invoice_id),
            ("manual", None, None),
        }
        for source_index, source_type in enumerate(("contract", "invoice", "manual")):
            for combination_index, (contract_id, invoice_id) in enumerate(source_combinations):
                record_id = (
                    f"64000000-0000-4000-8000-{source_index * 4 + combination_index + 1:012d}"
                )
                if (source_type, contract_id, invoice_id) in allowed_source_combinations:
                    insert_supplier(
                        database_url,
                        record_id=record_id,
                        source_type=source_type,
                        source_contract_id=contract_id,
                        source_invoice_id=invoice_id,
                    )
                else:

                    def insert_invalid_source_supplier(
                        bound_record_id: str = record_id,
                        bound_source_type: str = source_type,
                        bound_contract_id: str | None = contract_id,
                        bound_invoice_id: str | None = invoice_id,
                    ) -> None:
                        insert_supplier(
                            database_url,
                            record_id=bound_record_id,
                            source_type=bound_source_type,
                            source_contract_id=bound_contract_id,
                            source_invoice_id=bound_invoice_id,
                        )

                    assert call_expect_database_error(insert_invalid_source_supplier) == (
                        "23514",
                        "ck_suppliers_source_reference_matches_type",
                    )

        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000020",
            status="candidate",
        )
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000021",
            status="inactive",
        )
        assert call_expect_database_error(
            lambda: insert_supplier(
                database_url,
                record_id="64000000-0000-4000-8000-000000000022",
                status="active",
            )
        ) == ("23514", "ck_suppliers_active_tax_identity_required")
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000023",
            unified_social_credit_code="A0Z9",
            status="active",
        )
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000024",
            tax_number="合成税号甲乙",
            status="active",
        )
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000025",
            tax_number="é",
            status="active",
        )
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000026",
            tax_number="e\u0301",
            status="active",
        )
        for sequence, invalid_uscc in enumerate(
            ("a0z9", "A0-Z9", "统一代码", " A0Z9", "A0Z9 "),
            start=30,
        ):

            def insert_invalid_uscc_supplier(
                value: str = invalid_uscc,
                number: int = sequence,
            ) -> None:
                insert_supplier(
                    database_url,
                    record_id=f"64000000-0000-4000-8000-{number:012d}",
                    unified_social_credit_code=value,
                )

            assert call_expect_database_error(insert_invalid_uscc_supplier) == (
                "23514",
                "ck_suppliers_unified_social_credit_code_normalized",
            )
        for sequence, invalid_tax_number in enumerate(
            ("", " ", " TAX", "TAX ", "TAX\x01", "TAX\x1f", "TAX\x7f", "TAX\x80", "TAX\x9f"),
            start=40,
        ):

            def insert_invalid_tax_supplier(
                value: str = invalid_tax_number,
                number: int = sequence,
            ) -> None:
                insert_supplier(
                    database_url,
                    record_id=f"64000000-0000-4000-8000-{number:012d}",
                    tax_number=value,
                )

            assert call_expect_database_error(insert_invalid_tax_supplier) == (
                "23514",
                "ck_suppliers_tax_number_normalized",
            )
        with pytest.raises((StatementError, ValueError)):
            insert_supplier(
                database_url,
                record_id="64000000-0000-4000-8000-000000000059",
                tax_number="TAX\x00VALUE",
            )
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000060",
            unified_social_credit_code="SAME9001",
            tax_number="SAME9001",
            status="active",
        )
        assert call_expect_database_error(
            lambda: insert_supplier(
                database_url,
                record_id="64000000-0000-4000-8000-000000000061",
                unified_social_credit_code="DIFFERENT1",
                tax_number="DIFFERENT2",
            )
        ) == ("23514", "ck_suppliers_tax_identity_sources_equal")

        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000070",
            tax_number="SYNTHETIC-ACTIVE-TAX-9001",
            status="active",
        )
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000071",
            tax_number="SYNTHETIC-ACTIVE-TAX-9001",
            status="candidate",
        )
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000072",
            tax_number="SYNTHETIC-ACTIVE-TAX-9001",
            status="inactive",
        )
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000073",
            tax_number="SYNTHETIC-ACTIVE-TAX-9001",
            status="active",
            deleted=True,
        )
        assert execute_expect_database_error(
            database_url,
            "UPDATE suppliers SET status = 'active', confirmation_status = 'confirmed', "
            "confirmed_by = :actor_id, confirmed_at = now(), row_version = row_version + 1 "
            "WHERE id = :id",
            {
                "id": "64000000-0000-4000-8000-000000000071",
                "actor_id": FINANCIAL_ACTOR_ID,
            },
        ) == ("23505", "uq_suppliers_organization_tax_identity")
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000074",
            unified_social_credit_code="SYNTHETICUSCC9002",
            status="active",
        )
        assert call_expect_database_error(
            lambda: insert_supplier(
                database_url,
                record_id="64000000-0000-4000-8000-000000000075",
                tax_number="SYNTHETICUSCC9002",
                status="active",
            )
        ) == ("23505", "uq_suppliers_organization_tax_identity")
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000076",
            standard_name="same display name",
            tax_number="IDENTITY-A",
            status="active",
        )
        insert_supplier(
            database_url,
            record_id="64000000-0000-4000-8000-000000000077",
            standard_name="same display name",
            tax_number="IDENTITY-B",
            status="active",
        )

        insert_invoice(
            database_url,
            record_id="63000000-0000-4000-8000-000000000060",
            invoice_code="DUP-CODE",
            invoice_number="DUP-NUMBER",
            seller_tax_no="DUP-TAX",
        )
        insert_invoice(
            database_url,
            record_id="63000000-0000-4000-8000-000000000061",
            invoice_code="DUP-CODE",
            invoice_number="DUP-NUMBER",
            seller_tax_no="DUP-TAX",
        )
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                duplicate_count = connection.execute(
                    text(
                        "SELECT count(*) FROM invoices WHERE organization_id = :organization_id "
                        "AND invoice_code = 'DUP-CODE' AND invoice_number = 'DUP-NUMBER' "
                        "AND seller_tax_no = 'DUP-TAX'"
                    ),
                    {"organization_id": FINANCIAL_ORGANIZATION_ID},
                ).scalar_one()
                assert duplicate_count == 2
                defaults = connection.execute(
                    text(
                        "SELECT currency, duplicate_status, field_evidence_json "
                        "FROM invoices WHERE id = :id"
                    ),
                    {"id": "63000000-0000-4000-8000-000000000060"},
                ).one()
                observed_defaults = (
                    defaults.currency,
                    defaults.duplicate_status,
                    defaults.field_evidence_json,
                )
                assert observed_defaults == (
                    None,
                    "not_checked",
                    {},
                )
                connection.execute(text("SET LOCAL enable_seqscan = off"))
                plan = connection.execute(
                    text(
                        "EXPLAIN (FORMAT JSON) SELECT id FROM invoices "
                        "WHERE organization_id = :organization_id "
                        "AND invoice_code = 'DUP-CODE' AND invoice_number = 'DUP-NUMBER' "
                        "AND seller_tax_no = 'DUP-TAX' "
                        "AND deleted_at IS NULL AND status <> 'voided'"
                    ),
                    {"organization_id": FINANCIAL_ORGANIZATION_ID},
                ).scalar_one()
                assert query_plan_uses_index(plan, "idx_invoices_duplicate_lookup")
        finally:
            engine.dispose()
    finally:
        clear_financial_test_data(database_url)

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}\n{caplog.text}"
    for sensitive_value in sensitive_values:
        assert sensitive_value not in rendered_output
    if database_url.password and database_url.password in rendered_output:
        pytest.fail("财务主数据测试输出包含连接密码，输出内容已隐藏", pytrace=False)


def test_active_supplier_identity_concurrency_commits_exactly_once_and_is_atomic(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_financial_organization(database_url)
    shared_contract_no = "SYNTHETIC-CONCURRENT-CONTRACT-NUMBER"
    shared_tax_identity = "SYNTHETIC-CONCURRENT-TAX-9003"
    candidate_contract_pairs = (
        (
            "65000000-0000-4000-8000-000000000001",
            "62000000-0000-4000-8000-000000000101",
        ),
        (
            "65000000-0000-4000-8000-000000000002",
            "62000000-0000-4000-8000-000000000102",
        ),
    )
    try:
        contract_barrier = Barrier(2)

        def insert_duplicate_contract(record_id: str) -> tuple[str, str | None]:
            contract_barrier.wait(timeout=10)
            try:
                insert_contract(
                    database_url,
                    record_id=record_id,
                    contract_no=shared_contract_no,
                )
            except DBAPIError as error:
                sqlstate, constraint_name = safe_database_error_signature(error)
                return sqlstate or "unknown", constraint_name
            return "committed", None

        with ThreadPoolExecutor(max_workers=2) as executor:
            contract_futures = [
                executor.submit(
                    insert_duplicate_contract,
                    f"65000000-0000-4000-8000-{sequence:012d}",
                )
                for sequence in (101, 102)
            ]
            contract_outcomes = [future.result(timeout=20) for future in contract_futures]
        assert sorted(contract_outcomes) == [
            ("23505", "uq_contracts_organization_contract_no"),
            ("committed", None),
        ]

        for sequence, (candidate_id, contract_id) in enumerate(candidate_contract_pairs, start=1):
            insert_contract(
                database_url,
                record_id=contract_id,
                contract_no=f"SYNTHETIC-CONCURRENT-CONTRACT-{sequence}",
            )
            insert_supplier(
                database_url,
                record_id=candidate_id,
                standard_name=f"synthetic concurrent candidate {sequence}",
                tax_number=shared_tax_identity,
                source_type="contract",
                source_contract_id=contract_id,
                status="candidate",
            )

        barrier = Barrier(2)

        def activate_candidate(candidate_id: str, contract_id: str) -> tuple[str, str | None]:
            engine = create_migration_engine(database_url)
            try:
                try:
                    with engine.begin() as connection:
                        connection.execute(
                            text("SELECT id FROM contracts WHERE id = :id FOR UPDATE"),
                            {"id": contract_id},
                        ).one()
                        connection.execute(
                            text("SELECT id FROM suppliers WHERE id = :id FOR UPDATE"),
                            {"id": candidate_id},
                        ).one()
                        barrier.wait(timeout=10)
                        connection.execute(
                            text(
                                "UPDATE suppliers SET status = 'active', "
                                "confirmation_status = 'confirmed', confirmed_by = :actor_id, "
                                "confirmed_at = now(), row_version = row_version + 1 "
                                "WHERE id = :supplier_id"
                            ),
                            {"supplier_id": candidate_id, "actor_id": FINANCIAL_ACTOR_ID},
                        )
                        connection.execute(
                            text(
                                "UPDATE contracts SET supplier_id = :supplier_id, "
                                "row_version = row_version + 1 WHERE id = :contract_id"
                            ),
                            {"supplier_id": candidate_id, "contract_id": contract_id},
                        )
                except DBAPIError as error:
                    sqlstate, constraint_name = safe_database_error_signature(error)
                    return sqlstate or "unknown", constraint_name
                return "committed", None
            finally:
                engine.dispose()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(activate_candidate, candidate_id, contract_id)
                for candidate_id, contract_id in candidate_contract_pairs
            ]
            outcomes = [future.result(timeout=20) for future in futures]

        assert sorted(outcomes) == [
            ("23505", "uq_suppliers_organization_tax_identity"),
            ("committed", None),
        ]
        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                supplier_rows = connection.execute(
                    text(
                        "SELECT id::text, status, confirmation_status FROM suppliers "
                        "WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY id"
                    ),
                    {"ids": [pair[0] for pair in candidate_contract_pairs]},
                ).all()
                contract_rows = connection.execute(
                    text(
                        "SELECT id::text, supplier_id::text FROM contracts "
                        "WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY id"
                    ),
                    {"ids": [pair[1] for pair in candidate_contract_pairs]},
                ).all()
        finally:
            engine.dispose()

        assert sorted((row.status, row.confirmation_status) for row in supplier_rows) == [
            ("active", "confirmed"),
            ("candidate", "unconfirmed"),
        ]
        active_supplier_id = next(row.id for row in supplier_rows if row.status == "active")
        committed_contract_links = [row.supplier_id for row in contract_rows if row.supplier_id]
        assert committed_contract_links == [active_supplier_id]
        assert len([row for row in contract_rows if row.supplier_id is None]) == 1
    finally:
        clear_financial_test_data(database_url)

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}\n{caplog.text}"
    assert shared_contract_no not in rendered_output
    assert shared_tax_identity not in rendered_output
    if database_url.password and database_url.password in rendered_output:
        pytest.fail("并发测试输出包含连接密码，输出内容已隐藏", pytrace=False)


def test_financial_upgrade_fault_injection_rolls_back_all_seven_stages(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    command.downgrade(alembic_config, PREVIOUS_FINANCIAL_REVISION)
    assert current_revision(database_url) == PREVIOUS_FINANCIAL_REVISION
    expected_previous_tables = TABLES_AT_006 - set(FINANCIAL_TABLES)
    stages = (
        ("table", "contracts"),
        ("table", "invoices"),
        ("table", "suppliers"),
        ("foreign_key", "fk_contracts_supplier_id_suppliers"),
        ("foreign_key", "fk_invoices_supplier_id_suppliers"),
        ("foreign_key", "fk_suppliers_source_contract_id_contracts"),
        ("foreign_key", "fk_suppliers_source_invoice_id_invoices"),
    )
    original_create_table = cast(Callable[..., object], alembic_op.create_table)
    original_create_foreign_key = cast(Callable[..., object], alembic_op.create_foreign_key)

    for stage_kind, stage_name in stages:
        with monkeypatch.context() as stage_patch:

            def create_table(
                table_name: str,
                *args: object,
                _stage_kind: str = stage_kind,
                _stage_name: str = stage_name,
                **kwargs: object,
            ) -> object:
                result = original_create_table(table_name, *args, **kwargs)
                if _stage_kind == "table" and table_name == _stage_name:
                    raise InjectedMigrationFailure("injected financial upgrade failure")
                return result

            def create_foreign_key(
                constraint_name: str,
                *args: object,
                _stage_kind: str = stage_kind,
                _stage_name: str = stage_name,
                **kwargs: object,
            ) -> object:
                result = original_create_foreign_key(constraint_name, *args, **kwargs)
                if _stage_kind == "foreign_key" and constraint_name == _stage_name:
                    raise InjectedMigrationFailure("injected financial upgrade failure")
                return result

            stage_patch.setattr(alembic_op, "create_table", create_table)
            stage_patch.setattr(alembic_op, "create_foreign_key", create_foreign_key)
            with pytest.raises(InjectedMigrationFailure):
                command.upgrade(alembic_config, FINANCIAL_REVISION)

        assert current_revision(database_url) == PREVIOUS_FINANCIAL_REVISION
        assert installed_baseline_tables(database_url) == expected_previous_tables
        assert all(
            financial_constraint_contract(database_url, table_name) == {}
            for table_name in FINANCIAL_TABLES
        )

    command.upgrade(alembic_config, FINANCIAL_REVISION)
    assert current_revision(database_url) == FINANCIAL_REVISION
    assert installed_baseline_tables(database_url) == TABLES_AT_006
    assert all(
        count_financial_rows(database_url, table_name) == 0 for table_name in FINANCIAL_TABLES
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}\n{caplog.text}"
    if database_url.password and database_url.password in rendered_output:
        pytest.fail("升级故障注入输出包含连接密码，输出内容已隐藏", pytrace=False)


def test_financial_downgrade_fault_injection_preserves_all_objects(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    stages = (
        ("constraint", "fk_suppliers_source_invoice_id_invoices"),
        ("constraint", "fk_suppliers_source_contract_id_contracts"),
        ("constraint", "fk_invoices_supplier_id_suppliers"),
        ("constraint", "fk_contracts_supplier_id_suppliers"),
        ("table", "suppliers"),
        ("table", "invoices"),
        ("table", "contracts"),
    )
    original_drop_constraint = cast(Callable[..., object], alembic_op.drop_constraint)
    original_drop_table = cast(Callable[..., object], alembic_op.drop_table)

    for stage_kind, stage_name in stages:
        with monkeypatch.context() as stage_patch:

            def drop_constraint(
                constraint_name: str,
                *args: object,
                _stage_kind: str = stage_kind,
                _stage_name: str = stage_name,
                **kwargs: object,
            ) -> object:
                result = original_drop_constraint(constraint_name, *args, **kwargs)
                if _stage_kind == "constraint" and constraint_name == _stage_name:
                    raise InjectedMigrationFailure("injected financial downgrade failure")
                return result

            def drop_table(
                table_name: str,
                *args: object,
                _stage_kind: str = stage_kind,
                _stage_name: str = stage_name,
                **kwargs: object,
            ) -> object:
                result = original_drop_table(table_name, *args, **kwargs)
                if _stage_kind == "table" and table_name == _stage_name:
                    raise InjectedMigrationFailure("injected financial downgrade failure")
                return result

            stage_patch.setattr(alembic_op, "drop_constraint", drop_constraint)
            stage_patch.setattr(alembic_op, "drop_table", drop_table)
            with pytest.raises(InjectedMigrationFailure):
                command.downgrade(alembic_config, PREVIOUS_FINANCIAL_REVISION)

        assert current_revision(database_url) == CURRENT_REVISION
        assert installed_baseline_tables(database_url) == CURRENT_HEAD_TABLES
        observed_circular_foreign_keys = {
            name
            for table_name in FINANCIAL_TABLES
            for name, (kind, _) in financial_constraint_contract(database_url, table_name).items()
            if kind == "f" and name in CIRCULAR_FINANCIAL_FOREIGN_KEYS
        }
        assert observed_circular_foreign_keys == CIRCULAR_FINANCIAL_FOREIGN_KEYS
        assert all(
            count_financial_rows(database_url, table_name) == 0 for table_name in FINANCIAL_TABLES
        )

    command.downgrade(alembic_config, PREVIOUS_FINANCIAL_REVISION)
    assert current_revision(database_url) == PREVIOUS_FINANCIAL_REVISION
    command.upgrade(alembic_config, FINANCIAL_REVISION)
    assert current_revision(database_url) == FINANCIAL_REVISION

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}\n{caplog.text}"
    if database_url.password and database_url.password in rendered_output:
        pytest.fail("降级故障注入输出包含连接密码，输出内容已隐藏", pytrace=False)


def test_financial_empty_round_trip_repeats_and_each_nonempty_table_blocks_downgrade(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    expected_previous_tables = TABLES_AT_006 - set(FINANCIAL_TABLES)

    for _ in range(2):
        command.downgrade(alembic_config, PREVIOUS_FINANCIAL_REVISION)
        assert current_revision(database_url) == PREVIOUS_FINANCIAL_REVISION
        assert installed_baseline_tables(database_url) == expected_previous_tables
        command.upgrade(alembic_config, FINANCIAL_REVISION)
        assert current_revision(database_url) == FINANCIAL_REVISION
        assert installed_baseline_tables(database_url) == TABLES_AT_006
        assert all(
            count_financial_rows(database_url, table_name) == 0 for table_name in FINANCIAL_TABLES
        )

    for table_name in FINANCIAL_TABLES:
        seed_financial_organization(database_url)
        if table_name == "contracts":
            insert_contract(
                database_url,
                record_id="66000000-0000-4000-8000-000000000001",
                contract_no="SYNTHETIC-DOWNGRADE-GUARD-CONTRACT",
            )
        elif table_name == "invoices":
            insert_invoice(
                database_url,
                record_id="66000000-0000-4000-8000-000000000002",
            )
        else:
            insert_supplier(
                database_url,
                record_id="66000000-0000-4000-8000-000000000003",
            )

        with pytest.raises(DBAPIError) as error_info:
            command.downgrade(alembic_config, PREVIOUS_FINANCIAL_REVISION)
        assert safe_database_error_signature(error_info.value)[0] == "55000"
        assert current_revision(database_url) == FINANCIAL_REVISION
        assert installed_baseline_tables(database_url) == TABLES_AT_006
        assert count_financial_rows(database_url, table_name) == 1
        observed_circular_foreign_keys = {
            name
            for financial_table in FINANCIAL_TABLES
            for name, (kind, _) in financial_constraint_contract(
                database_url, financial_table
            ).items()
            if kind == "f" and name in CIRCULAR_FINANCIAL_FOREIGN_KEYS
        }
        assert observed_circular_foreign_keys == CIRCULAR_FINANCIAL_FOREIGN_KEYS
        clear_financial_test_data(database_url)

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}\n{caplog.text}"
    for sensitive_value in (
        "SYNTHETIC-DOWNGRADE-GUARD-CONTRACT",
        "SYNTHETIC-INVOICE-TAX",
    ):
        assert sensitive_value not in rendered_output
    if database_url.password and database_url.password in rendered_output:
        pytest.fail("非空降级测试输出包含连接密码，输出内容已隐藏", pytrace=False)


def test_privileged_auth_revision_static_contract_is_exact() -> None:
    revision_source = (
        BACKEND_ROOT / "alembic" / "versions" / "20260807_008_create_privileged_auth_core.py"
    ).read_text(encoding="utf-8")
    function_bodies = dict(
        re.findall(
            r"CREATE FUNCTION public\.([a-z][a-z0-9_]*)\(\)"
            r".*?AS \$\$(.*?)\$\$",
            revision_source,
            flags=re.DOTALL,
        )
    )
    assert set(function_bodies) == PRIVILEGED_AUTH_FUNCTIONS
    assert revision_source.count("RETURNS trigger") == 5
    assert revision_source.count("SECURITY INVOKER") == 5
    assert revision_source.count("PARALLEL UNSAFE") == 5
    assert revision_source.count("SET search_path = pg_catalog, pg_temp") == 5
    assert "SECURITY DEFINER" not in revision_source
    assert " CASCADE" not in revision_source
    assert " GRANT " not in revision_source

    break_glass_state_body = function_bodies["enforce_break_glass_requests_state_v1"]
    break_glass_clock_branches = (
        ("IF TG_OP = 'INSERT' THEN", "IF NEW.id IS DISTINCT FROM OLD.id"),
        (
            "IF OLD.status = 'pending' AND NEW.status = 'approved' THEN",
            "ELSIF OLD.status = 'pending' AND NEW.status = 'rejected' THEN",
        ),
        (
            "ELSIF OLD.status = 'pending' AND NEW.status = 'rejected' THEN",
            "ELSIF OLD.status = 'approved' AND NEW.status = 'revoked' THEN",
        ),
        (
            "ELSIF OLD.status = 'approved' AND NEW.status = 'revoked' THEN",
            "ELSIF OLD.status = 'approved' AND NEW.status = 'expired' THEN",
        ),
        (
            "ELSIF OLD.status = 'approved' AND NEW.status = 'expired' THEN",
            "ELSE\n                    RAISE EXCEPTION USING",
        ),
    )
    for branch_start, branch_end in break_glass_clock_branches:
        branch_body = break_glass_state_body.split(branch_start, maxsplit=1)[1].split(
            branch_end,
            maxsplit=1,
        )[0]
        assert branch_body.count("pg_catalog.clock_timestamp()") == 1

    user_roles_state_body = function_bodies["enforce_user_roles_state_v1"]
    assert user_roles_state_body.count("pg_catalog.clock_timestamp()") == 2
    ordinary_insert_branch = user_roles_state_body.split(
        "IF NEW.assignment_source IN ('bootstrap', 'user') THEN",
        maxsplit=1,
    )[1].split("ELSIF NEW.assignment_source = 'break_glass' THEN", maxsplit=1)[0]
    break_glass_insert_branch = user_roles_state_body.split(
        "ELSIF NEW.assignment_source = 'break_glass' THEN",
        maxsplit=1,
    )[1].split("ELSE\n                        RAISE EXCEPTION USING", maxsplit=1)[0]
    break_glass_revoke_branch = user_roles_state_body.split(
        "IF OLD.assignment_source = 'break_glass' THEN",
        maxsplit=1,
    )[1].split("ELSE\n                    database_now", maxsplit=1)[0]
    ordinary_revoke_branch = user_roles_state_body.split(
        "ELSE\n                    database_now",
        maxsplit=1,
    )[1]
    assert ordinary_insert_branch.count("pg_catalog.clock_timestamp()") == 1
    assert ordinary_revoke_branch.count("pg_catalog.clock_timestamp()") == 1
    assert "clock_timestamp" not in break_glass_insert_branch
    assert "clock_timestamp" not in break_glass_revoke_branch
    long_term_sod_body = function_bodies["enforce_long_term_role_separation_v1"]
    assert long_term_sod_body.count("pg_catalog.clock_timestamp()") == 2
    assert long_term_sod_body.count("assigned_at <= database_now") == 2
    user_roles_sod_branch, remaining_sod_branches = long_term_sod_body.split(
        "ELSIF TG_TABLE_NAME = 'users' THEN", maxsplit=1
    )
    assert "clock_timestamp" not in user_roles_sod_branch
    assert re.search(
        r"IF TG_OP = 'DELETE' THEN\s+RETURN NULL;\s+END IF;\s+"
        r"IF NEW\.assignment_source = 'break_glass' THEN\s+RETURN NULL;",
        user_roles_sod_branch,
    )
    assert re.search(
        r"IF TG_OP = 'INSERT' THEN\s+database_now := NEW\.assigned_at;\s+"
        r"ELSE\s+database_now := NEW\.revoked_at;",
        user_roles_sod_branch,
    )
    assert re.search(
        r"affected_user_id := NEW\.id;\s+"
        r"database_now := pg_catalog\.clock_timestamp\(\);\s+ELSE\s+"
        r"affected_user_id := NULL;\s+"
        r"database_now := pg_catalog\.clock_timestamp\(\);",
        remaining_sod_branches,
    )
    assert (
        "OR NEW.created_at IS DISTINCT FROM OLD.created_at"
        in function_bodies["enforce_roles_invariants_v1"]
    )
    for function_name in PRIVILEGED_AUTH_FUNCTIONS - {
        "enforce_break_glass_requests_state_v1",
        "enforce_user_roles_state_v1",
        "enforce_long_term_role_separation_v1",
    }:
        assert "clock_timestamp" not in function_bodies[function_name]
    assert all("ROW(" not in body for body in function_bodies.values())

    created_triggers = re.findall(
        r"(?m)^\s*CREATE (?:CONSTRAINT )?TRIGGER ([a-z][a-z0-9_]*)",
        revision_source,
    )
    assert len(created_triggers) == 10
    assert set(created_triggers) == set().union(*PRIVILEGED_AUTH_TRIGGERS.values())
    assert revision_source.index("fixed privileged-auth role preflight failed") < (
        revision_source.index('op.create_table(\n        "break_glass_requests"')
    )
    assert revision_source.index(
        "LOCK TABLE public.break_glass_requests IN ACCESS EXCLUSIVE MODE"
    ) < revision_source.index("LOCK TABLE public.user_roles IN ACCESS EXCLUSIVE MODE")
    assert revision_source.index("LOCK TABLE public.users IN ACCESS EXCLUSIVE MODE") < (
        revision_source.index("LOCK TABLE public.roles IN ACCESS EXCLUSIVE MODE")
    )
    assert "EXCLUDE USING gist" in revision_source
    assert "COALESCE(expires_at, 'infinity'::timestamptz)" in revision_source
    assert "'[)'" in revision_source
    assert "WHERE (revoked_at IS NULL)" in revision_source
    assert "uq_user_role_active" not in revision_source
    assert revision_source.count('schema="public"') == 4
    foreign_key_targets = re.findall(
        r"sa\.ForeignKeyConstraint\(\s*\[[^\]]+\],\s*\[\"([^\"]+)\"\]",
        revision_source,
    )
    assert sorted(foreign_key_targets) == sorted(
        ["public.organizations.id"]
        + ["public.users.id"] * 7
        + ["public.roles.id", "public.break_glass_requests.id"]
    )
    roles_invariant_body = function_bodies["enforce_roles_invariants_v1"]
    assert "NEW.id IS DISTINCT FROM OLD.id" in roles_invariant_body
    assert "NEW.code IS DISTINCT FROM OLD.code" in roles_invariant_body
    assert "NEW.is_system_role IS DISTINCT FROM OLD.is_system_role" in roles_invariant_body
    for allowed_role_update_column in ("name", "description", "is_enabled"):
        assert f"NEW.{allowed_role_update_column}" not in roles_invariant_body


def seed_privileged_auth_subjects(database_url: URL) -> dict[str, str]:
    subject_ids = {
        "organization_id": str(uuid4()),
        "requester_id": str(uuid4()),
        "decider_id": str(uuid4()),
        "target_id": str(uuid4()),
    }
    tax_identity = f"SYNTH-{uuid4().hex[:20]}"
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO organizations "
                    "(id, name, unified_social_credit_code, tax_number, status) "
                    "VALUES (:id, 'synthetic privileged auth organization', "
                    ":tax_identity, :tax_identity, 'active')"
                ),
                {
                    "id": subject_ids["organization_id"],
                    "tax_identity": tax_identity,
                },
            )
            for user_key in ("requester_id", "decider_id", "target_id"):
                connection.execute(
                    text(
                        "INSERT INTO users ("
                        "id, organization_id, username, display_name, password_hash, "
                        "status, password_changed_at) VALUES ("
                        ":id, :organization_id, :username, :display_name, "
                        "'synthetic-not-a-real-password-hash', 'active', now())"
                    ),
                    {
                        "id": subject_ids[user_key],
                        "organization_id": subject_ids["organization_id"],
                        "username": f"synthetic-{user_key}-{uuid4().hex[:8]}",
                        "display_name": f"Synthetic {user_key}",
                    },
                )
            for role_code in ("system_admin", "finance_reviewer", "audit_reviewer"):
                subject_ids[f"{role_code}_role_id"] = str(
                    connection.execute(
                        text("SELECT id FROM roles WHERE code = :code"),
                        {"code": role_code},
                    ).scalar_one()
                )
            for user_key in ("requester_id", "decider_id"):
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assignment_source, assignment_reason"
                        ") VALUES (:id, :user_id, :role_id, 'bootstrap', 'system_bootstrap')"
                    ),
                    {
                        "id": str(uuid4()),
                        "user_id": subject_ids[user_key],
                        "role_id": subject_ids["system_admin_role_id"],
                    },
                )
    finally:
        engine.dispose()
    return subject_ids


def clear_privileged_auth_subjects(database_url: URL, subject_ids: Mapping[str, str]) -> None:
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE user_roles DISABLE TRIGGER USER"))
            connection.execute(text("ALTER TABLE break_glass_requests DISABLE TRIGGER USER"))
            connection.execute(
                text(
                    "DELETE FROM user_roles WHERE user_id IN ("
                    "SELECT id FROM users WHERE organization_id = :organization_id)"
                ),
                {"organization_id": subject_ids["organization_id"]},
            )
            connection.execute(
                text("DELETE FROM break_glass_requests WHERE organization_id = :id"),
                {"id": subject_ids["organization_id"]},
            )
            connection.execute(text("ALTER TABLE break_glass_requests ENABLE TRIGGER USER"))
            connection.execute(text("ALTER TABLE user_roles ENABLE TRIGGER USER"))
            connection.execute(
                text("DELETE FROM users WHERE organization_id = :id"),
                {"id": subject_ids["organization_id"]},
            )
            connection.execute(
                text("DELETE FROM organizations WHERE id = :id"),
                {"id": subject_ids["organization_id"]},
            )
    finally:
        engine.dispose()


def public_relation_manifest(
    database_url: URL,
    table_names: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    allowed_tables = set(TABLES_AT_008)
    if not set(table_names) <= allowed_tables:
        raise AssertionError("manifest may inspect only current BASE-005 tables")

    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            manifest: dict[str, dict[str, object]] = {}
            for table_name in table_names:
                relation = connection.execute(
                    text(
                        "SELECT table_catalog.relowner::regrole::text AS owner_name, "
                        "COALESCE(table_catalog.relacl::text, '') AS raw_acl "
                        "FROM pg_class AS table_catalog "
                        "JOIN pg_namespace AS schema_catalog "
                        "ON schema_catalog.oid = table_catalog.relnamespace "
                        "WHERE schema_catalog.nspname = 'public' "
                        "AND table_catalog.relname = :table_name "
                        "AND table_catalog.relkind = 'r'"
                    ),
                    {"table_name": table_name},
                ).one_or_none()
                if relation is None:
                    continue
                columns = connection.execute(
                    text(
                        "SELECT column_name, udt_name, is_nullable, "
                        "character_maximum_length, column_default "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = :table_name "
                        "ORDER BY ordinal_position"
                    ),
                    {"table_name": table_name},
                ).all()
                constraints = connection.execute(
                    text(
                        "SELECT constraint_catalog.conname, constraint_catalog.contype, "
                        "constraint_catalog.convalidated, constraint_catalog.condeferrable, "
                        "constraint_catalog.condeferred, "
                        "pg_get_constraintdef(constraint_catalog.oid, true) AS definition "
                        "FROM pg_constraint AS constraint_catalog "
                        "JOIN pg_class AS table_catalog "
                        "ON table_catalog.oid = constraint_catalog.conrelid "
                        "JOIN pg_namespace AS schema_catalog "
                        "ON schema_catalog.oid = table_catalog.relnamespace "
                        "WHERE schema_catalog.nspname = 'public' "
                        "AND table_catalog.relname = :table_name "
                        "AND constraint_catalog.contype <> 't' "
                        "ORDER BY constraint_catalog.conname"
                    ),
                    {"table_name": table_name},
                ).all()
                indexes = connection.execute(
                    text(
                        "SELECT index_catalog.relname, index_state.indisunique, "
                        "index_state.indisprimary, index_state.indisexclusion, "
                        "pg_get_indexdef(index_catalog.oid, 0, true) AS definition, "
                        "pg_get_expr(index_state.indpred, index_state.indrelid, true) "
                        "AS predicate "
                        "FROM pg_index AS index_state "
                        "JOIN pg_class AS index_catalog "
                        "ON index_catalog.oid = index_state.indexrelid "
                        "JOIN pg_class AS table_catalog "
                        "ON table_catalog.oid = index_state.indrelid "
                        "JOIN pg_namespace AS schema_catalog "
                        "ON schema_catalog.oid = table_catalog.relnamespace "
                        "WHERE schema_catalog.nspname = 'public' "
                        "AND table_catalog.relname = :table_name "
                        "ORDER BY index_catalog.relname"
                    ),
                    {"table_name": table_name},
                ).all()
                triggers = connection.execute(
                    text(
                        "SELECT trigger_catalog.tgname, trigger_catalog.tgtype, "
                        "trigger_catalog.tgdeferrable, trigger_catalog.tginitdeferred, "
                        "trigger_catalog.tgenabled, function_catalog.proname, "
                        "pg_get_triggerdef(trigger_catalog.oid, true) AS definition "
                        "FROM pg_trigger AS trigger_catalog "
                        "JOIN pg_class AS table_catalog "
                        "ON table_catalog.oid = trigger_catalog.tgrelid "
                        "JOIN pg_namespace AS schema_catalog "
                        "ON schema_catalog.oid = table_catalog.relnamespace "
                        "JOIN pg_proc AS function_catalog "
                        "ON function_catalog.oid = trigger_catalog.tgfoid "
                        "WHERE schema_catalog.nspname = 'public' "
                        "AND table_catalog.relname = :table_name "
                        "AND NOT trigger_catalog.tgisinternal "
                        "ORDER BY trigger_catalog.tgname"
                    ),
                    {"table_name": table_name},
                ).all()
                acl = connection.execute(
                    text(
                        "SELECT expanded_acl.grantor, expanded_acl.grantee, "
                        "expanded_acl.privilege_type, expanded_acl.is_grantable "
                        "FROM pg_class AS table_catalog "
                        "JOIN pg_namespace AS schema_catalog "
                        "ON schema_catalog.oid = table_catalog.relnamespace, "
                        "LATERAL aclexplode(COALESCE(table_catalog.relacl, "
                        "acldefault('r', table_catalog.relowner))) AS expanded_acl "
                        "WHERE schema_catalog.nspname = 'public' "
                        "AND table_catalog.relname = :table_name "
                        "ORDER BY expanded_acl.grantee, expanded_acl.privilege_type"
                    ),
                    {"table_name": table_name},
                ).all()
                rows = connection.execute(
                    text(
                        f"SELECT to_jsonb(row_value)::text FROM public.{table_name} "
                        "AS row_value ORDER BY row_value.id"
                    )
                ).scalars()
                manifest[table_name] = {
                    "columns": tuple(tuple(row) for row in columns),
                    "constraints": tuple(tuple(row) for row in constraints),
                    "indexes": tuple(tuple(row) for row in indexes),
                    "owner": str(relation.owner_name),
                    "raw_acl": str(relation.raw_acl),
                    "acl": tuple(tuple(row) for row in acl),
                    "triggers": tuple(tuple(row) for row in triggers),
                    "data": tuple(str(row) for row in rows),
                }
            return manifest
    finally:
        engine.dispose()


def privileged_auth_function_manifest(database_url: URL) -> tuple[tuple[object, ...], ...]:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT function_catalog.proname, function_catalog.pronargs, "
                    "function_catalog.prorettype::regtype::text, language_catalog.lanname, "
                    "function_catalog.prosecdef, function_catalog.provolatile, "
                    "function_catalog.proparallel, function_catalog.prokind, "
                    "function_catalog.proconfig, "
                    "function_catalog.proowner::regrole::text AS owner_name, "
                    "COALESCE(function_catalog.proacl::text, '') AS raw_acl, "
                    "pg_get_functiondef(function_catalog.oid) AS definition "
                    "FROM pg_proc AS function_catalog "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = function_catalog.pronamespace "
                    "JOIN pg_language AS language_catalog "
                    "ON language_catalog.oid = function_catalog.prolang "
                    "WHERE schema_catalog.nspname = 'public' "
                    "AND function_catalog.proname = ANY(CAST(:names AS text[])) "
                    "ORDER BY function_catalog.proname"
                ),
                {"names": sorted(PRIVILEGED_AUTH_FUNCTIONS)},
            ).all()
            return tuple(tuple(row) for row in rows)
    finally:
        engine.dispose()


def insert_pending_break_glass_request(
    connection: Connection,
    subject_ids: Mapping[str, str],
    *,
    target_role_code: str = "finance_reviewer",
    duration_seconds: int = 3600,
) -> str:
    request_id = str(uuid4())
    connection.execute(
        text(
            "INSERT INTO break_glass_requests ("
            "id, organization_id, target_user_id, target_role_code, requested_by, "
            "reason, requested_duration_seconds, status, created_at, updated_at, trace_id"
            ") VALUES ("
            ":id, :organization_id, :target_user_id, :target_role_code, :requested_by, "
            "'synthetic privileged access', :duration_seconds, 'pending', "
            "'2000-01-01 UTC', '2000-01-02 UTC', :trace_id)"
        ),
        {
            "id": request_id,
            "organization_id": subject_ids["organization_id"],
            "target_user_id": subject_ids["target_id"],
            "target_role_code": target_role_code,
            "requested_by": subject_ids["requester_id"],
            "duration_seconds": duration_seconds,
            "trace_id": str(uuid4()),
        },
    )
    return request_id


def approve_break_glass_request_with_role(
    connection: Connection,
    subject_ids: Mapping[str, str],
    request_id: str,
    *,
    target_role_code: str = "finance_reviewer",
    decision_reason: str = "synthetic approval",
) -> tuple[str, datetime, datetime]:
    approved = connection.execute(
        text(
            "UPDATE break_glass_requests SET status = 'approved', "
            "decided_by = :decided_by, decision_reason = :decision_reason, "
            "decision_at = '2000-01-01 UTC', effective_from = '2000-01-01 UTC', "
            "expires_at = '2000-01-02 UTC', updated_at = '2000-01-01 UTC', "
            "row_version = row_version + 1 WHERE id = :id "
            "RETURNING effective_from, expires_at"
        ),
        {
            "decided_by": subject_ids["decider_id"],
            "decision_reason": decision_reason,
            "id": request_id,
        },
    ).one()
    role_id = connection.execute(
        text("SELECT id FROM roles WHERE code = :code"),
        {"code": target_role_code},
    ).scalar_one()
    assignment_id = str(uuid4())
    connection.execute(
        text(
            "INSERT INTO user_roles ("
            "id, user_id, role_id, assigned_by, assignment_source, assigned_at, "
            "expires_at, break_glass_request_id, assignment_reason"
            ") VALUES ("
            ":id, :user_id, :role_id, :assigned_by, 'break_glass', :assigned_at, "
            ":expires_at, :request_id, :assignment_reason)"
        ),
        {
            "id": assignment_id,
            "user_id": subject_ids["target_id"],
            "role_id": role_id,
            "assigned_by": subject_ids["decider_id"],
            "assigned_at": approved.effective_from,
            "expires_at": approved.expires_at,
            "request_id": request_id,
            "assignment_reason": decision_reason,
        },
    )
    return assignment_id, approved.effective_from, approved.expires_at


@pytest.mark.parametrize(
    "role_drift",
    ("missing", "extra", "system_false", "duplicate_with_missing"),
)
def test_privileged_auth_role_preflight_rejects_every_drift_before_ddl(
    monkeypatch: pytest.MonkeyPatch,
    role_drift: str,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_privileged_auth_revision(database_url, alembic_config)
    command.downgrade(alembic_config, RELIABILITY_REVISION)
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            if role_drift == "missing":
                connection.execute(text("DELETE FROM roles WHERE code = 'read_only'"))
            elif role_drift == "extra":
                connection.execute(text("ALTER TABLE roles DROP CONSTRAINT ck_roles_code_allowed"))
                connection.execute(
                    text(
                        "INSERT INTO roles (code, name, is_system_role, is_enabled) "
                        "VALUES ('unexpected_role', 'synthetic unexpected role', TRUE, TRUE)"
                    )
                )
            elif role_drift == "system_false":
                connection.execute(
                    text("UPDATE roles SET is_system_role = FALSE WHERE code = 'read_only'")
                )
            else:
                connection.execute(text("DELETE FROM roles WHERE code = 'read_only'"))
                connection.execute(text("ALTER TABLE roles DROP CONSTRAINT uq_roles_code"))
                connection.execute(
                    text(
                        "INSERT INTO roles (code, name, is_system_role, is_enabled) "
                        "VALUES ('system_admin', 'synthetic duplicate role', TRUE, TRUE)"
                    )
                )

        drifted_roles_manifest = public_relation_manifest(database_url, ("roles",))
        with pytest.raises(DBAPIError) as error_info:
            command.upgrade(alembic_config, PRIVILEGED_AUTH_REVISION)
        assert safe_database_error_signature(error_info.value)[0] == "55000"
        assert current_revision(database_url) == RELIABILITY_REVISION
        assert installed_baseline_tables(database_url) == TABLES_AT_007
        assert user_trigger_names(database_url, "users") == set()
        assert user_trigger_names(database_url, "roles") == set()
        with engine.connect() as connection:
            function_count = connection.execute(
                text(
                    "SELECT count(*) FROM pg_proc AS function_catalog "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = function_catalog.pronamespace "
                    "WHERE schema_catalog.nspname = current_schema() "
                    "AND function_catalog.proname = ANY(CAST(:names AS text[]))"
                ),
                {"names": sorted(PRIVILEGED_AUTH_FUNCTIONS)},
            ).scalar_one()
            assert function_count == 0
        assert public_relation_manifest(database_url, ("roles",)) == drifted_roles_manifest
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, PRIVILEGED_AUTH_REVISION)


def test_privileged_auth_postgresql_catalog_is_exact_and_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_privileged_auth_revision(database_url, alembic_config)
    command.downgrade(alembic_config, RELIABILITY_REVISION)
    baseline_organization_id = str(uuid4())
    baseline_user_id = str(uuid4())
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            tax_identity = f"SYNTH-CATALOG-{uuid4().hex[:16]}"
            username = f"synthetic-catalog-{uuid4().hex[:10]}"
            connection.execute(
                text(
                    "INSERT INTO organizations ("
                    "id, name, unified_social_credit_code, tax_number, status) VALUES ("
                    ":id, 'synthetic catalog preservation', :tax_identity, "
                    ":tax_identity, 'active')"
                ),
                {"id": baseline_organization_id, "tax_identity": tax_identity},
            )
            connection.execute(
                text(
                    "INSERT INTO users ("
                    "id, organization_id, username, display_name, password_hash, status, "
                    "password_changed_at) VALUES ("
                    ":id, :organization_id, :username, :display_name, "
                    "'synthetic-not-a-real-password-hash', 'active', now())"
                ),
                {
                    "id": baseline_user_id,
                    "organization_id": baseline_organization_id,
                    "username": username,
                    "display_name": username,
                },
            )
    finally:
        engine.dispose()
    existing_tables_at_007 = tuple(sorted(TABLES_AT_007))
    pre_existing_manifest = public_relation_manifest(database_url, existing_tables_at_007)
    assert len(cast(tuple[str, ...], pre_existing_manifest["users"]["data"])) == 1
    assert len(cast(tuple[str, ...], pre_existing_manifest["roles"]["data"])) == 5
    assert pre_existing_manifest["users"]["triggers"] == ()
    assert pre_existing_manifest["roles"]["triggers"] == ()
    assert public_relation_manifest(database_url, PRIVILEGED_AUTH_TABLES) == {}
    assert privileged_auth_function_manifest(database_url) == ()
    command.upgrade(alembic_config, PRIVILEGED_AUTH_REVISION)

    assert current_revision(database_url) == PRIVILEGED_AUTH_REVISION
    assert installed_baseline_tables(database_url) == TABLES_AT_008
    assert seeded_role_codes(database_url) == EXPECTED_ROLE_CODES
    assert all(table_row_count(database_url, name) == 0 for name in PRIVILEGED_AUTH_TABLES)

    expected_columns = {
        "break_glass_requests": (
            ("id", "uuid", "NO", None, "gen_random_uuid()"),
            ("organization_id", "uuid", "NO", None, None),
            ("target_user_id", "uuid", "NO", None, None),
            ("target_role_code", "varchar", "NO", 40, None),
            ("requested_by", "uuid", "NO", None, None),
            ("reason", "text", "NO", None, None),
            ("requested_duration_seconds", "int4", "NO", None, None),
            ("status", "varchar", "NO", 20, None),
            ("effective_from", "timestamptz", "YES", None, None),
            ("expires_at", "timestamptz", "YES", None, None),
            ("decided_by", "uuid", "YES", None, None),
            ("decision_at", "timestamptz", "YES", None, None),
            ("decision_reason", "text", "YES", None, None),
            ("revoked_by", "uuid", "YES", None, None),
            ("revoked_at", "timestamptz", "YES", None, None),
            ("revoke_reason", "text", "YES", None, None),
            ("row_version", "int4", "NO", None, "1"),
            ("created_at", "timestamptz", "NO", None, None),
            ("updated_at", "timestamptz", "NO", None, None),
            ("trace_id", "uuid", "NO", None, None),
        ),
        "user_roles": (
            ("id", "uuid", "NO", None, "gen_random_uuid()"),
            ("user_id", "uuid", "NO", None, None),
            ("role_id", "uuid", "NO", None, None),
            ("assigned_by", "uuid", "YES", None, None),
            ("assignment_source", "varchar", "NO", 20, None),
            ("assigned_at", "timestamptz", "NO", None, "now()"),
            ("expires_at", "timestamptz", "YES", None, None),
            ("break_glass_request_id", "uuid", "YES", None, None),
            ("assignment_reason", "text", "NO", None, None),
            ("revoked_at", "timestamptz", "YES", None, None),
            ("revoked_by", "uuid", "YES", None, None),
            ("revoke_reason", "text", "YES", None, None),
        ),
    }
    expected_constraints = {
        "break_glass_requests": {
            "ck_break_glass_requests_decision_reason_nonempty",
            "ck_break_glass_requests_reason_nonempty",
            "ck_break_glass_requests_requested_duration_bounds",
            "ck_break_glass_requests_revoke_reason_nonempty",
            "ck_break_glass_requests_row_version_positive",
            "ck_break_glass_requests_state_field_matrix",
            "ck_break_glass_requests_status_allowed",
            "ck_break_glass_requests_target_role_code_allowed",
            "ck_break_glass_requests_time_matrix",
            "fk_break_glass_requests_decided_by_users",
            "fk_break_glass_requests_organization_id_organizations",
            "fk_break_glass_requests_requested_by_users",
            "fk_break_glass_requests_revoked_by_users",
            "fk_break_glass_requests_target_user_id_users",
            "pk_break_glass_requests",
        },
        "user_roles": {
            "ck_user_roles_assignment_reason_nonempty",
            "ck_user_roles_assignment_source_allowed",
            "ck_user_roles_assignment_source_matrix",
            "ck_user_roles_revocation_matrix",
            "ck_user_roles_time_order",
            "ex_user_roles_effective_range_no_overlap",
            "fk_user_roles_assigned_by_users",
            "fk_user_roles_break_glass_request_id_break_glass_requests",
            "fk_user_roles_revoked_by_users",
            "fk_user_roles_role_id_roles",
            "fk_user_roles_user_id_users",
            "pk_user_roles",
            "uq_user_roles_break_glass_request_id",
        },
    }
    expected_constraint_contract = {
        table_name: {
            name: (
                "c"
                if name.startswith("ck_")
                else "f"
                if name.startswith("fk_")
                else "p"
                if name.startswith("pk_")
                else "u"
                if name.startswith("uq_")
                else "x",
                True,
                False,
                False,
            )
            for name in names
        }
        for table_name, names in expected_constraints.items()
    }
    exact_noncheck_definitions = {
        "fk_break_glass_requests_decided_by_users": (
            "FOREIGN KEY (decided_by) REFERENCES users(id)"
        ),
        "fk_break_glass_requests_organization_id_organizations": (
            "FOREIGN KEY (organization_id) REFERENCES organizations(id)"
        ),
        "fk_break_glass_requests_requested_by_users": (
            "FOREIGN KEY (requested_by) REFERENCES users(id)"
        ),
        "fk_break_glass_requests_revoked_by_users": (
            "FOREIGN KEY (revoked_by) REFERENCES users(id)"
        ),
        "fk_break_glass_requests_target_user_id_users": (
            "FOREIGN KEY (target_user_id) REFERENCES users(id)"
        ),
        "pk_break_glass_requests": "PRIMARY KEY (id)",
        "fk_user_roles_assigned_by_users": "FOREIGN KEY (assigned_by) REFERENCES users(id)",
        "fk_user_roles_break_glass_request_id_break_glass_requests": (
            "FOREIGN KEY (break_glass_request_id) REFERENCES break_glass_requests(id)"
        ),
        "fk_user_roles_revoked_by_users": "FOREIGN KEY (revoked_by) REFERENCES users(id)",
        "fk_user_roles_role_id_roles": "FOREIGN KEY (role_id) REFERENCES roles(id)",
        "fk_user_roles_user_id_users": "FOREIGN KEY (user_id) REFERENCES users(id)",
        "pk_user_roles": "PRIMARY KEY (id)",
        "uq_user_roles_break_glass_request_id": "UNIQUE (break_glass_request_id)",
    }
    required_check_semantics = {
        "ck_break_glass_requests_target_role_code_allowed": (
            "system_admin",
            "finance_reviewer",
            "audit_reviewer",
            "contract_admin",
        ),
        "ck_break_glass_requests_requested_duration_bounds": ("1", "14400"),
        "ck_break_glass_requests_status_allowed": (
            "pending",
            "approved",
            "rejected",
            "revoked",
            "expired",
        ),
        "ck_break_glass_requests_reason_nonempty": ("length(btrim(reason)) > 0",),
        "ck_break_glass_requests_decision_reason_nonempty": (
            "decision_reason IS NULL",
            "length(btrim(decision_reason)) > 0",
        ),
        "ck_break_glass_requests_revoke_reason_nonempty": (
            "revoke_reason IS NULL",
            "length(btrim(revoke_reason)) > 0",
        ),
        "ck_break_glass_requests_row_version_positive": ("row_version > 0",),
        "ck_break_glass_requests_state_field_matrix": (
            "status::text = 'pending'::text",
            "status::text = 'approved'::text",
            "status::text = 'rejected'::text",
            "status::text = 'revoked'::text",
            "status::text = 'expired'::text",
            "decided_by IS NOT NULL",
            "revoked_by IS NOT NULL",
        ),
        "ck_break_glass_requests_time_matrix": (
            "created_at <= updated_at",
            "created_at <= decision_at",
            "decision_at = effective_from",
            "effective_from < expires_at",
            "requested_duration_seconds::double precision * '00:00:01'::interval",
            "effective_from <= revoked_at",
            "revoked_at < expires_at",
            "updated_at >= expires_at",
        ),
        "ck_user_roles_assignment_source_allowed": ("bootstrap", "user", "break_glass"),
        "ck_user_roles_assignment_source_matrix": (
            "assignment_source::text = 'bootstrap'::text",
            "assignment_source::text = 'user'::text",
            "assignment_source::text = 'break_glass'::text",
            "system_bootstrap",
            "break_glass_request_id IS NOT NULL",
        ),
        "ck_user_roles_assignment_reason_nonempty": (
            "length(btrim(assignment_reason)) > 0",
            "assignment_reason = btrim(assignment_reason)",
        ),
        "ck_user_roles_revocation_matrix": (
            "revoked_at IS NULL",
            "revoked_by IS NULL",
            "revoke_reason IS NULL",
            "length(btrim(revoke_reason)) > 0",
            "revoke_reason = btrim(revoke_reason)",
        ),
        "ck_user_roles_time_order": (
            "assigned_at < expires_at",
            "revoked_at >= assigned_at",
        ),
    }
    expected_index_flags = {
        "break_glass_requests": {"pk_break_glass_requests": (True, True, False)},
        "user_roles": {
            "ex_user_roles_effective_range_no_overlap": (False, False, True),
            "pk_user_roles": (True, True, False),
            "uq_user_roles_break_glass_request_id": (True, False, False),
        },
    }
    expected_definition_sha256 = {
        "break_glass_requests": {
            "constraints": {
                "ck_break_glass_requests_decision_reason_nonempty": (
                    "8a29a9d8ea3969558479f7d51630ff6bca1bb961efba1ebee26d289e1e568982"
                ),
                "ck_break_glass_requests_reason_nonempty": (
                    "3a69ae4f5bca8565e1a7b2ed07cacdff350f3a8ab798fe7544c56762e164737d"
                ),
                "ck_break_glass_requests_requested_duration_bounds": (
                    "ba20eda9455912a0ade87c01f501ab0848bd241cd138e79f989e5a17c2c3ef05"
                ),
                "ck_break_glass_requests_revoke_reason_nonempty": (
                    "bad394fec6163e853c6b7f5919a1fc98cbe431f6bb259598253dc5826a28375a"
                ),
                "ck_break_glass_requests_row_version_positive": (
                    "90fcf2bf597c0c1ce3a5ef4068948742aa55b9c07df58817cf0c03637aa4ec13"
                ),
                "ck_break_glass_requests_state_field_matrix": (
                    "d9a63c35354fbdc538c177f8dd8dc1f789cb0f3a91fa1e5db038ab458344e392"
                ),
                "ck_break_glass_requests_status_allowed": (
                    "814b2f67ddb4b68262e4366462ac341f9b3f187d36ba55b882860d16231f515c"
                ),
                "ck_break_glass_requests_target_role_code_allowed": (
                    "d21d8b502af28f739abf709d4bf8be0512c5baec0529ed8cf88f8e7e0bc7633d"
                ),
                "ck_break_glass_requests_time_matrix": (
                    "0625bacf455999a0db4def67a30459768a692d2fe1310aa610ad355dd3b2830e"
                ),
                "fk_break_glass_requests_decided_by_users": (
                    "3ff4ca05483a4ef43a40c33a21b35f0b371c504128ded24ccbc94157c5dd60bd"
                ),
                "fk_break_glass_requests_organization_id_organizations": (
                    "5b2390f259fc1c18f325c4574022cde7c814a851c072d7bef06bb9b6ece80a9a"
                ),
                "fk_break_glass_requests_requested_by_users": (
                    "daabbf298bee70e7f95bbc36167ccb82ae9fcaaa73c87f75f771dc543667ac53"
                ),
                "fk_break_glass_requests_revoked_by_users": (
                    "2aaad62282c925a86e824c1d463f6a88569ba5e8420d4f428123f457753e875c"
                ),
                "fk_break_glass_requests_target_user_id_users": (
                    "f4a3b65c26fa5284717bb76a0e22abc6776f34d8b58136b2a5f2ec7f69c1c681"
                ),
                "pk_break_glass_requests": (
                    "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5"
                ),
            },
            "indexes": {
                "pk_break_glass_requests": (
                    "692de5ba8c6d799fd81d45421cfa37fd2fc65f74623c0a9b4d892749febf6285"
                ),
            },
        },
        "user_roles": {
            "constraints": {
                "ck_user_roles_assignment_reason_nonempty": (
                    "7a99ab2ee1a44f324fcdf18592d2ce5f7258d0887c933288e842e513b718fc8a"
                ),
                "ck_user_roles_assignment_source_allowed": (
                    "54f9e031e6e8ad8adce067f4494238e618eb1eac054b162221ee29c0525c36f7"
                ),
                "ck_user_roles_assignment_source_matrix": (
                    "19a88e38bec781fca52d1c01b0332da12bf7f1841497ed749bde995ed195cc03"
                ),
                "ck_user_roles_revocation_matrix": (
                    "6d7b516415b3cd1421ce2821ea1ffca23954f9ce3916de8c82a2982dfae1485b"
                ),
                "ck_user_roles_time_order": (
                    "ff605714fc0926290ad1d700a8eca0426923f4375d37dde9658ac8ba6b2670fa"
                ),
                "ex_user_roles_effective_range_no_overlap": (
                    "4d5f576f5ccba150fc1547f26afb8fe0b3fd43e010c6730ead173c10f1403e7a"
                ),
                "fk_user_roles_assigned_by_users": (
                    "7eefe2659fce1e773000090bf61f00e274cec07240dadebd87094c0b39b14d72"
                ),
                "fk_user_roles_break_glass_request_id_break_glass_requests": (
                    "ac5de70029176a03a67595d69f9dae7a6cc82d0a7a15e9b2458bdf2e09199132"
                ),
                "fk_user_roles_revoked_by_users": (
                    "2aaad62282c925a86e824c1d463f6a88569ba5e8420d4f428123f457753e875c"
                ),
                "fk_user_roles_role_id_roles": (
                    "0f4a7665ce96059315515eb1fbbc839e934118a143b05bfe6d9f59fd1b390c0e"
                ),
                "fk_user_roles_user_id_users": (
                    "35bba6df01802e7850bd1a753b95ff643a2a01ec56aa476981cbe9dc42705cf3"
                ),
                "pk_user_roles": (
                    "8c8464f42472e42ee190fc91ca8db79b5351d3a4609040516578d229c56f6fa5"
                ),
                "uq_user_roles_break_glass_request_id": (
                    "c8071ed072e04b5617d1b2f3e5e32865d9188fb449a3f4f4ed572ab968e1b01d"
                ),
            },
            "indexes": {
                "ex_user_roles_effective_range_no_overlap": (
                    "40aa36157bf2d02615eb2cf88b0d832bc4a8bef20a700bb027b6490003f365b8"
                ),
                "pk_user_roles": (
                    "d8141bc6d50e6d24a1ee8c46fc490da283f2db1b75b6cf1d8f8c1a8b7a76467e"
                ),
                "uq_user_roles_break_glass_request_id": (
                    "5f14a03781a41d716f53622c39d38a5ed7b0a029222bf271abc79c5730025da3"
                ),
            },
        },
    }
    expected_function_source_sha256 = {
        "enforce_break_glass_requests_state_v1": (
            "a82948d8499918e4085aed542e7e0f7af50f92685d18834ac24d9e4fe27412d3"
        ),
        "enforce_user_roles_state_v1": (
            "9b136e5f76d10e6a083bcb4b0272f76fc728eab941da7c480f1c4d6b701b5739"
        ),
        "enforce_break_glass_role_consistency_v1": (
            "81c89c4418a233f21b5e1d0a06e9c55b26e9a9c54037dcb1438062cca8dab7ba"
        ),
        "enforce_long_term_role_separation_v1": (
            "ed2aba7852b1d5f6d33e2043b8f8072409172e870fbd8ddfdd208ac0495b2ffc"
        ),
        "enforce_roles_invariants_v1": (
            "fdf2f7feb3f3ffae7b6fdf29748d4436ba7fc47790cd1f87a36091b7fd722ec4"
        ),
    }

    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            for table_name, expected in expected_columns.items():
                rows = connection.execute(
                    text(
                        "SELECT column_name, udt_name, is_nullable, "
                        "character_maximum_length, column_default "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = :table_name "
                        "ORDER BY ordinal_position"
                    ),
                    {"table_name": table_name},
                )
                assert tuple(tuple(row) for row in rows) == expected
                constraint_rows = connection.execute(
                    text(
                        "SELECT constraint_catalog.conname, constraint_catalog.contype, "
                        "constraint_catalog.convalidated, constraint_catalog.condeferrable, "
                        "constraint_catalog.condeferred, "
                        "pg_get_constraintdef(constraint_catalog.oid, true) AS definition "
                        "FROM pg_constraint AS constraint_catalog "
                        "JOIN pg_class AS table_catalog "
                        "ON table_catalog.oid = constraint_catalog.conrelid "
                        "JOIN pg_namespace AS schema_catalog "
                        "ON schema_catalog.oid = table_catalog.relnamespace "
                        "WHERE schema_catalog.nspname = 'public' "
                        "AND table_catalog.relname = :table_name "
                        "AND constraint_catalog.contype <> 't'"
                    ),
                    {"table_name": table_name},
                ).all()
                assert {str(row.conname) for row in constraint_rows} == expected_constraints[
                    table_name
                ]
                observed_constraint_contract = {
                    str(row.conname): (
                        str(row.contype),
                        bool(row.convalidated),
                        bool(row.condeferrable),
                        bool(row.condeferred),
                    )
                    for row in constraint_rows
                }
                assert observed_constraint_contract == expected_constraint_contract[table_name]
                constraint_definitions = {
                    str(row.conname): str(row.definition) for row in constraint_rows
                }
                assert {
                    name: sha256(definition.encode()).hexdigest()
                    for name, definition in constraint_definitions.items()
                } == expected_definition_sha256[table_name]["constraints"]
                for constraint_name, expected_definition in exact_noncheck_definitions.items():
                    if constraint_name in constraint_definitions:
                        assert constraint_definitions[constraint_name] == expected_definition
                for constraint_name, required_fragments in required_check_semantics.items():
                    if constraint_name in constraint_definitions:
                        missing_fragments = tuple(
                            fragment
                            for fragment in required_fragments
                            if fragment not in constraint_definitions[constraint_name]
                        )
                        assert not missing_fragments, (
                            constraint_name,
                            missing_fragments,
                            constraint_definitions[constraint_name],
                        )
                assert all(
                    "ON UPDATE" not in row.definition and "ON DELETE" not in row.definition
                    for row in constraint_rows
                    if row.contype == "f"
                )
                if table_name == "user_roles":
                    exclusion = next(row for row in constraint_rows if row.contype == "x")
                    assert exclusion.condeferrable is False
                    assert exclusion.condeferred is False
                    assert "EXCLUDE USING gist" in exclusion.definition
                    assert "'[)'::text" in exclusion.definition
                    assert "WHERE (revoked_at IS NULL)" in exclusion.definition
                index_rows = connection.execute(
                    text(
                        "SELECT index_catalog.relname, index_state.indisunique, "
                        "index_state.indisprimary, index_state.indisexclusion, "
                        "pg_get_indexdef(index_catalog.oid, 0, true) AS definition "
                        "FROM pg_index AS index_state "
                        "JOIN pg_class AS index_catalog "
                        "ON index_catalog.oid = index_state.indexrelid "
                        "JOIN pg_class AS table_catalog "
                        "ON table_catalog.oid = index_state.indrelid "
                        "JOIN pg_namespace AS schema_catalog "
                        "ON schema_catalog.oid = table_catalog.relnamespace "
                        "WHERE schema_catalog.nspname = 'public' "
                        "AND table_catalog.relname = :table_name"
                    ),
                    {"table_name": table_name},
                ).all()
                assert {
                    str(row.relname): (
                        bool(row.indisunique),
                        bool(row.indisprimary),
                        bool(row.indisexclusion),
                    )
                    for row in index_rows
                } == expected_index_flags[table_name]
                assert {
                    str(row.relname): sha256(str(row.definition).encode()).hexdigest()
                    for row in index_rows
                } == expected_definition_sha256[table_name]["indexes"]
                for row in index_rows:
                    definition = str(row.definition)
                    assert f"{row.relname} ON {table_name} USING " in definition
                    if row.relname == "ex_user_roles_effective_range_no_overlap":
                        assert "USING gist" in definition
                        assert "tstzrange(assigned_at" in definition
                        assert "'[)'::text" in definition
                        assert "WHERE revoked_at IS NULL" in definition
                    else:
                        assert "USING btree" in definition

            function_rows = connection.execute(
                text(
                    "SELECT function_catalog.proname, function_catalog.pronargs, "
                    "function_catalog.prorettype::regtype::text AS return_type, "
                    "language_catalog.lanname, function_catalog.prosecdef, "
                    "function_catalog.provolatile, function_catalog.proparallel, "
                    "function_catalog.prokind, function_catalog.proconfig, "
                    "function_catalog.proowner::regrole::text AS owner_name, "
                    "function_catalog.prosrc AS source, "
                    "pg_get_functiondef(function_catalog.oid) AS definition, NOT EXISTS ("
                    "SELECT 1 FROM aclexplode(COALESCE(function_catalog.proacl, "
                    "acldefault('f', function_catalog.proowner))) AS function_acl "
                    "WHERE function_acl.grantee = 0 "
                    "AND function_acl.privilege_type = 'EXECUTE'"
                    ") AS public_execute_revoked, NOT EXISTS ("
                    "SELECT 1 FROM aclexplode(COALESCE(function_catalog.proacl, "
                    "acldefault('f', function_catalog.proowner))) AS function_acl "
                    "WHERE function_acl.grantee <> 0 "
                    "AND function_acl.grantee <> function_catalog.proowner"
                    ") AS named_grants_absent, EXISTS ("
                    "SELECT 1 FROM aclexplode(COALESCE(function_catalog.proacl, "
                    "acldefault('f', function_catalog.proowner))) AS function_acl "
                    "WHERE function_acl.grantee = function_catalog.proowner "
                    "AND function_acl.privilege_type = 'EXECUTE' "
                    "AND NOT function_acl.is_grantable"
                    ") AS owner_execute_present "
                    "FROM pg_proc AS function_catalog "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = function_catalog.pronamespace "
                    "JOIN pg_language AS language_catalog "
                    "ON language_catalog.oid = function_catalog.prolang "
                    "WHERE schema_catalog.nspname = 'public' "
                    "AND function_catalog.proname = ANY(CAST(:names AS text[]))"
                ),
                {"names": sorted(PRIVILEGED_AUTH_FUNCTIONS)},
            ).all()
            assert {str(row.proname) for row in function_rows} == PRIVILEGED_AUTH_FUNCTIONS
            current_owner = str(connection.execute(text("SELECT current_user")).scalar_one())
            current_owner_oid = int(
                connection.execute(
                    text("SELECT oid FROM pg_roles WHERE rolname = current_user")
                ).scalar_one()
            )
            for row in function_rows:
                assert (
                    row.pronargs,
                    row.return_type,
                    row.lanname,
                    row.prosecdef,
                    row.provolatile,
                    row.proparallel,
                    row.prokind,
                    tuple(row.proconfig),
                ) == (
                    0,
                    "trigger",
                    "plpgsql",
                    False,
                    "v",
                    "u",
                    "f",
                    ("search_path=pg_catalog, pg_temp",),
                )
                assert row.owner_name == current_owner
                assert row.public_execute_revoked is True
                assert row.named_grants_absent is True
                assert row.owner_execute_present is True
                assert "SECURITY DEFINER" not in row.definition
                assert "EXECUTE " not in row.definition
                function_source = str(row.source)
                assert (
                    sha256(function_source.encode()).hexdigest()
                    == (expected_function_source_sha256[str(row.proname)])
                )
                source_without_literals = re.sub(
                    r"'(?:''|[^'])*'",
                    "''",
                    function_source,
                    flags=re.DOTALL,
                )
                assert (
                    re.search(
                        r"\b(?:INSERT|UPDATE|DELETE|TRUNCATE|CREATE|ALTER|DROP|GRANT|REVOKE|"
                        r"COPY|CALL|DO|LISTEN|NOTIFY|MERGE|VACUUM|ANALYZE)\b",
                        source_without_literals,
                        flags=re.IGNORECASE,
                    )
                    is None
                )
                assert (
                    re.search(
                        r"\b(?:EXECUTE|set_config|dblink|pg_read_file|pg_write_file|"
                        r"pg_advisory_[a-z_]+|lo_[a-z_]+|postgres_fdw|file_fdw)\b",
                        source_without_literals,
                        flags=re.IGNORECASE,
                    )
                    is None
                )
                referenced_relations = set(
                    re.findall(
                        r"(?<!DISTINCT )\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_.]*)",
                        source_without_literals,
                        flags=re.IGNORECASE,
                    )
                )
                assert referenced_relations <= {
                    "public.users",
                    "public.roles",
                    "public.break_glass_requests",
                    "public.user_roles",
                }
                call_like_tokens = set(
                    re.findall(
                        r"\b((?:pg_catalog\.|public\.)?[a-z_][a-z0-9_.]*)\s*\(",
                        function_source.lower(),
                    )
                )
                assert call_like_tokens <= {
                    f"public.{row.proname}",
                    "and",
                    "if",
                    "in",
                    "exists",
                    "or",
                    "pg_catalog.clock_timestamp",
                    "varchar",
                    "where",
                }
            function_acl_rows = connection.execute(
                text(
                    "SELECT function_catalog.proname, function_acl.grantor, "
                    "function_acl.grantee, function_acl.privilege_type, "
                    "function_acl.is_grantable "
                    "FROM pg_proc AS function_catalog "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = function_catalog.pronamespace, "
                    "LATERAL aclexplode(COALESCE(function_catalog.proacl, "
                    "acldefault('f', function_catalog.proowner))) AS function_acl "
                    "WHERE schema_catalog.nspname = 'public' "
                    "AND function_catalog.proname = ANY(CAST(:names AS text[])) "
                    "ORDER BY function_catalog.proname, function_acl.grantee, "
                    "function_acl.privilege_type"
                ),
                {"names": sorted(PRIVILEGED_AUTH_FUNCTIONS)},
            ).all()
            assert tuple(tuple(row) for row in function_acl_rows) == tuple(
                (function_name, current_owner_oid, current_owner_oid, "EXECUTE", False)
                for function_name in sorted(PRIVILEGED_AUTH_FUNCTIONS)
            )

            trigger_rows = connection.execute(
                text(
                    "SELECT table_catalog.relname AS table_name, trigger_catalog.tgname, "
                    "trigger_catalog.tgtype, "
                    "trigger_catalog.tgdeferrable, trigger_catalog.tginitdeferred, "
                    "trigger_catalog.tgenabled, function_catalog.proname AS function_name, "
                    "pg_get_triggerdef(trigger_catalog.oid, true) AS definition "
                    "FROM pg_trigger AS trigger_catalog "
                    "JOIN pg_class AS table_catalog "
                    "ON table_catalog.oid = trigger_catalog.tgrelid "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = table_catalog.relnamespace "
                    "JOIN pg_proc AS function_catalog "
                    "ON function_catalog.oid = trigger_catalog.tgfoid "
                    "WHERE schema_catalog.nspname = 'public' "
                    "AND table_catalog.relname = ANY(CAST(:tables AS text[])) "
                    "AND NOT trigger_catalog.tgisinternal"
                ),
                {"tables": list(PRIVILEGED_AUTH_TRIGGERS)},
            ).all()
            observed_trigger_names = {
                table_name: {
                    str(row.tgname) for row in trigger_rows if row.table_name == table_name
                }
                for table_name in PRIVILEGED_AUTH_TRIGGERS
            }
            assert observed_trigger_names == PRIVILEGED_AUTH_TRIGGERS
            expected_trigger_contract = {
                "trg_break_glass_requests_state_v1": (
                    31,
                    False,
                    False,
                    "enforce_break_glass_requests_state_v1",
                    "CREATE TRIGGER trg_break_glass_requests_state_v1 BEFORE INSERT OR DELETE "
                    "OR UPDATE ON break_glass_requests FOR EACH ROW EXECUTE FUNCTION "
                    "enforce_break_glass_requests_state_v1()",
                ),
                "trg_break_glass_requests_no_truncate_v1": (
                    34,
                    False,
                    False,
                    "enforce_break_glass_requests_state_v1",
                    "CREATE TRIGGER trg_break_glass_requests_no_truncate_v1 BEFORE TRUNCATE "
                    "ON break_glass_requests FOR EACH STATEMENT EXECUTE FUNCTION "
                    "enforce_break_glass_requests_state_v1()",
                ),
                "trg_break_glass_requests_consistency_v1": (
                    29,
                    True,
                    True,
                    "enforce_break_glass_role_consistency_v1",
                    "CREATE CONSTRAINT TRIGGER trg_break_glass_requests_consistency_v1 "
                    "AFTER INSERT OR DELETE OR UPDATE ON break_glass_requests DEFERRABLE "
                    "INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
                    "enforce_break_glass_role_consistency_v1()",
                ),
                "trg_user_roles_state_v1": (
                    31,
                    False,
                    False,
                    "enforce_user_roles_state_v1",
                    "CREATE TRIGGER trg_user_roles_state_v1 BEFORE INSERT OR DELETE OR UPDATE "
                    "ON user_roles FOR EACH ROW EXECUTE FUNCTION enforce_user_roles_state_v1()",
                ),
                "trg_user_roles_no_truncate_v1": (
                    34,
                    False,
                    False,
                    "enforce_user_roles_state_v1",
                    "CREATE TRIGGER trg_user_roles_no_truncate_v1 BEFORE TRUNCATE ON user_roles "
                    "FOR EACH STATEMENT EXECUTE FUNCTION enforce_user_roles_state_v1()",
                ),
                "trg_user_roles_consistency_v1": (
                    29,
                    True,
                    True,
                    "enforce_break_glass_role_consistency_v1",
                    "CREATE CONSTRAINT TRIGGER trg_user_roles_consistency_v1 AFTER INSERT OR "
                    "DELETE OR UPDATE ON user_roles DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                    "EXECUTE FUNCTION enforce_break_glass_role_consistency_v1()",
                ),
                "trg_user_roles_sod_v1": (
                    29,
                    True,
                    True,
                    "enforce_long_term_role_separation_v1",
                    "CREATE CONSTRAINT TRIGGER trg_user_roles_sod_v1 AFTER INSERT OR DELETE OR "
                    "UPDATE ON user_roles DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE "
                    "FUNCTION enforce_long_term_role_separation_v1()",
                ),
                "trg_users_role_sod_v1": (
                    21,
                    True,
                    True,
                    "enforce_long_term_role_separation_v1",
                    "CREATE CONSTRAINT TRIGGER trg_users_role_sod_v1 AFTER INSERT OR UPDATE OF "
                    "organization_id, status, deleted_at ON users DEFERRABLE INITIALLY DEFERRED "
                    "FOR EACH ROW EXECUTE FUNCTION enforce_long_term_role_separation_v1()",
                ),
                "trg_roles_invariants_v1": (
                    31,
                    False,
                    False,
                    "enforce_roles_invariants_v1",
                    "CREATE TRIGGER trg_roles_invariants_v1 BEFORE INSERT OR DELETE OR UPDATE "
                    "ON roles FOR EACH ROW EXECUTE FUNCTION enforce_roles_invariants_v1()",
                ),
                "trg_roles_role_sod_v1": (
                    17,
                    True,
                    True,
                    "enforce_long_term_role_separation_v1",
                    "CREATE CONSTRAINT TRIGGER trg_roles_role_sod_v1 AFTER UPDATE OF is_enabled "
                    "ON roles DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
                    "enforce_long_term_role_separation_v1()",
                ),
            }
            for row in trigger_rows:
                expected_trigger = expected_trigger_contract[str(row.tgname)]
                assert int(row.tgtype) == expected_trigger[0]
                assert bool(row.tgdeferrable) is expected_trigger[1]
                assert bool(row.tginitdeferred) is expected_trigger[2]
                assert row.tgenabled == "O"
                assert row.function_name == expected_trigger[3]
                assert row.definition == expected_trigger[4]

            acl_rows = connection.execute(
                text(
                    "SELECT table_catalog.relname, "
                    "table_catalog.relowner::regrole::text AS owner_name, NOT EXISTS ("
                    "SELECT 1 FROM aclexplode(COALESCE(table_catalog.relacl, "
                    "acldefault('r', table_catalog.relowner))) AS table_acl "
                    "WHERE table_acl.grantee = 0"
                    ") AS public_privileges_revoked, NOT EXISTS ("
                    "SELECT 1 FROM aclexplode(COALESCE(table_catalog.relacl, "
                    "acldefault('r', table_catalog.relowner))) AS table_acl "
                    "WHERE table_acl.grantee <> 0 "
                    "AND table_acl.grantee <> table_catalog.relowner"
                    ") AS named_grants_absent "
                    "FROM pg_class AS table_catalog "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = table_catalog.relnamespace "
                    "WHERE schema_catalog.nspname = 'public' "
                    "AND table_catalog.relname = ANY(CAST(:tables AS text[]))"
                ),
                {"tables": list(PRIVILEGED_AUTH_TABLES)},
            ).all()
            assert {str(row.relname) for row in acl_rows} == set(PRIVILEGED_AUTH_TABLES)
            assert all(row.public_privileges_revoked is True for row in acl_rows)
            assert all(row.named_grants_absent is True for row in acl_rows)
            assert all(row.owner_name == current_owner for row in acl_rows)
    finally:
        engine.dispose()

    assert {
        table_name: user_trigger_names(database_url, table_name)
        for table_name in PRIVILEGED_AUTH_TRIGGERS
    } == PRIVILEGED_AUTH_TRIGGERS

    post_existing_manifest = public_relation_manifest(database_url, existing_tables_at_007)
    post_privileged_manifest = public_relation_manifest(database_url, PRIVILEGED_AUTH_TABLES)
    post_function_manifest = privileged_auth_function_manifest(database_url)
    expected_owner_table_privileges = (
        ("DELETE", False),
        ("INSERT", False),
        ("REFERENCES", False),
        ("SELECT", False),
        ("TRIGGER", False),
        ("TRUNCATE", False),
        ("UPDATE", False),
    )
    for table_name in PRIVILEGED_AUTH_TABLES:
        expanded_acl = cast(
            tuple[tuple[object, ...], ...],
            post_privileged_manifest[table_name]["acl"],
        )
        assert len({(int(row[0]), int(row[1])) for row in expanded_acl}) == 1
        assert all(int(row[0]) == int(row[1]) != 0 for row in expanded_acl)
        assert tuple((str(row[2]), bool(row[3])) for row in expanded_acl) == (
            expected_owner_table_privileges
        )
    for table_name in existing_tables_at_007:
        if table_name in {"users", "roles"}:
            assert {
                key: value
                for key, value in post_existing_manifest[table_name].items()
                if key != "triggers"
            } == {
                key: value
                for key, value in pre_existing_manifest[table_name].items()
                if key != "triggers"
            }
        else:
            assert post_existing_manifest[table_name] == pre_existing_manifest[table_name]
    for table_name in ("users", "roles"):
        assert post_existing_manifest[table_name]["triggers"] == tuple(
            (
                trigger_name,
                expected_trigger_contract[trigger_name][0],
                expected_trigger_contract[trigger_name][1],
                expected_trigger_contract[trigger_name][2],
                "O",
                expected_trigger_contract[trigger_name][3],
                expected_trigger_contract[trigger_name][4],
            )
            for trigger_name in sorted(PRIVILEGED_AUTH_TRIGGERS[table_name])
        )

    command.downgrade(alembic_config, RELIABILITY_REVISION)
    assert current_revision(database_url) == RELIABILITY_REVISION
    assert public_relation_manifest(database_url, existing_tables_at_007) == pre_existing_manifest
    assert public_relation_manifest(database_url, PRIVILEGED_AUTH_TABLES) == {}
    assert privileged_auth_function_manifest(database_url) == ()
    command.upgrade(alembic_config, PRIVILEGED_AUTH_REVISION)
    assert current_revision(database_url) == PRIVILEGED_AUTH_REVISION
    assert public_relation_manifest(database_url, existing_tables_at_007) == (
        post_existing_manifest
    )
    assert public_relation_manifest(database_url, PRIVILEGED_AUTH_TABLES) == (
        post_privileged_manifest
    )
    assert privileged_auth_function_manifest(database_url) == post_function_manifest
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": baseline_user_id},
            )
            connection.execute(
                text("DELETE FROM organizations WHERE id = :id"),
                {"id": baseline_organization_id},
            )
    finally:
        engine.dispose()


def test_privileged_auth_action_time_matrix_and_deferred_final_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_privileged_auth_revision(database_url, alembic_config)
    subjects = seed_privileged_auth_subjects(database_url)
    engine = create_migration_engine(database_url)

    def create_request(*, duration_seconds: int = 3600) -> str:
        selected_request_id = str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO break_glass_requests ("
                    "id, organization_id, target_user_id, target_role_code, requested_by, "
                    "reason, requested_duration_seconds, status, trace_id"
                    ") VALUES ("
                    ":id, :organization_id, :target_id, 'finance_reviewer', :requester_id, "
                    "'synthetic action-time probe', :duration, 'pending', :trace_id)"
                ),
                {
                    "id": selected_request_id,
                    "organization_id": subjects["organization_id"],
                    "target_id": subjects["target_id"],
                    "requester_id": subjects["requester_id"],
                    "duration": duration_seconds,
                    "trace_id": str(uuid4()),
                },
            )
        return selected_request_id

    def approve_request(selected_request_id: str) -> str:
        assignment_id = str(uuid4())
        with engine.begin() as connection:
            approved = connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'approved', "
                    "decided_by = :decider_id, decision_reason = 'approved action-time probe', "
                    "row_version = row_version + 1 WHERE id = :id "
                    "RETURNING effective_from, expires_at"
                ),
                {"decider_id": subjects["decider_id"], "id": selected_request_id},
            ).one()
            connection.execute(
                text(
                    "INSERT INTO user_roles ("
                    "id, user_id, role_id, assigned_by, assignment_source, assigned_at, "
                    "expires_at, break_glass_request_id, assignment_reason"
                    ") VALUES ("
                    ":id, :target_id, :role_id, :decider_id, 'break_glass', "
                    ":assigned_at, :expires_at, :request_id, 'approved action-time probe')"
                ),
                {
                    "id": assignment_id,
                    "target_id": subjects["target_id"],
                    "role_id": subjects["finance_reviewer_role_id"],
                    "decider_id": subjects["decider_id"],
                    "assigned_at": approved.effective_from,
                    "expires_at": approved.expires_at,
                    "request_id": selected_request_id,
                },
            )
        return assignment_id

    try:
        with pytest.raises(DBAPIError) as create_recheck_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO break_glass_requests ("
                        "id, organization_id, target_user_id, target_role_code, requested_by, "
                        "reason, requested_duration_seconds, status, trace_id"
                        ") VALUES ("
                        ":id, :organization_id, :target_id, 'finance_reviewer', "
                        ":requester_id, 'same transaction create bypass', 60, "
                        "'pending', :trace_id)"
                    ),
                    {
                        "id": str(uuid4()),
                        "organization_id": subjects["organization_id"],
                        "target_id": subjects["target_id"],
                        "requester_id": subjects["requester_id"],
                        "trace_id": str(uuid4()),
                    },
                )
                connection.execute(
                    text("UPDATE users SET status = 'disabled' WHERE id = :id"),
                    {"id": subjects["target_id"]},
                )
        assert safe_database_error_signature(create_recheck_error.value)[0] == "23514"

        reject_request_id = create_request()
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET status = 'disabled' WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": [subjects["requester_id"], subjects["target_id"]]},
            )
        with engine.begin() as connection:
            rejected = connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'rejected', "
                    "decided_by = :decider_id, decision_reason = 'safe rejection', "
                    "decision_at = '2000-01-01 UTC', updated_at = '2000-01-01 UTC', "
                    "row_version = row_version + 1 WHERE id = :id "
                    "RETURNING status, decision_at, updated_at"
                ),
                {"decider_id": subjects["decider_id"], "id": reject_request_id},
            ).one()
            assert rejected.status == "rejected"
            assert rejected.decision_at == rejected.updated_at
            assert rejected.decision_at.year != 2000
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status, row_version FROM break_glass_requests WHERE id = :id"),
                {"id": reject_request_id},
            ).one() == ("rejected", 2)
            assert tuple(
                connection.execute(
                    text(
                        "SELECT status FROM users WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY id"
                    ),
                    {"ids": [subjects["requester_id"], subjects["target_id"]]},
                ).scalars()
            ) == ("disabled", "disabled")
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET status = 'active' WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": [subjects["requester_id"], subjects["target_id"]]},
            )

        invalid_approval_id = create_request()
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET status = 'disabled' WHERE id = :id"),
                {"id": subjects["target_id"]},
            )
        with pytest.raises(DBAPIError) as invalid_approval_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE break_glass_requests SET status = 'approved', "
                        "decided_by = :decider_id, decision_reason = 'must fail', "
                        "row_version = row_version + 1 WHERE id = :id"
                    ),
                    {"decider_id": subjects["decider_id"], "id": invalid_approval_id},
                )
        assert safe_database_error_signature(invalid_approval_error.value)[0] == "23514"
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT status, row_version FROM break_glass_requests WHERE id = :id"),
                {"id": invalid_approval_id},
            ).one() == ("pending", 1)
            connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'rejected', "
                    "decided_by = :decider_id, decision_reason = 'close invalid approval', "
                    "row_version = row_version + 1 WHERE id = :id"
                ),
                {"decider_id": subjects["decider_id"], "id": invalid_approval_id},
            )
            connection.execute(
                text("UPDATE users SET status = 'active' WHERE id = :id"),
                {"id": subjects["target_id"]},
            )

        deferred_approval_id = create_request()
        with pytest.raises(DBAPIError) as approve_recheck_error:
            with engine.begin() as connection:
                approved = connection.execute(
                    text(
                        "UPDATE break_glass_requests SET status = 'approved', "
                        "decided_by = :decider_id, decision_reason = 'same transaction probe', "
                        "row_version = row_version + 1 WHERE id = :id "
                        "RETURNING effective_from, expires_at"
                    ),
                    {"decider_id": subjects["decider_id"], "id": deferred_approval_id},
                ).one()
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assigned_by, assignment_source, assigned_at, "
                        "expires_at, break_glass_request_id, assignment_reason"
                        ") VALUES ("
                        ":assignment_id, :target_id, :role_id, :decider_id, 'break_glass', "
                        ":assigned_at, :expires_at, :request_id, 'same transaction probe')"
                    ),
                    {
                        "assignment_id": str(uuid4()),
                        "target_id": subjects["target_id"],
                        "role_id": subjects["finance_reviewer_role_id"],
                        "decider_id": subjects["decider_id"],
                        "assigned_at": approved.effective_from,
                        "expires_at": approved.expires_at,
                        "request_id": deferred_approval_id,
                    },
                )
                connection.execute(
                    text("UPDATE users SET status = 'disabled' WHERE id = :id"),
                    {"id": subjects["target_id"]},
                )
        assert safe_database_error_signature(approve_recheck_error.value)[0] == "23514"

        expiring_request_id = create_request(duration_seconds=1)
        expiring_assignment_id = approve_request(expiring_request_id)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET status = 'disabled' WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": [subjects["requester_id"], subjects["target_id"]]},
            )
            connection.execute(text("SELECT pg_sleep(1.1)"))
            expired = connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'expired', "
                    "updated_at = '2000-01-01 UTC', row_version = row_version + 1 "
                    "WHERE id = :id RETURNING status, updated_at, expires_at"
                ),
                {"id": expiring_request_id},
            ).one()
            assert expired.status == "expired"
            assert expired.updated_at >= expired.expires_at
            assert expired.updated_at.year != 2000
            assignment_revocation = connection.execute(
                text("SELECT revoked_by, revoked_at, revoke_reason FROM user_roles WHERE id = :id"),
                {"id": expiring_assignment_id},
            ).one()
            assert assignment_revocation == (None, None, None)
    finally:
        clear_privileged_auth_subjects(database_url, subjects)
        engine.dispose()


def test_privileged_auth_action_time_current_facts_and_actors_are_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_privileged_auth_revision(database_url, alembic_config)
    subjects = seed_privileged_auth_subjects(database_url)
    engine = create_migration_engine(database_url)
    other_organization_id = str(uuid4())
    third_admin_id = str(uuid4())
    singleton_constraint_dropped = False
    governed_user_ids = (
        subjects["requester_id"],
        subjects["decider_id"],
        subjects["target_id"],
        third_admin_id,
    )

    def apply_user_fact(user_id: str, fact: str) -> None:
        statements = {
            "disabled": "UPDATE users SET status = 'disabled' WHERE id = :id",
            "deleted": (
                "UPDATE users SET deleted_at = clock_timestamp(), "
                "delete_reason = 'synthetic action-time fact' WHERE id = :id"
            ),
            "cross_org": (
                "UPDATE users SET organization_id = :other_organization_id WHERE id = :id"
            ),
        }
        parameters = {
            "id": user_id,
            "other_organization_id": other_organization_id,
        }
        with engine.begin() as connection:
            connection.execute(text(statements[fact]), parameters)

    def restore_user(user_id: str) -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE users SET organization_id = :organization_id, status = 'active', "
                    "deleted_at = NULL, delete_reason = NULL WHERE id = :id"
                ),
                {
                    "organization_id": subjects["organization_id"],
                    "id": user_id,
                },
            )

    def create_pending_request(
        *,
        target_role_code: str = "finance_reviewer",
        duration_seconds: int = 3600,
    ) -> str:
        with engine.begin() as connection:
            return insert_pending_break_glass_request(
                connection,
                subjects,
                target_role_code=target_role_code,
                duration_seconds=duration_seconds,
            )

    def assert_pending_unchanged(request_id: str) -> None:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status, row_version FROM break_glass_requests WHERE id = :id"),
                {"id": request_id},
            ).one() == ("pending", 1)
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE break_glass_request_id = :id"),
                    {"id": request_id},
                ).scalar_one()
                == 0
            )

    try:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE public.organizations DROP CONSTRAINT uq_organizations_singleton")
            )
            tax_identity = f"SYNTH-ACTION-{uuid4().hex[:16]}"
            connection.execute(
                text(
                    "INSERT INTO organizations ("
                    "id, name, unified_social_credit_code, tax_number, status) VALUES ("
                    ":id, 'synthetic action-time other organization', "
                    ":tax_identity, :tax_identity, 'active')"
                ),
                {"id": other_organization_id, "tax_identity": tax_identity},
            )
            username = f"synthetic-third-admin-{uuid4().hex[:10]}"
            connection.execute(
                text(
                    "INSERT INTO users ("
                    "id, organization_id, username, display_name, password_hash, status, "
                    "password_changed_at) VALUES ("
                    ":id, :organization_id, :username, :display_name, "
                    "'synthetic-not-a-real-password-hash', 'active', now())"
                ),
                {
                    "id": third_admin_id,
                    "organization_id": subjects["organization_id"],
                    "username": username,
                    "display_name": "Synthetic third administrator",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO user_roles ("
                    "id, user_id, role_id, assignment_source, assignment_reason) "
                    "VALUES (:id, :user_id, :role_id, 'bootstrap', 'system_bootstrap')"
                ),
                {
                    "id": str(uuid4()),
                    "user_id": third_admin_id,
                    "role_id": subjects["system_admin_role_id"],
                },
            )
        singleton_constraint_dropped = True

        for subject_key, fact in (
            ("requester_id", "deleted"),
            ("requester_id", "cross_org"),
            ("target_id", "deleted"),
            ("target_id", "cross_org"),
        ):
            user_id = subjects[subject_key]
            apply_user_fact(user_id, fact)
            failed_request_id = str(uuid4())
            with pytest.raises(DBAPIError) as create_error:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO break_glass_requests ("
                            "id, organization_id, target_user_id, target_role_code, "
                            "requested_by, reason, requested_duration_seconds, status, "
                            "trace_id) VALUES ("
                            ":id, :organization_id, :target_id, 'contract_admin', "
                            ":requester_id, 'current fact create probe', 60, "
                            "'pending', :trace_id)"
                        ),
                        {
                            "id": failed_request_id,
                            "organization_id": subjects["organization_id"],
                            "target_id": subjects["target_id"],
                            "requester_id": subjects["requester_id"],
                            "trace_id": str(uuid4()),
                        },
                    )
            assert safe_database_error_signature(create_error.value) == ("23514", None)
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM break_glass_requests WHERE id = :id"),
                        {"id": failed_request_id},
                    ).scalar_one()
                    == 0
                )
            restore_user(user_id)

        approval_fact_cases = (
            ("requester_id", "disabled", "decider_id"),
            ("requester_id", "deleted", "decider_id"),
            ("requester_id", "cross_org", "decider_id"),
            ("target_id", "deleted", "decider_id"),
            ("target_id", "cross_org", "decider_id"),
            ("decider_id", "disabled", "decider_id"),
            ("decider_id", "cross_org", "decider_id"),
        )
        for subject_key, fact, actor_key in approval_fact_cases:
            request_id = create_pending_request(target_role_code="contract_admin")
            user_id = subjects[subject_key]
            apply_user_fact(user_id, fact)
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    with pytest.raises(DBAPIError) as approval_error:
                        connection.execute(
                            text(
                                "UPDATE break_glass_requests SET status = 'approved', "
                                "decided_by = :actor, decision_reason = 'current fact probe', "
                                "row_version = row_version + 1 WHERE id = :id"
                            ),
                            {"actor": subjects[actor_key], "id": request_id},
                        )
                    assert safe_database_error_signature(approval_error.value) == (
                        "23514",
                        None,
                    )
                finally:
                    transaction.rollback()
            assert_pending_unchanged(request_id)
            restore_user(user_id)

        target_actor_request_id = create_pending_request(target_role_code="contract_admin")
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with pytest.raises(DBAPIError) as target_actor_error:
                    connection.execute(
                        text(
                            "UPDATE break_glass_requests SET status = 'approved', "
                            "decided_by = :actor, decision_reason = 'target actor probe', "
                            "row_version = row_version + 1 WHERE id = :id"
                        ),
                        {"actor": subjects["target_id"], "id": target_actor_request_id},
                    )
                assert safe_database_error_signature(target_actor_error.value) == (
                    "23514",
                    None,
                )
            finally:
                transaction.rollback()
        assert_pending_unchanged(target_actor_request_id)

        conflict_request_id = create_pending_request()
        conflict_assignment_id = str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO user_roles ("
                    "id, user_id, role_id, assigned_by, assignment_source, "
                    "assignment_reason) VALUES ("
                    ":id, :user_id, :role_id, :assigned_by, 'user', 'existing role probe')"
                ),
                {
                    "id": conflict_assignment_id,
                    "user_id": subjects["target_id"],
                    "role_id": subjects["finance_reviewer_role_id"],
                    "assigned_by": third_admin_id,
                },
            )
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with pytest.raises(DBAPIError) as conflict_approval_error:
                    connection.execute(
                        text(
                            "UPDATE break_glass_requests SET status = 'approved', "
                            "decided_by = :actor, decision_reason = 'existing role probe', "
                            "row_version = row_version + 1 WHERE id = :id"
                        ),
                        {"actor": subjects["decider_id"], "id": conflict_request_id},
                    )
                assert safe_database_error_signature(conflict_approval_error.value) == (
                    "23514",
                    None,
                )
            finally:
                transaction.rollback()
        assert_pending_unchanged(conflict_request_id)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE user_roles SET revoked_by = :actor, "
                    "revoke_reason = 'remove existing role probe' WHERE id = :id"
                ),
                {"actor": third_admin_id, "id": conflict_assignment_id},
            )

        reject_request_id = create_pending_request(target_role_code="contract_admin")
        apply_user_fact(third_admin_id, "disabled")
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with pytest.raises(DBAPIError) as reject_actor_error:
                    connection.execute(
                        text(
                            "UPDATE break_glass_requests SET status = 'rejected', "
                            "decided_by = :actor, decision_reason = 'invalid actor probe', "
                            "row_version = row_version + 1 WHERE id = :id"
                        ),
                        {"actor": third_admin_id, "id": reject_request_id},
                    )
                assert safe_database_error_signature(reject_actor_error.value) == (
                    "23514",
                    None,
                )
            finally:
                transaction.rollback()
        assert_pending_unchanged(reject_request_id)
        restore_user(third_admin_id)

        apply_user_fact(subjects["requester_id"], "deleted")
        apply_user_fact(subjects["target_id"], "cross_org")
        apply_user_fact(subjects["decider_id"], "disabled")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'rejected', "
                    "decided_by = :actor, decision_reason = 'eligible third actor', "
                    "row_version = row_version + 1 WHERE id = :id"
                ),
                {"actor": third_admin_id, "id": reject_request_id},
            )
        with engine.connect() as connection:
            rejected_row = connection.execute(
                text(
                    "SELECT status, row_version, decided_by FROM break_glass_requests "
                    "WHERE id = :id"
                ),
                {"id": reject_request_id},
            ).one()
            assert (
                rejected_row.status,
                rejected_row.row_version,
                str(rejected_row.decided_by),
            ) == ("rejected", 2, third_admin_id)
        for user_id in governed_user_ids:
            restore_user(user_id)

        revoke_request_id = create_pending_request()
        with engine.begin() as connection:
            revoke_assignment_id, _, _ = approve_break_glass_request_with_role(
                connection,
                subjects,
                revoke_request_id,
            )
        apply_user_fact(third_admin_id, "disabled")
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with pytest.raises(DBAPIError) as revoke_actor_error:
                    connection.execute(
                        text(
                            "UPDATE break_glass_requests SET status = 'revoked', "
                            "revoked_by = :actor, revoke_reason = 'invalid actor probe', "
                            "row_version = row_version + 1 WHERE id = :id"
                        ),
                        {"actor": third_admin_id, "id": revoke_request_id},
                    )
                assert safe_database_error_signature(revoke_actor_error.value) == (
                    "23514",
                    None,
                )
            finally:
                transaction.rollback()
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status, row_version FROM break_glass_requests WHERE id = :id"),
                {"id": revoke_request_id},
            ).one() == ("approved", 2)
            assert (
                connection.execute(
                    text("SELECT revoked_at FROM user_roles WHERE id = :id"),
                    {"id": revoke_assignment_id},
                ).scalar_one_or_none()
                is None
            )
        restore_user(third_admin_id)

        apply_user_fact(subjects["requester_id"], "disabled")
        apply_user_fact(subjects["target_id"], "cross_org")
        apply_user_fact(subjects["decider_id"], "deleted")
        with engine.begin() as connection:
            revoked_at = connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'revoked', "
                    "revoked_by = :actor, revoke_reason = 'eligible third actor', "
                    "row_version = row_version + 1 WHERE id = :id RETURNING revoked_at"
                ),
                {"actor": third_admin_id, "id": revoke_request_id},
            ).scalar_one()
            connection.execute(
                text(
                    "UPDATE user_roles SET revoked_by = :actor, revoked_at = :revoked_at, "
                    "revoke_reason = 'eligible third actor' WHERE id = :id"
                ),
                {
                    "actor": third_admin_id,
                    "revoked_at": revoked_at,
                    "id": revoke_assignment_id,
                },
            )
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT request.status, request.row_version, assignment.revoked_at "
                    "FROM break_glass_requests AS request JOIN user_roles AS assignment "
                    "ON assignment.break_glass_request_id = request.id "
                    "WHERE request.id = :id"
                ),
                {"id": revoke_request_id},
            ).one() == ("revoked", 3, revoked_at)
        for user_id in governed_user_ids:
            restore_user(user_id)

        expire_request_id = create_pending_request(
            target_role_code="audit_reviewer",
            duration_seconds=1,
        )
        with engine.begin() as connection:
            expire_assignment_id, _, _ = approve_break_glass_request_with_role(
                connection,
                subjects,
                expire_request_id,
                target_role_code="audit_reviewer",
            )
        apply_user_fact(subjects["requester_id"], "deleted")
        apply_user_fact(subjects["target_id"], "cross_org")
        apply_user_fact(subjects["decider_id"], "disabled")
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_sleep(1.1)"))
            connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'expired', "
                    "row_version = row_version + 1 WHERE id = :id"
                ),
                {"id": expire_request_id},
            )
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT request.status, request.row_version, assignment.revoked_at "
                    "FROM break_glass_requests AS request JOIN user_roles AS assignment "
                    "ON assignment.break_glass_request_id = request.id "
                    "WHERE request.id = :id"
                ),
                {"id": expire_request_id},
            ).one() == ("expired", 3, None)
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE id = :id"),
                    {"id": expire_assignment_id},
                ).scalar_one()
                == 1
            )
    finally:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE users SET organization_id = :organization_id, "
                        "status = 'active', deleted_at = NULL, delete_reason = NULL "
                        "WHERE id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {
                        "organization_id": subjects["organization_id"],
                        "ids": list(governed_user_ids),
                    },
                )
        finally:
            try:
                if singleton_constraint_dropped:
                    with engine.begin() as connection:
                        connection.execute(
                            text("DELETE FROM organizations WHERE id = :id"),
                            {"id": other_organization_id},
                        )
                        connection.execute(
                            text(
                                "ALTER TABLE public.organizations ADD CONSTRAINT "
                                "uq_organizations_singleton UNIQUE (singleton_key)"
                            )
                        )
                clear_privileged_auth_subjects(database_url, subjects)
            finally:
                engine.dispose()


def test_privileged_auth_core_transitions_sod_gist_and_downgrade_are_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_privileged_auth_revision(database_url, alembic_config)
    organization_id = str(uuid4())
    requester_id = str(uuid4())
    decider_id = str(uuid4())
    target_id = str(uuid4())
    request_id = str(uuid4())
    break_glass_assignment_id = str(uuid4())
    ordinary_assignment_id = str(uuid4())
    engine = create_migration_engine(database_url)

    def clear_synthetic_auth_data() -> None:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE user_roles DISABLE TRIGGER USER"))
            connection.execute(text("ALTER TABLE break_glass_requests DISABLE TRIGGER USER"))
            connection.execute(
                text("DELETE FROM user_roles WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": [requester_id, decider_id, target_id]},
            )
            connection.execute(
                text("DELETE FROM break_glass_requests WHERE organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            connection.execute(text("ALTER TABLE break_glass_requests ENABLE TRIGGER USER"))
            connection.execute(text("ALTER TABLE user_roles ENABLE TRIGGER USER"))
            connection.execute(
                text("DELETE FROM users WHERE organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            connection.execute(
                text("DELETE FROM organizations WHERE id = :organization_id"),
                {"organization_id": organization_id},
            )

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO organizations "
                    "(id, name, unified_social_credit_code, tax_number, status) "
                    "VALUES (:id, 'synthetic privileged auth organization', "
                    "'SYNTHETIC-PRIVILEGED-USCC', 'SYNTHETIC-PRIVILEGED-TAX', 'active')"
                ),
                {"id": organization_id},
            )
            for user_id, username in (
                (requester_id, "synthetic-requester"),
                (decider_id, "synthetic-decider"),
                (target_id, "synthetic-target"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO users ("
                        "id, organization_id, username, display_name, password_hash, "
                        "status, password_changed_at) VALUES ("
                        ":id, :organization_id, :username, :display_name, "
                        "'synthetic-not-a-real-password-hash', 'active', now())"
                    ),
                    {
                        "id": user_id,
                        "organization_id": organization_id,
                        "username": username,
                        "display_name": username,
                    },
                )
            system_admin_role_id = connection.execute(
                text("SELECT id FROM roles WHERE code = 'system_admin'")
            ).scalar_one()
            finance_role_id = connection.execute(
                text("SELECT id FROM roles WHERE code = 'finance_reviewer'")
            ).scalar_one()
            for user_id in (requester_id, decider_id):
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assignment_source, assignment_reason"
                        ") VALUES (:id, :user_id, :role_id, 'bootstrap', 'system_bootstrap')"
                    ),
                    {
                        "id": str(uuid4()),
                        "user_id": user_id,
                        "role_id": system_admin_role_id,
                    },
                )

        with pytest.raises(DBAPIError) as role_created_at_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE roles SET created_at = created_at + interval '1 second' "
                        "WHERE code = 'finance_reviewer'"
                    )
                )
        assert safe_database_error_signature(role_created_at_error.value)[0] == "23514"

        with pytest.raises(DBAPIError) as pre_revoked_insert_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assigned_by, assignment_source, "
                        "assignment_reason, revoked_at, revoked_by, revoke_reason"
                        ") VALUES ("
                        ":id, :user_id, :role_id, :assigned_by, 'user', "
                        "'ordinary review', now(), :revoked_by, 'already revoked')"
                    ),
                    {
                        "id": str(uuid4()),
                        "user_id": target_id,
                        "role_id": finance_role_id,
                        "assigned_by": requester_id,
                        "revoked_by": requester_id,
                    },
                )
        assert safe_database_error_signature(pre_revoked_insert_error.value)[0] == "23514"

        with engine.begin() as connection:
            created_request = connection.execute(
                text(
                    "INSERT INTO break_glass_requests ("
                    "id, organization_id, target_user_id, target_role_code, requested_by, "
                    "reason, requested_duration_seconds, status, created_at, updated_at, trace_id"
                    ") VALUES ("
                    ":id, :organization_id, :target_user_id, 'finance_reviewer', "
                    ":requested_by, 'synthetic urgent review', 3600, 'pending', "
                    "'2000-01-01 UTC', '2000-01-02 UTC', :trace_id) "
                    "RETURNING created_at, updated_at"
                ),
                {
                    "id": request_id,
                    "organization_id": organization_id,
                    "target_user_id": target_id,
                    "requested_by": requester_id,
                    "trace_id": str(uuid4()),
                },
            ).one()
            assert created_request.created_at == created_request.updated_at
            assert created_request.created_at.year != 2000

        with pytest.raises(DBAPIError) as mismatch_error:
            with engine.begin() as connection:
                approved = connection.execute(
                    text(
                        "UPDATE break_glass_requests SET status = 'approved', "
                        "decided_by = :decided_by, decision_reason = 'approved', "
                        "decision_at = '2000-01-01 UTC', effective_from = '2000-01-01 UTC', "
                        "expires_at = '2000-01-02 UTC', updated_at = '2000-01-01 UTC', "
                        "row_version = row_version + 1 WHERE id = :id "
                        "RETURNING effective_from, expires_at"
                    ),
                    {"decided_by": decider_id, "id": request_id},
                ).one()
                finance_role_id = connection.execute(
                    text("SELECT id FROM roles WHERE code = 'finance_reviewer'")
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assigned_by, assignment_source, assigned_at, "
                        "expires_at, break_glass_request_id, assignment_reason"
                        ") VALUES ("
                        ":id, :user_id, :role_id, :assigned_by, 'break_glass', "
                        ":assigned_at + interval '1 second', :expires_at, :request_id, 'approved')"
                    ),
                    {
                        "id": break_glass_assignment_id,
                        "user_id": target_id,
                        "role_id": finance_role_id,
                        "assigned_by": decider_id,
                        "assigned_at": approved.effective_from,
                        "expires_at": approved.expires_at,
                        "request_id": request_id,
                    },
                )
        assert safe_database_error_signature(mismatch_error.value)[0] == "23514"

        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT status, row_version FROM break_glass_requests WHERE id = :id"),
                {"id": request_id},
            ).one() == ("pending", 1)
            approved = connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'approved', "
                    "decided_by = :decided_by, decision_reason = 'approved', "
                    "decision_at = '2000-01-01 UTC', effective_from = '2000-01-01 UTC', "
                    "expires_at = '2000-01-02 UTC', updated_at = '2000-01-01 UTC', "
                    "row_version = row_version + 1 WHERE id = :id "
                    "RETURNING decision_at, effective_from, expires_at, updated_at"
                ),
                {"decided_by": decider_id, "id": request_id},
            ).one()
            assert approved.decision_at == approved.effective_from == approved.updated_at
            assert approved.expires_at - approved.effective_from == timedelta(seconds=3600)
            finance_role_id = connection.execute(
                text("SELECT id FROM roles WHERE code = 'finance_reviewer'")
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO user_roles ("
                    "id, user_id, role_id, assigned_by, assignment_source, assigned_at, "
                    "expires_at, break_glass_request_id, assignment_reason"
                    ") VALUES ("
                    ":id, :user_id, :role_id, :assigned_by, 'break_glass', "
                    ":assigned_at, :expires_at, :request_id, 'approved')"
                ),
                {
                    "id": break_glass_assignment_id,
                    "user_id": target_id,
                    "role_id": finance_role_id,
                    "assigned_by": decider_id,
                    "assigned_at": approved.effective_from,
                    "expires_at": approved.expires_at,
                    "request_id": request_id,
                },
            )

        with pytest.raises(DBAPIError) as sod_error:
            with engine.begin() as connection:
                finance_role_id = connection.execute(
                    text("SELECT id FROM roles WHERE code = 'finance_reviewer'")
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assigned_by, assignment_source, assignment_reason"
                        ") VALUES ("
                        ":id, :user_id, :role_id, :assigned_by, 'user', 'separate reviewer')"
                    ),
                    {
                        "id": str(uuid4()),
                        "user_id": requester_id,
                        "role_id": finance_role_id,
                        "assigned_by": decider_id,
                    },
                )
        assert safe_database_error_signature(sod_error.value)[0] == "23514"

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET status = 'disabled' WHERE id = :target_id"),
                {"target_id": target_id},
            )

        with engine.begin() as connection:
            revoked = connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'revoked', "
                    "revoked_by = :revoked_by, revoke_reason = 'review complete', "
                    "row_version = row_version + 1 WHERE id = :id RETURNING revoked_at"
                ),
                {"revoked_by": requester_id, "id": request_id},
            ).one()
            connection.execute(
                text(
                    "UPDATE user_roles SET revoked_by = :revoked_by, "
                    "revoked_at = :revoked_at, revoke_reason = 'review complete' "
                    "WHERE id = :id"
                ),
                {
                    "revoked_by": requester_id,
                    "revoked_at": revoked.revoked_at,
                    "id": break_glass_assignment_id,
                },
            )
            connection.execute(
                text("UPDATE users SET status = 'active' WHERE id = :target_id"),
                {"target_id": target_id},
            )
            finance_role_id = connection.execute(
                text("SELECT id FROM roles WHERE code = 'finance_reviewer'")
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO user_roles ("
                    "id, user_id, role_id, assigned_by, assignment_source, assignment_reason"
                    ") VALUES (:id, :user_id, :role_id, :assigned_by, 'user', 'ordinary review')"
                ),
                {
                    "id": ordinary_assignment_id,
                    "user_id": target_id,
                    "role_id": finance_role_id,
                    "assigned_by": requester_id,
                },
            )

        with pytest.raises(DBAPIError) as overlap_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assigned_by, assignment_source, assignment_reason"
                        ") SELECT :id, user_id, role_id, :assigned_by, 'user', "
                        "'overlapping review' FROM user_roles WHERE id = :source_id"
                    ),
                    {
                        "id": str(uuid4()),
                        "assigned_by": requester_id,
                        "source_id": ordinary_assignment_id,
                    },
                )
        assert safe_database_error_signature(overlap_error.value)[0] == "23P01"

        with pytest.raises(DBAPIError) as downgrade_error:
            command.downgrade(alembic_config, RELIABILITY_REVISION)
        assert safe_database_error_signature(downgrade_error.value)[0] == "55000"
        assert current_revision(database_url) == PRIVILEGED_AUTH_REVISION
    finally:
        clear_synthetic_auth_data()
        engine.dispose()

    command.downgrade(alembic_config, RELIABILITY_REVISION)
    assert current_revision(database_url) == RELIABILITY_REVISION
    assert installed_baseline_tables(database_url) == TABLES_AT_007
    command.upgrade(alembic_config, PRIVILEGED_AUTH_REVISION)
    assert current_revision(database_url) == PRIVILEGED_AUTH_REVISION
    assert installed_baseline_tables(database_url) == TABLES_AT_008


def test_privileged_auth_state_source_bidirectional_and_time_owner_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_privileged_auth_revision(database_url, alembic_config)
    subjects = seed_privileged_auth_subjects(database_url)
    engine = create_migration_engine(database_url)
    ordinary_assignment_id = str(uuid4())

    def row_json(table_name: str, row_id: str) -> str:
        if table_name not in PRIVILEGED_AUTH_TABLES:
            raise AssertionError("row snapshot is restricted to privileged-auth tables")
        with engine.connect() as connection:
            return str(
                connection.execute(
                    text(
                        f"SELECT to_jsonb(row_value)::text FROM public.{table_name} "
                        "AS row_value WHERE id = :id"
                    ),
                    {"id": row_id},
                ).scalar_one()
            )

    def assert_immediate_error(
        statement: str,
        parameters: Mapping[str, object],
        expected_signature: tuple[str | None, str | None],
    ) -> None:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with pytest.raises(DBAPIError) as error_info:
                    connection.execute(text(statement), parameters)
                assert safe_database_error_signature(error_info.value) == expected_signature
            finally:
                transaction.rollback()

    try:
        with engine.begin() as connection:
            assigned_at = connection.execute(
                text(
                    "INSERT INTO user_roles ("
                    "id, user_id, role_id, assigned_by, assignment_source, assigned_at, "
                    "assignment_reason) VALUES ("
                    ":id, :user_id, :role_id, :assigned_by, 'user', "
                    "'2000-01-01 UTC', 'ordinary audit review') RETURNING assigned_at"
                ),
                {
                    "id": ordinary_assignment_id,
                    "user_id": subjects["target_id"],
                    "role_id": subjects["audit_reviewer_role_id"],
                    "assigned_by": subjects["requester_id"],
                },
            ).scalar_one()
            assert assigned_at.year != 2000
            bootstrap_rows = connection.execute(
                text(
                    "SELECT assignment_source, assigned_by, assignment_reason, "
                    "assigned_at <= clock_timestamp(), expires_at, break_glass_request_id, "
                    "revoked_at, revoked_by, revoke_reason FROM user_roles "
                    "WHERE user_id = ANY(CAST(:ids AS uuid[])) ORDER BY user_id"
                ),
                {"ids": [subjects["requester_id"], subjects["decider_id"]]},
            ).all()
            assert (
                tuple(tuple(row) for row in bootstrap_rows)
                == (("bootstrap", None, "system_bootstrap", True, None, None, None, None, None),)
                * 2
            )

        for invalid_insert in (
            (
                "INSERT INTO user_roles (id, user_id, role_id, assigned_by, "
                "assignment_source, assignment_reason) VALUES ("
                ":id, :user_id, :role_id, :assigned_by, 'user', ' padded reason ')",
                subjects["finance_reviewer_role_id"],
            ),
            (
                "INSERT INTO user_roles (id, user_id, role_id, assigned_by, "
                "assignment_source, assignment_reason) VALUES ("
                ":id, :user_id, :role_id, :assigned_by, 'bootstrap', 'system_bootstrap')",
                subjects["finance_reviewer_role_id"],
            ),
            (
                "INSERT INTO user_roles (id, user_id, role_id, assigned_by, "
                "assignment_source, assignment_reason, revoked_at, revoked_by, revoke_reason) "
                "VALUES (:id, :user_id, :role_id, :assigned_by, 'user', "
                "'pre-revoked role', now(), :assigned_by, 'pre-revoked')",
                subjects["finance_reviewer_role_id"],
            ),
        ):
            invalid_id = str(uuid4())
            with pytest.raises(DBAPIError) as invalid_insert_error:
                with engine.begin() as connection:
                    connection.execute(
                        text(invalid_insert[0]),
                        {
                            "id": invalid_id,
                            "user_id": subjects["target_id"],
                            "role_id": invalid_insert[1],
                            "assigned_by": subjects["requester_id"],
                        },
                    )
            assert safe_database_error_signature(invalid_insert_error.value)[0] == "23514"
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM user_roles WHERE id = :id"),
                        {"id": invalid_id},
                    ).scalar_one()
                    == 0
                )

        fk_probe_id = str(uuid4())
        with pytest.raises(DBAPIError) as fk_probe_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assigned_by, assignment_source, "
                        "assignment_reason) VALUES ("
                        ":id, :user_id, :missing_role_id, :assigned_by, "
                        "'user', 'foreign key probe')"
                    ),
                    {
                        "id": fk_probe_id,
                        "user_id": subjects["target_id"],
                        "missing_role_id": str(uuid4()),
                        "assigned_by": subjects["requester_id"],
                    },
                )
        assert safe_database_error_signature(fk_probe_error.value) == (
            "23503",
            "fk_user_roles_role_id_roles",
        )
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE id = :id"),
                    {"id": fk_probe_id},
                ).scalar_one()
                == 0
            )

        active_assignment_snapshot = row_json("user_roles", ordinary_assignment_id)
        missing_id = str(uuid4())
        immutable_cases: tuple[tuple[str, Mapping[str, object]], ...] = (
            ("id = :value", {"value": str(uuid4())}),
            ("user_id = :value", {"value": missing_id}),
            ("role_id = :value", {"value": missing_id}),
            ("assigned_by = :value", {"value": subjects["decider_id"]}),
            ("assignment_source = 'bootstrap'", {}),
            ("assigned_at = assigned_at + interval '1 second'", {}),
            ("expires_at = assigned_at + interval '1 hour'", {}),
            ("break_glass_request_id = :value", {"value": missing_id}),
            ("assignment_reason = 'changed'", {}),
            ("assignment_reason = assignment_reason", {}),
        )
        for set_clause, extra_parameters in immutable_cases:
            assert_immediate_error(
                f"UPDATE user_roles SET {set_clause} WHERE id = :id",
                {"id": ordinary_assignment_id, **extra_parameters},
                ("23514", None),
            )
            assert row_json("user_roles", ordinary_assignment_id) == active_assignment_snapshot

        partial_revocation_cases = (
            "revoked_by = :actor",
            "revoke_reason = 'reason only'",
            "revoked_at = now()",
            "revoked_by = :actor, revoked_at = now()",
            "revoke_reason = 'reason and time', revoked_at = now()",
        )
        for set_clause in partial_revocation_cases:
            assert_immediate_error(
                f"UPDATE user_roles SET {set_clause} WHERE id = :id",
                {"actor": subjects["requester_id"], "id": ordinary_assignment_id},
                ("23514", None),
            )
            assert row_json("user_roles", ordinary_assignment_id) == active_assignment_snapshot
        for invalid_reason in (" ", " padded "):
            assert_immediate_error(
                "UPDATE user_roles SET revoked_by = :actor, revoke_reason = :reason WHERE id = :id",
                {
                    "actor": subjects["requester_id"],
                    "reason": invalid_reason,
                    "id": ordinary_assignment_id,
                },
                ("23514", "ck_user_roles_revocation_matrix"),
            )
            assert row_json("user_roles", ordinary_assignment_id) == active_assignment_snapshot

        with engine.begin() as connection:
            revoked = connection.execute(
                text(
                    "UPDATE user_roles SET revoked_by = :actor, revoked_at = '2000-01-01 UTC', "
                    "revoke_reason = 'ordinary review complete' WHERE id = :id "
                    "RETURNING revoked_by, revoked_at, revoke_reason"
                ),
                {"actor": subjects["requester_id"], "id": ordinary_assignment_id},
            ).one()
            assert str(revoked.revoked_by) == subjects["requester_id"]
            assert revoked.revoked_at.year != 2000
            assert revoked.revoke_reason == "ordinary review complete"

        revoked_assignment_snapshot = row_json("user_roles", ordinary_assignment_id)
        for invalid_set_clause in (
            "revoked_by = revoked_by",
            "revoked_at = revoked_at",
            "revoke_reason = revoke_reason",
            "revoked_by = NULL, revoked_at = NULL, revoke_reason = NULL",
            "revoked_by = NULL",
            "revoked_at = NULL",
            "revoke_reason = NULL",
            "revoke_reason = 'second revoke'",
            "assignment_reason = 'changed'",
        ):
            assert_immediate_error(
                f"UPDATE user_roles SET {invalid_set_clause} WHERE id = :id",
                {"id": ordinary_assignment_id},
                ("23514", None),
            )
            assert row_json("user_roles", ordinary_assignment_id) == (revoked_assignment_snapshot)
        with engine.connect() as connection:
            persisted_revoke = connection.execute(
                text(
                    "SELECT revoked_at, revoke_reason, assignment_reason FROM user_roles "
                    "WHERE id = :id"
                ),
                {"id": ordinary_assignment_id},
            ).one()
            assert persisted_revoke.revoked_at == revoked.revoked_at
            assert persisted_revoke.revoke_reason == "ordinary review complete"
            assert persisted_revoke.assignment_reason == "ordinary audit review"

        for destructive_sql in (
            "DELETE FROM user_roles WHERE id = :id",
            "TRUNCATE TABLE user_roles",
        ):
            with pytest.raises(DBAPIError) as destructive_error:
                with engine.begin() as connection:
                    connection.execute(text(destructive_sql), {"id": ordinary_assignment_id})
            assert safe_database_error_signature(destructive_error.value)[0] == "55000"
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE id = :id"),
                    {"id": ordinary_assignment_id},
                ).scalar_one()
                == 1
            )

        with engine.begin() as connection:
            request_id = insert_pending_break_glass_request(connection, subjects)
        with engine.connect() as connection:
            pending = connection.execute(
                text(
                    "SELECT status, row_version, created_at, updated_at FROM "
                    "break_glass_requests WHERE id = :id"
                ),
                {"id": request_id},
            ).one()
            assert pending.status == "pending"
            assert pending.row_version == 1
            assert pending.created_at == pending.updated_at
            assert pending.created_at.year != 2000

        invalid_request_updates = (
            "UPDATE break_glass_requests SET status = status, "
            "row_version = row_version + 1 WHERE id = :id",
            "UPDATE break_glass_requests SET status = 'rejected', decided_by = :decider, "
            "decision_reason = 'bad cas', row_version = row_version + 2 WHERE id = :id",
            "UPDATE break_glass_requests SET status = 'rejected', decided_by = :decider, "
            "decision_reason = 'immutable', reason = 'changed', "
            "row_version = row_version + 1 WHERE id = :id",
        )
        for invalid_request_update in invalid_request_updates:
            with pytest.raises(DBAPIError) as invalid_transition_error:
                with engine.begin() as connection:
                    connection.execute(
                        text(invalid_request_update),
                        {"id": request_id, "decider": subjects["decider_id"]},
                    )
            assert safe_database_error_signature(invalid_transition_error.value)[0] == "23514"
            with engine.connect() as connection:
                assert connection.execute(
                    text(
                        "SELECT status, row_version, reason FROM break_glass_requests "
                        "WHERE id = :id"
                    ),
                    {"id": request_id},
                ).one() == ("pending", 1, "synthetic privileged access")

        with pytest.raises(DBAPIError) as missing_assignment_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE break_glass_requests SET status = 'approved', "
                        "decided_by = :decider, decision_reason = 'missing assignment', "
                        "row_version = row_version + 1 WHERE id = :id"
                    ),
                    {"id": request_id, "decider": subjects["decider_id"]},
                )
                connection.execute(
                    text("SET CONSTRAINTS trg_break_glass_requests_consistency_v1 IMMEDIATE")
                )
        assert safe_database_error_signature(missing_assignment_error.value)[0] == "23514"
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status, row_version FROM break_glass_requests WHERE id = :id"),
                {"id": request_id},
            ).one() == ("pending", 1)

        with engine.begin() as connection:
            alternate_pending_request_id = insert_pending_break_glass_request(
                connection,
                subjects,
                target_role_code="contract_admin",
            )
        pending_request_snapshot = row_json("break_glass_requests", request_id)
        for mismatch_field in (
            "user_id",
            "role_id",
            "assigned_by",
            "assigned_at",
            "expires_at",
            "request_id",
            "assignment_reason",
        ):
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    approved = connection.execute(
                        text(
                            "UPDATE break_glass_requests SET status = 'approved', "
                            "decided_by = :decider, "
                            "decision_reason = 'synthetic mismatch approval', "
                            "row_version = row_version + 1 WHERE id = :id "
                            "RETURNING effective_from, expires_at"
                        ),
                        {"id": request_id, "decider": subjects["decider_id"]},
                    ).one()
                    mismatch_parameters: dict[str, object] = {
                        "assignment_id": str(uuid4()),
                        "user_id": subjects["target_id"],
                        "role_id": subjects["finance_reviewer_role_id"],
                        "assigned_by": subjects["decider_id"],
                        "assigned_at": approved.effective_from,
                        "expires_at": approved.expires_at,
                        "request_id": request_id,
                        "assignment_reason": "synthetic mismatch approval",
                    }
                    mismatch_parameters[mismatch_field] = {
                        "user_id": subjects["requester_id"],
                        "role_id": subjects["audit_reviewer_role_id"],
                        "assigned_by": subjects["requester_id"],
                        "assigned_at": approved.effective_from + timedelta(seconds=1),
                        "expires_at": approved.expires_at - timedelta(seconds=1),
                        "request_id": alternate_pending_request_id,
                        "assignment_reason": "mismatch",
                    }[mismatch_field]
                    with pytest.raises(DBAPIError) as mismatch_error:
                        connection.execute(
                            text(
                                "INSERT INTO user_roles ("
                                "id, user_id, role_id, assigned_by, assignment_source, "
                                "assigned_at, expires_at, break_glass_request_id, "
                                "assignment_reason) VALUES ("
                                ":assignment_id, :user_id, :role_id, :assigned_by, "
                                "'break_glass', :assigned_at, :expires_at, :request_id, "
                                ":assignment_reason)"
                            ),
                            mismatch_parameters,
                        )
                    assert safe_database_error_signature(mismatch_error.value) == (
                        "23514",
                        None,
                    )
                finally:
                    transaction.rollback()
            assert row_json("break_glass_requests", request_id) == pending_request_snapshot
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM user_roles WHERE break_glass_request_id = :id"),
                        {"id": request_id},
                    ).scalar_one()
                    == 0
                )

        with engine.begin() as connection:
            break_glass_assignment_id, effective_from, expires_at = (
                approve_break_glass_request_with_role(connection, subjects, request_id)
            )
        assert effective_from.year != 2000
        assert expires_at - effective_from == timedelta(seconds=3600)

        duplicate_assignment_id = str(uuid4())
        with pytest.raises(DBAPIError) as duplicate_assignment_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assigned_by, assignment_source, assigned_at, "
                        "expires_at, break_glass_request_id, assignment_reason) "
                        "SELECT :new_id, user_id, role_id, assigned_by, assignment_source, "
                        "assigned_at, expires_at, break_glass_request_id, assignment_reason "
                        "FROM user_roles WHERE id = :source_id"
                    ),
                    {
                        "new_id": duplicate_assignment_id,
                        "source_id": break_glass_assignment_id,
                    },
                )
        assert safe_database_error_signature(duplicate_assignment_error.value) == (
            "23505",
            "uq_user_roles_break_glass_request_id",
        )
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE id = :id"),
                    {"id": duplicate_assignment_id},
                ).scalar_one()
                == 0
            )

        approved_request_snapshot = row_json("break_glass_requests", request_id)
        approved_assignment_snapshot = row_json("user_roles", break_glass_assignment_id)
        assert_immediate_error(
            "UPDATE user_roles SET revoked_by = :actor, revoked_at = now(), "
            "revoke_reason = 'assignment-only revoke' WHERE id = :id",
            {
                "actor": subjects["requester_id"],
                "id": break_glass_assignment_id,
            },
            ("23514", None),
        )
        assert row_json("user_roles", break_glass_assignment_id) == (approved_assignment_snapshot)

        with pytest.raises(DBAPIError) as request_only_revoke_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE break_glass_requests SET status = 'revoked', "
                        "revoked_by = :actor, revoke_reason = 'request-only revoke', "
                        "row_version = row_version + 1 WHERE id = :id"
                    ),
                    {"actor": subjects["requester_id"], "id": request_id},
                )
                connection.execute(
                    text("SET CONSTRAINTS trg_break_glass_requests_consistency_v1 IMMEDIATE")
                )
        assert safe_database_error_signature(request_only_revoke_error.value) == (
            "23514",
            None,
        )
        assert row_json("break_glass_requests", request_id) == approved_request_snapshot
        assert row_json("user_roles", break_glass_assignment_id) == (approved_assignment_snapshot)

        for mismatch_field in ("revoked_by", "revoked_at", "revoke_reason"):
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    revoked_at = connection.execute(
                        text(
                            "UPDATE break_glass_requests SET status = 'revoked', "
                            "revoked_by = :actor, revoke_reason = 'matched revoke', "
                            "row_version = row_version + 1 WHERE id = :id "
                            "RETURNING revoked_at"
                        ),
                        {"actor": subjects["requester_id"], "id": request_id},
                    ).scalar_one()
                    revoke_parameters: dict[str, object] = {
                        "revoked_by": subjects["requester_id"],
                        "revoked_at": revoked_at,
                        "revoke_reason": "matched revoke",
                        "id": break_glass_assignment_id,
                    }
                    revoke_parameters[mismatch_field] = {
                        "revoked_by": subjects["decider_id"],
                        "revoked_at": revoked_at + timedelta(seconds=1),
                        "revoke_reason": "mismatch",
                    }[mismatch_field]
                    with pytest.raises(DBAPIError) as revoke_mismatch_error:
                        connection.execute(
                            text(
                                "UPDATE user_roles SET revoked_by = :revoked_by, "
                                "revoked_at = :revoked_at, revoke_reason = :revoke_reason "
                                "WHERE id = :id"
                            ),
                            revoke_parameters,
                        )
                    assert safe_database_error_signature(revoke_mismatch_error.value) == (
                        "23514",
                        None,
                    )
                finally:
                    transaction.rollback()
            assert row_json("break_glass_requests", request_id) == approved_request_snapshot
            assert row_json("user_roles", break_glass_assignment_id) == (
                approved_assignment_snapshot
            )

        with pytest.raises(DBAPIError) as approved_noop_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE break_glass_requests SET status = status, "
                        "row_version = row_version + 1 WHERE id = :id"
                    ),
                    {"id": request_id},
                )
        assert safe_database_error_signature(approved_noop_error.value)[0] == "23514"

        with engine.begin() as connection:
            request_revoke = connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'revoked', "
                    "revoked_by = :actor, revoked_at = '2000-01-01 UTC', "
                    "revoke_reason = 'break glass complete', row_version = row_version + 1 "
                    "WHERE id = :id RETURNING revoked_at, updated_at"
                ),
                {"actor": subjects["requester_id"], "id": request_id},
            ).one()
            connection.execute(
                text(
                    "UPDATE user_roles SET revoked_by = :actor, revoked_at = :revoked_at, "
                    "revoke_reason = 'break glass complete' WHERE id = :id"
                ),
                {
                    "actor": subjects["requester_id"],
                    "revoked_at": request_revoke.revoked_at,
                    "id": break_glass_assignment_id,
                },
            )
            assert request_revoke.revoked_at == request_revoke.updated_at
            assert request_revoke.revoked_at.year != 2000
        with engine.connect() as connection:
            persisted_pair = connection.execute(
                text(
                    "SELECT request.status, request.row_version, request.revoked_by, "
                    "request.revoked_at, request.revoke_reason, assignment.revoked_by, "
                    "assignment.revoked_at, assignment.revoke_reason "
                    "FROM break_glass_requests AS request "
                    "JOIN user_roles AS assignment "
                    "ON assignment.break_glass_request_id = request.id WHERE request.id = :id"
                ),
                {"id": request_id},
            ).one()
            assert persisted_pair.status == "revoked"
            assert persisted_pair.row_version == 3
            assert persisted_pair.revoked_by == persisted_pair[5]
            assert persisted_pair.revoked_at == persisted_pair[6]
            assert persisted_pair.revoke_reason == persisted_pair[7]

        with pytest.raises(DBAPIError) as terminal_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE break_glass_requests SET status = 'expired', "
                        "row_version = row_version + 1 WHERE id = :id"
                    ),
                    {"id": request_id},
                )
        assert safe_database_error_signature(terminal_error.value)[0] == "23514"
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status, row_version FROM break_glass_requests WHERE id = :id"),
                {"id": request_id},
            ).one() == ("revoked", 3)

        with engine.begin() as connection:
            rejected_request_id = insert_pending_break_glass_request(
                connection,
                subjects,
                target_role_code="contract_admin",
            )
        with engine.begin() as connection:
            rejected = connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'rejected', "
                    "decided_by = :decider, decision_at = '2000-01-01 UTC', "
                    "decision_reason = 'not required', updated_at = '2000-01-01 UTC', "
                    "row_version = row_version + 1 WHERE id = :id "
                    "RETURNING decision_at, updated_at"
                ),
                {"id": rejected_request_id, "decider": subjects["decider_id"]},
            ).one()
            assert rejected.decision_at == rejected.updated_at
            assert rejected.decision_at.year != 2000
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE break_glass_request_id = :id"),
                    {"id": rejected_request_id},
                ).scalar_one()
                == 0
            )

        for inconsistent_request_id in (
            alternate_pending_request_id,
            rejected_request_id,
        ):
            inconsistent_request_snapshot = row_json(
                "break_glass_requests",
                inconsistent_request_id,
            )
            fabricated_assignment_id = str(uuid4())
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    contract_admin_role_id = connection.execute(
                        text("SELECT id FROM roles WHERE code = 'contract_admin'")
                    ).scalar_one()
                    connection.execute(
                        text(
                            "ALTER TABLE public.user_roles DISABLE TRIGGER trg_user_roles_state_v1"
                        )
                    )
                    connection.execute(
                        text(
                            "INSERT INTO user_roles ("
                            "id, user_id, role_id, assigned_by, assignment_source, "
                            "assigned_at, expires_at, break_glass_request_id, "
                            "assignment_reason) VALUES ("
                            ":id, :user_id, :role_id, :assigned_by, 'break_glass', "
                            "now(), now() + interval '1 hour', :request_id, "
                            "'fabricated association')"
                        ),
                        {
                            "id": fabricated_assignment_id,
                            "user_id": subjects["target_id"],
                            "role_id": contract_admin_role_id,
                            "assigned_by": subjects["decider_id"],
                            "request_id": inconsistent_request_id,
                        },
                    )
                    with pytest.raises(DBAPIError) as consistency_error:
                        connection.execute(
                            text("SET CONSTRAINTS trg_user_roles_consistency_v1 IMMEDIATE")
                        )
                    assert safe_database_error_signature(consistency_error.value) == (
                        "23514",
                        None,
                    )
                finally:
                    transaction.rollback()
            assert row_json("break_glass_requests", inconsistent_request_id) == (
                inconsistent_request_snapshot
            )
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM user_roles WHERE id = :id"),
                        {"id": fabricated_assignment_id},
                    ).scalar_one()
                    == 0
                )
            assert "trg_user_roles_state_v1" in user_trigger_names(
                database_url,
                "user_roles",
            )

        with engine.begin() as connection:
            approved_graph_request_id = insert_pending_break_glass_request(
                connection,
                subjects,
            )
        with engine.begin() as connection:
            approve_break_glass_request_with_role(
                connection,
                subjects,
                approved_graph_request_id,
            )
        with engine.begin() as connection:
            expired_graph_request_id = insert_pending_break_glass_request(
                connection,
                subjects,
                target_role_code="audit_reviewer",
                duration_seconds=1,
            )
        with engine.begin() as connection:
            approve_break_glass_request_with_role(
                connection,
                subjects,
                expired_graph_request_id,
                target_role_code="audit_reviewer",
            )
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_sleep(1.1)"))
            connection.execute(
                text(
                    "UPDATE break_glass_requests SET status = 'expired', "
                    "row_version = row_version + 1 WHERE id = :id"
                ),
                {"id": expired_graph_request_id},
            )

        forbidden_targets = {
            "pending": ("pending", "revoked", "expired"),
            "approved": ("pending", "approved", "rejected"),
            "rejected": ("pending", "approved", "rejected", "revoked", "expired"),
            "revoked": ("pending", "approved", "rejected", "revoked", "expired"),
            "expired": ("pending", "approved", "rejected", "revoked", "expired"),
        }
        graph_request_ids = {
            "pending": alternate_pending_request_id,
            "approved": approved_graph_request_id,
            "rejected": rejected_request_id,
            "revoked": request_id,
            "expired": expired_graph_request_id,
        }
        graph_snapshots = {
            status: row_json("break_glass_requests", graph_request_id)
            for status, graph_request_id in graph_request_ids.items()
        }
        for source_status, target_statuses in forbidden_targets.items():
            graph_request_id = graph_request_ids[source_status]
            for target_status in target_statuses:
                assert_immediate_error(
                    "UPDATE break_glass_requests SET status = :target_status, "
                    "row_version = row_version + 1 WHERE id = :id",
                    {"id": graph_request_id, "target_status": target_status},
                    ("23514", None),
                )
                assert (
                    row_json("break_glass_requests", graph_request_id)
                    == (graph_snapshots[source_status])
                )

        for destructive_sql in (
            "DELETE FROM break_glass_requests WHERE id = :id",
            "TRUNCATE TABLE break_glass_requests CASCADE",
        ):
            with pytest.raises(DBAPIError) as request_destructive_error:
                with engine.begin() as connection:
                    connection.execute(
                        text(destructive_sql),
                        {"id": rejected_request_id},
                    )
            assert safe_database_error_signature(request_destructive_error.value)[0] == "55000"
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT status FROM break_glass_requests WHERE id = :id"),
                    {"id": rejected_request_id},
                ).scalar_one()
                == "rejected"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM break_glass_requests "
                        "WHERE id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": [request_id, rejected_request_id]},
                ).scalar_one()
                == 2
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE id = ANY(CAST(:ids AS uuid[]))"),
                    {"ids": [ordinary_assignment_id, break_glass_assignment_id]},
                ).scalar_one()
                == 2
            )
    finally:
        clear_privileged_auth_subjects(database_url, subjects)
        engine.dispose()


def test_privileged_auth_sod_and_action_time_paths_are_environment_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_privileged_auth_revision(database_url, alembic_config)
    subjects = seed_privileged_auth_subjects(database_url)
    engine = create_migration_engine(database_url)
    inactive_user_id = str(uuid4())
    role_user_id = str(uuid4())
    future_user_id = str(uuid4())
    temporary_admin_id = str(uuid4())
    reverse_user_id = str(uuid4())

    try:
        with engine.begin() as connection:
            for user_id, status in (
                (inactive_user_id, "disabled"),
                (role_user_id, "active"),
                (future_user_id, "active"),
                (temporary_admin_id, "active"),
                (reverse_user_id, "active"),
            ):
                username = f"synthetic-sod-{uuid4().hex[:10]}"
                connection.execute(
                    text(
                        "INSERT INTO users ("
                        "id, organization_id, username, display_name, password_hash, status, "
                        "password_changed_at) VALUES ("
                        ":id, :organization_id, :username, :display_name, "
                        "'synthetic-not-a-real-password-hash', :status, now())"
                    ),
                    {
                        "id": user_id,
                        "organization_id": subjects["organization_id"],
                        "username": username,
                        "display_name": username,
                        "status": status,
                    },
                )

            for role_id, source, assigned_by, reason in (
                (
                    subjects["system_admin_role_id"],
                    "bootstrap",
                    None,
                    "system_bootstrap",
                ),
                (
                    subjects["finance_reviewer_role_id"],
                    "user",
                    subjects["requester_id"],
                    "inactive finance review",
                ),
            ):
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assigned_by, assignment_source, "
                        "assignment_reason) VALUES ("
                        ":id, :user_id, :role_id, :assigned_by, :source, :reason)"
                    ),
                    {
                        "id": str(uuid4()),
                        "user_id": inactive_user_id,
                        "role_id": role_id,
                        "assigned_by": assigned_by,
                        "source": source,
                        "reason": reason,
                    },
                )

        with pytest.raises(DBAPIError) as user_activation_error:
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE users SET status = 'active' WHERE id = :id"),
                    {"id": inactive_user_id},
                )
        assert safe_database_error_signature(user_activation_error.value)[0] == "23514"
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT status FROM users WHERE id = :id"),
                    {"id": inactive_user_id},
                ).scalar_one()
                == "disabled"
            )

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE roles SET is_enabled = FALSE WHERE code = 'finance_reviewer'")
            )
            for role_id, source, assigned_by, reason in (
                (
                    subjects["system_admin_role_id"],
                    "bootstrap",
                    None,
                    "system_bootstrap",
                ),
                (
                    subjects["finance_reviewer_role_id"],
                    "user",
                    subjects["requester_id"],
                    "disabled role review",
                ),
            ):
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assigned_by, assignment_source, "
                        "assignment_reason) VALUES ("
                        ":id, :user_id, :role_id, :assigned_by, :source, :reason)"
                    ),
                    {
                        "id": str(uuid4()),
                        "user_id": role_user_id,
                        "role_id": role_id,
                        "assigned_by": assigned_by,
                        "source": source,
                        "reason": reason,
                    },
                )
        with pytest.raises(DBAPIError) as role_enable_error:
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE roles SET is_enabled = TRUE WHERE code = 'finance_reviewer'")
                )
        assert safe_database_error_signature(role_enable_error.value)[0] == "23514"
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT is_enabled FROM roles WHERE code = 'finance_reviewer'")
                ).scalar_one()
                is False
            )

        with engine.begin() as connection:
            finance_assignment_id = connection.execute(
                text(
                    "SELECT assignment.id FROM user_roles AS assignment "
                    "JOIN roles AS role ON role.id = assignment.role_id "
                    "WHERE assignment.user_id = :user_id "
                    "AND role.code = 'finance_reviewer'"
                ),
                {"user_id": role_user_id},
            ).scalar_one()
            connection.execute(
                text(
                    "UPDATE user_roles SET revoked_by = :actor, "
                    "revoke_reason = 'resolve role conflict' WHERE id = :id"
                ),
                {"actor": subjects["requester_id"], "id": finance_assignment_id},
            )
            connection.execute(
                text("UPDATE roles SET is_enabled = TRUE WHERE code = 'finance_reviewer'")
            )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO user_roles ("
                    "id, user_id, role_id, assignment_source, assignment_reason) "
                    "VALUES (:id, :user_id, :role_id, 'bootstrap', 'system_bootstrap')"
                ),
                {
                    "id": str(uuid4()),
                    "user_id": future_user_id,
                    "role_id": subjects["system_admin_role_id"],
                },
            )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO user_roles ("
                    "id, user_id, role_id, assigned_by, assignment_source, "
                    "assignment_reason) VALUES ("
                    ":id, :user_id, :role_id, :actor, 'user', 'reverse audit review')"
                ),
                {
                    "id": str(uuid4()),
                    "user_id": reverse_user_id,
                    "role_id": subjects["audit_reviewer_role_id"],
                    "actor": subjects["requester_id"],
                },
            )
        reverse_admin_assignment_id = str(uuid4())
        with pytest.raises(DBAPIError) as reverse_order_sod_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assignment_source, assignment_reason) "
                        "VALUES (:id, :user_id, :role_id, 'bootstrap', 'system_bootstrap')"
                    ),
                    {
                        "id": reverse_admin_assignment_id,
                        "user_id": reverse_user_id,
                        "role_id": subjects["system_admin_role_id"],
                    },
                )
        assert safe_database_error_signature(reverse_order_sod_error.value) == (
            "23514",
            None,
        )
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE user_id = :id"),
                    {"id": reverse_user_id},
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE id = :id"),
                    {"id": reverse_admin_assignment_id},
                ).scalar_one()
                == 0
            )

        future_assignment_id = str(uuid4())
        with pytest.raises(DBAPIError) as future_assignment_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assigned_by, assignment_source, assigned_at, "
                        "assignment_reason) VALUES ("
                        ":id, :user_id, :role_id, :actor, 'user', "
                        "clock_timestamp() + interval '1 day', 'future caller role')"
                    ),
                    {
                        "id": future_assignment_id,
                        "user_id": future_user_id,
                        "role_id": subjects["finance_reviewer_role_id"],
                        "actor": subjects["requester_id"],
                    },
                )
        assert safe_database_error_signature(future_assignment_error.value)[0] == "23514"
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE id = :id"),
                    {"id": future_assignment_id},
                ).scalar_one()
                == 0
            )

        governance_subjects = dict(subjects)
        governance_subjects["target_id"] = subjects["requester_id"]
        with engine.begin() as connection:
            temporary_finance_request = insert_pending_break_glass_request(
                connection,
                governance_subjects,
            )
        with engine.begin() as connection:
            approve_break_glass_request_with_role(
                connection,
                governance_subjects,
                temporary_finance_request,
            )

        temporary_admin_subjects = dict(subjects)
        temporary_admin_subjects["target_id"] = temporary_admin_id
        with engine.begin() as connection:
            temporary_admin_request = insert_pending_break_glass_request(
                connection,
                temporary_admin_subjects,
                target_role_code="system_admin",
            )
        with engine.begin() as connection:
            approve_break_glass_request_with_role(
                connection,
                temporary_admin_subjects,
                temporary_admin_request,
                target_role_code="system_admin",
            )

        chained_request_id = str(uuid4())
        with pytest.raises(DBAPIError) as temporary_admin_governance_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO break_glass_requests ("
                        "id, organization_id, target_user_id, target_role_code, requested_by, "
                        "reason, requested_duration_seconds, status, trace_id) VALUES ("
                        ":id, :organization_id, :target_id, 'contract_admin', :requested_by, "
                        "'temporary admin must not govern', 60, 'pending', :trace_id)"
                    ),
                    {
                        "id": chained_request_id,
                        "organization_id": subjects["organization_id"],
                        "target_id": subjects["target_id"],
                        "requested_by": temporary_admin_id,
                        "trace_id": str(uuid4()),
                    },
                )
        assert safe_database_error_signature(temporary_admin_governance_error.value)[0] == ("23514")
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM break_glass_requests WHERE id = :id"),
                    {"id": chained_request_id},
                ).scalar_one()
                == 0
            )

        with engine.begin() as connection:
            self_approval_request = insert_pending_break_glass_request(
                connection,
                subjects,
                target_role_code="contract_admin",
            )
        with pytest.raises(DBAPIError) as self_approval_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE break_glass_requests SET status = 'approved', "
                        "decided_by = :requester, decision_reason = 'self approval', "
                        "row_version = row_version + 1 WHERE id = :id"
                    ),
                    {"requester": subjects["requester_id"], "id": self_approval_request},
                )
        assert safe_database_error_signature(self_approval_error.value)[0] == "23514"
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status, row_version FROM break_glass_requests WHERE id = :id"),
                {"id": self_approval_request},
            ).one() == ("pending", 1)

        with engine.begin() as connection:
            disabled_role_request = insert_pending_break_glass_request(
                connection,
                subjects,
                target_role_code="contract_admin",
            )
            connection.execute(
                text("UPDATE roles SET is_enabled = FALSE WHERE code = 'contract_admin'")
            )
        with pytest.raises(DBAPIError) as disabled_role_approval_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE break_glass_requests SET status = 'approved', "
                        "decided_by = :decider, decision_reason = 'disabled role', "
                        "row_version = row_version + 1 WHERE id = :id"
                    ),
                    {"decider": subjects["decider_id"], "id": disabled_role_request},
                )
        assert safe_database_error_signature(disabled_role_approval_error.value)[0] == "23514"
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT status, row_version FROM break_glass_requests WHERE id = :id"),
                {"id": disabled_role_request},
            ).one() == ("pending", 1)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE roles SET is_enabled = TRUE WHERE code = 'contract_admin'")
            )
    finally:
        clear_privileged_auth_subjects(database_url, subjects)
        engine.dispose()


def test_privileged_auth_gist_half_open_history_and_concurrent_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_privileged_auth_revision(database_url, alembic_config)
    subjects = seed_privileged_auth_subjects(database_url)
    engine = create_migration_engine(database_url)
    base_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
    long_term_overlap_user_id = str(uuid4())

    def insert_interval_probe(
        connection: Connection,
        *,
        start_at: datetime,
        end_at: datetime,
        role_code: str = "finance_reviewer",
        status: str = "expired",
        revoked_at: datetime | None = None,
        target_user_id: str | None = None,
    ) -> tuple[str, str]:
        request_id = str(uuid4())
        assignment_id = str(uuid4())
        selected_target_user_id = target_user_id or subjects["target_id"]
        role_id = connection.execute(
            text("SELECT id FROM roles WHERE code = :code"),
            {"code": role_code},
        ).scalar_one()
        duration_seconds = int((end_at - start_at).total_seconds())
        connection.execute(
            text(
                "INSERT INTO break_glass_requests ("
                "id, organization_id, target_user_id, target_role_code, requested_by, "
                "reason, requested_duration_seconds, status, effective_from, expires_at, "
                "decided_by, decision_at, decision_reason, revoked_by, revoked_at, "
                "revoke_reason, row_version, created_at, updated_at, trace_id) VALUES ("
                ":id, :organization_id, :target_id, :role_code, :requester_id, "
                "'synthetic interval probe', :duration_seconds, :status, :start_at, :end_at, "
                ":decider_id, :start_at, 'synthetic interval approval', :revoked_by, "
                ":revoked_at, :revoke_reason, :row_version, :created_at, "
                ":updated_at, :trace_id)"
            ),
            {
                "id": request_id,
                "organization_id": subjects["organization_id"],
                "target_id": selected_target_user_id,
                "role_code": role_code,
                "requester_id": subjects["requester_id"],
                "duration_seconds": duration_seconds,
                "status": status,
                "start_at": start_at,
                "end_at": end_at,
                "decider_id": subjects["decider_id"],
                "revoked_by": subjects["requester_id"] if revoked_at else None,
                "revoked_at": revoked_at,
                "revoke_reason": "synthetic interval revoke" if revoked_at else None,
                "row_version": 2 if status == "approved" else 3,
                "created_at": start_at - timedelta(seconds=1),
                "updated_at": (
                    start_at if status == "approved" else revoked_at if revoked_at else end_at
                ),
                "trace_id": str(uuid4()),
            },
        )
        connection.execute(
            text(
                "INSERT INTO user_roles ("
                "id, user_id, role_id, assigned_by, assignment_source, assigned_at, "
                "expires_at, break_glass_request_id, assignment_reason, revoked_at, "
                "revoked_by, revoke_reason) VALUES ("
                ":id, :user_id, :role_id, :assigned_by, 'break_glass', :start_at, "
                ":end_at, :request_id, 'synthetic interval approval', :revoked_at, "
                ":revoked_by, :revoke_reason)"
            ),
            {
                "id": assignment_id,
                "user_id": selected_target_user_id,
                "role_id": role_id,
                "assigned_by": subjects["decider_id"],
                "start_at": start_at,
                "end_at": end_at,
                "request_id": request_id,
                "revoked_at": revoked_at,
                "revoked_by": subjects["requester_id"] if revoked_at else None,
                "revoke_reason": "synthetic interval revoke" if revoked_at else None,
            },
        )
        return request_id, assignment_id

    try:
        with engine.begin() as connection:
            overlap_username = f"synthetic-long-term-overlap-{uuid4().hex[:8]}"
            connection.execute(
                text(
                    "INSERT INTO users ("
                    "id, organization_id, username, display_name, password_hash, status, "
                    "password_changed_at) VALUES ("
                    ":id, :organization_id, :username, :display_name, "
                    "'synthetic-not-a-real-password-hash', 'active', now())"
                ),
                {
                    "id": long_term_overlap_user_id,
                    "organization_id": subjects["organization_id"],
                    "username": overlap_username,
                    "display_name": "Synthetic long term overlap",
                },
            )
            connection.execute(text("ALTER TABLE break_glass_requests DISABLE TRIGGER USER"))
            connection.execute(text("ALTER TABLE user_roles DISABLE TRIGGER USER"))
            insert_interval_probe(
                connection,
                start_at=base_time,
                end_at=base_time + timedelta(hours=1),
            )
            insert_interval_probe(
                connection,
                start_at=base_time + timedelta(hours=1),
                end_at=base_time + timedelta(hours=2),
            )
            insert_interval_probe(
                connection,
                start_at=base_time + timedelta(minutes=15),
                end_at=base_time + timedelta(minutes=45),
                status="revoked",
                revoked_at=base_time + timedelta(minutes=30),
            )
            insert_interval_probe(
                connection,
                start_at=base_time + timedelta(minutes=30),
                end_at=base_time + timedelta(hours=1, minutes=30),
                role_code="audit_reviewer",
            )
            insert_interval_probe(
                connection,
                start_at=base_time + timedelta(hours=3),
                end_at=base_time + timedelta(hours=4),
            )
            _, revoked_history_assignment_id = insert_interval_probe(
                connection,
                start_at=base_time + timedelta(hours=5),
                end_at=base_time + timedelta(hours=6),
                status="revoked",
                revoked_at=base_time + timedelta(hours=5, minutes=30),
            )
            _, replacement_assignment_id = insert_interval_probe(
                connection,
                start_at=base_time + timedelta(hours=5),
                end_at=base_time + timedelta(hours=6),
            )
            finite_start = datetime.now(timezone.utc) - timedelta(minutes=1)
            _, finite_assignment_id = insert_interval_probe(
                connection,
                start_at=finite_start,
                end_at=finite_start + timedelta(hours=1),
                status="approved",
                target_user_id=long_term_overlap_user_id,
            )
            connection.execute(text("ALTER TABLE user_roles ENABLE TRIGGER USER"))
            connection.execute(text("ALTER TABLE break_glass_requests ENABLE TRIGGER USER"))

        with engine.connect() as connection:
            replacement_rows = connection.execute(
                text(
                    "SELECT id, revoked_at FROM user_roles "
                    "WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY id"
                ),
                {"ids": [revoked_history_assignment_id, replacement_assignment_id]},
            ).all()
            assert len(replacement_rows) == 2
            assert sum(row.revoked_at is None for row in replacement_rows) == 1

        long_term_assignment_id = str(uuid4())
        with pytest.raises(DBAPIError) as long_term_overlap_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO user_roles ("
                        "id, user_id, role_id, assigned_by, assignment_source, "
                        "assignment_reason) VALUES ("
                        ":id, :user_id, :role_id, :assigned_by, 'user', "
                        "'long term overlap probe')"
                    ),
                    {
                        "id": long_term_assignment_id,
                        "user_id": long_term_overlap_user_id,
                        "role_id": subjects["finance_reviewer_role_id"],
                        "assigned_by": subjects["requester_id"],
                    },
                )
        assert safe_database_error_signature(long_term_overlap_error.value) == (
            "23P01",
            "ex_user_roles_effective_range_no_overlap",
        )
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE id = :id"),
                    {"id": long_term_assignment_id},
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE id = :id"),
                    {"id": finite_assignment_id},
                ).scalar_one()
                == 1
            )

        with pytest.raises(DBAPIError) as overlap_error:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE break_glass_requests DISABLE TRIGGER USER"))
                connection.execute(text("ALTER TABLE user_roles DISABLE TRIGGER USER"))
                insert_interval_probe(
                    connection,
                    start_at=base_time + timedelta(minutes=30),
                    end_at=base_time + timedelta(hours=1, minutes=30),
                )
        assert safe_database_error_signature(overlap_error.value) == (
            "23P01",
            "ex_user_roles_effective_range_no_overlap",
        )
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM user_roles AS assignment "
                        "JOIN roles AS role ON role.id = assignment.role_id "
                        "WHERE assignment.user_id = :user_id "
                        "AND role.code = 'finance_reviewer'"
                    ),
                    {"user_id": subjects["target_id"]},
                ).scalar_one()
                == 6
            )

        concurrent_user_id = str(uuid4())
        with engine.begin() as connection:
            username = f"synthetic-concurrent-{uuid4().hex[:10]}"
            connection.execute(
                text(
                    "INSERT INTO users ("
                    "id, organization_id, username, display_name, password_hash, status, "
                    "password_changed_at) VALUES ("
                    ":id, :organization_id, :username, :display_name, "
                    "'synthetic-not-a-real-password-hash', 'active', now())"
                ),
                {
                    "id": concurrent_user_id,
                    "organization_id": subjects["organization_id"],
                    "username": username,
                    "display_name": username,
                },
            )

        barrier = Barrier(2)

        def insert_concurrent_role(sequence: int) -> tuple[str, str]:
            worker_engine = create_migration_engine(database_url)
            assignment_id = str(uuid4())
            try:
                with worker_engine.begin() as connection:
                    barrier.wait(timeout=10)
                    connection.execute(
                        text(
                            "INSERT INTO user_roles ("
                            "id, user_id, role_id, assigned_by, assignment_source, "
                            "assignment_reason) VALUES ("
                            ":id, :user_id, :role_id, :assigned_by, 'user', :reason)"
                        ),
                        {
                            "id": assignment_id,
                            "user_id": concurrent_user_id,
                            "role_id": subjects["finance_reviewer_role_id"],
                            "assigned_by": subjects["requester_id"],
                            "reason": f"concurrent role {sequence}",
                        },
                    )
                return "ok", assignment_id
            except DBAPIError as error:
                return safe_database_error_signature(error)[0] or "unknown", assignment_id
            finally:
                worker_engine.dispose()

        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent_results = tuple(executor.map(insert_concurrent_role, (1, 2)))
        concurrent_statuses = sorted(result[0] for result in concurrent_results)
        assert concurrent_statuses[1] == "ok"
        assert concurrent_statuses[0] in {"23P01", "40P01"}
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM user_roles WHERE user_id = :user_id"),
                    {"user_id": concurrent_user_id},
                ).scalar_one()
                == 1
            )
    finally:
        clear_privileged_auth_subjects(database_url, subjects)
        engine.dispose()


@pytest.mark.parametrize(
    ("occupancy", "expected_request_rows", "expected_assignment_rows"),
    (("bgr_only", 1, 0), ("ur_only", 0, 2), ("both", 1, 2)),
)
def test_privileged_auth_each_nonempty_shape_blocks_downgrade_atomically(
    monkeypatch: pytest.MonkeyPatch,
    occupancy: str,
    expected_request_rows: int,
    expected_assignment_rows: int,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_privileged_auth_revision(database_url, alembic_config)
    subjects = seed_privileged_auth_subjects(database_url)
    engine = create_migration_engine(database_url)
    try:
        if occupancy in {"bgr_only", "both"}:
            with engine.begin() as connection:
                insert_pending_break_glass_request(connection, subjects)
        if occupancy == "bgr_only":
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE user_roles DISABLE TRIGGER USER"))
                connection.execute(
                    text(
                        "DELETE FROM user_roles WHERE user_id IN ("
                        "SELECT id FROM users WHERE organization_id = :organization_id)"
                    ),
                    {"organization_id": subjects["organization_id"]},
                )
                connection.execute(text("ALTER TABLE user_roles ENABLE TRIGGER USER"))

        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM break_glass_requests")).scalar_one()
                == expected_request_rows
            )
            assert connection.execute(text("SELECT count(*) FROM user_roles")).scalar_one() == (
                expected_assignment_rows
            )
        before_relations = public_relation_manifest(
            database_url,
            ("break_glass_requests", "user_roles", "users", "roles"),
        )
        before_functions = privileged_auth_function_manifest(database_url)
        assert current_revision(database_url) == PRIVILEGED_AUTH_REVISION

        with pytest.raises(DBAPIError) as downgrade_error:
            command.downgrade(alembic_config, RELIABILITY_REVISION)
        assert safe_database_error_signature(downgrade_error.value)[0] == "55000"

        assert current_revision(database_url) == PRIVILEGED_AUTH_REVISION
        assert (
            public_relation_manifest(
                database_url,
                ("break_glass_requests", "user_roles", "users", "roles"),
            )
            == before_relations
        )
        assert privileged_auth_function_manifest(database_url) == before_functions
    finally:
        clear_privileged_auth_subjects(database_url, subjects)
        engine.dispose()


@pytest.mark.parametrize(
    "locked_table",
    ("break_glass_requests", "user_roles", "users", "roles"),
)
def test_privileged_auth_downgrade_lock_timeout_is_bounded_and_atomic(
    monkeypatch: pytest.MonkeyPatch,
    locked_table: str,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_privileged_auth_revision(database_url, alembic_config)
    before_relations = public_relation_manifest(
        database_url,
        ("break_glass_requests", "user_roles", "users", "roles"),
    )
    before_functions = privileged_auth_function_manifest(database_url)
    holder_engine = create_migration_engine(database_url)
    holder_connection = holder_engine.connect()
    holder_transaction = holder_connection.begin()
    try:
        holder_connection.execute(text(f"LOCK TABLE public.{locked_table} IN ACCESS SHARE MODE"))
        started_at = monotonic()
        with pytest.raises(DBAPIError) as downgrade_error:
            command.downgrade(alembic_config, RELIABILITY_REVISION)
        elapsed_seconds = monotonic() - started_at
        assert safe_database_error_signature(downgrade_error.value)[0] == "55P03"
        assert 4.0 <= elapsed_seconds < 12.0
        assert current_revision(database_url) == PRIVILEGED_AUTH_REVISION
        assert (
            public_relation_manifest(
                database_url,
                ("break_glass_requests", "user_roles", "users", "roles"),
            )
            == before_relations
        )
        assert privileged_auth_function_manifest(database_url) == before_functions
    finally:
        holder_transaction.rollback()
        holder_connection.close()
        holder_engine.dispose()


def test_reliability_revision_declares_exactly_four_functions() -> None:
    revision_source = (
        BACKEND_ROOT / "alembic" / "versions" / "20260807_007_create_reliability_core.py"
    ).read_text(encoding="utf-8")
    created_functions = re.findall(
        r"(?m)^\s*CREATE FUNCTION ([a-z][a-z0-9_]*)\(\)",
        revision_source,
    )
    assert len(created_functions) == 4
    assert set(created_functions) == RELIABILITY_FUNCTIONS


def test_reliability_postgresql_catalog_is_exact_and_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)

    assert current_revision(database_url) == CURRENT_REVISION
    assert installed_baseline_tables(database_url) == CURRENT_HEAD_TABLES
    assert tuple(len(RELIABILITY_COLUMN_CONTRACT[name]) for name in RELIABILITY_TABLES) == (
        33,
        11,
        15,
    )
    for table_name, expected_columns in RELIABILITY_COLUMN_CONTRACT.items():
        observed_columns = reliability_column_contract(database_url, table_name)
        assert tuple(column[:4] for column in observed_columns) == expected_columns
        expected_constraints = {
            name: (kind, True, False, False, definition)
            for name, (kind, definition) in RELIABILITY_CONSTRAINTS[table_name].items()
        }
        assert reliability_constraint_contract(database_url, table_name) == expected_constraints
        assert table_row_count(database_url, table_name) == 0

    defaults = {
        table_name: {
            column_name: default
            for column_name, _, _, _, default in reliability_column_contract(
                database_url, table_name
            )
            if default is not None
        }
        for table_name in RELIABILITY_TABLES
    }
    assert defaults == {
        "async_jobs": {
            "id": "gen_random_uuid()",
            "attempt_no": "0",
            "row_version": "'1'::bigint",
            "created_at": "now()",
        },
        "async_job_steps": {"id": "gen_random_uuid()", "summary_json": "'{}'::jsonb"},
        "outbox_events": {
            "id": "gen_random_uuid()",
            "attempt_count": "0",
            "created_at": "now()",
        },
    }

    indexes = {
        table_name: reliability_index_contract(database_url, table_name)
        for table_name in RELIABILITY_TABLES
    }
    assert indexes == RELIABILITY_INDEX_CONTRACT

    functions = reliability_function_contract(database_url)
    assert set(functions) == RELIABILITY_FUNCTION_IDENTITIES
    assert {contract[:6] for contract in functions.values()} == {
        (0, "trigger", "plpgsql", False, "v", "f")
    }
    function_sql = "\n".join(contract[-1] for contract in functions.values())
    for required_semantic in (
        "unsupported async job lease policy",
        "cancel request must preserve async job fencing",
        "invalid async job step lease recovery terminal",
        "active attempt contains an invalid prior terminal step",
        "terminal attempt contains an invalid prior step",
        "DELIVERY_ATTEMPTS_EXHAUSTED",
        "UNKNOWN_DELIVERY_ERROR",
    ):
        assert required_semantic in function_sql
    triggers = reliability_trigger_contract(database_url)
    assert triggers == RELIABILITY_TRIGGER_CONTRACT


def test_reliability_empty_round_trip_and_each_nonempty_table_blocks_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)

    for _ in range(2):
        command.downgrade(alembic_config, FINANCIAL_REVISION)
        assert current_revision(database_url) == FINANCIAL_REVISION
        assert installed_baseline_tables(database_url) == TABLES_AT_006
        command.upgrade(alembic_config, CURRENT_REVISION)
        assert current_revision(database_url) == CURRENT_REVISION
        assert installed_baseline_tables(database_url) == CURRENT_HEAD_TABLES
        assert all(
            table_row_count(database_url, table_name) == 0 for table_name in RELIABILITY_TABLES
        )

    for table_name in RELIABILITY_TABLES:
        seed_reliability_organization(database_url)
        if table_name == "async_jobs":
            insert_queued_job(database_url)
        elif table_name == "async_job_steps":
            job_id = insert_queued_job(database_url)
            claim_job_with_step(database_url, job_id)
        else:
            execute_database_statement(
                database_url,
                """
                INSERT INTO outbox_events (
                    aggregate_type, aggregate_id, event_id, event_type,
                    event_version, event_sequence, payload_json, status, trace_id
                ) VALUES (
                    'synthetic', :aggregate_id, :event_id, 'synthetic.created',
                    1, 1, '{}'::jsonb, 'pending', :trace_id
                )
                """,
                {
                    "aggregate_id": str(uuid4()),
                    "event_id": str(uuid4()),
                    "trace_id": str(uuid4()),
                },
            )

        with pytest.raises(DBAPIError) as error_info:
            command.downgrade(alembic_config, FINANCIAL_REVISION)
        assert safe_database_error_signature(error_info.value)[0] == "55000"
        assert current_revision(database_url) == CURRENT_REVISION
        assert installed_baseline_tables(database_url) == CURRENT_HEAD_TABLES
        assert table_row_count(database_url, table_name) == 1
        clear_reliability_test_data(database_url)


@pytest.mark.parametrize("locked_table", RELIABILITY_TABLES)
def test_reliability_downgrade_lock_timeout_is_bounded_and_atomic(
    monkeypatch: pytest.MonkeyPatch,
    locked_table: str,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    holder_engine = create_migration_engine(database_url)
    holder_connection = holder_engine.connect()
    holder_transaction = holder_connection.begin()
    try:
        holder_connection.execute(text(f"LOCK TABLE {locked_table} IN ACCESS SHARE MODE"))
        started_at = monotonic()
        with pytest.raises(DBAPIError) as error_info:
            command.downgrade(alembic_config, FINANCIAL_REVISION)
        elapsed_seconds = monotonic() - started_at
        assert safe_database_error_signature(error_info.value)[0] == "55P03"
        assert 4.0 <= elapsed_seconds < 12.0
        assert current_revision(database_url) == CURRENT_REVISION
        assert installed_baseline_tables(database_url) == CURRENT_HEAD_TABLES
        assert set(reliability_function_contract(database_url)) == (RELIABILITY_FUNCTION_IDENTITIES)
    finally:
        holder_transaction.rollback()
        holder_connection.close()
        holder_engine.dispose()


def test_reliability_upgrade_fault_injection_rolls_back_every_object_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    command.downgrade(alembic_config, FINANCIAL_REVISION)
    upgrade_stages = tuple(("table", name) for name in RELIABILITY_TABLES) + tuple(
        ("sql", marker)
        for marker in (
            *(f"CREATE FUNCTION {name}" for name in sorted(RELIABILITY_FUNCTIONS)),
            "CREATE TRIGGER trg_async_jobs_state_v1",
            "CREATE CONSTRAINT TRIGGER trg_async_jobs_consistency_v1",
            "CREATE TRIGGER trg_async_job_steps_state_v1",
            "CREATE TRIGGER trg_async_job_steps_no_truncate_v1",
            "CREATE CONSTRAINT TRIGGER trg_async_job_steps_consistency_v1",
            "CREATE TRIGGER trg_outbox_events_state_v1",
            "CREATE TRIGGER trg_outbox_events_no_truncate_v1",
        )
    )
    original_create_table = cast(Callable[..., object], alembic_op.create_table)
    original_execute = cast(Callable[..., object], alembic_op.execute)

    for stage_kind, stage_marker in upgrade_stages:
        with monkeypatch.context() as stage_patch:

            def create_table(
                table_name: str,
                *args: object,
                _stage_kind: str = stage_kind,
                _stage_marker: str = stage_marker,
                **kwargs: object,
            ) -> object:
                result = original_create_table(table_name, *args, **kwargs)
                if _stage_kind == "table" and table_name == _stage_marker:
                    raise InjectedMigrationFailure("injected reliability upgrade failure")
                return result

            def execute(
                statement: object,
                *args: object,
                _stage_kind: str = stage_kind,
                _stage_marker: str = stage_marker,
                **kwargs: object,
            ) -> object:
                result = original_execute(statement, *args, **kwargs)
                if _stage_kind == "sql" and _stage_marker in str(statement):
                    raise InjectedMigrationFailure("injected reliability upgrade failure")
                return result

            stage_patch.setattr(alembic_op, "create_table", create_table)
            stage_patch.setattr(alembic_op, "execute", execute)
            with pytest.raises(InjectedMigrationFailure):
                command.upgrade(alembic_config, CURRENT_REVISION)

        assert current_revision(database_url) == FINANCIAL_REVISION
        assert installed_baseline_tables(database_url) == TABLES_AT_006
        assert reliability_function_contract(database_url) == {}

    command.upgrade(alembic_config, CURRENT_REVISION)
    assert current_revision(database_url) == CURRENT_REVISION


def test_reliability_downgrade_fault_injection_preserves_every_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    downgrade_stages = tuple(("table", name) for name in reversed(RELIABILITY_TABLES)) + tuple(
        ("sql", f"DROP FUNCTION {name}") for name in RELIABILITY_FUNCTIONS
    )
    original_drop_table = cast(Callable[..., object], alembic_op.drop_table)
    original_execute = cast(Callable[..., object], alembic_op.execute)

    for stage_kind, stage_marker in downgrade_stages:
        with monkeypatch.context() as stage_patch:

            def drop_table(
                table_name: str,
                *args: object,
                _stage_kind: str = stage_kind,
                _stage_marker: str = stage_marker,
                **kwargs: object,
            ) -> object:
                result = original_drop_table(table_name, *args, **kwargs)
                if _stage_kind == "table" and table_name == _stage_marker:
                    raise InjectedMigrationFailure("injected reliability downgrade failure")
                return result

            def execute(
                statement: object,
                *args: object,
                _stage_kind: str = stage_kind,
                _stage_marker: str = stage_marker,
                **kwargs: object,
            ) -> object:
                result = original_execute(statement, *args, **kwargs)
                if _stage_kind == "sql" and _stage_marker in str(statement):
                    raise InjectedMigrationFailure("injected reliability downgrade failure")
                return result

            stage_patch.setattr(alembic_op, "drop_table", drop_table)
            stage_patch.setattr(alembic_op, "execute", execute)
            with pytest.raises(InjectedMigrationFailure):
                command.downgrade(alembic_config, FINANCIAL_REVISION)

        assert current_revision(database_url) == CURRENT_REVISION
        assert installed_baseline_tables(database_url) == CURRENT_HEAD_TABLES
        assert set(reliability_function_contract(database_url)) == (RELIABILITY_FUNCTION_IDENTITIES)
        assert {
            table_name: set(definitions)
            for table_name, definitions in reliability_trigger_contract(database_url).items()
        } == RELIABILITY_TRIGGERS

    command.downgrade(alembic_config, FINANCIAL_REVISION)
    assert current_revision(database_url) == FINANCIAL_REVISION
    command.upgrade(alembic_config, CURRENT_REVISION)


def test_reliability_unknown_lease_policy_is_fail_closed_but_expired_cancel_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)
    try:
        queued_unknown_job = insert_queued_job(
            database_url,
            lease_policy_version="unknown-policy",
            lease_policy_hash="f" * 64,
        )
        assert (
            call_expect_database_error(
                lambda: claim_job_with_step(database_url, queued_unknown_job)
            )[0]
            == "23514"
        )

        active_unknown_job = insert_queued_job(database_url)
        claim_job_with_step(database_url, active_unknown_job)
        replace_active_job_policy_with_unknown(database_url, active_unknown_job)
        heartbeat_statement = (
            "UPDATE async_jobs SET heartbeat_at = clock_timestamp(), "
            "lease_expires_at = clock_timestamp() + interval '60 seconds', "
            "row_version = row_version + 1 WHERE id = :job_id"
        )
        assert (
            execute_expect_database_error(
                database_url, heartbeat_statement, {"job_id": active_unknown_job}
            )[0]
            == "23514"
        )

        expire_active_job_lease(database_url, active_unknown_job)
        assert (
            execute_expect_database_error(
                database_url,
                """
            UPDATE async_jobs SET
                attempt_no = attempt_no + 1,
                stage = current_attempt_start_step_code,
                worker_id = 'recovery-worker',
                row_version = row_version + 1
            WHERE id = :job_id
            """,
                {"job_id": active_unknown_job},
            )[0]
            == "23514"
        )

        execute_database_statement(
            database_url,
            "UPDATE async_jobs SET status = 'cancel_requested', "
            "row_version = row_version + 1 WHERE id = :job_id",
            {"job_id": active_unknown_job},
        )
        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT status FROM async_jobs WHERE id = :job_id"),
                        {"job_id": active_unknown_job},
                    ).scalar_one()
                    == "cancel_requested"
                )
        finally:
            engine.dispose()
    finally:
        clear_reliability_test_data(database_url)


def test_reliability_job_cas_identity_and_database_state_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)
    try:
        guarded_job = insert_queued_job(database_url)
        for row_version_assignment in (
            "row_version = row_version",
            "row_version = row_version + 2",
        ):
            assert (
                execute_expect_database_error(
                    database_url,
                    f"UPDATE async_jobs SET {row_version_assignment} WHERE id = :job_id",
                    {"job_id": guarded_job},
                )[0]
                == "23514"
            )

        immutable_assignments = (
            "input_hash = repeat('c', 64)",
            "input_json = jsonb_build_object('synthetic', false)",
            "input_schema_version = 2",
            "handler_registry_version = 'mutated'",
            "handler_registry_hash = repeat('c', 64)",
            "retry_policy_version = 'mutated'",
            "retry_policy_hash = repeat('c', 64)",
            "lease_policy_version = 'mutated'",
            "lease_policy_hash = repeat('c', 64)",
        )
        for assignment in immutable_assignments:
            assert (
                execute_expect_database_error(
                    database_url,
                    f"UPDATE async_jobs SET {assignment}, row_version = row_version + 1 "
                    "WHERE id = :job_id",
                    {"job_id": guarded_job},
                )[0]
                == "23514"
            )

        for terminal_status, terminal_error in (
            ("cancelled", "JOB_CANCELLED"),
            ("failed", "JOB_DISPATCH_FAILED"),
        ):
            assert (
                execute_expect_database_error(
                    database_url,
                    "UPDATE async_jobs SET status = :status, "
                    "finished_at = clock_timestamp() + interval '1 hour', "
                    "error_code = :error_code, row_version = row_version + 1 "
                    "WHERE id = :job_id",
                    {
                        "error_code": terminal_error,
                        "job_id": guarded_job,
                        "status": terminal_status,
                    },
                )[0]
                == "23514"
            )

        cancelled_job = insert_queued_job(database_url)
        execute_database_statement(
            database_url,
            "UPDATE async_jobs SET status = 'cancelled', finished_at = clock_timestamp(), "
            "error_code = 'JOB_CANCELLED', row_version = row_version + 1 "
            "WHERE id = :job_id",
            {"job_id": cancelled_job},
        )

        dispatch_failed_jobs: list[str] = []
        for dispatch_error in (
            "JOB_DISPATCH_FAILED",
            "JOB_DISPATCH_OUTCOME_UNKNOWN",
        ):
            dispatch_failed_job = insert_queued_job(database_url)
            dispatch_failed_jobs.append(dispatch_failed_job)
            execute_database_statement(
                database_url,
                "UPDATE async_jobs SET status = 'failed', "
                "finished_at = clock_timestamp(), error_code = :error_code, "
                "error_message = 'synthetic dispatch finalizer', "
                "row_version = row_version + 1 WHERE id = :job_id",
                {"error_code": dispatch_error, "job_id": dispatch_failed_job},
            )

        retry_job = insert_queued_job(database_url, max_attempts=2)
        retry_step = claim_job_with_step(database_url, retry_job)
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                finished_at = connection.execute(text("SELECT clock_timestamp()"))
                finished_at = finished_at.scalar_one()
                connection.execute(
                    text(
                        "UPDATE async_job_steps SET status = 'failed', "
                        "finished_at = :finished_at, error_code = 'DATABASE_TRANSIENT' "
                        "WHERE id = :step_id"
                    ),
                    {"finished_at": finished_at, "step_id": retry_step},
                )
                connection.execute(
                    text(
                        "UPDATE async_jobs SET status = 'failed', "
                        "finished_at = :finished_at, error_code = 'DATABASE_TRANSIENT', "
                        "error_message = 'synthetic transient', next_retry_at = :finished_at, "
                        "worker_id = NULL, lease_owner = NULL, lease_expires_at = NULL, "
                        "heartbeat_at = NULL, row_version = row_version + 1 "
                        "WHERE id = :job_id"
                    ),
                    {"finished_at": finished_at, "job_id": retry_job},
                )
        finally:
            engine.dispose()
        execute_database_statement(
            database_url,
            "UPDATE async_jobs SET status = 'queued', stage = NULL, next_retry_at = NULL, "
            "started_at = NULL, finished_at = NULL, error_code = NULL, error_message = NULL, "
            "row_version = row_version + 1 WHERE id = :job_id",
            {"job_id": retry_job},
        )

        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                state_rows = connection.execute(
                    text(
                        "SELECT id::text, status FROM async_jobs "
                        "WHERE id = ANY(CAST(:job_ids AS uuid[]))"
                    ),
                    {
                        "job_ids": [
                            cancelled_job,
                            *dispatch_failed_jobs,
                            retry_job,
                        ]
                    },
                ).all()
                states: dict[str, str] = {str(row[0]): str(row[1]) for row in state_rows}
                assert states == {
                    cancelled_job: "cancelled",
                    **{job_id: "failed" for job_id in dispatch_failed_jobs},
                    retry_job: "queued",
                }
        finally:
            engine.dispose()
    finally:
        clear_reliability_test_data(database_url)


def test_reliability_atomic_claim_shares_database_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)
    try:
        job_id = insert_queued_job(database_url)
        started_at, heartbeat_at, lease_expires_at, step_started_at = claim_job_with_step_atomic(
            database_url, job_id
        )
        assert started_at == heartbeat_at == step_started_at
        assert lease_expires_at == started_at + timedelta(seconds=60)
    finally:
        clear_reliability_test_data(database_url)


def test_reliability_job_recovery_is_rejected_during_expiry_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)
    try:
        job_id = insert_queued_job(database_url, max_attempts=2)
        claim_job_with_step(database_url, job_id)
        move_active_job_lease_into_recovery_grace(database_url, job_id)
        assert (
            execute_expect_database_error(
                database_url,
                "WITH recovery_clock AS MATERIALIZED ("
                "SELECT clock_timestamp() AS t) "
                "UPDATE async_jobs SET attempt_no = attempt_no + 1, "
                "stage = current_attempt_start_step_code, worker_id = 'grace-worker', "
                "started_at = recovery_clock.t, heartbeat_at = recovery_clock.t, "
                "lease_expires_at = recovery_clock.t + interval '60 seconds', "
                "row_version = row_version + 1 FROM recovery_clock "
                "WHERE id = :job_id",
                {"job_id": job_id},
            )[0]
            == "23514"
        )
    finally:
        clear_reliability_test_data(database_url)


@pytest.mark.parametrize(
    ("terminal_status", "terminal_error"),
    (("succeeded", None), ("failed", "DEPENDENCY_TIMEOUT"), ("cancelled", "JOB_CANCELLED")),
)
def test_reliability_terminal_transition_preserves_started_at(
    monkeypatch: pytest.MonkeyPatch,
    terminal_status: str,
    terminal_error: str | None,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)
    try:
        job_id = insert_queued_job(database_url)
        step_id = claim_job_with_step(database_url, job_id)
        if terminal_status == "cancelled":
            execute_database_statement(
                database_url,
                "UPDATE async_jobs SET status = 'cancel_requested', "
                "row_version = row_version + 1 WHERE id = :job_id",
                {"job_id": job_id},
            )

        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                original_started_at = connection.execute(
                    text("SELECT started_at FROM async_jobs WHERE id = :job_id"),
                    {"job_id": job_id},
                ).scalar_one()
        finally:
            engine.dispose()

        def terminalize(*, mutate_started_at: bool) -> None:
            transaction_engine = create_migration_engine(database_url)
            try:
                with transaction_engine.begin() as connection:
                    finished_at = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                    connection.execute(
                        text(
                            "UPDATE async_job_steps SET status = :status, "
                            "finished_at = :finished_at, error_code = :error_code "
                            "WHERE id = :step_id"
                        ),
                        {
                            "status": terminal_status,
                            "finished_at": finished_at,
                            "error_code": terminal_error,
                            "step_id": step_id,
                        },
                    )
                    connection.execute(
                        text(
                            "UPDATE async_jobs SET status = :status, "
                            "started_at = CASE WHEN :mutate_started_at "
                            "THEN started_at + interval '1 microsecond' ELSE started_at END, "
                            "finished_at = :finished_at, error_code = :error_code, "
                            "error_message = :error_message, next_retry_at = :next_retry_at, "
                            "worker_id = NULL, lease_owner = NULL, lease_expires_at = NULL, "
                            "heartbeat_at = NULL, row_version = row_version + 1 "
                            "WHERE id = :job_id"
                        ),
                        {
                            "status": terminal_status,
                            "mutate_started_at": mutate_started_at,
                            "finished_at": finished_at,
                            "error_code": terminal_error,
                            "error_message": (
                                "synthetic terminal failure"
                                if terminal_status == "failed"
                                else None
                            ),
                            "next_retry_at": (finished_at if terminal_status == "failed" else None),
                            "job_id": job_id,
                        },
                    )
            finally:
                transaction_engine.dispose()

        assert call_expect_database_error(lambda: terminalize(mutate_started_at=True))[0] == (
            "23514"
        )
        terminalize(mutate_started_at=False)
        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                row = connection.execute(
                    text("SELECT status, started_at FROM async_jobs WHERE id = :job_id"),
                    {"job_id": job_id},
                ).one()
                assert row.status == terminal_status
                assert row.started_at == original_started_at
        finally:
            engine.dispose()
    finally:
        clear_reliability_test_data(database_url)


def test_reliability_step_recovery_codes_follow_attempt_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)
    try:
        retryable_job = insert_queued_job(database_url, max_attempts=2)
        retryable_step = claim_job_with_step(database_url, retryable_job)
        expire_active_job_lease(database_url, retryable_job)
        assert (
            execute_expect_database_error(
                database_url,
                "UPDATE async_job_steps SET status = 'failed', finished_at = clock_timestamp(), "
                "error_code = 'WORKER_LOST' WHERE id = :step_id",
                {"step_id": retryable_step},
            )[0]
            == "23514"
        )

        assert (
            call_expect_database_error(
                lambda: attempt_atomic_recovery_with_invalid_clock(
                    database_url,
                    retryable_job,
                    retryable_step,
                    future_clock=False,
                )
            )[0]
            == "23514"
        )
        assert (
            call_expect_database_error(
                lambda: attempt_atomic_recovery_with_invalid_clock(
                    database_url,
                    retryable_job,
                    retryable_step,
                    future_clock=True,
                )
            )[0]
            == "23514"
        )
        recovery_timestamps = recover_job_with_step_atomic(
            database_url,
            retryable_job,
            retryable_step,
        )
        recovery_time, old_step_finished, job_started, lease_expires, new_step_started = (
            recovery_timestamps
        )
        assert recovery_time == old_step_finished == job_started == new_step_started
        assert lease_expires == recovery_time + timedelta(seconds=60)

        exhausted_job = insert_queued_job(database_url, max_attempts=1)
        exhausted_step = claim_job_with_step(database_url, exhausted_job)
        expire_active_job_lease(database_url, exhausted_job)
        assert (
            execute_expect_database_error(
                database_url,
                "UPDATE async_job_steps SET status = 'failed', finished_at = clock_timestamp(), "
                "error_code = 'LEASE_EXPIRED' WHERE id = :step_id",
                {"step_id": exhausted_step},
            )[0]
            == "23514"
        )

        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                finished_at = connection.execute(text("SELECT clock_timestamp()"))
                finished_at = finished_at.scalar_one()
                connection.execute(
                    text(
                        "UPDATE async_job_steps SET status = 'failed', "
                        "finished_at = :finished_at, error_code = 'WORKER_LOST' "
                        "WHERE id = :step_id"
                    ),
                    {"finished_at": finished_at, "step_id": exhausted_step},
                )
                connection.execute(
                    text(
                        "UPDATE async_jobs SET status = 'failed', "
                        "finished_at = :finished_at, error_code = 'WORKER_LOST', "
                        "error_message = 'synthetic worker loss', next_retry_at = NULL, "
                        "worker_id = NULL, lease_owner = NULL, lease_expires_at = NULL, "
                        "heartbeat_at = NULL, row_version = row_version + 1 "
                        "WHERE id = :job_id"
                    ),
                    {"finished_at": finished_at, "job_id": exhausted_job},
                )
        finally:
            engine.dispose()

        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                retryable_state = connection.execute(
                    text("SELECT status, attempt_no FROM async_jobs WHERE id = :job_id"),
                    {"job_id": retryable_job},
                ).one()
                assert (retryable_state.status, retryable_state.attempt_no) == ("running", 2)
                assert (
                    connection.execute(
                        text("SELECT error_code FROM async_job_steps WHERE id = :step_id"),
                        {"step_id": retryable_step},
                    ).scalar_one()
                    == "LEASE_EXPIRED"
                )
                exhausted_state = connection.execute(
                    text("SELECT status, error_code FROM async_jobs WHERE id = :job_id"),
                    {"job_id": exhausted_job},
                ).one()
                assert (exhausted_state.status, exhausted_state.error_code) == (
                    "failed",
                    "WORKER_LOST",
                )
        finally:
            engine.dispose()
    finally:
        clear_reliability_test_data(database_url)


def test_reliability_adjacent_steps_share_one_database_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)

    def advance_to_second_step(
        job_id: str,
        first_step_id: str,
        *,
        stage_mismatch: bool = False,
        stage_only: bool = False,
        heartbeat_only: bool = False,
        lease_only: bool = False,
        pair_time_mismatch: bool = False,
        adjacent_mismatch: bool = False,
    ) -> tuple[datetime, datetime, datetime, datetime, datetime, str, str]:
        second_step_id = str(uuid4())
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                row = connection.execute(
                    text(
                        "WITH transition_clock AS MATERIALIZED ("
                        "SELECT clock_timestamp() AS t), "
                        "finished_previous AS ("
                        "UPDATE async_job_steps SET status = 'succeeded', "
                        "finished_at = transition_clock.t - CASE "
                        "WHEN :adjacent_mismatch THEN interval '1 millisecond' "
                        "ELSE interval '0 seconds' END FROM transition_clock "
                        "WHERE id = :first_step_id "
                        "RETURNING job_id, step_seq, attempt_no, finished_at), "
                        "advanced_job AS ("
                        "UPDATE async_jobs SET stage = 'execute', "
                        "heartbeat_at = CASE "
                        "WHEN :stage_only OR :lease_only THEN async_jobs.heartbeat_at "
                        "WHEN :pair_time_mismatch THEN "
                        "transition_clock.t - interval '1 millisecond' "
                        "ELSE transition_clock.t END, "
                        "lease_expires_at = CASE "
                        "WHEN :stage_only OR :heartbeat_only THEN async_jobs.lease_expires_at "
                        "WHEN :pair_time_mismatch THEN "
                        "transition_clock.t - interval '1 millisecond' + interval '60 seconds' "
                        "ELSE transition_clock.t + interval '60 seconds' END, "
                        "row_version = row_version + 1 "
                        "FROM transition_clock, finished_previous "
                        "WHERE async_jobs.id = :job_id "
                        "AND finished_previous.job_id = async_jobs.id "
                        "RETURNING async_jobs.id, async_jobs.attempt_no, "
                        "async_jobs.stage, async_jobs.heartbeat_at, "
                        "async_jobs.lease_expires_at, async_jobs.trace_id), "
                        "created_step AS ("
                        "INSERT INTO async_job_steps ("
                        "id, job_id, step_seq, step_code, status, attempt_no, "
                        "started_at, trace_id) SELECT :second_step_id, advanced_job.id, "
                        "finished_previous.step_seq + 1, CASE WHEN :stage_mismatch "
                        "THEN 'unexpected_stage' ELSE advanced_job.stage END, 'running', "
                        "advanced_job.attempt_no, transition_clock.t, advanced_job.trace_id "
                        "FROM transition_clock, finished_previous, advanced_job "
                        "RETURNING started_at, step_code) "
                        "SELECT transition_clock.t AS transition_timestamp, "
                        "finished_previous.finished_at, advanced_job.heartbeat_at, "
                        "advanced_job.lease_expires_at, created_step.started_at, "
                        "advanced_job.stage, created_step.step_code "
                        "FROM transition_clock, finished_previous, advanced_job, created_step"
                    ),
                    {
                        "adjacent_mismatch": adjacent_mismatch,
                        "first_step_id": first_step_id,
                        "heartbeat_only": heartbeat_only,
                        "job_id": job_id,
                        "lease_only": lease_only,
                        "pair_time_mismatch": pair_time_mismatch,
                        "second_step_id": second_step_id,
                        "stage_mismatch": stage_mismatch,
                        "stage_only": stage_only,
                    },
                ).one()
                return (
                    cast(datetime, row.transition_timestamp),
                    cast(datetime, row.finished_at),
                    cast(datetime, row.heartbeat_at),
                    cast(datetime, row.lease_expires_at),
                    cast(datetime, row.started_at),
                    str(row.stage),
                    str(row.step_code),
                )
        finally:
            engine.dispose()

    try:
        invalid_cases = (
            "stage",
            "heartbeat_only",
            "lease_only",
            "pair_time",
            "adjacent",
        )
        for case_name in invalid_cases:
            invalid_job = insert_queued_job(database_url)
            invalid_first_step = claim_job_with_step(database_url, invalid_job)
            try:
                returned = advance_to_second_step(
                    invalid_job,
                    invalid_first_step,
                    stage_mismatch=case_name == "stage",
                    heartbeat_only=case_name == "heartbeat_only",
                    lease_only=case_name == "lease_only",
                    pair_time_mismatch=case_name == "pair_time",
                    adjacent_mismatch=case_name == "adjacent",
                )
            except DBAPIError as error:
                assert safe_database_error_signature(error)[0] == "23514"
                continue

            engine = create_migration_engine(database_url)
            try:
                with engine.connect() as connection:
                    persisted = connection.execute(
                        text(
                            "SELECT job.stage AS job_stage, "
                            "job.heartbeat_at, job.lease_expires_at, "
                            "first_step.finished_at, second_step.started_at, "
                            "second_step.step_code AS step_code "
                            "FROM async_jobs AS job "
                            "JOIN async_job_steps AS first_step "
                            "ON first_step.job_id = job.id "
                            "AND first_step.attempt_no = job.attempt_no "
                            "AND first_step.step_seq = 1 "
                            "LEFT JOIN async_job_steps AS second_step "
                            "ON second_step.job_id = job.id "
                            "AND second_step.attempt_no = job.attempt_no "
                            "AND second_step.step_seq = 2 WHERE job.id = :job_id"
                        ),
                        {"job_id": invalid_job},
                    ).one()
                    persisted_contract = (
                        str(persisted.job_stage),
                        persisted.heartbeat_at,
                        persisted.lease_expires_at,
                        persisted.finished_at,
                        persisted.started_at,
                        None if persisted.step_code is None else str(persisted.step_code),
                    )
            finally:
                engine.dispose()
            returned_contract = returned[1:]
            raise AssertionError(
                f"{case_name} mismatch unexpectedly committed: "
                f"returned={returned_contract}, persisted={persisted_contract}"
            )

        stage_only_job = insert_queued_job(database_url)
        stage_only_first_step = claim_job_with_step(database_url, stage_only_job)
        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                old_lease_pair = connection.execute(
                    text(
                        "SELECT heartbeat_at, lease_expires_at FROM async_jobs WHERE id = :job_id"
                    ),
                    {"job_id": stage_only_job},
                ).one()
        finally:
            engine.dispose()
        (
            stage_transition_timestamp,
            stage_first_finished_at,
            unchanged_heartbeat_at,
            unchanged_lease_expires_at,
            stage_second_started_at,
            stage_only_job_stage,
            stage_only_step_code,
        ) = advance_to_second_step(
            stage_only_job,
            stage_only_first_step,
            stage_only=True,
        )
        assert stage_transition_timestamp == stage_first_finished_at == stage_second_started_at
        assert unchanged_heartbeat_at == old_lease_pair.heartbeat_at
        assert unchanged_lease_expires_at == old_lease_pair.lease_expires_at
        assert stage_only_job_stage == stage_only_step_code == "execute"

        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                stage_only_persisted = connection.execute(
                    text(
                        "SELECT job.stage, job.heartbeat_at, job.lease_expires_at, "
                        "first_step.finished_at, second_step.started_at, "
                        "second_step.step_code FROM async_jobs AS job "
                        "JOIN async_job_steps AS first_step ON first_step.job_id = job.id "
                        "AND first_step.attempt_no = job.attempt_no "
                        "AND first_step.step_seq = 1 "
                        "JOIN async_job_steps AS second_step ON second_step.job_id = job.id "
                        "AND second_step.attempt_no = job.attempt_no "
                        "AND second_step.step_seq = 2 WHERE job.id = :job_id"
                    ),
                    {"job_id": stage_only_job},
                ).one()
                assert stage_only_persisted.stage == stage_only_persisted.step_code == "execute"
                assert (
                    stage_only_persisted.finished_at
                    == stage_only_persisted.started_at
                    == stage_transition_timestamp
                )
                assert stage_only_persisted.heartbeat_at == old_lease_pair.heartbeat_at
                assert stage_only_persisted.lease_expires_at == old_lease_pair.lease_expires_at
        finally:
            engine.dispose()

        valid_job = insert_queued_job(database_url)
        valid_first_step = claim_job_with_step(database_url, valid_job)
        (
            transition_timestamp,
            first_finished_at,
            job_heartbeat_at,
            job_lease_expires_at,
            second_started_at,
            job_stage,
            second_step_code,
        ) = advance_to_second_step(valid_job, valid_first_step)
        assert transition_timestamp == first_finished_at == job_heartbeat_at == second_started_at
        assert job_lease_expires_at == transition_timestamp + timedelta(seconds=60)
        assert job_stage == second_step_code == "execute"

        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                persisted = connection.execute(
                    text(
                        "SELECT job.stage, job.heartbeat_at, job.lease_expires_at, "
                        "first_step.finished_at, second_step.started_at, "
                        "second_step.step_code "
                        "FROM async_jobs AS job "
                        "JOIN async_job_steps AS first_step ON first_step.job_id = job.id "
                        "JOIN async_job_steps AS second_step "
                        "ON second_step.job_id = first_step.job_id "
                        "AND second_step.attempt_no = first_step.attempt_no "
                        "AND second_step.step_seq = first_step.step_seq + 1 "
                        "WHERE job.id = :job_id AND first_step.id = :step_id"
                    ),
                    {"job_id": valid_job, "step_id": valid_first_step},
                ).one()
                assert persisted.stage == persisted.step_code == "execute"
                assert persisted.heartbeat_at == persisted.finished_at == persisted.started_at
                assert persisted.lease_expires_at == persisted.heartbeat_at + timedelta(seconds=60)
        finally:
            engine.dispose()
    finally:
        clear_reliability_test_data(database_url)


@pytest.mark.parametrize(
    ("prior_status", "prior_error", "accepted"),
    (
        ("failed", "STEP_FAILED", False),
        ("cancelled", "JOB_CANCELLED", False),
        ("succeeded", None, True),
        ("skipped", "STEP_SKIPPED", True),
    ),
)
def test_reliability_later_step_cannot_hide_invalid_prior_current_attempt_step(
    monkeypatch: pytest.MonkeyPatch,
    prior_status: str,
    prior_error: str | None,
    accepted: bool,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)
    try:
        job_id = insert_queued_job(database_url)
        first_step_id = claim_job_with_step(database_url, job_id)

        def advance_to_later_step() -> None:
            engine = create_migration_engine(database_url)
            try:
                with engine.begin() as connection:
                    finished_at = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                    connection.execute(
                        text(
                            "UPDATE async_job_steps SET status = :status, "
                            "finished_at = :finished_at, error_code = :error_code "
                            "WHERE id = :step_id"
                        ),
                        {
                            "status": prior_status,
                            "finished_at": finished_at,
                            "error_code": prior_error,
                            "step_id": first_step_id,
                        },
                    )
                    job = connection.execute(
                        text(
                            "UPDATE async_jobs SET stage = 'execute', "
                            "row_version = row_version + 1 WHERE id = :job_id "
                            "RETURNING attempt_no, trace_id"
                        ),
                        {"job_id": job_id},
                    ).one()
                    connection.execute(
                        text(
                            "INSERT INTO async_job_steps ("
                            "job_id, step_seq, step_code, status, attempt_no, started_at, trace_id"
                            ") VALUES ("
                            ":job_id, 2, 'execute', 'running', :attempt_no, "
                            ":started_at, :trace_id)"
                        ),
                        {
                            "attempt_no": job.attempt_no,
                            "job_id": job_id,
                            "started_at": finished_at,
                            "trace_id": job.trace_id,
                        },
                    )
            finally:
                engine.dispose()

        if accepted:
            advance_to_later_step()
            engine = create_migration_engine(database_url)
            try:
                with engine.connect() as connection:
                    assert connection.execute(
                        text(
                            "SELECT array_agg(status ORDER BY step_seq) "
                            "FROM async_job_steps WHERE job_id = :job_id"
                        ),
                        {"job_id": job_id},
                    ).scalar_one() == [prior_status, "running"]
            finally:
                engine.dispose()
        else:
            assert call_expect_database_error(advance_to_later_step)[0] == "23514"
    finally:
        clear_reliability_test_data(database_url)


def test_reliability_steps_are_fenced_immutable_and_non_deletable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)
    try:
        job_id = insert_queued_job(database_url)
        step_id = claim_job_with_step(database_url, job_id)
        other_job_id = insert_queued_job(database_url)
        immutable_assignments = (
            "id = gen_random_uuid()",
            "job_id = CAST(:other_job_id AS uuid)",
            "step_seq = step_seq + 1",
            "step_code = 'mutated'",
            "attempt_no = attempt_no + 1",
            "started_at = started_at - interval '1 second'",
            "trace_id = gen_random_uuid()",
        )
        for assignment in immutable_assignments:
            assert (
                execute_expect_database_error(
                    database_url,
                    f"UPDATE async_job_steps SET status = 'succeeded', "
                    f"finished_at = clock_timestamp(), {assignment} WHERE id = :step_id",
                    {"other_job_id": other_job_id, "step_id": step_id},
                )[0]
                == "23514"
            )

        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                finished_at = connection.execute(text("SELECT clock_timestamp()"))
                finished_at = finished_at.scalar_one()
                connection.execute(
                    text(
                        "UPDATE async_job_steps SET status = 'succeeded', "
                        "finished_at = :finished_at, "
                        "summary_json = jsonb_build_object('result', 'synthetic') "
                        "WHERE id = :step_id"
                    ),
                    {"finished_at": finished_at, "step_id": step_id},
                )
                connection.execute(
                    text(
                        "UPDATE async_jobs SET status = 'succeeded', "
                        "finished_at = :finished_at, worker_id = NULL, lease_owner = NULL, "
                        "lease_expires_at = NULL, heartbeat_at = NULL, "
                        "row_version = row_version + 1 WHERE id = :job_id"
                    ),
                    {"finished_at": finished_at, "job_id": job_id},
                )
        finally:
            engine.dispose()
        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                assert connection.execute(
                    text("SELECT summary_json FROM async_job_steps WHERE id = :step_id"),
                    {"step_id": step_id},
                ).scalar_one() == {"result": "synthetic"}
        finally:
            engine.dispose()
        assert (
            execute_expect_database_error(
                database_url,
                "DELETE FROM async_job_steps WHERE id = :step_id",
                {"step_id": step_id},
            )[0]
            == "55000"
        )
        assert execute_expect_database_error(database_url, "TRUNCATE async_job_steps")[0] == (
            "55000"
        )
        assert table_row_count(database_url, "async_job_steps") == 1
    finally:
        clear_reliability_test_data(database_url)


def test_reliability_outbox_identity_retry_exhaustion_and_terminal_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)
    try:
        job_id = insert_queued_job(database_url)
        invalid_dispatch_parameters = {
            "aggregate_id": job_id,
            "event_id": str(uuid4()),
            "trace_id": str(uuid4()),
        }
        assert (
            execute_expect_database_error(
                database_url,
                """
            INSERT INTO outbox_events (
                aggregate_type, aggregate_id, event_id, event_type,
                event_version, event_sequence, payload_json, status, trace_id
            ) VALUES (
                'async_job', :aggregate_id, :event_id, 'job.dispatch.requested',
                1, 1, '{}'::jsonb, 'pending', :trace_id
            )
            """,
                invalid_dispatch_parameters,
            )[0]
            == "23514"
        )
        execute_database_statement(
            database_url,
            """
            INSERT INTO outbox_events (
                aggregate_type, aggregate_id, event_id, event_type,
                event_version, event_sequence, payload_json, status, trace_id
            ) VALUES (
                'async_job', :aggregate_id, :event_id, 'job.dispatch.requested',
                1, 1, jsonb_build_object('job_id', CAST(:payload_job_id AS text)),
                'pending', :trace_id
            )
            """,
            {
                "aggregate_id": job_id,
                "payload_job_id": job_id,
                "event_id": str(uuid4()),
                "trace_id": str(uuid4()),
            },
        )

        lease_event_id = str(uuid4())
        execute_database_statement(
            database_url,
            """
            INSERT INTO outbox_events (
                id, aggregate_type, aggregate_id, event_id, event_type,
                event_version, event_sequence, payload_json, status, trace_id
            ) VALUES (
                :id, 'synthetic', :aggregate_id, :event_id, 'synthetic.lease',
                1, 1, '{}'::jsonb, 'pending', :trace_id
            )
            """,
            {
                "id": lease_event_id,
                "aggregate_id": str(uuid4()),
                "event_id": str(uuid4()),
                "trace_id": str(uuid4()),
            },
        )
        immutable_assignments = (
            "id = gen_random_uuid()",
            "aggregate_type = 'mutated'",
            "aggregate_id = gen_random_uuid()",
            "event_id = gen_random_uuid()",
            "event_type = 'synthetic.mutated'",
            "event_version = 2",
            "event_sequence = 2",
            "payload_json = jsonb_build_object('mutated', true)",
            "trace_id = gen_random_uuid()",
            "created_at = created_at - interval '1 second'",
        )
        for assignment in immutable_assignments:
            assert (
                execute_expect_database_error(
                    database_url,
                    f"UPDATE outbox_events SET status = 'processing', {assignment} WHERE id = :id",
                    {"id": lease_event_id},
                )[0]
                == "23514"
            )
        execute_database_statement(
            database_url,
            "UPDATE outbox_events SET status = 'processing' WHERE id = :id",
            {"id": lease_event_id},
        )
        assert (
            execute_expect_database_error(
                database_url,
                "UPDATE outbox_events SET status = 'failed', "
                "last_error = 'PROCESSING_LEASE_EXPIRED' WHERE id = :id",
                {"id": lease_event_id},
            )[0]
            == "23514"
        )
        for early_dead_letter_error in (
            "BROKER_TIMEOUT",
            "DELIVERY_ATTEMPTS_EXHAUSTED",
        ):
            assert (
                execute_expect_database_error(
                    database_url,
                    "UPDATE outbox_events SET status = 'dead_letter', "
                    "last_error = :last_error WHERE id = :id",
                    {"id": lease_event_id, "last_error": early_dead_letter_error},
                )[0]
                == "23514"
            )
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE outbox_events DISABLE TRIGGER USER"))
                connection.execute(
                    text(
                        "UPDATE outbox_events SET next_attempt_at = "
                        "clock_timestamp() - interval '1 second' WHERE id = :id"
                    ),
                    {"id": lease_event_id},
                )
                connection.execute(text("ALTER TABLE outbox_events ENABLE TRIGGER USER"))
        finally:
            engine.dispose()
        execute_database_statement(
            database_url,
            "UPDATE outbox_events SET status = 'failed', "
            "last_error = 'PROCESSING_LEASE_EXPIRED' WHERE id = :id",
            {"id": lease_event_id},
        )
        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                lease_state = connection.execute(
                    text(
                        "SELECT status, attempt_count, last_error FROM outbox_events WHERE id = :id"
                    ),
                    {"id": lease_event_id},
                ).one()
                assert (
                    lease_state.status,
                    lease_state.attempt_count,
                    lease_state.last_error,
                ) == ("failed", 1, "PROCESSING_LEASE_EXPIRED")
        finally:
            engine.dispose()
        assert (
            execute_expect_database_error(
                database_url,
                "UPDATE outbox_events SET status = 'processing' WHERE id = :id",
                {"id": lease_event_id},
            )[0]
            == "23514"
        )
        for early_dead_letter_error in (
            "BROKER_TIMEOUT",
            "DELIVERY_ATTEMPTS_EXHAUSTED",
        ):
            assert (
                execute_expect_database_error(
                    database_url,
                    "UPDATE outbox_events SET status = 'dead_letter', "
                    "last_error = :last_error WHERE id = :id",
                    {"id": lease_event_id, "last_error": early_dead_letter_error},
                )[0]
                == "23514"
            )

        retry_event_id = str(uuid4())
        execute_database_statement(
            database_url,
            """
            INSERT INTO outbox_events (
                id, aggregate_type, aggregate_id, event_id, event_type,
                event_version, event_sequence, payload_json, status, trace_id
            ) VALUES (
                :id, 'synthetic', :aggregate_id, :event_id, 'synthetic.created',
                1, 1, '{}'::jsonb, 'pending', :trace_id
            )
            """,
            {
                "id": retry_event_id,
                "aggregate_id": str(uuid4()),
                "event_id": str(uuid4()),
                "trace_id": str(uuid4()),
            },
        )
        execute_database_statement(
            database_url,
            "UPDATE outbox_events SET status = 'processing' WHERE id = :id",
            {"id": retry_event_id},
        )
        for attempt_count in range(1, 8):
            (
                observed_attempt,
                next_attempt_at,
                transition_before,
                transition_after,
            ) = fail_outbox_and_observe_retry(
                database_url,
                retry_event_id,
            )
            assert observed_attempt == attempt_count
            retry_seconds = (1, 2, 4, 8, 16, 32, 60)[attempt_count - 1]
            jitter_milliseconds = outbox_retry_jitter_milliseconds(
                retry_event_id,
                attempt_count,
            )
            inferred_transition_time = next_attempt_at - timedelta(
                seconds=retry_seconds,
                milliseconds=jitter_milliseconds,
            )
            assert transition_before <= inferred_transition_time <= transition_after
            engine = create_migration_engine(database_url)
            try:
                with engine.begin() as connection:
                    connection.execute(text("ALTER TABLE outbox_events DISABLE TRIGGER USER"))
                    connection.execute(
                        text(
                            "UPDATE outbox_events SET next_attempt_at = "
                            "clock_timestamp() - interval '1 second' WHERE id = :id"
                        ),
                        {"id": retry_event_id},
                    )
                    connection.execute(text("ALTER TABLE outbox_events ENABLE TRIGGER USER"))
            finally:
                engine.dispose()
            execute_database_statement(
                database_url,
                "UPDATE outbox_events SET status = 'processing' WHERE id = :id",
                {"id": retry_event_id},
            )
            engine = create_migration_engine(database_url)
            try:
                with engine.connect() as connection:
                    assert (
                        connection.execute(
                            text("SELECT attempt_count FROM outbox_events WHERE id = :id"),
                            {"id": retry_event_id},
                        ).scalar_one()
                        == attempt_count + 1
                    )
            finally:
                engine.dispose()

        assert (
            execute_expect_database_error(
                database_url,
                "UPDATE outbox_events SET status = 'dead_letter', "
                "last_error = 'PROCESSING_LEASE_EXPIRED' WHERE id = :id",
                {"id": retry_event_id},
            )[0]
            == "23514"
        )
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE outbox_events DISABLE TRIGGER USER"))
                connection.execute(
                    text(
                        "UPDATE outbox_events SET next_attempt_at = "
                        "clock_timestamp() - interval '1 second' WHERE id = :id"
                    ),
                    {"id": retry_event_id},
                )
                connection.execute(text("ALTER TABLE outbox_events ENABLE TRIGGER USER"))
        finally:
            engine.dispose()
        execute_database_statement(
            database_url,
            "UPDATE outbox_events SET status = 'dead_letter', "
            "last_error = 'PROCESSING_LEASE_EXPIRED' WHERE id = :id",
            {"id": retry_event_id},
        )
        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                retry_state = connection.execute(
                    text(
                        "SELECT status, attempt_count, last_error, next_attempt_at "
                        "FROM outbox_events WHERE id = :id"
                    ),
                    {"id": retry_event_id},
                ).one()
                assert (retry_state.status, retry_state.attempt_count, retry_state.last_error) == (
                    "dead_letter",
                    8,
                    "DELIVERY_ATTEMPTS_EXHAUSTED",
                )
                assert retry_state.next_attempt_at is None
        finally:
            engine.dispose()
        assert (
            execute_expect_database_error(
                database_url,
                "UPDATE outbox_events SET last_error = 'mutated' WHERE id = :id",
                {"id": retry_event_id},
            )[0]
            == "23514"
        )

        unknown_event_id = str(uuid4())
        execute_database_statement(
            database_url,
            """
            INSERT INTO outbox_events (
                id, aggregate_type, aggregate_id, event_id, event_type,
                event_version, event_sequence, payload_json, status, trace_id
            ) VALUES (
                :id, 'synthetic', :aggregate_id, :event_id, 'synthetic.unknown',
                1, 1, '{}'::jsonb, 'pending', :trace_id
            )
            """,
            {
                "id": unknown_event_id,
                "aggregate_id": str(uuid4()),
                "event_id": str(uuid4()),
                "trace_id": str(uuid4()),
            },
        )
        execute_database_statement(
            database_url,
            "UPDATE outbox_events SET status = 'processing' WHERE id = :id",
            {"id": unknown_event_id},
        )
        execute_database_statement(
            database_url,
            "UPDATE outbox_events SET status = 'dead_letter', "
            "last_error = 'UNRECOGNIZED_FAILURE' WHERE id = :id",
            {"id": unknown_event_id},
        )
        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT last_error FROM outbox_events WHERE id = :id"),
                        {"id": unknown_event_id},
                    ).scalar_one()
                    == "UNKNOWN_DELIVERY_ERROR"
                )
        finally:
            engine.dispose()

        assert (
            execute_expect_database_error(
                database_url,
                "DELETE FROM outbox_events WHERE id = :id",
                {"id": retry_event_id},
            )[0]
            == "55000"
        )
        assert execute_expect_database_error(database_url, "TRUNCATE outbox_events")[0] == ("55000")
    finally:
        clear_reliability_test_data(database_url)


def test_reliability_partial_unique_indexes_commit_exactly_once_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)
    try:
        shared_resource_id = str(uuid4())
        job_barrier = Barrier(2)

        def insert_competing_job() -> str:
            job_barrier.wait(timeout=10)
            try:
                insert_queued_job(database_url, resource_id=shared_resource_id)
            except DBAPIError as error:
                return safe_database_error_signature(error)[0] or "unknown"
            return "committed"

        with ThreadPoolExecutor(max_workers=2) as executor:
            job_results = list(executor.map(lambda _: insert_competing_job(), range(2)))
        assert sorted(job_results) == ["23505", "committed"]

        step_job = insert_queued_job(database_url)
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE async_jobs DISABLE TRIGGER trg_async_jobs_consistency_v1")
                )
                job = connection.execute(
                    text(
                        "UPDATE async_jobs SET status = 'running', "
                        "stage = current_attempt_start_step_code, attempt_no = attempt_no + 1, "
                        "worker_id = 'concurrency-worker', row_version = row_version + 1 "
                        "WHERE id = :job_id RETURNING attempt_no, stage, started_at, trace_id"
                    ),
                    {"job_id": step_job},
                ).one()
                connection.execute(
                    text("ALTER TABLE async_jobs ENABLE TRIGGER trg_async_jobs_consistency_v1")
                )
        finally:
            engine.dispose()

        step_barrier = Barrier(2)

        def insert_competing_step(step_seq: int) -> str:
            step_barrier.wait(timeout=10)
            try:
                execute_database_statement(
                    database_url,
                    """
                    INSERT INTO async_job_steps (
                        job_id, step_seq, step_code, status,
                        attempt_no, started_at, trace_id
                    ) VALUES (
                        :job_id, :step_seq, :step_code, 'running',
                        :attempt_no, :started_at, :trace_id
                    )
                    """,
                    {
                        "job_id": step_job,
                        "step_seq": step_seq,
                        "step_code": job.stage,
                        "attempt_no": job.attempt_no,
                        "started_at": job.started_at,
                        "trace_id": job.trace_id,
                    },
                )
            except DBAPIError as error:
                return safe_database_error_signature(error)[0] or "unknown"
            return "committed"

        with ThreadPoolExecutor(max_workers=2) as executor:
            step_results = list(executor.map(insert_competing_step, (1, 2)))
        assert sorted(step_results) == ["23505", "committed"]

        aggregate_id = str(uuid4())
        outbox_barrier = Barrier(2)

        def insert_competing_outbox() -> str:
            outbox_barrier.wait(timeout=10)
            try:
                execute_database_statement(
                    database_url,
                    """
                    INSERT INTO outbox_events (
                        aggregate_type, aggregate_id, event_id, event_type,
                        event_version, event_sequence, payload_json, status, trace_id
                    ) VALUES (
                        'synthetic', :aggregate_id, :event_id, 'synthetic.concurrent',
                        1, 1, '{}'::jsonb, 'pending', :trace_id
                    )
                    """,
                    {
                        "aggregate_id": aggregate_id,
                        "event_id": str(uuid4()),
                        "trace_id": str(uuid4()),
                    },
                )
            except DBAPIError as error:
                return safe_database_error_signature(error)[0] or "unknown"
            return "committed"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outbox_results = list(executor.map(lambda _: insert_competing_outbox(), range(2)))
        assert sorted(outbox_results) == ["23505", "committed"]

        shared_event_id = str(uuid4())
        event_identity_barrier = Barrier(2)

        def insert_competing_outbox_identity() -> tuple[str, str | None]:
            event_identity_barrier.wait(timeout=10)
            try:
                execute_database_statement(
                    database_url,
                    """
                    INSERT INTO outbox_events (
                        aggregate_type, aggregate_id, event_id, event_type,
                        event_version, event_sequence, payload_json, status, trace_id
                    ) VALUES (
                        'synthetic', :aggregate_id, :event_id,
                        'synthetic.identity.concurrent',
                        1, 1, '{}'::jsonb, 'pending', :trace_id
                    )
                    """,
                    {
                        "aggregate_id": str(uuid4()),
                        "event_id": shared_event_id,
                        "trace_id": str(uuid4()),
                    },
                )
            except DBAPIError as error:
                sqlstate, constraint_name = safe_database_error_signature(error)
                return sqlstate or "unknown", constraint_name
            return "committed", None

        with ThreadPoolExecutor(max_workers=2) as executor:
            identity_results = list(
                executor.map(lambda _: insert_competing_outbox_identity(), range(2))
            )
        assert sorted(result[0] for result in identity_results) == ["23505", "committed"]
        assert {result[1] for result in identity_results if result[0] == "23505"} == {
            "uq_outbox_events_event_id_event_type"
        }
    finally:
        clear_reliability_test_data(database_url)


def test_reliability_processing_event_terminal_race_commits_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    seed_reliability_organization(database_url)
    try:
        event_id = str(uuid4())
        execute_database_statement(
            database_url,
            """
            INSERT INTO outbox_events (
                id, aggregate_type, aggregate_id, event_id, event_type,
                event_version, event_sequence, payload_json, status, trace_id
            ) VALUES (
                :id, 'synthetic', :aggregate_id, :event_id, 'synthetic.terminal.race',
                1, 1, '{}'::jsonb, 'pending', :trace_id
            )
            """,
            {
                "id": event_id,
                "aggregate_id": str(uuid4()),
                "event_id": str(uuid4()),
                "trace_id": str(uuid4()),
            },
        )
        execute_database_statement(
            database_url,
            "UPDATE outbox_events SET status = 'processing' WHERE id = :id",
            {"id": event_id},
        )
        terminal_barrier = Barrier(2)

        def terminalize_event(terminal_status: str) -> str:
            terminal_barrier.wait(timeout=10)
            try:
                if terminal_status == "published":
                    execute_database_statement(
                        database_url,
                        "UPDATE outbox_events SET status = 'published' WHERE id = :id",
                        {"id": event_id},
                    )
                else:
                    execute_database_statement(
                        database_url,
                        "UPDATE outbox_events SET status = 'dead_letter', "
                        "last_error = 'SERIALIZATION_FAILED' WHERE id = :id",
                        {"id": event_id},
                    )
            except DBAPIError as error:
                return safe_database_error_signature(error)[0] or "unknown"
            return "committed"

        with ThreadPoolExecutor(max_workers=2) as executor:
            terminal_results = list(executor.map(terminalize_event, ("published", "dead_letter")))
        assert sorted(terminal_results) == ["23514", "committed"]

        engine = create_migration_engine(database_url)
        try:
            with engine.connect() as connection:
                terminal_state = connection.execute(
                    text(
                        "SELECT status, published_at IS NOT NULL AS has_published_at, last_error "
                        "FROM outbox_events WHERE id = :id"
                    ),
                    {"id": event_id},
                ).one()
                assert terminal_state.status in {"published", "dead_letter"}
                if terminal_state.status == "published":
                    assert terminal_state.has_published_at is True
                    assert terminal_state.last_error is None
                else:
                    assert terminal_state.has_published_at is False
                    assert terminal_state.last_error == "SERIALIZATION_FAILED"
        finally:
            engine.dispose()
        assert (
            execute_expect_database_error(
                database_url,
                "UPDATE outbox_events SET status = status WHERE id = :id",
                {"id": event_id},
            )[0]
            == "23514"
        )
    finally:
        clear_reliability_test_data(database_url)


@pytest.mark.parametrize("locked_table", FINANCIAL_TABLES)
def test_financial_downgrade_lock_timeout_is_bounded_and_atomic(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    locked_table: str,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    holder_engine = create_migration_engine(database_url)
    holder_connection = holder_engine.connect()
    holder_transaction = holder_connection.begin()
    try:
        holder_connection.execute(text(f"LOCK TABLE {locked_table} IN ACCESS SHARE MODE"))
        started_at = monotonic()
        with pytest.raises(DBAPIError) as error_info:
            command.downgrade(alembic_config, PREVIOUS_FINANCIAL_REVISION)
        elapsed_seconds = monotonic() - started_at
        assert safe_database_error_signature(error_info.value)[0] == "55P03"
        assert 4.0 <= elapsed_seconds < 12.0
        assert current_revision(database_url) == CURRENT_REVISION
        assert installed_baseline_tables(database_url) == CURRENT_HEAD_TABLES
        assert all(
            count_financial_rows(database_url, table_name) == 0 for table_name in FINANCIAL_TABLES
        )
        observed_circular_foreign_keys = {
            name
            for table_name in FINANCIAL_TABLES
            for name, (kind, _) in financial_constraint_contract(database_url, table_name).items()
            if kind == "f" and name in CIRCULAR_FINANCIAL_FOREIGN_KEYS
        }
        assert observed_circular_foreign_keys == CIRCULAR_FINANCIAL_FOREIGN_KEYS
    finally:
        holder_transaction.rollback()
        holder_connection.close()
        holder_engine.dispose()

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}\n{caplog.text}"
    if database_url.password and database_url.password in rendered_output:
        pytest.fail("锁超时测试输出包含连接密码，输出内容已隐藏", pytrace=False)


def test_operation_log_migration_catalog_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            columns = connection.execute(
                text(
                    "SELECT column_name, udt_name, is_nullable, "
                    "character_maximum_length, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'operation_logs' "
                    "ORDER BY ordinal_position"
                )
            ).all()
            constraints = {
                str(row.conname): (str(row.contype), str(row.definition))
                for row in connection.execute(
                    text(
                        "SELECT constraint_catalog.conname, constraint_catalog.contype, "
                        "pg_get_constraintdef(constraint_catalog.oid, true) AS definition "
                        "FROM pg_constraint AS constraint_catalog "
                        "WHERE constraint_catalog.conrelid = 'operation_logs'::regclass"
                    )
                )
            }
            indexes = {
                str(row.relname)
                for row in connection.execute(
                    text(
                        "SELECT index_catalog.relname "
                        "FROM pg_index AS index_state "
                        "JOIN pg_class AS index_catalog "
                        "ON index_catalog.oid = index_state.indexrelid "
                        "WHERE index_state.indrelid = 'operation_logs'::regclass"
                    )
                )
            }
            function_row = connection.execute(
                text(
                    "SELECT function_catalog.prosecdef, function_catalog.provolatile, "
                    "function_catalog.proparallel, "
                    "pg_get_functiondef(function_catalog.oid) AS definition "
                    "FROM pg_proc AS function_catalog "
                    "JOIN pg_namespace AS schema_catalog "
                    "ON schema_catalog.oid = function_catalog.pronamespace "
                    "WHERE schema_catalog.nspname = current_schema() "
                    "AND function_catalog.proname = "
                    "'enforce_operation_logs_append_only_v1'"
                )
            ).one()
    finally:
        engine.dispose()

    assert [
        (
            str(row.column_name),
            str(row.udt_name),
            str(row.is_nullable),
            row.character_maximum_length,
            None if row.column_default is None else str(row.column_default),
        )
        for row in columns
    ] == [
        ("id", "uuid", "NO", None, "gen_random_uuid()"),
        ("organization_id", "uuid", "YES", None, None),
        ("actor_kind", "varchar", "NO", 20, None),
        ("actor_id", "uuid", "YES", None, None),
        ("action_code", "varchar", "NO", 100, None),
        ("outcome", "varchar", "NO", 20, None),
        ("resource_type", "varchar", "YES", 80, None),
        ("resource_id", "uuid", "YES", None, None),
        ("trace_id", "uuid", "NO", None, None),
        ("change_summary_json", "jsonb", "NO", None, "'{}'::jsonb"),
        ("created_at", "timestamptz", "NO", None, "now()"),
    ]
    assert set(constraints) == {
        "ck_operation_logs_action_code_format",
        "ck_operation_logs_actor_matrix",
        "ck_operation_logs_change_summary_object",
        "ck_operation_logs_outcome_allowed",
        "ck_operation_logs_resource_matrix",
        "ck_operation_logs_resource_type_format",
        "fk_operation_logs_actor_id_users",
        "fk_operation_logs_organization_id_organizations",
        "pk_operation_logs",
    }
    assert constraints["fk_operation_logs_actor_id_users"][0] == "f"
    assert constraints["fk_operation_logs_organization_id_organizations"][0] == "f"
    assert indexes == {
        "idx_operation_logs_actor_created",
        "idx_operation_logs_organization_created",
        "idx_operation_logs_resource_created",
        "idx_operation_logs_trace",
        "pk_operation_logs",
    }
    assert function_row.prosecdef is False
    assert function_row.provolatile == "v"
    assert function_row.proparallel == "u"
    assert "SET search_path TO 'pg_catalog', 'pg_temp'" in function_row.definition
    assert user_trigger_names(database_url, "operation_logs") == {
        "trg_operation_logs_append_only_v1",
        "trg_operation_logs_no_truncate_v1",
    }


def test_financial_fact_detail_migration_catalog_and_empty_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    command.downgrade(alembic_config, FINANCIAL_FACT_DETAIL_REVISION)

    assert current_revision(database_url) == FINANCIAL_FACT_DETAIL_REVISION
    assert installed_baseline_tables(database_url) == TABLES_AT_014
    for table_name in FINANCIAL_FACT_DETAIL_TABLES:
        assert table_row_count(database_url, table_name) == 0
        assert user_trigger_names(database_url, table_name) == {
            f"trg_{table_name}_state_v1",
            f"trg_{table_name}_no_truncate_v1",
        }

    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            function = connection.execute(
                text(
                    "SELECT prosecdef, provolatile, proparallel, "
                    "pg_get_functiondef(oid) AS definition FROM pg_proc "
                    "WHERE proname = 'enforce_financial_fact_details_v1'"
                )
            ).one()
    finally:
        engine.dispose()
    assert function.prosecdef is False
    assert function.provolatile == "v"
    assert function.proparallel == "u"
    assert "SET search_path TO 'pg_catalog', 'pg_temp'" in function.definition

    command.downgrade(alembic_config, DOCUMENT_PROCESSING_REVISION)
    assert current_revision(database_url) == DOCUMENT_PROCESSING_REVISION
    assert installed_baseline_tables(database_url) == TABLES_AT_013
    command.upgrade(alembic_config, FINANCIAL_FACT_DETAIL_REVISION)
    assert current_revision(database_url) == FINANCIAL_FACT_DETAIL_REVISION
    assert installed_baseline_tables(database_url) == TABLES_AT_014


def test_contract_invoice_history_migration_catalog_and_empty_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    command.downgrade(alembic_config, CONTRACT_INVOICE_HISTORY_REVISION)

    assert current_revision(database_url) == CONTRACT_INVOICE_HISTORY_REVISION
    assert user_trigger_names(database_url, "contract_invoices") == {
        "trg_contract_invoices_history_v1",
        "trg_contract_invoices_no_truncate_v1",
    }
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            function = connection.execute(
                text(
                    "SELECT prosecdef, provolatile, proparallel, "
                    "pg_get_functiondef(oid) AS definition FROM pg_proc "
                    "WHERE proname = 'enforce_contract_invoice_history_v1'"
                )
            ).one()
    finally:
        engine.dispose()
    assert function.prosecdef is False
    assert function.provolatile == "v"
    assert function.proparallel == "u"
    assert "SET search_path TO 'pg_catalog', 'pg_temp'" in function.definition

    command.downgrade(alembic_config, FINANCIAL_FACT_DETAIL_REVISION)
    assert current_revision(database_url) == FINANCIAL_FACT_DETAIL_REVISION
    assert user_trigger_names(database_url, "contract_invoices") == set()
    command.upgrade(alembic_config, CONTRACT_INVOICE_HISTORY_REVISION)
    assert current_revision(database_url) == CONTRACT_INVOICE_HISTORY_REVISION


def test_contract_invoice_history_upgrade_preflight_accepts_valid_history_and_rejects_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    command.downgrade(alembic_config, FINANCIAL_FACT_DETAIL_REVISION)
    organization_id = str(uuid4())
    user_id = str(uuid4())
    contract_id = str(uuid4())
    invoice_id = str(uuid4())
    relation_id = str(uuid4())
    reasons = (
        "jsonb_build_object("
        "'tax_no', jsonb_build_object('status','matched','code','tax_no_matched'),"
        "'name', jsonb_build_object('status','matched','code','name_matched'),"
        "'date', jsonb_build_object('status','matched','code','date_in_range'))"
    )
    try:
        execute_database_statement(
            database_url,
            "INSERT INTO organizations (id, name, unified_social_credit_code, tax_number, status) "
            "VALUES (:id, 'link preflight organization', 'LINK-PREFLIGHT-USCC', "
            "'LINK-PREFLIGHT-TAX', 'active')",
            {"id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO users (id, organization_id, username, display_name, password_hash, "
            "status, password_changed_at, token_invalid_before) VALUES "
            "(:id, :organization_id, 'link.preflight.actor', 'link preflight actor', "
            "'synthetic-password-hash', 'active', now(), now())",
            {"id": user_id, "organization_id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO contracts (id, organization_id, name, confirmation_status, status, "
            "critical_fact_hash) VALUES (:id, :organization_id, 'link preflight contract', "
            "'confirmed', 'active', repeat('a', 64))",
            {"id": contract_id, "organization_id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO invoices (id, organization_id, confirmation_status, status, "
            "critical_fact_hash) VALUES (:id, :organization_id, 'confirmed', "
            "'confirmed', repeat('b', 64))",
            {"id": invoice_id, "organization_id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO contract_invoices (id, contract_id, invoice_id, status, "
            "match_reasons_json, suggested_by, confirmed_by, confirmed_at, created_by) VALUES "
            f"(:id, :contract_id, :invoice_id, 'confirmed_primary', {reasons}, "
            "'user', :user_id, now(), :user_id)",
            {
                "id": relation_id,
                "contract_id": contract_id,
                "invoice_id": invoice_id,
                "user_id": user_id,
            },
        )
        command.upgrade(alembic_config, CONTRACT_INVOICE_HISTORY_REVISION)
        assert current_revision(database_url) == CONTRACT_INVOICE_HISTORY_REVISION
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE contract_invoices DISABLE TRIGGER USER"))
                connection.execute(text("ALTER TABLE invoices DISABLE TRIGGER USER"))
                connection.execute(
                    text("DELETE FROM contract_invoices WHERE id=:id"),
                    {"id": relation_id},
                )
                connection.execute(text("ALTER TABLE invoices ENABLE TRIGGER USER"))
                connection.execute(text("ALTER TABLE contract_invoices ENABLE TRIGGER USER"))
        finally:
            engine.dispose()
        command.downgrade(alembic_config, FINANCIAL_FACT_DETAIL_REVISION)
        assert current_revision(database_url) == FINANCIAL_FACT_DETAIL_REVISION

        execute_database_statement(
            database_url,
            "INSERT INTO contract_invoices (id, contract_id, invoice_id, status, "
            "match_reasons_json, suggested_by, confirmed_by, confirmed_at, created_by) VALUES "
            "(:id, :contract_id, :invoice_id, 'confirmed_primary', "
            "jsonb_build_object('tax_no', true, 'name', true, 'date', true), "
            "'user', :user_id, now(), :user_id)",
            {
                "id": relation_id,
                "contract_id": contract_id,
                "invoice_id": invoice_id,
                "user_id": user_id,
            },
        )
        with pytest.raises(DBAPIError) as upgrade_error:
            command.upgrade(alembic_config, CONTRACT_INVOICE_HISTORY_REVISION)
        assert safe_database_error_signature(upgrade_error.value) == (
            "55000",
            None,
        )
        assert current_revision(database_url) == FINANCIAL_FACT_DETAIL_REVISION
        assert user_trigger_names(database_url, "contract_invoices") == set()
    finally:
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE invoices DISABLE TRIGGER USER"))
                connection.execute(
                    text("DELETE FROM contract_invoices WHERE id=:id"),
                    {"id": relation_id},
                )
                connection.execute(text("DELETE FROM invoices WHERE id=:id"), {"id": invoice_id})
                connection.execute(text("ALTER TABLE invoices ENABLE TRIGGER USER"))
                connection.execute(text("DELETE FROM contracts WHERE id=:id"), {"id": contract_id})
                connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
                connection.execute(
                    text("DELETE FROM organizations WHERE id=:id"), {"id": organization_id}
                )
        finally:
            engine.dispose()


def test_contract_invoice_history_guards_shape_transitions_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    command.downgrade(alembic_config, CONTRACT_INVOICE_HISTORY_REVISION)
    organization_id = str(uuid4())
    user_id = str(uuid4())
    contract_id = str(uuid4())
    invoice_id = str(uuid4())
    relation_id = str(uuid4())
    reasons = (
        "jsonb_build_object("
        "'tax_no', jsonb_build_object('status','matched','code','tax_no_matched'),"
        "'name', jsonb_build_object('status','matched','code','name_matched'),"
        "'date', jsonb_build_object('status','matched','code','date_in_range'))"
    )
    try:
        execute_database_statement(
            database_url,
            "INSERT INTO organizations (id, name, unified_social_credit_code, tax_number, status) "
            "VALUES (:id, 'link history organization', 'LINK-HISTORY-USCC', "
            "'LINK-HISTORY-TAX', 'active')",
            {"id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO users (id, organization_id, username, display_name, password_hash, "
            "status, password_changed_at, token_invalid_before) VALUES "
            "(:id, :organization_id, 'link.history.actor', 'link history actor', "
            "'synthetic-password-hash', 'active', now(), now())",
            {"id": user_id, "organization_id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO contracts (id, organization_id, name, confirmation_status, status, "
            "critical_fact_hash) VALUES (:id, :organization_id, 'link contract', "
            "'confirmed', 'active', repeat('a', 64))",
            {"id": contract_id, "organization_id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO invoices (id, organization_id, confirmation_status, status, "
            "critical_fact_hash) VALUES (:id, :organization_id, 'confirmed', "
            "'confirmed', repeat('b', 64))",
            {"id": invoice_id, "organization_id": organization_id},
        )
        assert (
            execute_expect_database_error(
                database_url,
                "INSERT INTO contract_invoices (id, contract_id, invoice_id, status, "
                "match_reasons_json, suggested_by, created_by) VALUES "
                "(:id, :contract_id, :invoice_id, 'confirmed_primary', "
                f"{reasons}, 'user', :user_id)",
                {
                    "id": str(uuid4()),
                    "contract_id": contract_id,
                    "invoice_id": invoice_id,
                    "user_id": user_id,
                },
            )[0]
            == "55000"
        )
        assert (
            execute_expect_database_error(
                database_url,
                "INSERT INTO contract_invoices (id, contract_id, invoice_id, status, "
                "match_reasons_json, suggested_by, created_by) VALUES "
                "(:id, :contract_id, :invoice_id, 'candidate', "
                f"{reasons}, 'user', :user_id)",
                {
                    "id": str(uuid4()),
                    "contract_id": contract_id,
                    "invoice_id": invoice_id,
                    "user_id": user_id,
                },
            )[0]
            == "23514"
        )
        assert (
            execute_expect_database_error(
                database_url,
                "INSERT INTO contract_invoices (id, contract_id, invoice_id, status, "
                "match_reasons_json, suggested_by, created_by) VALUES "
                "(:id, :contract_id, :invoice_id, 'suggested', "
                '\'{"tax_no":{"status":"matched","code":"tax_no_mismatched"},'
                '"name":{"status":"matched","code":"name_matched"},'
                '"date":{"status":"matched","code":"date_in_range"}}\'::jsonb, '
                "'user', :user_id)",
                {
                    "id": str(uuid4()),
                    "contract_id": contract_id,
                    "invoice_id": invoice_id,
                    "user_id": user_id,
                },
            )[0]
            == "23514"
        )
        assert (
            execute_expect_database_error(
                database_url,
                "INSERT INTO contract_invoices (id, contract_id, invoice_id, status, "
                "match_reasons_json, suggested_by, created_by, deleted_at) VALUES "
                f"(:id, :contract_id, :invoice_id, 'suggested', {reasons}, "
                "'user', :user_id, now())",
                {
                    "id": str(uuid4()),
                    "contract_id": contract_id,
                    "invoice_id": invoice_id,
                    "user_id": user_id,
                },
            )[0]
            == "23514"
        )
        execute_database_statement(
            database_url,
            "INSERT INTO contract_invoices (id, contract_id, invoice_id, status, "
            "match_reasons_json, suggested_by, created_by) VALUES "
            f"(:id, :contract_id, :invoice_id, 'suggested', {reasons}, 'user', :user_id)",
            {
                "id": relation_id,
                "contract_id": contract_id,
                "invoice_id": invoice_id,
                "user_id": user_id,
            },
        )
        execute_database_statement(
            database_url,
            "UPDATE contract_invoices SET status='confirmed_primary', confirmed_by=:user_id, "
            "confirmed_at=now(), row_version=row_version+1 WHERE id=:id",
            {"id": relation_id, "user_id": user_id},
        )
        assert (
            execute_expect_database_error(
                database_url,
                "UPDATE contract_invoices SET status='confirmed_primary', "
                "row_version=row_version+1 WHERE id=:id",
                {"id": relation_id},
            )[0]
            == "55000"
        )
        execute_database_statement(
            database_url,
            "UPDATE contract_invoices SET status='cancelled', cancelled_by=:user_id, "
            "cancelled_at=now(), cancel_reason='synthetic cancel', "
            "row_version=row_version+1 WHERE id=:id",
            {"id": relation_id, "user_id": user_id},
        )
        for statement in (
            "DELETE FROM contract_invoices WHERE id=:id",
            "TRUNCATE TABLE contract_invoices",
        ):
            assert (
                execute_expect_database_error(
                    database_url,
                    statement,
                    {"id": relation_id},
                )[0]
                == "55000"
            )
        with pytest.raises(DBAPIError) as downgrade_error:
            command.downgrade(alembic_config, FINANCIAL_FACT_DETAIL_REVISION)
        assert safe_database_error_signature(downgrade_error.value)[0] == "55000"
        assert current_revision(database_url) == CONTRACT_INVOICE_HISTORY_REVISION
    finally:
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE contract_invoices DISABLE TRIGGER USER"))
                connection.execute(
                    text("DELETE FROM contract_invoices WHERE id=:id"),
                    {"id": relation_id},
                )
                connection.execute(text("ALTER TABLE contract_invoices ENABLE TRIGGER USER"))
                connection.execute(text("DELETE FROM invoices WHERE id=:id"), {"id": invoice_id})
                connection.execute(text("DELETE FROM contracts WHERE id=:id"), {"id": contract_id})
                connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
                connection.execute(
                    text("DELETE FROM organizations WHERE id=:id"), {"id": organization_id}
                )
        finally:
            engine.dispose()


def test_invoice_facts_migration_catalog_and_empty_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    command.downgrade(alembic_config, INVOICE_FACTS_REVISION)

    assert current_revision(database_url) == INVOICE_FACTS_REVISION
    assert installed_baseline_tables(database_url) == TABLES_AT_016
    assert user_trigger_names(database_url, "invoices") == {
        "trg_invoices_state_v1",
        "trg_invoices_no_truncate_v1",
    }
    assert user_trigger_names(database_url, "invoice_items") == {
        "trg_invoice_items_state_v1",
        "trg_invoice_items_no_truncate_v1",
    }
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            functions = {
                str(row.proname): (
                    bool(row.prosecdef),
                    str(row.provolatile),
                    str(row.proparallel),
                    str(row.definition),
                )
                for row in connection.execute(
                    text(
                        "SELECT proname, prosecdef, provolatile, proparallel, "
                        "pg_get_functiondef(oid) AS definition FROM pg_proc "
                        "WHERE proname IN ('enforce_invoices_state_v1',"
                        "'enforce_invoice_items_state_v1',"
                        "'prevent_invoice_fact_truncate_v1')"
                    )
                )
            }
    finally:
        engine.dispose()
    assert set(functions) == {
        "enforce_invoices_state_v1",
        "enforce_invoice_items_state_v1",
        "prevent_invoice_fact_truncate_v1",
    }
    assert all(not item[0] and item[1:3] == ("v", "u") for item in functions.values())
    assert all(
        "SET search_path TO 'pg_catalog', 'pg_temp'" in item[3] for item in functions.values()
    )

    command.downgrade(alembic_config, CONTRACT_INVOICE_HISTORY_REVISION)
    assert current_revision(database_url) == CONTRACT_INVOICE_HISTORY_REVISION
    assert user_trigger_names(database_url, "invoices") == set()
    assert user_trigger_names(database_url, "invoice_items") == set()
    command.upgrade(alembic_config, INVOICE_FACTS_REVISION)
    assert current_revision(database_url) == INVOICE_FACTS_REVISION


def test_invoice_facts_upgrade_preflight_and_runtime_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    command.downgrade(alembic_config, CONTRACT_INVOICE_HISTORY_REVISION)
    organization_id = str(uuid4())
    user_id = str(uuid4())
    invoice_id = str(uuid4())
    item_id = str(uuid4())
    try:
        execute_database_statement(
            database_url,
            "INSERT INTO organizations (id, name, unified_social_credit_code, tax_number, status) "
            "VALUES (:id, 'invoice facts organization', 'INVOICE-FACTS-USCC', "
            "'INVOICE-FACTS-TAX', 'active')",
            {"id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO users (id, organization_id, username, display_name, password_hash, "
            "status, password_changed_at, token_invalid_before) VALUES "
            "(:id, :organization_id, 'invoice.facts.actor', 'invoice facts actor', "
            "'synthetic-password-hash', 'active', now(), now())",
            {"id": user_id, "organization_id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO invoices (id, organization_id, invoice_code, confirmation_status, "
            "status, field_evidence_json, critical_fact_hash) VALUES "
            "(:id, :organization_id, 'INV-016', 'unconfirmed', 'draft', "
            "'{}'::jsonb, repeat('a', 64))",
            {"id": invoice_id, "organization_id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO invoice_items (id, invoice_id, line_no, evidence_json) VALUES "
            "(:id, :invoice_id, 1, '{}'::jsonb)",
            {"id": item_id, "invoice_id": invoice_id},
        )
        command.upgrade(alembic_config, INVOICE_FACTS_REVISION)
        assert current_revision(database_url) == INVOICE_FACTS_REVISION

        assert (
            execute_expect_database_error(
                database_url,
                "UPDATE invoices SET invoice_code='DRIFT' WHERE id=:id",
                {"id": invoice_id},
            )[0]
            == "23514"
        )
        execute_database_statement(
            database_url,
            "UPDATE invoices SET confirmation_status='confirmed', status='confirmed', "
            "confirmed_by=:user_id, confirmed_at=now(), row_version=row_version+1 "
            "WHERE id=:id",
            {"id": invoice_id, "user_id": user_id},
        )
        for statement in (
            "UPDATE invoices SET invoice_code='DRIFT', row_version=row_version+1 WHERE id=:id",
            "DELETE FROM invoices WHERE id=:id",
            "UPDATE invoice_items SET item_name='DRIFT', row_version=row_version+1 WHERE id=:id",
            "DELETE FROM invoice_items WHERE id=:id",
            "TRUNCATE TABLE invoice_items",
        ):
            assert (
                execute_expect_database_error(
                    database_url,
                    statement,
                    {"id": item_id if "invoice_items" in statement else invoice_id},
                )[0]
                == "55000"
            )
        execute_database_statement(
            database_url,
            "UPDATE invoices SET duplicate_status='suspected', row_version=row_version+1 "
            "WHERE id=:id",
            {"id": invoice_id},
        )

        with pytest.raises(DBAPIError) as downgrade_error:
            command.downgrade(alembic_config, CONTRACT_INVOICE_HISTORY_REVISION)
        assert safe_database_error_signature(downgrade_error.value)[0] == "55000"
        assert current_revision(database_url) == INVOICE_FACTS_REVISION
    finally:
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                for table_name in ("invoice_items", "invoices"):
                    connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
                connection.execute(text("DELETE FROM invoice_items WHERE id=:id"), {"id": item_id})
                connection.execute(text("DELETE FROM invoices WHERE id=:id"), {"id": invoice_id})
                for table_name in reversed(("invoice_items", "invoices")):
                    connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))
                connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
                connection.execute(
                    text("DELETE FROM organizations WHERE id=:id"), {"id": organization_id}
                )
        finally:
            engine.dispose()

    command.downgrade(alembic_config, CONTRACT_INVOICE_HISTORY_REVISION)
    invalid_invoice_id = str(uuid4())
    try:
        execute_database_statement(
            database_url,
            "INSERT INTO organizations (id, name, unified_social_credit_code, tax_number, status) "
            "VALUES (:id, 'invoice drift organization', 'INVOICE-DRIFT-USCC', "
            "'INVOICE-DRIFT-TAX', 'active')",
            {"id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO invoices (id, organization_id, confirmation_status, status, "
            "field_evidence_json, critical_fact_hash) VALUES "
            "(:id, :organization_id, 'unconfirmed', 'draft', '[]'::jsonb, repeat('b',64))",
            {"id": invalid_invoice_id, "organization_id": organization_id},
        )
        with pytest.raises(DBAPIError) as upgrade_error:
            command.upgrade(alembic_config, INVOICE_FACTS_REVISION)
        assert safe_database_error_signature(upgrade_error.value) == (
            "55000",
            None,
        )
        assert current_revision(database_url) == CONTRACT_INVOICE_HISTORY_REVISION
        assert user_trigger_names(database_url, "invoices") == set()
    finally:
        execute_database_statement(
            database_url,
            "DELETE FROM invoices WHERE id=:id",
            {"id": invalid_invoice_id},
        )
        execute_database_statement(
            database_url,
            "DELETE FROM organizations WHERE id=:id",
            {"id": organization_id},
        )
        command.upgrade(alembic_config, INVOICE_FACTS_REVISION)


def test_financial_fact_detail_append_only_and_terminal_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    organization_id = str(uuid4())
    user_id = str(uuid4())
    contract_id = str(uuid4())
    agreement_id = str(uuid4())
    correction_id = str(uuid4())
    try:
        execute_database_statement(
            database_url,
            "INSERT INTO organizations (id, name, unified_social_credit_code, tax_number, status) "
            "VALUES (:id, 'financial details organization', 'DETAILS-USCC', "
            "'DETAILS-TAX', 'active')",
            {"id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO users (id, organization_id, username, display_name, password_hash, "
            "status, password_changed_at, token_invalid_before) VALUES "
            "(:id, :organization_id, 'financial.details', 'financial details actor', "
            "'synthetic-password-hash', 'active', now(), now())",
            {"id": user_id, "organization_id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO contracts (id, organization_id, name, confirmation_status, status, "
            "critical_fact_hash) VALUES (:id, :organization_id, 'details contract', "
            "'unconfirmed', 'draft', repeat('a', 64))",
            {"id": contract_id, "organization_id": organization_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO supplementary_agreements (id, organization_id, contract_id, name, "
            "effective_date, status, confirmation_status, critical_fact_hash) VALUES "
            "(:id, :organization_id, :contract_id, 'details agreement', current_date, "
            "'draft', 'unconfirmed', repeat('b', 64))",
            {
                "id": agreement_id,
                "organization_id": organization_id,
                "contract_id": contract_id,
            },
        )
        execute_database_statement(
            database_url,
            "INSERT INTO supplementary_agreement_changes "
            "(supplementary_agreement_id, field_code, value_type, new_value_json, "
            "confirmation_status) VALUES (:agreement_id, 'amount', 'number', "
            "'\"12.34\"'::jsonb, 'unconfirmed')",
            {"agreement_id": agreement_id},
        )
        execute_database_statement(
            database_url,
            "INSERT INTO user_corrections (id, organization_id, correction_type, "
            "object_type, object_id, field_path, after_value_json, reason, actor_id, "
            "actor_role_code, trace_id) VALUES (:id, :organization_id, "
            "'supplementary_agreement_changes', 'supplementary_agreement', :object_id, "
            "'changes', '{\"changes\":[]}'::jsonb, 'synthetic correction', :actor_id, "
            "'contract_admin', :trace_id)",
            {
                "id": correction_id,
                "organization_id": organization_id,
                "object_id": agreement_id,
                "actor_id": user_id,
                "trace_id": str(uuid4()),
            },
        )
        for statement, parameters in (
            (
                "UPDATE user_corrections SET reason = 'mutated' WHERE id = :id",
                {"id": correction_id},
            ),
            (
                "DELETE FROM user_corrections WHERE id = :id",
                {"id": correction_id},
            ),
            ("TRUNCATE TABLE user_corrections", {}),
        ):
            assert execute_expect_database_error(database_url, statement, parameters)[0] == "55000"

        execute_database_statement(
            database_url,
            "UPDATE supplementary_agreements SET status = 'rejected', "
            "confirmation_status = 'rejected', confirmed_by = :user_id, "
            "confirmed_at = now(), confirmation_reason = 'synthetic rejection', "
            "row_version = row_version + 1 WHERE id = :id",
            {"id": agreement_id, "user_id": user_id},
        )
        assert (
            execute_expect_database_error(
                database_url,
                "UPDATE supplementary_agreement_changes SET new_value_json = '13'::jsonb "
                "WHERE supplementary_agreement_id = :id",
                {"id": agreement_id},
            )[0]
            == "55000"
        )
        with pytest.raises(DBAPIError) as downgrade_error:
            command.downgrade(alembic_config, DOCUMENT_PROCESSING_REVISION)
        assert safe_database_error_signature(downgrade_error.value)[0] == "55000"
        assert current_revision(database_url) == CURRENT_REVISION
    finally:
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                for table_name in (
                    "user_corrections",
                    "supplementary_agreement_changes",
                ):
                    connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
                    connection.execute(text(f"DELETE FROM {table_name}"))
                    connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))
                connection.execute(
                    text("DELETE FROM supplementary_agreements WHERE id = :id"),
                    {"id": agreement_id},
                )
                connection.execute(
                    text("DELETE FROM contracts WHERE id = :id"), {"id": contract_id}
                )
                connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
                connection.execute(
                    text("DELETE FROM organizations WHERE id = :id"), {"id": organization_id}
                )
        finally:
            engine.dispose()


def test_operation_logs_are_append_only_and_reject_invalid_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    log_id = str(uuid4())
    try:
        execute_database_statement(
            database_url,
            """
            INSERT INTO operation_logs (
                id, actor_kind, action_code, outcome, trace_id, change_summary_json
            ) VALUES (
                :id, 'anonymous', 'auth.login.failed', 'denied', :trace_id,
                jsonb_build_object('failure_code', 'INVALID_CREDENTIALS')
            )
            """,
            {"id": log_id, "trace_id": str(uuid4())},
        )
        for statement in (
            "UPDATE operation_logs SET outcome = 'failed' WHERE id = :id",
            "DELETE FROM operation_logs WHERE id = :id",
            "TRUNCATE TABLE operation_logs",
        ):
            assert (
                execute_expect_database_error(database_url, statement, {"id": log_id})[0] == "55000"
            )
        assert table_row_count(database_url, "operation_logs") == 1

        assert (
            execute_expect_database_error(
                database_url,
                "INSERT INTO operation_logs (actor_kind, action_code, outcome, trace_id) "
                "VALUES ('robot', 'auth.login.failed', 'denied', :trace_id)",
                {"trace_id": str(uuid4())},
            )[0]
            == "23514"
        )
        assert (
            execute_expect_database_error(
                database_url,
                "INSERT INTO operation_logs (actor_kind, action_code, outcome, trace_id, "
                "change_summary_json) VALUES ('anonymous', 'auth.login.failed', 'denied', "
                ":trace_id, '[]'::jsonb)",
                {"trace_id": str(uuid4())},
            )[0]
            == "23514"
        )
    finally:
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE operation_logs DISABLE TRIGGER USER"))
                connection.execute(text("DELETE FROM operation_logs"))
                connection.execute(text("ALTER TABLE operation_logs ENABLE TRIGGER USER"))
        finally:
            engine.dispose()


def test_operation_log_empty_downgrade_and_upgrade_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)

    command.downgrade(alembic_config, FINANCIAL_RELATIONSHIP_REVISION)
    assert current_revision(database_url) == FINANCIAL_RELATIONSHIP_REVISION
    assert installed_baseline_tables(database_url) == TABLES_AT_009

    command.upgrade(alembic_config, OPERATION_LOG_REVISION)
    assert current_revision(database_url) == OPERATION_LOG_REVISION
    assert installed_baseline_tables(database_url) == TABLES_AT_010
    assert user_trigger_names(database_url, "operation_logs") == {
        "trg_operation_logs_append_only_v1",
        "trg_operation_logs_no_truncate_v1",
    }


def test_operation_log_nonempty_downgrade_is_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    execute_database_statement(
        database_url,
        "INSERT INTO operation_logs (actor_kind, action_code, outcome, trace_id) "
        "VALUES ('system', 'authorization.denied', 'denied', :trace_id)",
        {"trace_id": str(uuid4())},
    )
    before_triggers = user_trigger_names(database_url, "operation_logs")
    try:
        with pytest.raises(DBAPIError) as downgrade_error:
            command.downgrade(alembic_config, FINANCIAL_RELATIONSHIP_REVISION)
        assert safe_database_error_signature(downgrade_error.value)[0] == "55000"
        assert current_revision(database_url) == CURRENT_REVISION
        assert installed_baseline_tables(database_url) == CURRENT_HEAD_TABLES
        assert table_row_count(database_url, "operation_logs") == 1
        assert user_trigger_names(database_url, "operation_logs") == before_triggers
    finally:
        engine = create_migration_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE operation_logs DISABLE TRIGGER USER"))
                connection.execute(text("DELETE FROM operation_logs"))
                connection.execute(text("ALTER TABLE operation_logs ENABLE TRIGGER USER"))
        finally:
            engine.dispose()
