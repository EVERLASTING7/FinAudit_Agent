import re
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import OperationalError

from alembic import command
from app.db.migration import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    MigrationConfigError,
    create_migration_engine,
    read_migration_url,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RELIABILITY_TABLE_COLUMNS = {
    "async_jobs": (
        "id",
        "organization_id",
        "job_type",
        "resource_type",
        "resource_id",
        "status",
        "stage",
        "attempt_no",
        "max_attempts",
        "current_attempt_start_step_code",
        "next_retry_at",
        "worker_id",
        "started_at",
        "finished_at",
        "error_code",
        "error_message",
        "input_hash",
        "input_json",
        "input_schema_version",
        "idempotency_record_id",
        "handler_registry_version",
        "handler_registry_hash",
        "retry_policy_version",
        "retry_policy_hash",
        "lease_policy_version",
        "lease_policy_hash",
        "lease_owner",
        "lease_expires_at",
        "heartbeat_at",
        "row_version",
        "trace_id",
        "created_by",
        "created_at",
    ),
    "async_job_steps": (
        "id",
        "job_id",
        "step_seq",
        "step_code",
        "status",
        "attempt_no",
        "started_at",
        "finished_at",
        "summary_json",
        "error_code",
        "trace_id",
    ),
    "outbox_events": (
        "id",
        "aggregate_type",
        "aggregate_id",
        "event_id",
        "event_type",
        "event_version",
        "event_sequence",
        "payload_json",
        "status",
        "attempt_count",
        "next_attempt_at",
        "published_at",
        "last_error",
        "trace_id",
        "created_at",
    ),
}
RELIABILITY_FUNCTIONS = (
    "enforce_async_jobs_state_v1",
    "enforce_async_job_steps_state_v1",
    "enforce_job_step_consistency_v1",
    "enforce_outbox_events_state_v1",
)
RELIABILITY_TRIGGERS = (
    "trg_async_jobs_state_v1",
    "trg_async_jobs_consistency_v1",
    "trg_async_job_steps_state_v1",
    "trg_async_job_steps_no_truncate_v1",
    "trg_async_job_steps_consistency_v1",
    "trg_outbox_events_state_v1",
    "trg_outbox_events_no_truncate_v1",
)


def _offline_table_columns(rendered_sql: str, table_name: str) -> tuple[str, ...]:
    match = re.search(
        rf"CREATE TABLE (?:public\.)?{re.escape(table_name)} \(\n(?P<body>.*?)\n\);",
        rendered_sql,
        flags=re.DOTALL,
    )
    assert match is not None
    return tuple(
        re.findall(
            r"(?m)^[ \t]+([a-z][a-z0-9_]*)[ \t]+"
            r"(?:UUID|VARCHAR|CHAR|INTEGER|BIGINT|NUMERIC|DATE|TEXT|JSONB|TIMESTAMP)",
            match.group("body"),
        )
    )


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_or_empty_database_url_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", value)

    with pytest.raises(MigrationConfigError, match="DATABASE_URL"):
        read_migration_url()


@pytest.mark.parametrize(
    "placeholder",
    [
        "CHANGE_ME",
        "postgresql+psycopg://user:CHANGE_ME@localhost/test_db",
        "REPLACE_DATABASE_URL",
        "postgresql+psycopg://user:REPLACE_PASSWORD@localhost/test_db",
    ],
)
def test_placeholder_database_url_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    placeholder: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", placeholder)

    with pytest.raises(MigrationConfigError) as exc_info:
        read_migration_url()

    assert placeholder not in str(exc_info.value)


def test_invalid_database_url_error_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    password = "migration-password-must-not-leak"
    invalid_url = f"://migration:{password}@localhost/test_db"
    monkeypatch.setenv("DATABASE_URL", invalid_url)

    with pytest.raises(MigrationConfigError) as exc_info:
        read_migration_url()

    rendered_error = f"{exc_info.value!r}\n{exc_info.value}"
    assert password not in rendered_error
    assert invalid_url not in rendered_error


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///finaudit_test.db",
        "postgresql://migration@localhost/finaudit_test",
        "postgresql+psycopg2://migration@localhost/finaudit_test",
        "postgresql+psycopg://migration@localhost",
    ],
)
def test_non_psycopg_or_database_less_url_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)

    with pytest.raises(MigrationConfigError) as exc_info:
        read_migration_url()

    assert database_url not in str(exc_info.value)


