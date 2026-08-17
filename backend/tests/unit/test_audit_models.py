from sqlalchemy import CHAR, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models import AUDIT_TASK_STATUSES, RISK_LEVELS, Base


def test_audit_task_contract_is_exact() -> None:
    table = Base.metadata.tables["audit_tasks"]

    assert list(table.c.keys()) == [
        "id",
        "organization_id",
        "task_no",
        "name",
        "owner_id",
        "current_execution_id",
        "status",
        "description",
        "row_version",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "deleted_at",
        "deleted_by",
        "delete_reason",
    ]
    assert AUDIT_TASK_STATUSES == ("open", "completed", "archived")
    assert table.c.task_no.type.length == 80
    assert table.c.name.type.length == 300
    assert table.c.status.type.length == 30
    assert str(table.c.row_version.server_default.arg) == "1"
    assert str(table.c.created_at.server_default.arg) == "now()"
    assert str(table.c.updated_at.server_default.arg) == "now()"
    assert {column.name for column in table.c if column.nullable} == {
        "current_execution_id",
        "description",
        "created_by",
        "updated_by",
        "deleted_at",
        "deleted_by",
        "delete_reason",
    }
    assert {
        column.name: str(column.server_default.arg)
        for column in table.c
        if column.server_default is not None
    } == {
        "id": "gen_random_uuid()",
        "row_version": "1",
        "created_at": "now()",
        "updated_at": "now()",
    }
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
    foreign_keys = {
        constraint.name: tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert checks == {
        "ck_audit_tasks_soft_delete_reason_required",
        "ck_audit_tasks_status_allowed",
    }
    assert uniques == {"uq_audit_tasks_organization_id_task_no"}
    assert foreign_keys == {
        "fk_audit_tasks_created_by_users": ("users.id",),
        "fk_audit_tasks_current_execution_id_audit_task_executions": ("audit_task_executions.id",),
        "fk_audit_tasks_deleted_by_users": ("users.id",),
        "fk_audit_tasks_organization_id_organizations": ("organizations.id",),
        "fk_audit_tasks_owner_id_users": ("users.id",),
        "fk_audit_tasks_updated_by_users": ("users.id",),
    }
    assert all(
        element.ondelete is None
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        for element in constraint.elements
    )


def test_audit_rule_contract_is_exact() -> None:
    table = Base.metadata.tables["audit_rules"]

    assert list(table.c.keys()) == [
        "id",
        "rule_code",
        "version",
        "name",
        "category",
        "input_schema_json",
        "implementation_key",
        "implementation_hash",
        "application_release",
        "catalog_manifest_sha256",
        "default_risk_level",
        "explanation_template",
        "requires_policy_citation",
        "is_enabled",
        "published_at",
        "change_reason",
        "created_at",
    ]
    assert RISK_LEVELS == ("none", "notice", "low", "medium", "high")
    assert isinstance(table.c.input_schema_json.type, JSONB)
    assert isinstance(table.c.implementation_hash.type, CHAR)
    assert table.c.implementation_hash.type.length == 64
    assert isinstance(table.c.catalog_manifest_sha256.type, CHAR)
    assert table.c.catalog_manifest_sha256.type.length == 64
    assert str(table.c.requires_policy_citation.server_default.arg) == "false"
    assert str(table.c.is_enabled.server_default.arg) == "true"

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
    assert checks == {
        "ck_audit_rules_application_release_nonempty",
        "ck_audit_rules_catalog_manifest_hash_format",
        "ck_audit_rules_default_risk_level_allowed",
        "ck_audit_rules_version_positive",
    }
    assert uniques == {"uq_audit_rules_code_version"}
