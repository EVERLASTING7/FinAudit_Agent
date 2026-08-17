from uuid import UUID

import pytest
from pydantic import ValidationError

from app.workers.messages import JOB_EVENT_SCHEMA_VERSION, JobDispatchMessage

JOB_ID = UUID("70000000-0000-0000-0000-000000000001")


def test_job_dispatch_message_has_only_the_authorized_body_fields() -> None:
    message = JobDispatchMessage.model_validate(
        {
            "job_id": str(JOB_ID),
            "event_schema_version": JOB_EVENT_SCHEMA_VERSION,
        }
    )

    assert message.model_dump(mode="json") == {
        "job_id": str(JOB_ID),
        "event_schema_version": JOB_EVENT_SCHEMA_VERSION,
    }


@pytest.mark.parametrize("field", ["trace_id", "traceparent", "input_json", "resource_id"])
def test_job_dispatch_message_rejects_non_contract_body_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        JobDispatchMessage.model_validate(
            {
                "job_id": str(JOB_ID),
                "event_schema_version": JOB_EVENT_SCHEMA_VERSION,
                field: "must-travel-outside-the-body",
            }
        )


@pytest.mark.parametrize("version", [0, 2, "1", None])
def test_job_dispatch_message_rejects_unsupported_schema_versions(version: object) -> None:
    with pytest.raises(ValidationError):
        JobDispatchMessage.model_validate(
            {
                "job_id": str(JOB_ID),
                "event_schema_version": version,
            }
        )


def test_job_dispatch_message_rejects_invalid_job_id() -> None:
    with pytest.raises(ValidationError):
        JobDispatchMessage.model_validate(
            {
                "job_id": "not-a-uuid",
                "event_schema_version": JOB_EVENT_SCHEMA_VERSION,
            }
        )