@pytest.mark.parametrize(
    "query",
    [
        "host=override-db",
        "hostaddr=127.0.0.2",
        "port=6543",
        "dbname=other_db",
        "service=other_service",
        "servicefile=other_service.conf",
    ],
)
def test_migration_url_rejects_query_parameters_that_override_the_target(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
) -> None:
    database_url = (
        "postgresql+psycopg://migration:safe-test-value@validated-db:5432/finaudit_test?" + query
    )
    monkeypatch.setenv("DATABASE_URL", database_url)

    with pytest.raises(MigrationConfigError) as exc_info:
        read_migration_url()

    assert database_url not in str(exc_info.value)


def test_migration_url_allows_non_target_application_name_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://migration:safe-test-value@validated-db:5432/finaudit_test"
        "?application_name=finaudit-migration",
    )

    assert read_migration_url().query["application_name"] == "finaudit-migration"


def test_engine_hides_url_password_and_sql_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    password = "migration-password-must-not-leak"
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql+psycopg://migration:{password}@localhost/test_db",
    )

    engine = create_migration_engine(read_migration_url())

    assert engine.hide_parameters is True
    assert password not in repr(engine.url)
    engine.dispose()


def test_engine_has_bounded_default_connect_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://migration:safe-test-value@localhost/finaudit_test",
    )

    with patch("app.db.migration.create_engine") as mocked_create_engine:
        create_migration_engine(read_migration_url())

    assert mocked_create_engine.call_args.kwargs["connect_args"] == {
        "connect_timeout": DEFAULT_CONNECT_TIMEOUT_SECONDS,
        "client_encoding": "UTF8",
    }


