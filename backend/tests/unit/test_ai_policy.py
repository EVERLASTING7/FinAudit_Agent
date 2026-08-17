from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.ai.policy import AiPolicyPayloadV1, canonicalize_jcs


def _operation(
    *,
    deadline_seconds: int,
    max_input_tokens_per_request: int,
    max_output_tokens_per_request: int,
    max_total_tokens: int,
    max_cost_micro_usd: int,
    max_attempts: int = 3,
    max_same_target_attempts: int = 2,
    max_provider_attempts_per_business_operation: int = 6,
    max_model_repairs: int = 2,
    report_use_fallback: bool = False,
) -> dict[str, object]:
    return {
        "connect_timeout_seconds": 5,
        "deadline_seconds": deadline_seconds,
        "max_attempts": max_attempts,
        "max_same_target_attempts": max_same_target_attempts,
        "max_provider_attempts_per_business_operation": (
            max_provider_attempts_per_business_operation
        ),
        "max_model_repairs": max_model_repairs,
        "max_input_tokens_per_request": max_input_tokens_per_request,
        "max_output_tokens_per_request": max_output_tokens_per_request,
        "max_total_tokens": max_total_tokens,
        "max_cost_micro_usd": max_cost_micro_usd,
        "report_use_fallback": report_use_fallback,
    }


def _content_payload() -> dict[str, object]:
    return {
        "policy_version": 1,
        "provider_calls_enabled": False,
        "profiles": {
            "llm_primary": {
                "profile_type": "openai-chat-completions-v1",
                "base_url": "https://llm.example.test/v1",
                "model_id": "synthetic-llm-v1",
                "allowed_response_model_ids": ("synthetic-llm-v1",),
                "auth_scheme": "bearer",
                "secret_slot": "LLM_API_KEY",
                "context_window_tokens": 65_536,
                "tokenizer_id": "synthetic-tokenizer-v1",
                "tokenizer_hash": "1" * 64,
                "embedding_dimension": None,
                "pricing_version": "synthetic-pricing-v1",
                "billing_mode": "external_usd",
                "input_price_micro_usd_per_million": 100,
                "output_price_micro_usd_per_million": 200,
                "redis_unavailable_mode": "fail_closed",
            },
            "embedding_primary": {
                "profile_type": "openai-embeddings-v1",
                "base_url": "https://embedding.example.test/v1",
                "model_id": "synthetic-embedding-v1",
                "allowed_response_model_ids": ("synthetic-embedding-v1",),
                "auth_scheme": "bearer",
                "secret_slot": "EMBEDDING_API_KEY",
                "context_window_tokens": 32_768,
                "tokenizer_id": "synthetic-embedding-tokenizer-v1",
                "tokenizer_hash": "2" * 64,
                "embedding_dimension": 1_024,
                "pricing_version": "synthetic-embedding-pricing-v1",
                "billing_mode": "external_usd",
                "input_price_micro_usd_per_million": 10,
                "output_price_micro_usd_per_million": 0,
                "redis_unavailable_mode": "fail_closed",
            },
        },
        "operations": {
            "contract_field_extraction": _operation(
                deadline_seconds=120,
                max_input_tokens_per_request=32_768,
                max_output_tokens_per_request=2_500,
                max_total_tokens=212_000,
                max_cost_micro_usd=500_000,
            ),
            "invoice_field_extraction": _operation(
                deadline_seconds=60,
                max_input_tokens_per_request=16_384,
                max_output_tokens_per_request=2_500,
                max_total_tokens=114_000,
                max_cost_micro_usd=250_000,
            ),
            "risk_explanation": _operation(
                deadline_seconds=60,
                max_input_tokens_per_request=16_384,
                max_output_tokens_per_request=1_600,
                max_total_tokens=108_000,
                max_cost_micro_usd=250_000,
            ),
            "rag_answer": _operation(
                deadline_seconds=90,
                max_input_tokens_per_request=16_384,
                max_output_tokens_per_request=1_800,
                max_total_tokens=110_000,
                max_cost_micro_usd=250_000,
            ),
            "report_draft": _operation(
                deadline_seconds=90,
                max_attempts=2,
                max_input_tokens_per_request=16_384,
                max_output_tokens_per_request=3_000,
                max_total_tokens=117_000,
                max_cost_micro_usd=250_000,
            ),
            "embedding": _operation(
                deadline_seconds=30,
                max_attempts=3,
                max_same_target_attempts=3,
                max_provider_attempts_per_business_operation=3,
                max_model_repairs=0,
                max_input_tokens_per_request=16_384,
                max_output_tokens_per_request=0,
                max_total_tokens=50_000,
                max_cost_micro_usd=50_000,
            ),
        },
        "retry": {
            "backoff_base_seconds": 1,
            "backoff_multiplier": 2,
            "backoff_max_seconds": 30,
            "jitter_ratio": 0.2,
        },
        "breaker": {
            "failures": 5,
            "window_seconds": 60,
            "open_seconds": 30,
            "half_open_probes": 1,
        },
        "rate_limits": {
            "rag": {"concurrency": 2, "rpm": 12, "tpm": 100_000, "burst": 2},
            "async_generation": {
                "concurrency": 4,
                "rpm": 30,
                "tpm": 250_000,
                "burst": 4,
            },
            "embedding": {"concurrency": 2, "rpm": 30, "tpm": 500_000, "burst": 2},
        },
        "outbound_limits": {
            "max_request_bytes": 4_194_304,
            "max_response_header_bytes": 65_536,
            "max_chat_decompressed_bytes": 2_097_152,
            "max_embedding_decompressed_bytes": 4_194_304,
        },
    }


