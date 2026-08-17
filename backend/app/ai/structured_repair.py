"""结构化 AI 输出的离线修复编排与共享预算门禁。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from inspect import isasyncgen, isawaitable, iscoroutine, isgenerator
from math import isfinite
from typing import Protocol, TypeVar, cast

from pydantic import BaseModel

from app.ai.output_validation import (
    CitationValidationError,
    RiskExplanationValidationError,
)
from app.ai.policy_resolver import ResolvedTargetIdentity
from app.ai.pricing import (
    AttemptReservation,
    BudgetProfile,
    PricingProfile,
    calculate_preflight_reservation,
)
from app.ai.structured_output import (
    StructuredOutputIssue,
    StructuredOutputValidationError,
    validate_structured_output,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def _require_non_negative_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class StructuredRepairRequest:
    """单次 repair 可见的最小安全输入；不含原值或 Provider 原文。"""

    attempt_no: int
    target: ResolvedTargetIdentity
    issues: tuple[StructuredOutputIssue, ...]
    reservation: AttemptReservation

    def __post_init__(self) -> None:
        if (
            isinstance(self.attempt_no, bool)
            or not isinstance(self.attempt_no, int)
            or not 1 <= self.attempt_no <= 2
        ):
            raise ValueError("attempt_no must be 1 or 2")
        if not isinstance(self.target, ResolvedTargetIdentity):
            raise ValueError("target must be a ResolvedTargetIdentity")
        if (
            not isinstance(self.issues, tuple)
            or not self.issues
            or not all(isinstance(issue, StructuredOutputIssue) for issue in self.issues)
        ):
            raise ValueError("issues must be a non-empty tuple of StructuredOutputIssue")
        if not isinstance(self.reservation, AttemptReservation):
            raise ValueError("reservation must be an AttemptReservation")


class StructuredRepairCall(Protocol):
    """恰好一次物理 repair 请求；不得在回调内部 retry 或 fallback。"""

    def __call__(self, request: StructuredRepairRequest) -> str: ...


class StructuredRepairUnavailableError(Exception):
    """repair 的共享门禁或单次物理调用不可用；不携带底层原文。"""

    code = "MODEL_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class _ResultValidatorInternalError(RuntimeError):
    """结果校验器内部故障；固定消息避免泄露业务原值。"""

    code = "INTERNAL_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class StructuredRepairBudgetTracker:
    """持有单个业务操作已经提交的 Provider 最坏预算。"""

    __slots__ = (
        "_budget_profile",
        "_deadline_monotonic",
        "_monotonic",
        "_pricing_profile",
        "_provider_attempts_used",
        "_reserved_cost_micro_usd",
        "_reserved_total_tokens",
    )

    def __init__(
        self,
        *,
        budget_profile: BudgetProfile,
        pricing_profile: PricingProfile,
        provider_attempts_used: int,
        reserved_total_tokens: int,
        reserved_cost_micro_usd: int,
        deadline_monotonic: float,
        monotonic: Callable[[], float],
    ) -> None:
        if not isinstance(budget_profile, BudgetProfile):
            raise ValueError("budget_profile must be a BudgetProfile")
        if not isinstance(pricing_profile, PricingProfile):
            raise ValueError("pricing_profile must be a PricingProfile")
        _require_non_negative_integer("provider_attempts_used", provider_attempts_used)
        _require_non_negative_integer("reserved_total_tokens", reserved_total_tokens)
        _require_non_negative_integer("reserved_cost_micro_usd", reserved_cost_micro_usd)
        if provider_attempts_used > budget_profile.max_provider_attempts_per_business_operation:
            raise ValueError("provider_attempts_used exceeds budget profile")
        if reserved_total_tokens > budget_profile.max_total_tokens:
            raise ValueError("reserved_total_tokens exceeds budget profile")
        if reserved_cost_micro_usd > budget_profile.max_cost_micro_usd:
            raise ValueError("reserved_cost_micro_usd exceeds budget profile")
        if (
            isinstance(deadline_monotonic, bool)
            or not isinstance(deadline_monotonic, (int, float))
            or not isfinite(deadline_monotonic)
        ):
            raise ValueError("deadline_monotonic must be finite")
        if not callable(monotonic):
            raise ValueError("monotonic must be callable")

        self._budget_profile = budget_profile
        self._pricing_profile = pricing_profile
        self._provider_attempts_used = provider_attempts_used
        self._reserved_total_tokens = reserved_total_tokens
        self._reserved_cost_micro_usd = reserved_cost_micro_usd
        self._deadline_monotonic = float(deadline_monotonic)
        self._monotonic = monotonic

    @property
    def provider_attempts_used(self) -> int:
        return self._provider_attempts_used

    @property
    def reserved_total_tokens(self) -> int:
        return self._reserved_total_tokens

    @property
    def reserved_cost_micro_usd(self) -> int:
        return self._reserved_cost_micro_usd

    def _deadline_has_capacity(self, minimum_attempt_seconds: float) -> bool:
        try:
            now = self._monotonic()
        except Exception:
            return False
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not isfinite(now):
            return False
        return float(now) + minimum_attempt_seconds < self._deadline_monotonic

    def _deadline_is_open(self) -> bool:
        return self._deadline_has_capacity(0.0)

    def _try_reserve(
        self,
        *,
        future_model_repair_slots: int,
        input_tokens: int,
        max_output_tokens: int,
        context_window_tokens: int,
        minimum_attempt_seconds: float,
    ) -> AttemptReservation | None:
        if not self._deadline_has_capacity(minimum_attempt_seconds):
            return None
        try:
            reservation = calculate_preflight_reservation(
                self._budget_profile,
                self._pricing_profile,
                provider_attempts_used=self._provider_attempts_used,
                future_model_repair_slots=future_model_repair_slots,
                reserved_total_tokens=self._reserved_total_tokens,
                reserved_cost_micro_usd=self._reserved_cost_micro_usd,
                input_tokens=input_tokens,
                max_output_tokens=max_output_tokens,
                context_window_tokens=context_window_tokens,
            )
        except ValueError:
            return None

        # 发送前提交最坏预留；失败或异常后也不释放，避免重放导致超支。
        self._provider_attempts_used += 1
        self._reserved_total_tokens += reservation.reserved_total_tokens
        self._reserved_cost_micro_usd += reservation.reserved_cost_micro_usd
        return reservation


def _assert_result_valid(
    result: ModelT,
    result_validator: Callable[[ModelT], None],
) -> None:
    """在深拷贝上执行断言，并只透传固定消息的领域异常。"""

    validator_failed = False
    try:
        runtime_validator = cast(Callable[[ModelT], object], result_validator)
        validator_result = runtime_validator(result.model_copy(deep=True))
        if isasyncgen(validator_result):
            validator_failed = True
        elif isgenerator(validator_result):
            validator_result.close()
            validator_failed = True
        elif isawaitable(validator_result):
            if iscoroutine(validator_result):
                validator_result.close()
            validator_failed = True
    except Exception as error:
        if type(error) is CitationValidationError or type(error) is RiskExplanationValidationError:
            raise
        validator_failed = True
    if validator_failed:
        raise _ResultValidatorInternalError


def validate_structured_output_with_repair(
    raw_output: str,
    model_type: type[ModelT],
    *,
    repair_call: StructuredRepairCall,
    repair_target: ResolvedTargetIdentity,
    result_validator: Callable[[ModelT], None],
    budget: StructuredRepairBudgetTracker,
    max_model_repairs: int,
    repair_input_tokens: int,
    repair_max_output_tokens: int,
    context_window_tokens: int,
    minimum_attempt_seconds: float,
) -> ModelT:
    """先本地校验，再在共享预算内最多发送两次脱敏 repair 请求。"""

    if not callable(repair_call):
        raise TypeError("repair_call must be callable")
    if not isinstance(repair_target, ResolvedTargetIdentity):
        raise TypeError("repair_target must be a ResolvedTargetIdentity")
    if not callable(result_validator):
        raise TypeError("result_validator must be callable")
    if not isinstance(budget, StructuredRepairBudgetTracker):
        raise TypeError("budget must be a StructuredRepairBudgetTracker")
    _require_non_negative_integer("max_model_repairs", max_model_repairs)
    if max_model_repairs > 2:
        raise ValueError("max_model_repairs must not exceed 2")
    _require_non_negative_integer("repair_input_tokens", repair_input_tokens)
    _require_non_negative_integer("repair_max_output_tokens", repair_max_output_tokens)
    _require_non_negative_integer("context_window_tokens", context_window_tokens)
    if context_window_tokens == 0:
        raise ValueError("context_window_tokens must be positive")
    if (
        isinstance(minimum_attempt_seconds, bool)
        or not isinstance(minimum_attempt_seconds, (int, float))
        or not isfinite(minimum_attempt_seconds)
        or minimum_attempt_seconds <= 0
    ):
        raise ValueError("minimum_attempt_seconds must be positive and finite")

    try:
        initial_result = validate_structured_output(raw_output, model_type)
    except StructuredOutputValidationError as error:
        safe_issues = error.issues
    else:
        # 业务事实、权限和引用校验失败不是格式修复，必须原样终止。
        # validator 只作断言；不得用其返回值替换已通过严格 Schema 的对象。
        _assert_result_valid(initial_result, result_validator)
        if budget._deadline_is_open():
            return initial_result
        raise StructuredRepairUnavailableError from None

    for attempt_no in range(1, max_model_repairs + 1):
        reservation = budget._try_reserve(
            future_model_repair_slots=max_model_repairs - attempt_no,
            input_tokens=repair_input_tokens,
            max_output_tokens=repair_max_output_tokens,
            context_window_tokens=context_window_tokens,
            minimum_attempt_seconds=float(minimum_attempt_seconds),
        )
        if reservation is None:
            raise StructuredRepairUnavailableError from None

        request = StructuredRepairRequest(
            attempt_no=attempt_no,
            target=repair_target,
            issues=safe_issues,
            reservation=reservation,
        )
        repair_failed = False
        repaired_output: object = None
        try:
            repaired_output = repair_call(request)
        except Exception:
            repair_failed = True
        if repair_failed:
            raise StructuredRepairUnavailableError
        if not isinstance(repaired_output, str):
            raise StructuredRepairUnavailableError from None

        try:
            result = validate_structured_output(repaired_output, model_type)
        except StructuredOutputValidationError as error:
            safe_issues = error.issues
            continue
        # 每次修复后的完整业务校验必须通过；失败不得触发下一次格式修复。
        _assert_result_valid(result, result_validator)
        if budget._deadline_is_open():
            return result
        raise StructuredRepairUnavailableError from None

    raise StructuredOutputValidationError(safe_issues) from None
