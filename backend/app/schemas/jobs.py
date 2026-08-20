"""资源详情内嵌的最小 Job action 投影。"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PositiveIntegerString = Annotated[str, Field(pattern=r"^[1-9]\d*$")]


class JobActionProjectionData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    status: Literal[
        "queued",
        "running",
        "cancel_requested",
        "succeeded",
        "failed",
        "cancelled",
    ]
    stage: str | None = Field(default=None, min_length=1, max_length=80)
    attempt_no: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    row_version: PositiveIntegerString
    retryable: bool


__all__ = ["JobActionProjectionData"]