def test_jcs_matches_rfc_8785_serialization_example() -> None:
    value = {
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27],
        "string": '€$\u000f\nA\'B"\\"/',
        "literals": [None, True, False],
    }

    assert canonicalize_jcs(value).decode() == (
        '{"literals":[null,true,false],'
        '"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
        '"string":"€$\\u000f\\nA\'B\\"\\\\\\"/"}'
    )


def test_policy_payload_digest_is_deterministic() -> None:
    first = AiPolicyPayloadV1.model_validate(_content_payload())
    reversed_payload = _content_payload()
    profiles = reversed_payload["profiles"]
    operations = reversed_payload["operations"]
    assert isinstance(profiles, dict)
    assert isinstance(operations, dict)
    reversed_payload["profiles"] = dict(reversed(tuple(profiles.items())))
    reversed_payload["operations"] = dict(reversed(tuple(operations.items())))
    second = AiPolicyPayloadV1.model_validate(reversed_payload)

    assert first.payload_sha256() == second.payload_sha256()
    assert len(first.payload_sha256()) == 64
    assert first.canonical_payload() == second.canonical_payload()


def test_policy_payload_accepts_its_strict_json_representation() -> None:
    payload = _content_payload()

    parsed = AiPolicyPayloadV1.model_validate_json(json.dumps(payload))

    assert parsed.policy_version == 1
    assert parsed.provider_calls_enabled is False


def test_policy_is_deeply_immutable() -> None:
    policy = AiPolicyPayloadV1.model_validate(_content_payload())

    with pytest.raises(ValidationError):
        policy.policy_version = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        policy.profiles["other"] = policy.profiles["llm_primary"]  # type: ignore[index]
    with pytest.raises(TypeError):
        policy.operations["rag_answer"] = policy.operations["embedding"]  # type: ignore[index]


def test_policy_rejects_unknown_fields_and_secret_values() -> None:
    payload = _content_payload()
    profiles = payload["profiles"]
    assert isinstance(profiles, dict)
    profiles["llm_primary"]["api_key"] = "synthetic-secret-must-not-be-stored"

    with pytest.raises(ValidationError):
        AiPolicyPayloadV1.model_validate(payload)


@pytest.mark.parametrize("error_source", ["extra_field", "embedded_url_credentials"])
def test_policy_validation_errors_never_echo_raw_inputs(error_source: str) -> None:
    sentinel = "synthetic-secret-must-never-be-rendered"
    payload = _content_payload()
    profiles = payload["profiles"]
    assert isinstance(profiles, dict)
    if error_source == "extra_field":
        profiles["llm_primary"]["api_key"] = sentinel
    else:
        profiles["llm_primary"]["base_url"] = f"https://user:{sentinel}@example.test/v1"

    with pytest.raises(ValidationError) as exc_info:
        AiPolicyPayloadV1.model_validate(payload)

    rendered = "\n".join(
        (
            str(exc_info.value),
            json.dumps(exc_info.value.errors(), ensure_ascii=False, default=str),
            exc_info.value.json(),
        )
    )
    assert sentinel not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_policy_json_validation_errors_never_echo_raw_inputs() -> None:
    sentinel = "synthetic-json-secret-must-never-be-rendered"
    payload = _content_payload()
    profiles = payload["profiles"]
    assert isinstance(profiles, dict)
    profiles["llm_primary"]["api_key"] = sentinel

    with pytest.raises(ValidationError) as exc_info:
        AiPolicyPayloadV1.model_validate_json(json.dumps(payload))

    rendered = "\n".join(
        (
            str(exc_info.value),
            json.dumps(exc_info.value.errors(), ensure_ascii=False, default=str),
            exc_info.value.json(),
        )
    )
    assert sentinel not in rendered


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("policy_version", True),
        ("provider_calls_enabled", 0),
    ],
)
def test_policy_rejects_bool_integer_literal_confusion(field: str, invalid: object) -> None:
    payload = _content_payload()
    payload[field] = invalid

    with pytest.raises(ValidationError, match=field):
        AiPolicyPayloadV1.model_validate(payload)


