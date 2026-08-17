"""CR-011-R4 contract/offline 的纯 operation/Profile 引用图 resolver。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, NamedTuple, NoReturn, TypeAlias

AdapterId: TypeAlias = Literal["openai_chat_completions_v1", "openai_embeddings_v1"]
Capability: TypeAlias = Literal["llm_extraction", "llm_generation", "embedding"]

_PROFILE_ID = re.compile(r"^[a-z0-9_-]{1,100}$")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_OPERATION_ORDER = (
    "contract_field_extraction",
    "embedding",
    "invoice_field_extraction",
    "rag_answer",
    "report_draft",
    "risk_explanation",
)
_REQUIRED_CAPABILITY = {
    "contract_field_extraction": "llm_extraction",
    "embedding": "embedding",
    "invoice_field_extraction": "llm_extraction",
    "rag_answer": "llm_generation",
    "report_draft": "llm_generation",
    "risk_explanation": "llm_generation",
}
_MANDATORY_FALLBACK_OPERATIONS = frozenset(
    {
        "contract_field_extraction",
        "invoice_field_extraction",
        "rag_answer",
        "risk_explanation",
    }
)
_LLM_CAPABILITIES = frozenset({"llm_extraction", "llm_generation"})


class PolicyResolutionError(ValueError):
    """引用图输入无效；固定错误不携带原始标识或业务值。"""

    code = "AI_POLICY_ROUTE_GRAPH_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class ProfileValue:
    profile_id: str
    adapter_id: AdapterId
    endpoint_id: str
    model_id: str
    capabilities: tuple[Capability, ...]


@dataclass(frozen=True, slots=True)
class OperationValue:
    operation_id: str
    primary_profile_id: str
    fallback_profile_id: str | None
    report_use_fallback: bool


class ResolvedTargetIdentity(NamedTuple):
    profile_id: str
    adapter_id: AdapterId
    endpoint_id: str
    model_id: str


class ResolvedOperation(NamedTuple):
    operation_id: str
    primary: ResolvedTargetIdentity
    fallback: ResolvedTargetIdentity | None


def _fail() -> NoReturn:
    raise PolicyResolutionError


def _validate_profile(profile: ProfileValue) -> None:
    try:
        invalid = (
            type(profile.profile_id) is not str
            or _PROFILE_ID.fullmatch(profile.profile_id) is None
            or type(profile.adapter_id) is not str
            or profile.adapter_id not in {"openai_chat_completions_v1", "openai_embeddings_v1"}
            or type(profile.endpoint_id) is not str
            or _STABLE_ID.fullmatch(profile.endpoint_id) is None
            or type(profile.model_id) is not str
            or not 1 <= len(profile.model_id) <= 200
            or type(profile.capabilities) is not tuple
            or not profile.capabilities
            or not all(type(value) is str for value in profile.capabilities)
            or len(profile.capabilities) != len(set(profile.capabilities))
        )
    except AttributeError:
        _fail()
    if invalid:
        _fail()
    capability_set = set(profile.capabilities)
    if profile.adapter_id == "openai_embeddings_v1":
        if profile.capabilities != ("embedding",):
            _fail()
    elif not capability_set <= _LLM_CAPABILITIES:
        _fail()


def _target(profile: ProfileValue) -> ResolvedTargetIdentity:
    return ResolvedTargetIdentity(
        profile_id=profile.profile_id,
        adapter_id=profile.adapter_id,
        endpoint_id=profile.endpoint_id,
        model_id=profile.model_id,
    )


def resolve_policy_operations(
    *,
    profiles: tuple[ProfileValue, ...],
    operations: tuple[OperationValue, ...],
) -> tuple[ResolvedOperation, ...]:
    """一次性校验六类 operation 的完整引用图并返回不可变目标身份。"""

    if type(profiles) is not tuple or type(operations) is not tuple:
        _fail()
    if not profiles or not all(type(profile) is ProfileValue for profile in profiles):
        _fail()
    if not all(type(operation) is OperationValue for operation in operations):
        _fail()

    profile_by_id: dict[str, ProfileValue] = {}
    target_identities: set[tuple[str, str, str]] = set()
    for profile in profiles:
        _validate_profile(profile)
        identity = (profile.adapter_id, profile.endpoint_id, profile.model_id)
        if profile.profile_id in profile_by_id or identity in target_identities:
            _fail()
        profile_by_id[profile.profile_id] = profile
        target_identities.add(identity)

    operation_by_id: dict[str, OperationValue] = {}
    for operation in operations:
        try:
            invalid = (
                type(operation.operation_id) is not str
                or type(operation.primary_profile_id) is not str
                or not operation.primary_profile_id
                or (
                    operation.fallback_profile_id is not None
                    and (
                        type(operation.fallback_profile_id) is not str
                        or not operation.fallback_profile_id
                    )
                )
                or type(operation.report_use_fallback) is not bool
                or operation.operation_id in operation_by_id
            )
        except AttributeError:
            _fail()
        if invalid:
            _fail()
        operation_by_id[operation.operation_id] = operation
    if set(operation_by_id) != set(_OPERATION_ORDER):
        _fail()

    used_profile_ids: set[str] = set()
    resolved: list[ResolvedOperation] = []
    for operation_id in _OPERATION_ORDER:
        operation = operation_by_id[operation_id]
        fallback_id = operation.fallback_profile_id
        if operation_id in _MANDATORY_FALLBACK_OPERATIONS:
            if fallback_id is None or operation.report_use_fallback:
                _fail()
        elif operation_id == "report_draft":
            if operation.report_use_fallback != (fallback_id is not None):
                _fail()
        elif fallback_id is not None or operation.report_use_fallback:
            _fail()
        if fallback_id == operation.primary_profile_id:
            _fail()

        primary = profile_by_id.get(operation.primary_profile_id)
        fallback = profile_by_id.get(fallback_id) if fallback_id is not None else None
        if primary is None or (fallback_id is not None and fallback is None):
            _fail()
        required_capability = _REQUIRED_CAPABILITY[operation_id]
        if required_capability not in primary.capabilities or (
            fallback is not None and required_capability not in fallback.capabilities
        ):
            _fail()

        used_profile_ids.add(primary.profile_id)
        if fallback is not None:
            used_profile_ids.add(fallback.profile_id)
        resolved.append(
            ResolvedOperation(
                operation_id=operation_id,
                primary=_target(primary),
                fallback=_target(fallback) if fallback is not None else None,
            )
        )

    if used_profile_ids != set(profile_by_id):
        _fail()
    return tuple(resolved)
