from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import URL, func, select, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from app.audit.rule_catalog import RuleCatalogError, publish_builtin_catalog
from app.db.migration import create_migration_engine
from app.db.session import create_session_factory
from app.models.audit import AuditRule
from tests.integration.database.test_migrations import (
    AUDIT_REPORT_RUNTIME_REVISION,
    CURRENT_REVISION,
    RETRIEVAL_RUNTIME_REVISION,
    configure_disposable_database,
    current_revision,
    reset_disposable_database_to_head,
    safe_database_error_signature,
    user_trigger_names,
)

pytestmark = pytest.mark.integration

AUDIT_RUNTIME_TABLES = (
    "audit_task_items",
    "audit_task_executions",
    "audit_task_snapshots",
    "rule_executions",
    "audit_risks",
    "risk_citations",
    "audit_reports",
    "ai_call_logs",
)


def _clear_rules(database_url: URL) -> None:
    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE audit_rules DISABLE TRIGGER USER"))
            connection.execute(text("DELETE FROM audit_rules"))
            connection.execute(text("ALTER TABLE audit_rules ENABLE TRIGGER USER"))
    finally:
        engine.dispose()


def test_audit_runtime_catalog_and_empty_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)

    for table_name in AUDIT_RUNTIME_TABLES:
        assert user_trigger_names(database_url, table_name) == {
            f"trg_{table_name}_no_truncate_v1",
            f"trg_{table_name}_state_v1",
        }
    assert user_trigger_names(database_url, "audit_tasks") == {"trg_audit_tasks_runtime_v1"}

    command.downgrade(alembic_config, RETRIEVAL_RUNTIME_REVISION)
    assert current_revision(database_url) == RETRIEVAL_RUNTIME_REVISION
    command.upgrade(alembic_config, AUDIT_REPORT_RUNTIME_REVISION)
    assert current_revision(database_url) == AUDIT_REPORT_RUNTIME_REVISION


def test_builtin_rule_catalog_is_atomic_idempotent_and_blocks_nonempty_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory.begin() as session:
            first = publish_builtin_catalog(
                session,
                application_release="test-release-1",
                change_reason="publish synthetic catalog",
            )
        with factory.begin() as session:
            replay = publish_builtin_catalog(
                session,
                application_release="test-release-1",
                change_reason="replay synthetic catalog",
            )
        with factory.begin() as session:
            second = publish_builtin_catalog(
                session,
                application_release="test-release-2",
                change_reason="publish next synthetic catalog",
            )

        assert (first.outcome, first.version) == ("published", 1)
        assert replay == first.__class__("noop", 1, first.manifest_sha256)
        assert (second.outcome, second.version) == ("published", 2)
        with factory() as session:
            rows = tuple(
                session.scalars(select(AuditRule).order_by(AuditRule.version, AuditRule.rule_code))
            )
            assert len(rows) == 30
            assert session.scalar(select(func.count()).select_from(AuditRule)) == 30
            assert {row.catalog_manifest_sha256 for row in rows if row.version == 1} == {
                first.manifest_sha256
            }
            assert {row.catalog_manifest_sha256 for row in rows if row.version == 2} == {
                second.manifest_sha256
            }

        with pytest.raises(DBAPIError) as downgrade_error:
            command.downgrade(alembic_config, RETRIEVAL_RUNTIME_REVISION)
        assert safe_database_error_signature(downgrade_error.value) == ("55000", None)
        assert current_revision(database_url) == CURRENT_REVISION

        with factory.begin() as session:
            latest = rows[-1]
            session.add(
                AuditRule(
                    id=uuid4(),
                    rule_code="RULE-999",
                    version=3,
                    name="synthetic invalid extra rule",
                    category="identity",
                    input_schema_json={
                        "type": "object",
                        "additionalProperties": False,
                        "required": [],
                        "properties": {},
                    },
                    implementation_key="synthetic.invalid",
                    implementation_hash="a" * 64,
                    application_release="test-release-3",
                    catalog_manifest_sha256="b" * 64,
                    default_risk_level="notice",
                    explanation_template="synthetic invalid extra rule",
                    requires_policy_citation=False,
                    is_enabled=True,
                    published_at=latest.published_at,
                    change_reason="verify fail closed",
                    created_at=latest.created_at,
                )
            )
        with pytest.raises(RuleCatalogError):
            with factory.begin() as session:
                publish_builtin_catalog(
                    session,
                    application_release="test-release-3",
                    change_reason="must fail on extra row",
                )
    finally:
        engine.dispose()
        _clear_rules(database_url)

    command.downgrade(alembic_config, RETRIEVAL_RUNTIME_REVISION)
    assert current_revision(database_url) == RETRIEVAL_RUNTIME_REVISION
    command.upgrade(alembic_config, AUDIT_REPORT_RUNTIME_REVISION)
