"""MiniMax M3 本地真实调用 Policy 的固定机器事实源。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, cast

from app.ai.policy import canonicalize_jcs
from app.ai.strict_json import parse_strict_json

LIVE_POLICY_RESOURCE_PACKAGE: Final = "app.ai.artifacts.minimax_m3_local_v1"
LIVE_POLICY_RESOURCE_NAME: Final = "live-ai-policy-v1.json"
LIVE_POLICY_ID: Final = "minimax-m3-local-v1"
LIVE_POLICY_RAW_SHA256: Final = "477c204f1c7d9811e4dd964c9e9ff63cc11f2eacf7388472e3e8c86a76417175"

_REGISTRY_SHA256 = "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"


@dataclass(frozen=True, slots=True)
class LiveOperationPolicy:
    deadline_seconds: int
    max_provider_attempts_per_business_operation: int
    max_model_repairs: int
    max_input_tokens_per_request: int
    max_output_tokens_per_request: int
    max_total_tokens: int
    max_cost_micro_usd: int


@dataclass(frozen=True, slots=True)
class LiveLlmPolicy:
    endpoint_id: str
    base_url: str
    approved_hostnames: tuple[str, ...]
    allowed_cidrs: tuple[str, ...]
    model_id: str
    model_version: str
    allowed_response_model_ids: tuple[str, ...]
    context_window_tokens: int
    pricing_version: str
    input_price_micro_usd_per_million: int
    output_price_micro_usd_per_million: int
    max_request_bytes: int
    max_response_header_bytes: int
    max_response_body_bytes: int
    temperature: float
    top_p: float
    use_max_completion_tokens: bool
    thinking_mode: Literal["disabled", "adaptive", "enabled"] | None
    service_tier: Literal["standard"] | None
    operations: Mapping[str, LiveOperationPolicy]


_OPERATIONS: Final = MappingProxyType(
    {
        "contract_field_extraction": LiveOperationPolicy(
            120, 3, 2, 262_144, 2_500, 793_932, 250_000
        ),
        "invoice_field_extraction": LiveOperationPolicy(60, 3, 2, 262_144, 2_500, 793_932, 250_000),
        "risk_explanation": LiveOperationPolicy(60, 3, 2, 131_072, 1_600, 397_416, 250_000),
        "rag_answer": LiveOperationPolicy(90, 3, 2, 131_072, 1_800, 398_616, 250_000),
        "report_draft": LiveOperationPolicy(90, 2, 1, 131_072, 3_000, 268_144, 250_000),
    }
)

LIVE_LLM_POLICY: Final = LiveLlmPolicy(
    endpoint_id="minimax-global-api-v1",
    base_url="https://api.minimaxi.com/v1",
    approved_hostnames=("api.minimaxi.com",),
    allowed_cidrs=(),
    model_id="MiniMax-M3",
    model_version="minimax-m3-2026-06-01",
    allowed_response_model_ids=("MiniMax-M3",),
    context_window_tokens=512_000,
    pricing_version="minimax-m3-paygo-2026-08-16-lte-512k",
    input_price_micro_usd_per_million=300_000,
    output_price_micro_usd_per_million=1_200_000,
    max_request_bytes=4_194_304,
    max_response_header_bytes=65_536,
    max_response_body_bytes=2_097_152,
    temperature=0.0,
    top_p=0.95,
    use_max_completion_tokens=True,
    thinking_mode="disabled",
    service_tier="standard",
    operations=_OPERATIONS,
)


def _expected_policy() -> dict[str, object]:
    return {
        "environment_scope": ["local", "test"],
        "llm_profile": {
            "adapter_id": "openai_chat_completions_v1",
            "address_policy_version": "ip-deny-cidrs-v1",
            "allowed_cidrs": [],
            "allowed_response_model_ids": list(LIVE_LLM_POLICY.allowed_response_model_ids),
            "approved_hostnames": list(LIVE_LLM_POLICY.approved_hostnames),
            "base_url": LIVE_LLM_POLICY.base_url,
            "billing_mode": "external_usd",
            "completion_token_field": "max_completion_tokens",
            "context_window_tokens": LIVE_LLM_POLICY.context_window_tokens,
            "endpoint_id": LIVE_LLM_POLICY.endpoint_id,
            "input_accounting_mode": "request_utf8_bytes_plus_4096_v1",
            "input_price_micro_usd_per_million": (
                LIVE_LLM_POLICY.input_price_micro_usd_per_million
            ),
            "model_id": LIVE_LLM_POLICY.model_id,
            "model_version": LIVE_LLM_POLICY.model_version,
            "network_scope": "external_public",
            "output_price_micro_usd_per_million": (
                LIVE_LLM_POLICY.output_price_micro_usd_per_million
            ),
            "pricing_version": LIVE_LLM_POLICY.pricing_version,
            "secret_slot": "LLM_API_KEY",
            "service_tier": LIVE_LLM_POLICY.service_tier,
            "thinking_mode": LIVE_LLM_POLICY.thinking_mode,
        },
        "operations": {
            operation_id: {
                "deadline_seconds": operation.deadline_seconds,
                "max_cost_micro_usd": operation.max_cost_micro_usd,
                "max_input_tokens_per_request": operation.max_input_tokens_per_request,
                "max_model_repairs": operation.max_model_repairs,
                "max_output_tokens_per_request": operation.max_output_tokens_per_request,
                "max_provider_attempts_per_business_operation": (
                    operation.max_provider_attempts_per_business_operation
                ),
                "max_total_tokens": operation.max_total_tokens,
            }
            for operation_id, operation in LIVE_LLM_POLICY.operations.items()
        },
        "outbound_limits": {
            "ip_deny_registry_sha256": _REGISTRY_SHA256,
            "ip_deny_registry_version": "ip-deny-cidrs-v1",
            "max_chat_decompressed_bytes": LIVE_LLM_POLICY.max_response_body_bytes,
            "max_request_bytes": LIVE_LLM_POLICY.max_request_bytes,
            "max_response_header_bytes": LIVE_LLM_POLICY.max_response_header_bytes,
        },
        "policy_id": LIVE_POLICY_ID,
        "policy_version": 1,
        "provider_calls_enabled": True,
        "sampling": {
            "temperature": LIVE_LLM_POLICY.temperature,
            "top_p": LIVE_LLM_POLICY.top_p,
        },
    }


LIVE_POLICY_CANONICAL_BYTES: Final = canonicalize_jcs(_expected_policy())
LIVE_POLICY_HASH: Final = hashlib.sha256(LIVE_POLICY_CANONICAL_BYTES).hexdigest()


def validate_live_policy_bytes(raw_policy: bytes) -> bool:
    """仅接受固定字节身份和精确字段，不反射不可信内容。"""

    if (
        type(raw_policy) is not bytes
        or hashlib.sha256(raw_policy).hexdigest() != LIVE_POLICY_RAW_SHA256
    ):
        return False
    try:
        parsed = parse_strict_json(raw_policy).value
    except (TypeError, ValueError):
        return False
    return parsed == cast(object, _expected_policy())


__all__ = [
    "LIVE_LLM_POLICY",
    "LIVE_POLICY_HASH",
    "LIVE_POLICY_ID",
    "LIVE_POLICY_RAW_SHA256",
    "LIVE_POLICY_RESOURCE_NAME",
    "LIVE_POLICY_RESOURCE_PACKAGE",
    "LiveLlmPolicy",
    "LiveOperationPolicy",
    "validate_live_policy_bytes",
]
