from uuid import uuid4

import pytest

from app.workers.audit_handler_registry import (
    AUDIT_HANDLER_REGISTRY_HASH,
    audit_registry_artifact_hashes,
    load_audit_handler,
)
from app.workers.handler_registry import HandlerRegistryError


def test_audit_handler_registry_is_pinned_and_routes_to_audit() -> None:
    handler = load_audit_handler()

    assert handler.registry_hash == AUDIT_HANDLER_REGISTRY_HASH
    assert handler.handler.job_type == "audit_execute"
    assert handler.handler.logical_queue == "audit"
    assert handler.handler.max_attempts == 3
    assert tuple(step.step_code for step in handler.handler.steps) == ("evaluate",)
    assert tuple(scope.start_step_code for scope in handler.handler.retry_scopes) == ("evaluate",)


def test_audit_handler_validates_exact_input_and_summary() -> None:
    handler = load_audit_handler()
    execution_id = str(uuid4())
    snapshot_id = str(uuid4())
    handler.validate_input(
        {
            "execution_id": execution_id,
            "snapshot_id": snapshot_id,
            "snapshot_sha256": "a" * 64,
        }
    )
    handler.validate_summary(
        {
            "execution_id": execution_id,
            "rule_count": 15,
            "risk_count": 3,
            "overall_level": "medium",
            "retrieval_status": "degraded",
        }
    )

    with pytest.raises(HandlerRegistryError):
        handler.validate_input(
            {
                "execution_id": execution_id,
                "snapshot_id": snapshot_id,
            }
        )
    with pytest.raises(HandlerRegistryError):
        handler.validate_summary(
            {
                "execution_id": execution_id,
                "rule_count": 14,
                "risk_count": 3,
                "overall_level": "medium",
                "retrieval_status": "degraded",
            }
        )


def test_audit_registry_raw_artifacts_are_stable() -> None:
    assert audit_registry_artifact_hashes() == {
        "registry.json": "f03e675c895b44ba247cd1e4dd155637e43b0278b395e951c003781b676cdb08",
        "input.audit_execute.v1.schema.json": (
            "ceb062889d07b5c066897b06da14f8fdbff9dec0f9e4b395af2fb1c11d1454d3"
        ),
        "summary.audit_execute.v1.schema.json": (
            "3f52ec9ff332a5208fd98920e885715cd8abdf30cce231355293dc688883e871"
        ),
    }
