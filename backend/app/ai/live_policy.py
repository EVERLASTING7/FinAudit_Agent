"""MiniMax M3 + 百炼 Embedding 本地真实调用 Policy 的固定机器事实源。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, cast

from app.ai.policy import canonicalize_jcs
from app.ai.strict_json import parse_strict_json

LIVE_POLICY_RESOURCE_PACKAGE: Final = "app.ai.artifacts.minimax_m3_bailian_qwen37_local_v2"
LIVE_POLICY_RESOURCE_NAME: Final = "live-ai-policy-v2.json"
LIVE_POLICY_ID: Final = "minimax-m3-bailian-qwen37-local-v2"
LIVE_POLICY_RAW_SHA256: Final = "cf638f0e9053bbea90835133bd996fc67483ee9f4fc4b47164320eeaeb1d6ea8"

_REGISTRY_SHA256 = "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"


@dataclass(frozen=True, slots=True)
class LiveOperationPolicy:
    deadline_seconds: int
    max_provider_attempts_per_business_operation: int
    max_model_repairs: int
    max_input_tokens_per_request: int
    max_output_tokens_per_request: int
    max_total_tokens: int
    cost_currency: Literal["USD"]
    max_cost_microunits: int


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
    cost_currency: Literal["USD"]
    input_price_microunits_per_million: int
    output_price_microunits_per_million: int
    max_request_bytes: int
    max_response_header_bytes: int
    max_response_body_bytes: int
    temperature: float
    top_p: float
    use_max_completion_tokens: bool
    thinking_mode: Literal["disabled", "adaptive", "enabled"] | None
    service_tier: Literal["standard"] | None
    operations: Mapping[str, LiveOperationPolicy]


@dataclass(frozen=True, slots=True)
class LiveEmbeddingOperationPolicy:
    deadline_seconds: int
    max_provider_attempts_per_business_operation: int
    max_batch_size: int
    max_input_tokens_per_text: int
    max_total_tokens: int
    cost_currency: Literal["CNY"]
    max_cost_microunits: int


@dataclass(frozen=True, slots=True)
class LiveEmbeddingPolicy:
    endpoint_id: str
    base_url: str
    approved_hostnames: tuple[str, ...]
    allowed_cidrs: tuple[str, ...]
    model_id: str
    model_revision_mode: Literal["provider_managed_alias"]
    allowed_response_model_ids: tuple[str, ...]
    embedding_dimension: int
    pricing_version: str
    cost_currency: Literal["CNY"]
    input_price_microunits_per_million: int
    output_price_microunits_per_million: int
    max_request_bytes: int
    max_response_header_bytes: int
    max_response_body_bytes: int
    operation: LiveEmbeddingOperationPolicy


_OPERATIONS: Final = MappingProxyType(
    {
        "contract_field_extraction": LiveOperationPolicy(
            120, 3, 2, 262_144, 2_500, 793_932, "USD", 250_000
        ),
        "invoice_field_extraction": LiveOperationPolicy(
            60, 3, 2, 262_144, 2_500, 793_932, "USD", 250_000
        ),
        "risk_explanation": LiveOperationPolicy(60, 3, 2, 131_072, 1_600, 397_416, "USD", 250_000),
        "rag_answer": LiveOperationPolicy(90, 3, 2, 131_072, 1_800, 398_616, "USD", 250_000),
        "report_draft": LiveOperationPolicy(90, 2, 1, 131_072, 3_000, 268_144, "USD", 250_000),
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
    cost_currency="USD",
    input_price_microunits_per_million=300_000,
    output_price_microunits_per_million=1_200_000,
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

LIVE_EMBEDDING_POLICY: Final = LiveEmbeddingPolicy(
    endpoint_id="bailian-beijing-compatible-v1",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    approved_hostnames=("dashscope.aliyuncs.com",),
    allowed_cidrs=(),
    model_id="qwen3.7-text-embedding",
    model_revision_mode="provider_managed_alias",
    allowed_response_model_ids=("qwen3.7-text-embedding",),
    embedding_dimension=1_024,
    pricing_version="bailian-qwen37-embedding-cny-2026-08-17",
    cost_currency="CNY",
    input_price_microunits_per_million=500_000,
    output_price_microunits_per_million=0,
    max_request_bytes=4_194_304,
    max_response_header_bytes=65_536,
    max_response_body_bytes=4_194_304,
    operation=LiveEmbeddingOperationPolicy(
        deadline_seconds=30,
        max_provider_attempts_per_business_operation=1,
        max_batch_size=20,
        max_input_tokens_per_text=128_000,
        max_total_tokens=2_560_000,
        cost_currency="CNY",
        max_cost_microunits=1_280_000,
    ),
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
            "cost_currency": LIVE_LLM_POLICY.cost_currency,
            "completion_token_field": "max_completion_tokens",
            "context_window_tokens": LIVE_LLM_POLICY.context_window_tokens,
            "endpoint_id": LIVE_LLM_POLICY.endpoint_id,
            "input_accounting_mode": "request_utf8_bytes_plus_4096_v1",
            "input_price_microunits_per_million": (
                LIVE_LLM_POLICY.input_price_microunits_per_million
            ),
            "model_id": LIVE_LLM_POLICY.model_id,
            "model_version": LIVE_LLM_POLICY.model_version,
            "network_scope": "external_public",
            "output_price_microunits_per_million": (
                LIVE_LLM_POLICY.output_price_microunits_per_million
            ),
            "pricing_version": LIVE_LLM_POLICY.pricing_version,
            "secret_slot": "LLM_API_KEY",
            "service_tier": LIVE_LLM_POLICY.service_tier,
            "thinking_mode": LIVE_LLM_POLICY.thinking_mode,
        },
        "embedding_profile": {
            "adapter_id": "openai_embeddings_v1",
            "address_policy_version": "ip-deny-cidrs-v1",
            "allowed_cidrs": [],
            "allowed_response_model_ids": list(LIVE_EMBEDDING_POLICY.allowed_response_model_ids),
            "approved_hostnames": list(LIVE_EMBEDDING_POLICY.approved_hostnames),
            "base_url": LIVE_EMBEDDING_POLICY.base_url,
            "billing_mode": "external_cny",
            "cost_currency": LIVE_EMBEDDING_POLICY.cost_currency,
            "embedding_dimension": LIVE_EMBEDDING_POLICY.embedding_dimension,
            "endpoint_id": LIVE_EMBEDDING_POLICY.endpoint_id,
            "input_price_microunits_per_million": (
                LIVE_EMBEDDING_POLICY.input_price_microunits_per_million
            ),
            "model_id": LIVE_EMBEDDING_POLICY.model_id,
            "model_revision_mode": LIVE_EMBEDDING_POLICY.model_revision_mode,
            "network_scope": "external_public",
            "pricing_version": LIVE_EMBEDDING_POLICY.pricing_version,
            "secret_slot": "EMBEDDING_API_KEY",
            "usage_input_token_field": "prompt_tokens",
            "output_price_microunits_per_million": (
                LIVE_EMBEDDING_POLICY.output_price_microunits_per_million
            ),
        },
        "operations": {
            **{
                operation_id: {
                    "deadline_seconds": operation.deadline_seconds,
                    "cost_currency": operation.cost_currency,
                    "max_cost_microunits": operation.max_cost_microunits,
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
            "embedding": {
                "deadline_seconds": LIVE_EMBEDDING_POLICY.operation.deadline_seconds,
                "max_batch_size": LIVE_EMBEDDING_POLICY.operation.max_batch_size,
                "cost_currency": LIVE_EMBEDDING_POLICY.operation.cost_currency,
                "max_input_tokens_per_text": (
                    LIVE_EMBEDDING_POLICY.operation.max_input_tokens_per_text
                ),
                "max_total_tokens": LIVE_EMBEDDING_POLICY.operation.max_total_tokens,
                "max_cost_microunits": (LIVE_EMBEDDING_POLICY.operation.max_cost_microunits),
                "max_provider_attempts_per_business_operation": (
                    LIVE_EMBEDDING_POLICY.operation.max_provider_attempts_per_business_operation
                ),
            },
        },
        "outbound_limits": {
            "ip_deny_registry_sha256": _REGISTRY_SHA256,
            "ip_deny_registry_version": "ip-deny-cidrs-v1",
            "max_chat_decompressed_bytes": LIVE_LLM_POLICY.max_response_body_bytes,
            "max_embedding_decompressed_bytes": (LIVE_EMBEDDING_POLICY.max_response_body_bytes),
            "max_request_bytes": LIVE_LLM_POLICY.max_request_bytes,
            "max_response_header_bytes": LIVE_LLM_POLICY.max_response_header_bytes,
        },
        "policy_id": LIVE_POLICY_ID,
        "policy_version": 2,
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
    "LIVE_EMBEDDING_POLICY",
    "LIVE_LLM_POLICY",
    "LIVE_POLICY_HASH",
    "LIVE_POLICY_ID",
    "LIVE_POLICY_RAW_SHA256",
    "LIVE_POLICY_RESOURCE_NAME",
    "LIVE_POLICY_RESOURCE_PACKAGE",
    "LiveEmbeddingOperationPolicy",
    "LiveEmbeddingPolicy",
    "LiveLlmPolicy",
    "LiveOperationPolicy",
    "validate_live_policy_bytes",
]