def test_policy_rejects_boolean_for_integer_literal_in_nested_policy() -> None:
    payload = _content_payload()
    retry = payload["retry"]
    assert isinstance(retry, dict)
    retry["backoff_base_seconds"] = True

    with pytest.raises(ValidationError, match="retry"):
        AiPolicyPayloadV1.model_validate(payload)


def test_policy_json_rejects_duplicate_object_keys() -> None:
    raw = json.dumps(_content_payload())
    raw = raw.replace(
        '"provider_calls_enabled": false',
        '"provider_calls_enabled": true, "provider_calls_enabled": false',
        1,
    )

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        AiPolicyPayloadV1.model_validate_json(raw)


def test_policy_python_entry_cannot_disable_strict_validation() -> None:
    payload = _content_payload()
    operations = payload["operations"]
    assert isinstance(operations, dict)
    operations["rag_answer"]["deadline_seconds"] = "90"

    with pytest.raises(ValueError, match="cannot relax strict or extra rules"):
        AiPolicyPayloadV1.model_validate(payload, strict=False)


@pytest.mark.parametrize("use_json", [False, True])
def test_policy_entries_cannot_allow_unknown_secret_fields(use_json: bool) -> None:
    payload = _content_payload()
    profiles = payload["profiles"]
    assert isinstance(profiles, dict)
    profiles["llm_primary"]["api_key"] = "synthetic-secret"

    with pytest.raises(ValueError, match="cannot relax strict or extra rules"):
        if use_json:
            AiPolicyPayloadV1.model_validate_json(json.dumps(payload), extra="allow")
        else:
            AiPolicyPayloadV1.model_validate(payload, extra="allow")


def test_policy_rejects_string_coercion_entry() -> None:
    with pytest.raises(TypeError, match="does not support model_validate_strings"):
        AiPolicyPayloadV1.model_validate_strings({"policy_version": "1"})


def test_contract_scope_rejects_enabled_provider_calls() -> None:
    payload = _content_payload()
    payload["provider_calls_enabled"] = True

    with pytest.raises(ValidationError):
        AiPolicyPayloadV1.model_validate(payload)


def test_policy_rejects_operation_value_drift() -> None:
    payload = deepcopy(_content_payload())
    operations = payload["operations"]
    assert isinstance(operations, dict)
    operations["rag_answer"]["deadline_seconds"] = 91

    with pytest.raises(ValidationError):
        AiPolicyPayloadV1.model_validate(payload)


def test_external_profile_cannot_use_process_local_restricted_mode() -> None:
    payload = _content_payload()
    profiles = payload["profiles"]
    assert isinstance(profiles, dict)
    profiles["llm_primary"]["redis_unavailable_mode"] = "process_local_restricted"

    with pytest.raises(ValidationError, match="profiles"):
        AiPolicyPayloadV1.model_validate(payload)


def test_external_profile_requires_https() -> None:
    payload = _content_payload()
    profiles = payload["profiles"]
    assert isinstance(profiles, dict)
    profiles["llm_primary"]["base_url"] = "http://public.example.test/v1"

    with pytest.raises(ValidationError, match="profiles"):
        AiPolicyPayloadV1.model_validate(payload)


def test_report_fallback_requires_the_three_step_attempt_contract() -> None:
    payload = _content_payload()
    operations = payload["operations"]
    assert isinstance(operations, dict)
    operations["report_draft"]["report_use_fallback"] = True

    with pytest.raises(ValidationError):
        AiPolicyPayloadV1.model_validate(payload)

    operations["report_draft"]["max_attempts"] = 3
    AiPolicyPayloadV1.model_validate(payload)
