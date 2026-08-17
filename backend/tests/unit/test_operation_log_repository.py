from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.models.operations import OperationLog
from app.repositories.operation_log import OperationLogRepository


def _repository() -> tuple[OperationLogRepository, Mock]:
    session = Mock(spec=Session)
    return OperationLogRepository(session), session


def test_append_user_operation_adds_only_validated_projection() -> None:
    repository, session = _repository()
    organization_id = uuid4()
    actor_id = uuid4()
    resource_id = uuid4()
    trace_id = uuid4()

    record = repository.append(
        organization_id=organization_id,
        actor_kind="user",
        actor_id=actor_id,
        action_code="users.status_changed",
        outcome="succeeded",
        resource_type="user",
        resource_id=resource_id,
        trace_id=trace_id,
        change_summary={
            "from_status": "active",
            "to_status": "disabled",
            "row_version": "2",
        },
    )

    assert isinstance(record, OperationLog)
    assert record.organization_id == organization_id
    assert record.actor_id == actor_id
    assert record.resource_id == resource_id
    assert record.change_summary_json == {
        "from_status": "active",
        "to_status": "disabled",
        "row_version": "2",
    }
    session.add.assert_called_once_with(record)


@pytest.mark.parametrize(
    ("overrides", "summary"),
    (
        ({"actor_kind": "anonymous", "actor_id": uuid4()}, {"failure_code": "invalid_credentials"}),
        ({"actor_kind": "user", "organization_id": None}, {"failure_code": "invalid_credentials"}),
        ({"action_code": "users.unknown"}, {}),
        ({"outcome": "unknown"}, {"failure_code": "invalid_credentials"}),
        ({"resource_type": "user", "resource_id": None}, {"failure_code": "invalid_credentials"}),
        (
            {"resource_type": "User", "resource_id": uuid4()},
            {"failure_code": "invalid_credentials"},
        ),
    ),
)
def test_append_rejects_invalid_identity_shape(
    overrides: dict[str, object],
    summary: dict[str, object],
) -> None:
    repository, session = _repository()
    values: dict[str, object] = {
        "organization_id": None,
        "actor_kind": "anonymous",
        "actor_id": None,
        "action_code": "auth.login.failed",
        "outcome": "denied",
        "resource_type": None,
        "resource_id": None,
        "trace_id": uuid4(),
        "change_summary": summary,
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        repository.append(**values)  # type: ignore[arg-type]
    session.add.assert_not_called()


@pytest.mark.parametrize(
    ("action_code", "summary"),
    (
        ("auth.login.failed", {}),
        ("auth.login.failed", {"failure_code": "password-was-secret"}),
        ("auth.logout", {"session_recognized": "yes"}),
        ("authorization.denied", {"permission_code": "users.*"}),
        ("users.created", {"fixed_roles": ["system_admin"], "row_version": 1}),
        (
            "users.status_changed",
            {"from_status": "active", "to_status": "deleted", "row_version": "2"},
        ),
        ("users.password_reset", {"row_version": "0"}),
        (
            "users.roles_replaced",
            {
                "old_roles": ["read_only", "read_only"],
                "new_roles": ["system_admin"],
                "row_version": "2",
            },
        ),
        (
            "break_glass.requested",
            {
                "target_role_code": "read_only",
                "status": "pending",
                "row_version": "1",
                "requested_duration_seconds": 300,
            },
        ),
    ),
)
def test_append_rejects_unregistered_or_sensitive_summary_shape(
    action_code: str,
    summary: dict[str, object],
) -> None:
    repository, session = _repository()

    with pytest.raises(ValueError):
        repository.append(
            organization_id=None,
            actor_kind="anonymous",
            actor_id=None,
            action_code=action_code,
            outcome="denied",
            resource_type=None,
            resource_id=None,
            trace_id=uuid4(),
            change_summary=summary,
        )
    session.add.assert_not_called()


def test_append_accepts_exact_anonymous_login_failure_summary() -> None:
    repository, session = _repository()

    record = repository.append(
        organization_id=None,
        actor_kind="anonymous",
        actor_id=None,
        action_code="auth.login.failed",
        outcome="denied",
        resource_type=None,
        resource_id=None,
        trace_id=uuid4(),
        change_summary={"failure_code": "invalid_credentials"},
    )

    assert record.change_summary_json == {"failure_code": "invalid_credentials"}
    session.add.assert_called_once_with(record)


def test_append_accepts_redacted_invoice_extraction_summary() -> None:
    repository, session = _repository()

    record = repository.append(
        organization_id=uuid4(),
        actor_kind="system",
        actor_id=None,
        action_code="invoices.extraction_created",
        outcome="succeeded",
        resource_type="invoice",
        resource_id=uuid4(),
        trace_id=uuid4(),
        change_summary={
            "field_count": 9,
            "item_count": 1,
            "duplicate_status": "unique",
            "row_version": "1",
        },
    )

    assert record.change_summary_json == {
        "field_count": 9,
        "item_count": 1,
        "duplicate_status": "unique",
        "row_version": "1",
    }
    session.add.assert_called_once_with(record)


def test_append_accepts_redacted_audit_evaluation_summary() -> None:
    repository, session = _repository()

    record = repository.append(
        organization_id=uuid4(),
        actor_kind="system",
        actor_id=None,
        action_code="audits.execution_evaluated",
        outcome="succeeded",
        resource_type="audit_task_execution",
        resource_id=uuid4(),
        trace_id=uuid4(),
        change_summary={
            "retrieval_status": "degraded",
            "risk_count": 4,
            "rule_count": 15,
            "status": "pending_finance_review",
        },
    )

    assert record.change_summary_json == {
        "retrieval_status": "degraded",
        "risk_count": 4,
        "rule_count": 15,
        "status": "pending_finance_review",
    }
    session.add.assert_called_once_with(record)


def test_append_rejects_audit_reason_text_in_redacted_summary() -> None:
    repository, session = _repository()

    with pytest.raises(ValueError):
        repository.append(
            organization_id=uuid4(),
            actor_kind="user",
            actor_id=uuid4(),
            action_code="audits.execution_cancelled",
            outcome="succeeded",
            resource_type="audit_task_execution",
            resource_id=uuid4(),
            trace_id=uuid4(),
            change_summary={"reason": "sensitive", "status": "cancelled"},
        )
    session.add.assert_not_called()


def test_file_management_logs_only_reason_digest() -> None:
    repository, session = _repository()
    resource_id = uuid4()
    job_id = uuid4()

    archived = repository.append(
        organization_id=uuid4(),
        actor_kind="user",
        actor_id=uuid4(),
        action_code="files.archived",
        outcome="succeeded",
        resource_type="file",
        resource_id=resource_id,
        trace_id=uuid4(),
        change_summary={
            "reason_sha256": "a" * 64,
            "status": "archived",
            "row_version": "3",
        },
    )
    retried = repository.append(
        organization_id=uuid4(),
        actor_kind="user",
        actor_id=uuid4(),
        action_code="files.retry_queued",
        outcome="succeeded",
        resource_type="file",
        resource_id=resource_id,
        trace_id=uuid4(),
        change_summary={
            "job_id": str(job_id),
            "reason_sha256": "b" * 64,
            "stage": "scan",
            "row_version": "4",
        },
    )

    assert "reason" not in archived.change_summary_json
    assert "reason" not in retried.change_summary_json
    assert session.add.call_count == 2


def test_file_management_log_rejects_raw_reason_text() -> None:
    repository, session = _repository()

    with pytest.raises(ValueError):
        repository.append(
            organization_id=uuid4(),
            actor_kind="user",
            actor_id=uuid4(),
            action_code="files.archived",
            outcome="succeeded",
            resource_type="file",
            resource_id=uuid4(),
            trace_id=uuid4(),
            change_summary={
                "reason": "sensitive business text",
                "status": "archived",
                "row_version": "3",
            },
        )

    session.add.assert_not_called()
