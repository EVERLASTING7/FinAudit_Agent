"""代表性性能证据的确定性、可复算计算边界。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

PerformanceWorkload = Literal[
    "list_request",
    "upload_acceptance",
    "clear_invoice_process",
    "contract_20_page_process",
    "top5_retrieval",
    "full_rag_response",
]

PERFORMANCE_THRESHOLDS_MS: dict[PerformanceWorkload, int] = {
    "list_request": 800,
    "upload_acceptance": 3_000,
    "clear_invoice_process": 30_000,
    "contract_20_page_process": 120_000,
    "top5_retrieval": 2_000,
    "full_rag_response": 15_000,
}

DurationMs = Annotated[int, Field(gt=0)]
DurationSamples = Annotated[tuple[DurationMs, ...], Field(min_length=1)]
UnsuccessfulSampleCount = Annotated[int, Field(ge=0)]


def _parse_aware_timestamp(value: str) -> datetime:
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp must use ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


class PerformanceEvidenceProfile(BaseModel):
    """§8.2 要求随性能结果固定记录的参考条件。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    environment_id: str = Field(min_length=1, max_length=200)
    application_release: str = Field(min_length=1, max_length=200)
    hardware_profile: str = Field(min_length=1, max_length=1_000)
    model_profile: str = Field(min_length=1, max_length=1_000)
    document_profile: str = Field(min_length=1, max_length=1_000)
    concurrency_profile: str = Field(min_length=1, max_length=1_000)


class PerformanceRoundInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    workload_ids: ClassVar[tuple[PerformanceWorkload, ...]] = tuple(PERFORMANCE_THRESHOLDS_MS)

    round_number: int = Field(ge=1)
    evidence_ref: str = Field(min_length=1, max_length=500)
    started_at: str = Field(min_length=1, max_length=100)
    completed_at: str = Field(min_length=1, max_length=100)
    durations_ms: dict[PerformanceWorkload, DurationSamples]
    unsuccessful_sample_counts: dict[PerformanceWorkload, UnsuccessfulSampleCount]
    upload_waited_for_long_task: bool
    parallel_audit_task_count: int = Field(ge=0)
    lost_audit_result_count: int = Field(ge=0)
    duplicate_audit_adoption_count: int = Field(ge=0)

    @field_validator("durations_ms", mode="before")
    @classmethod
    def validate_duration_map(cls, value: object) -> object:
        if type(value) is not dict or set(value) != set(cls.workload_ids):
            raise ValueError("durations_ms must contain every frozen workload exactly once")
        return {
            workload_id: tuple(samples) if type(samples) is list else samples
            for workload_id, samples in value.items()
        }

    @field_validator("unsuccessful_sample_counts", mode="before")
    @classmethod
    def validate_unsuccessful_count_map(cls, value: object) -> object:
        if type(value) is not dict or set(value) != set(cls.workload_ids):
            raise ValueError(
                "unsuccessful_sample_counts must contain every frozen workload exactly once"
            )
        return value

    @model_validator(mode="after")
    def validate_time_window(self) -> Self:
        if _parse_aware_timestamp(self.completed_at) <= _parse_aware_timestamp(self.started_at):
            raise ValueError("completed_at must be later than started_at")
        if any(
            self.unsuccessful_sample_counts[workload_id] > len(self.durations_ms[workload_id])
            for workload_id in self.workload_ids
        ):
            raise ValueError("unsuccessful sample count cannot exceed sample count")
        return self


