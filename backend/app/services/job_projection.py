"""资源 API 共用的脱敏 Job fencing 投影。"""

from datetime import datetime
from typing import Literal, cast

from app.models.reliability import AsyncJob
from app.schemas.jobs import JobActionProjectionData

_RETRYABLE_ERROR_CODES = frozenset(
    {
        "DATABASE_TRANSIENT",
        "DEPENDENCY_TIMEOUT",
        "DEPENDENCY_UNAVAILABLE",
        "RATE_LIMITED",
        "STORAGE_TRANSIENT",
        "WORKER_LOST",
    }
)


def project_job_action(job: AsyncJob, database_now: datetime) -> JobActionProjectionData:
    if database_now.tzinfo is None:
        raise ValueError("database_now must be timezone-aware")
    retryable = bool(
        job.status == "failed"
        and job.error_code in _RETRYABLE_ERROR_CODES
        and job.next_retry_at is not None
        and job.next_retry_at <= database_now
        and job.attempt_no < job.max_attempts
    )
    stage = job.current_attempt_start_step_code if job.status == "queued" else job.stage
    return JobActionProjectionData(
        id=job.id,
        status=cast(
            Literal[
                "queued",
                "running",
                "cancel_requested",
                "succeeded",
                "failed",
                "cancelled",
            ],
            job.status,
        ),
        stage=stage,
        attempt_no=job.attempt_no,
        max_attempts=job.max_attempts,
        row_version=str(job.row_version),
        retryable=retryable,
    )


__all__ = ["project_job_action"]