def test_offline_sql_is_limited_to_the_approved_extension_baseline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "offline-migration-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "20260806_001", sql=True)

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    for extension in ("pgcrypto", "btree_gist", "citext"):
        assert f"CREATE EXTENSION IF NOT EXISTS {extension};" in rendered_output
    assert rendered_output.count("CREATE EXTENSION IF NOT EXISTS") == 3
    assert rendered_output.count("CREATE TABLE ") == 1
    assert "CREATE TABLE alembic_version" in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_offline_downgrade_only_reverts_the_revision_record(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "offline-downgrade-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.downgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "20260806_001:base", sql=True)

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    assert rendered_output.count("DELETE FROM alembic_version") == 1
    assert "20260806_001" in rendered_output
    assert "CREATE EXTENSION" not in rendered_output
    assert "DROP EXTENSION" not in rendered_output
    assert "CREATE TABLE" not in rendered_output
    assert "DROP TABLE" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_identity_core_offline_upgrade_is_exact_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "identity-offline-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260806_001:20260807_002",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    expected_tables = {"organizations", "users", "roles", "token_sessions"}
    assert rendered_output.count("CREATE TABLE ") == len(expected_tables)
    for table_name in expected_tables:
        assert f"CREATE TABLE {table_name}" in rendered_output
    for role_code in (
        "system_admin",
        "finance_reviewer",
        "audit_reviewer",
        "contract_admin",
        "read_only",
    ):
        assert role_code in rendered_output
    assert "INSERT INTO roles" in rendered_output
    assert "INSERT INTO organizations" not in rendered_output
    assert "INSERT INTO users" not in rendered_output
    assert "break_glass_requests" not in rendered_output
    assert "user_roles" not in rendered_output
    assert "ck_organizations_singleton_key_is_one" in rendered_output
    assert "ck_roles_code_allowed" in rendered_output
    assert "ck_users_failed_login_count_nonnegative" in rendered_output
    assert "ck_token_sessions_expires_after_issue" in rendered_output
    assert "_ck_organizations_" not in rendered_output
    assert "_ck_roles_" not in rendered_output
    assert "_ck_users_" not in rendered_output
    assert "_ck_token_sessions_" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_identity_core_offline_downgrade_drops_only_its_four_tables(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "identity-downgrade-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.downgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_002:20260806_001",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    expected_tables = {"organizations", "users", "roles", "token_sessions"}
    assert rendered_output.count("DROP TABLE ") == len(expected_tables)
    for table_name in expected_tables:
        assert f"DROP TABLE {table_name}" in rendered_output
    assert "DROP EXTENSION" not in rendered_output
    assert "break_glass_requests" not in rendered_output
    assert "user_roles" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_idempotency_offline_upgrade_creates_only_its_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "idempotency-offline-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_002:20260807_003",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    assert rendered_output.count("CREATE TABLE ") == 1
    assert "CREATE TABLE idempotency_records" in rendered_output
    assert "uq_idempotency_records_organization_user_key" in rendered_output
    assert "ck_idempotency_records_expires_after_creation" in rendered_output
    assert "_ck_idempotency_records_" not in rendered_output
    assert "INSERT INTO" not in rendered_output
    assert "CREATE EXTENSION" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_idempotency_offline_downgrade_drops_only_its_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "idempotency-downgrade-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.downgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_003:20260807_002",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    assert rendered_output.count("DROP TABLE ") == 1
    assert "DROP TABLE idempotency_records" in rendered_output
    assert "DROP EXTENSION" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_audit_rules_offline_upgrade_creates_only_immutable_empty_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "audit-rules-offline-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_003:20260807_004",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    assert rendered_output.count("CREATE TABLE ") == 1
    assert "CREATE TABLE audit_rules" in rendered_output
    assert "uq_audit_rules_code_version" in rendered_output
    assert "ck_audit_rules_version_positive" in rendered_output
    assert "ck_audit_rules_default_risk_level_allowed" in rendered_output
    assert "_ck_audit_rules_" not in rendered_output
    assert "CREATE FUNCTION finaudit_reject_audit_rules_mutation" in rendered_output
    assert "CREATE TRIGGER trg_audit_rules_immutable" in rendered_output
    assert "CREATE TRIGGER trg_audit_rules_no_truncate" in rendered_output
    assert "INSERT INTO" not in rendered_output
    assert "CREATE EXTENSION" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_audit_rules_offline_downgrade_is_empty_only_and_scoped(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "audit-rules-downgrade-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.downgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_004:20260807_003",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    assert "LOCK TABLE audit_rules IN ACCESS EXCLUSIVE MODE" in rendered_output
    assert "refusing to drop non-empty audit_rules" in rendered_output
    assert "DROP TRIGGER trg_audit_rules_no_truncate ON audit_rules" in rendered_output
    assert "DROP TRIGGER trg_audit_rules_immutable ON audit_rules" in rendered_output
    assert "DROP FUNCTION finaudit_reject_audit_rules_mutation()" in rendered_output
    assert rendered_output.count("DROP TABLE ") == 1
    assert "DROP TABLE audit_rules" in rendered_output
    assert "DROP EXTENSION" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_audit_tasks_offline_upgrade_creates_only_its_empty_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "audit-tasks-offline-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_004:20260807_005",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    assert rendered_output.count("CREATE TABLE ") == 1
    assert "CREATE TABLE audit_tasks" in rendered_output
    assert "uq_audit_tasks_organization_id_task_no" in rendered_output
    assert "ck_audit_tasks_status_allowed" in rendered_output
    assert "ck_audit_tasks_soft_delete_reason_required" in rendered_output
    assert "_ck_audit_tasks_" not in rendered_output
    assert "fk_audit_tasks_organization_id_organizations" in rendered_output
    assert "fk_audit_tasks_owner_id_users" in rendered_output
    assert "FOREIGN KEY(current_execution_id)" not in rendered_output
    assert "INSERT INTO" not in rendered_output
    assert "CREATE TRIGGER" not in rendered_output
    assert "CREATE FUNCTION" not in rendered_output
    assert "CREATE EXTENSION" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_audit_tasks_offline_downgrade_is_empty_only_and_scoped(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "audit-tasks-downgrade-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.downgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_005:20260807_004",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    assert "LOCK TABLE audit_tasks IN ACCESS EXCLUSIVE MODE" in rendered_output
    assert "refusing to drop non-empty audit_tasks" in rendered_output
    assert rendered_output.count("DROP TABLE ") == 1
    assert "DROP TABLE audit_tasks" in rendered_output
    assert "DROP EXTENSION" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_financial_master_offline_upgrade_is_exact_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "financial-master-offline-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_005:20260807_006",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    assert rendered_output.count("SHOW server_encoding;") == 1
    assert rendered_output.index("SHOW server_encoding;") < rendered_output.index(
        "CREATE TABLE contracts"
    )
    assert "current_setting('server_encoding')" in rendered_output
    assert "PostgreSQL server_encoding must be UTF8" in rendered_output
    assert rendered_output.count("CREATE TABLE ") == 3
    for table_name in ("contracts", "invoices", "suppliers"):
        assert f"CREATE TABLE {table_name}" in rendered_output
    for index_name in (
        "uq_contracts_organization_contract_no",
        "idx_contracts_org_status",
        "idx_contracts_party_b_tax",
        "idx_invoices_duplicate_lookup",
        "idx_invoices_org_date",
        "idx_invoices_seller_tax",
        "uq_suppliers_organization_tax_identity",
    ):
        assert f"INDEX {index_name}" in rendered_output
    assert (
        "CREATE INDEX idx_contracts_party_b_tax ON contracts (organization_id, party_b_tax_no);"
    ) in rendered_output
    circular_foreign_keys = (
        "fk_contracts_supplier_id_suppliers",
        "fk_invoices_supplier_id_suppliers",
        "fk_suppliers_source_contract_id_contracts",
        "fk_suppliers_source_invoice_id_invoices",
    )
    assert rendered_output.count("ALTER TABLE ") == len(circular_foreign_keys)
    for constraint_name in circular_foreign_keys:
        assert f"ADD CONSTRAINT {constraint_name}" in rendered_output
    assert "INSERT INTO" not in rendered_output
    assert "CREATE TRIGGER" not in rendered_output
    assert "CREATE FUNCTION" not in rendered_output
    assert "CREATE EXTENSION" not in rendered_output
    assert "CASCADE" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_financial_master_offline_downgrade_has_exact_lock_and_drop_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "financial-master-downgrade-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.downgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_006:20260807_005",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    lock_timeout_position = rendered_output.index("SET LOCAL lock_timeout = '5s';")
    contract_lock_position = rendered_output.index("LOCK TABLE contracts IN ACCESS EXCLUSIVE MODE;")
    invoice_lock_position = rendered_output.index("LOCK TABLE invoices IN ACCESS EXCLUSIVE MODE;")
    supplier_lock_position = rendered_output.index("LOCK TABLE suppliers IN ACCESS EXCLUSIVE MODE;")
    nonempty_guard_position = rendered_output.index("ERRCODE = '55000'")
    first_drop_position = rendered_output.index("ALTER TABLE suppliers DROP CONSTRAINT")
    assert (
        lock_timeout_position
        < contract_lock_position
        < invoice_lock_position
        < supplier_lock_position
        < nonempty_guard_position
        < first_drop_position
    )
    expected_drops = (
        "ALTER TABLE suppliers DROP CONSTRAINT fk_suppliers_source_invoice_id_invoices;",
        "ALTER TABLE suppliers DROP CONSTRAINT fk_suppliers_source_contract_id_contracts;",
        "ALTER TABLE invoices DROP CONSTRAINT fk_invoices_supplier_id_suppliers;",
        "ALTER TABLE contracts DROP CONSTRAINT fk_contracts_supplier_id_suppliers;",
        "DROP TABLE suppliers;",
        "DROP TABLE invoices;",
        "DROP TABLE contracts;",
    )
    positions = [rendered_output.index(statement) for statement in expected_drops]
    assert positions == sorted(positions)
    assert rendered_output.count("DROP CONSTRAINT") == 4
    assert rendered_output.count("DROP TABLE ") == 3
    assert "CASCADE" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_reliability_core_offline_upgrade_is_exact_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "reliability-offline-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_006:20260807_007",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    normalized_output = " ".join(rendered_output.split())
    assert rendered_output.count("CREATE TABLE ") == 3
    assert rendered_output.count("CREATE FUNCTION ") == 4
    assert len(re.findall(r"CREATE (?:CONSTRAINT )?TRIGGER ", rendered_output)) == 7
    assert len(re.findall(r"CREATE (?:UNIQUE )?INDEX ", rendered_output)) == 5
    for table_name, expected_columns in RELIABILITY_TABLE_COLUMNS.items():
        assert _offline_table_columns(rendered_output, table_name) == expected_columns
    table_positions = [
        rendered_output.index(f"CREATE TABLE {table_name}")
        for table_name in RELIABILITY_TABLE_COLUMNS
    ]
    assert table_positions == sorted(table_positions)
    for index_sql in (
        "CREATE UNIQUE INDEX uq_async_jobs_active_resource_input ON async_jobs "
        "(organization_id, job_type, resource_type, resource_id, input_hash) "
        "WHERE status IN ('queued', 'running', 'cancel_requested');",
        "CREATE INDEX idx_async_jobs_claim ON async_jobs (status, next_retry_at);",
        "CREATE INDEX idx_async_jobs_resource_created ON async_jobs "
        "(resource_type, resource_id, created_at DESC);",
        "CREATE UNIQUE INDEX uq_async_job_steps_one_running_per_attempt "
        "ON async_job_steps (job_id, attempt_no) WHERE status = 'running';",
        "CREATE INDEX idx_outbox_events_claim ON outbox_events "
        "(status, next_attempt_at, created_at);",
    ):
        assert index_sql in rendered_output
    for constraint_name in (
        "pk_async_jobs",
        "ck_async_jobs_status_allowed",
        "ck_async_jobs_attempt_bounds",
        "ck_async_jobs_input_schema_version_positive",
        "ck_async_jobs_row_version_positive",
        "ck_async_jobs_job_type_format",
        "ck_async_jobs_current_attempt_start_step_code_format",
        "ck_async_jobs_stage_format",
        "ck_async_jobs_hashes_lower_hex",
        "ck_async_jobs_version_formats",
        "ck_async_jobs_lease_owner_canonical_uuid_v4",
        "ck_async_jobs_error_code_safe_format",
        "ck_async_jobs_state_field_matrix",
        "fk_async_jobs_organization_id_organizations",
        "fk_async_jobs_idempotency_record_id_idempotency_records",
        "fk_async_jobs_created_by_users",
        "pk_async_job_steps",
        "ck_async_job_steps_step_seq_positive",
        "ck_async_job_steps_attempt_no_positive",
        "ck_async_job_steps_step_code_format",
        "ck_async_job_steps_status_allowed",
        "ck_async_job_steps_error_code_safe_format",
        "ck_async_job_steps_state_field_matrix",
        "fk_async_job_steps_job_id_async_jobs",
        "uq_async_job_steps_job_id_step_seq_attempt_no",
        "pk_outbox_events",
        "ck_outbox_events_event_version_positive",
        "ck_outbox_events_event_sequence_positive",
        "ck_outbox_events_attempt_count_bounds",
        "ck_outbox_events_status_allowed",
        "ck_outbox_events_identity_nonempty",
        "ck_outbox_events_state_field_matrix",
        "uq_outbox_events_event_id_event_type",
        "uq_outbox_events_aggregate_type_aggregate_id_event_sequence",
    ):
        assert rendered_output.count(constraint_name) == 1
    for function_name in RELIABILITY_FUNCTIONS:
        assert rendered_output.count(f"CREATE FUNCTION {function_name}()") == 1
    for trigger_name in RELIABILITY_TRIGGERS:
        assert rendered_output.count(f"TRIGGER {trigger_name}") == 1
    for required_semantic in (
        "unsupported async job lease policy",
        "cancel request must preserve async job fencing",
        "NEW.started_at IS DISTINCT FROM OLD.started_at",
        "invalid async job step lease recovery terminal",
        "active attempt contains an invalid prior terminal step",
        "terminal attempt contains an invalid prior step",
        "DELIVERY_ATTEMPTS_EXHAUSTED",
        "UNKNOWN_DELIVERY_ERROR",
    ):
        assert required_semantic in rendered_output
    assert "OLD.status = 'running' AND NEW.status = 'cancel_requested'" in normalized_output
    assert "INSERT INTO" not in rendered_output
    assert "CREATE EXTENSION" not in rendered_output
    assert "CASCADE" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_reliability_core_offline_downgrade_has_exact_lock_and_drop_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "reliability-downgrade-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.downgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_007:20260807_006",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    expected_order = (
        "SET LOCAL lock_timeout = '5s';",
        "LOCK TABLE async_jobs IN ACCESS EXCLUSIVE MODE;",
        "LOCK TABLE async_job_steps IN ACCESS EXCLUSIVE MODE;",
        "LOCK TABLE outbox_events IN ACCESS EXCLUSIVE MODE;",
        "ERRCODE = '55000'",
        "DROP TABLE outbox_events;",
        "DROP TABLE async_job_steps;",
        "DROP TABLE async_jobs;",
        "DROP FUNCTION enforce_job_step_consistency_v1();",
        "DROP FUNCTION enforce_outbox_events_state_v1();",
        "DROP FUNCTION enforce_async_job_steps_state_v1();",
        "DROP FUNCTION enforce_async_jobs_state_v1();",
    )
    positions = [rendered_output.index(statement) for statement in expected_order]
    assert positions == sorted(positions)
    assert "refusing to drop non-empty reliability core tables" in rendered_output
    assert rendered_output.count("DROP TABLE ") == 3
    assert rendered_output.count("DROP FUNCTION ") == 4
    assert "DROP TRIGGER" not in rendered_output
    assert "CASCADE" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_privileged_auth_core_offline_upgrade_is_exact_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "privileged-auth-offline-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_007:20260807_008",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    expected_columns = {
        "break_glass_requests": (
            "id",
            "organization_id",
            "target_user_id",
            "target_role_code",
            "requested_by",
            "reason",
            "requested_duration_seconds",
            "status",
            "effective_from",
            "expires_at",
            "decided_by",
            "decision_at",
            "decision_reason",
            "revoked_by",
            "revoked_at",
            "revoke_reason",
            "row_version",
            "created_at",
            "updated_at",
            "trace_id",
        ),
        "user_roles": (
            "id",
            "user_id",
            "role_id",
            "assigned_by",
            "assignment_source",
            "assigned_at",
            "expires_at",
            "break_glass_request_id",
            "assignment_reason",
            "revoked_at",
            "revoked_by",
            "revoke_reason",
        ),
    }

    assert rendered_output.count("CREATE TABLE public.") == 2
    for table_name, columns in expected_columns.items():
        assert f"CREATE TABLE public.{table_name}" in rendered_output
        assert _offline_table_columns(rendered_output, table_name) == columns
        assert f"REVOKE ALL ON TABLE public.{table_name} FROM PUBLIC;" in rendered_output
    assert rendered_output.count("CREATE FUNCTION public.") == 5
    assert len(re.findall(r"CREATE (?:CONSTRAINT )?TRIGGER ", rendered_output)) == 10
    assert rendered_output.count("REVOKE ALL ON FUNCTION public.") == 5
    assert rendered_output.count("assigned_at <= database_now") == 8
    assert "fixed privileged-auth role preflight failed" in rendered_output
    assert "EXCLUDE USING gist" in rendered_output
    assert "COALESCE(expires_at, 'infinity'::timestamptz)" in rendered_output
    assert "'[)'" in rendered_output
    assert "INSERT INTO" not in rendered_output
    assert "CREATE EXTENSION" not in rendered_output
    assert " GRANT " not in rendered_output
    assert "CASCADE" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_privileged_auth_core_offline_downgrade_has_exact_lock_and_drop_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "privileged-auth-downgrade-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.downgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_008:20260807_007",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    expected_order = (
        "SET LOCAL lock_timeout = '5s';",
        "LOCK TABLE public.break_glass_requests IN ACCESS EXCLUSIVE MODE;",
        "LOCK TABLE public.user_roles IN ACCESS EXCLUSIVE MODE;",
        "ERRCODE = '55000'",
        "LOCK TABLE public.users IN ACCESS EXCLUSIVE MODE;",
        "LOCK TABLE public.roles IN ACCESS EXCLUSIVE MODE;",
        "DROP TRIGGER trg_users_role_sod_v1 ON public.users;",
        "DROP TRIGGER trg_roles_role_sod_v1 ON public.roles;",
        "DROP TABLE public.user_roles;",
        "DROP TABLE public.break_glass_requests;",
        "DROP FUNCTION public.enforce_roles_invariants_v1();",
        "DROP FUNCTION public.enforce_break_glass_requests_state_v1();",
    )
    positions = [rendered_output.index(statement) for statement in expected_order]
    assert positions == sorted(positions)
    assert "refusing to drop non-empty privileged-auth tables" in rendered_output
    assert rendered_output.count("DROP TRIGGER ") == 10
    assert rendered_output.count("DROP TABLE public.") == 2
    assert rendered_output.count("DROP FUNCTION public.") == 5
    assert "CASCADE" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_financial_relationship_core_offline_upgrade_is_exact_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "financial-relationship-offline-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.upgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_008:20260807_009",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    expected_columns = {
        "supplementary_agreements": (
            "id",
            "organization_id",
            "contract_id",
            "agreement_no",
            "name",
            "signed_date",
            "effective_date",
            "status",
            "confirmation_status",
            "confirmed_by",
            "confirmed_at",
            "confirmation_reason",
            "critical_fact_hash",
            "row_version",
            "created_at",
            "created_by",
            "updated_at",
            "updated_by",
            "deleted_at",
            "deleted_by",
            "delete_reason",
        ),
        "invoice_items": (
            "id",
            "invoice_id",
            "line_no",
            "item_name",
            "specification",
            "unit",
            "quantity",
            "unit_price",
            "amount_excluding_tax",
            "tax_rate",
            "tax_amount",
            "total_amount",
            "evidence_json",
            "row_version",
        ),
        "contract_invoices": (
            "id",
            "contract_id",
            "invoice_id",
            "status",
            "match_reasons_json",
            "suggested_by",
            "confirmed_by",
            "confirmed_at",
            "cancelled_by",
            "cancelled_at",
            "cancel_reason",
            "row_version",
            "created_at",
            "created_by",
            "deleted_at",
        ),
    }

    assert rendered_output.count("CREATE TABLE public.") == 3
    for table_name, columns in expected_columns.items():
        assert f"CREATE TABLE public.{table_name}" in rendered_output
        assert _offline_table_columns(rendered_output, table_name) == columns
    assert "CREATE UNIQUE INDEX uq_contract_invoice_pair_active" in rendered_output
    assert "CREATE UNIQUE INDEX uq_invoice_confirmed_primary_contract" in rendered_output
    assert "CONSTRAINT uq_invoice_items_invoice_id_line_no UNIQUE" in rendered_output
    assert "supplementary_agreement_changes" not in rendered_output
    assert "INSERT INTO" not in rendered_output
    assert "CASCADE" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_financial_relationship_core_offline_downgrade_has_exact_lock_and_drop_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "financial-relationship-downgrade-value-must-not-leak"
    database_url = f"postgresql+psycopg://migration:{password}@localhost/finaudit_offline_test"
    monkeypatch.setenv("DATABASE_URL", database_url)

    command.downgrade(
        Config(str(BACKEND_ROOT / "alembic.ini")),
        "20260807_009:20260807_008",
        sql=True,
    )

    captured = capsys.readouterr()
    rendered_output = f"{captured.out}\n{captured.err}"
    expected_order = (
        "SET LOCAL lock_timeout = '5s';",
        "LOCK TABLE public.contract_invoices IN ACCESS EXCLUSIVE MODE;",
        "LOCK TABLE public.invoice_items IN ACCESS EXCLUSIVE MODE;",
        "LOCK TABLE public.supplementary_agreements IN ACCESS EXCLUSIVE MODE;",
        "ERRCODE = '55000'",
        "DROP TABLE public.contract_invoices;",
        "DROP TABLE public.invoice_items;",
        "DROP TABLE public.supplementary_agreements;",
    )
    positions = [rendered_output.index(statement) for statement in expected_order]
    assert positions == sorted(positions)
    assert "refusing to drop non-empty financial relationship tables" in rendered_output
    assert rendered_output.count("DROP TABLE public.") == 3
    assert "CASCADE" not in rendered_output
    assert password not in rendered_output
    assert database_url not in rendered_output


def test_financial_master_online_encoding_guard_rejects_non_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20260807_006")
    assert revision is not None
    module = revision.module
    result = SimpleNamespace(scalar_one=lambda: "LATIN1")
    bind = SimpleNamespace(execute=lambda statement: result)
    monkeypatch.setattr(module.op, "get_context", lambda: SimpleNamespace(as_sql=False))
    monkeypatch.setattr(module.op, "get_bind", lambda: bind)

    with pytest.raises(RuntimeError, match="server_encoding must be UTF8"):
        module._require_utf8_server_encoding()


def test_unreachable_database_error_does_not_leak_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    password = "migration-password-must-not-leak"
    monkeypatch.setattr("app.db.migration.DEFAULT_CONNECT_TIMEOUT_SECONDS", 1)
    with socket.socket() as reserved_socket:
        reserved_socket.bind(("127.0.0.1", 0))
        port = reserved_socket.getsockname()[1]
        monkeypatch.setenv(
            "DATABASE_URL",
            f"postgresql+psycopg://migration:{password}@127.0.0.1:{port}/finaudit_test",
        )

        with pytest.raises(OperationalError) as exc_info:
            command.current(Config(str(BACKEND_ROOT / "alembic.ini")))

    captured = capsys.readouterr()
    rendered_output = (
        f"{exc_info.value!r}\n{exc_info.value}\n{captured.out}\n{captured.err}\n{caplog.text}"
    )
    assert password not in rendered_output
