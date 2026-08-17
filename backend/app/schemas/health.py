from typing import Literal

from pydantic import BaseModel


class HealthData(BaseModel):
    status: Literal["ok"]
    service: Literal["backend"]
    version: str
    timestamp: str


DependencyName = Literal[
    "postgresql",
    "redis",
    "minio",
    "qdrant",
    "worker",
    "scanner",
    "ai_provider",
]
DependencyStatus = Literal["ok", "unavailable", "disabled"]


class DependencyCheckData(BaseModel):
    name: DependencyName
    required: bool
    status: DependencyStatus


class DependencyHealthData(BaseModel):
    status: Literal["ok", "unavailable"]
    dependencies: tuple[DependencyCheckData, ...]
    timestamp: str
