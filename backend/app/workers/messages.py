"""Celery Job 投递消息契约。"""

from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

JOB_EVENT_SCHEMA_VERSION: Final = 1


class JobDispatchMessage(BaseModel):
    """只携带可从 PostgreSQL 恢复 Job 的最小消息。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    job_id: UUID
    event_schema_version: Literal[1]

    @field_validator("job_id", mode="before")
    @classmethod
    def parse_canonical_job_id(cls, value: object) -> UUID:
        if type(value) is not str:
            raise ValueError("job_id must be a canonical UUID string")
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("job_id must be a canonical UUID string")
        return parsed