class RepresentativePerformanceEvaluationInput(BaseModel):
    """性能计算输入；引用字段不验证外部审批或代表性真实性。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["representative-performance-evaluation-v1"]
    evidence_set_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    evidence_set_version: str = Field(min_length=1, max_length=100)
    approval_ref: str = Field(min_length=1, max_length=500)
    representative: Literal[True]
    profile: PerformanceEvidenceProfile
    rounds: tuple[PerformanceRoundInput, ...] = Field(min_length=3)

    @field_validator("rounds", mode="before")
    @classmethod
    def parse_rounds(cls, value: object) -> object:
        return tuple(value) if type(value) is list else value

    @model_validator(mode="after")
    def validate_consecutive_rounds(self) -> Self:
        expected_numbers = tuple(range(1, len(self.rounds) + 1))
        actual_numbers = tuple(item.round_number for item in self.rounds)
        if actual_numbers != expected_numbers:
            raise ValueError("round_number must be consecutive and start at one")
        evidence_refs = tuple(item.evidence_ref for item in self.rounds)
        if len(evidence_refs) != len(set(evidence_refs)):
            raise ValueError("evidence_ref must be unique")
        for previous, current in zip(self.rounds[:-1], self.rounds[1:], strict=True):
            if _parse_aware_timestamp(current.started_at) < _parse_aware_timestamp(
                previous.completed_at
            ):
                raise ValueError("performance rounds must not overlap")
        return self


class P95Metric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    workload_id: PerformanceWorkload
    sample_count: int = Field(gt=0)
    unsuccessful_sample_count: int = Field(ge=0)
    p95_ms: int = Field(ge=0)
    threshold_ms: int = Field(gt=0)
    passed: bool


class ParallelAuditMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_count: int = Field(ge=0)
    lost_result_count: int = Field(ge=0)
    duplicate_adoption_count: int = Field(ge=0)
    passed: bool


class PerformanceRoundResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    round_number: int = Field(ge=1)
    evidence_ref: str
    workloads: tuple[P95Metric, ...]
    upload_async_passed: bool
    parallel_audit: ParallelAuditMetric
    passed: bool


class RepresentativePerformanceEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["representative-performance-evaluation-result-v1"]
    evidence_set_id: str
    evidence_set_version: str
    approval_ref: str
    profile: PerformanceEvidenceProfile
    round_count: int = Field(ge=3)
    rounds: tuple[PerformanceRoundResult, ...]
    threshold_status: Literal["PASSED", "FAILED"]
    formal_acceptance_status: Literal["NOT_DETERMINED"] = "NOT_DETERMINED"


def _nearest_rank_p95(samples: tuple[int, ...]) -> int:
    ordered = sorted(samples)
    rank = (len(ordered) * 95 + 99) // 100
    return ordered[rank - 1]


def _evaluate_round(item: PerformanceRoundInput) -> PerformanceRoundResult:
    workload_results = tuple(
        P95Metric(
            workload_id=workload_id,
            sample_count=len(item.durations_ms[workload_id]),
            unsuccessful_sample_count=item.unsuccessful_sample_counts[workload_id],
            p95_ms=(p95_ms := _nearest_rank_p95(item.durations_ms[workload_id])),
            threshold_ms=threshold_ms,
            passed=(p95_ms <= threshold_ms and item.unsuccessful_sample_counts[workload_id] == 0),
        )
        for workload_id, threshold_ms in PERFORMANCE_THRESHOLDS_MS.items()
    )
    parallel_audit = ParallelAuditMetric(
        task_count=item.parallel_audit_task_count,
        lost_result_count=item.lost_audit_result_count,
        duplicate_adoption_count=item.duplicate_audit_adoption_count,
        passed=(
            item.parallel_audit_task_count >= 3
            and item.lost_audit_result_count == 0
            and item.duplicate_audit_adoption_count == 0
        ),
    )
    upload_async_passed = not item.upload_waited_for_long_task
    passed = (
        all(metric.passed for metric in workload_results)
        and upload_async_passed
        and parallel_audit.passed
    )
    return PerformanceRoundResult(
        round_number=item.round_number,
        evidence_ref=item.evidence_ref,
        workloads=workload_results,
        upload_async_passed=upload_async_passed,
        parallel_audit=parallel_audit,
        passed=passed,
    )


def evaluate_representative_performance(
    evaluation: RepresentativePerformanceEvaluationInput,
) -> RepresentativePerformanceEvaluationResult:
    """计算 §8.2 门槛；不把数值通过升级为正式 AC/UAT 通过。"""

    rounds = tuple(_evaluate_round(item) for item in evaluation.rounds)
    return RepresentativePerformanceEvaluationResult(
        schema_version="representative-performance-evaluation-result-v1",
        evidence_set_id=evaluation.evidence_set_id,
        evidence_set_version=evaluation.evidence_set_version,
        approval_ref=evaluation.approval_ref,
        profile=evaluation.profile,
        round_count=len(rounds),
        rounds=rounds,
        threshold_status="PASSED" if all(item.passed for item in rounds) else "FAILED",
    )


__all__ = [
    "PERFORMANCE_THRESHOLDS_MS",
    "PerformanceEvidenceProfile",
    "PerformanceRoundInput",
    "RepresentativePerformanceEvaluationInput",
    "RepresentativePerformanceEvaluationResult",
    "evaluate_representative_performance",
]
