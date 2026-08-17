from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

import app.ai.policy_companion as policy_companion
from app.ai.policy import canonicalize_jcs
from app.ai.policy_companion import (
    CompanionArtifactError,
    PolicyValidationResult,
    SchemaValidator,
    ValidationTarget,
    validate_policy_full,
)
from app.ai.strict_json import JsonValue
from tests.unit.test_ai_policy_companion import (
    _cases,
    _mutated_policy,
    _refresh_hash,
    _source_bytes,
)

_ROOT = Path(__file__).parents[3]
_ARTIFACTS = _ROOT / "docs" / "change-requests" / "artifacts" / "CR-011"
_POSITIVE_BYTES = (_ARTIFACTS / "ai-policy-v1.positive.json").read_bytes()
_PREHASH_BYTES = (_ARTIFACTS / "ai-policy-v1.prehash.jcs.json").read_bytes()
_SCHEMA_BYTES = (_ARTIFACTS / "ai-policy-v1.schema.json").read_bytes()
_REGISTRY_BYTES = (_ARTIFACTS / "ip-deny-cidrs-v1.json").read_bytes()
_EXPECTED_PREHASH_SHA256 = "db946ad109baf5ec84455a2d0a09ce5e29602c0d9f9ce8404901f5c63683443d"
_SCHEMA_INVALID_SIGNATURES = {
    canonicalize_jcs(_mutated_policy(case))
    for case in _cases()
    if case["expected_rule_id"] == "POL-VAL-004"
}


class _ControlledSchemaValidator:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self,
        instance: JsonValue,
        root_schema: Mapping[str, JsonValue],
    ) -> bool:
        self.calls += 1
        assert root_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        return canonicalize_jcs(instance) not in _SCHEMA_INVALID_SIGNATURES


def _ordered_source_bytes(case: dict[str, Any]) -> bytes:
    if case["expected_stage"] not in {"cross_field", "network_registry"}:
        return _source_bytes(case)
    policy = _mutated_policy(case)
    _refresh_hash(policy)
    return json.dumps(policy, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@pytest.mark.parametrize(
    ("raw_policy_bytes", "validation_target"),
    [(_POSITIVE_BYTES, "final_envelope"), (_PREHASH_BYTES, "pre_hash_payload")],
)
def test_two_positive_entries_return_the_same_frozen_pre_hash(
    raw_policy_bytes: bytes,
    validation_target: ValidationTarget,
) -> None:
    schema_validator = _ControlledSchemaValidator()

    result = validate_policy_full(
        raw_policy_bytes,
        validation_target=validation_target,
        policy_schema_bytes=_SCHEMA_BYTES,
        registry_bytes=_REGISTRY_BYTES,
        schema_validator=schema_validator,
    )

    assert result.accepted is True
    assert result.stage == "complete"
    assert result.rule_id is None
    assert result.safe_error_code is None
    assert result.detail == "policy accepted by complete ordered validation"
    assert result.pre_hash_bytes == _PREHASH_BYTES
    assert result.pre_hash_sha256 == _EXPECTED_PREHASH_SHA256
    assert result.validated_policy is not None
    assert len(cast(bytes, result.pre_hash_bytes)) == 7_569
    assert schema_validator.calls == 1
    assert PolicyValidationResult.__dataclass_params__.frozen is True


def test_full_entrypoint_reuses_single_hash_evidence_and_freezes_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonicalize_calls = 0
    original_canonicalize = policy_companion.canonicalize_jcs

    def counting_canonicalize(value: JsonValue) -> bytes:
        nonlocal canonicalize_calls
        canonicalize_calls += 1
        return original_canonicalize(value)

    monkeypatch.setattr(policy_companion, "canonicalize_jcs", counting_canonicalize)
    result = validate_policy_full(
        _POSITIVE_BYTES,
        validation_target="final_envelope",
        policy_schema_bytes=_SCHEMA_BYTES,
        registry_bytes=_REGISTRY_BYTES,
        schema_validator=_ControlledSchemaValidator(),
    )

    assert canonicalize_calls == 1
    policy = cast(Mapping[str, object], result.validated_policy)
    with pytest.raises(TypeError):
        cast(dict[str, object], policy)["policy_version"] = 2
    profiles = cast(Mapping[str, object], policy["profiles"])
    extraction = cast(Mapping[str, object], profiles["llm_extraction_primary"])
    with pytest.raises(TypeError):
        cast(dict[str, object], extraction)["model_id"] = "rewritten"
    assert "synthetic-extraction-model" not in repr(result)
    assert _PREHASH_BYTES.decode("utf-8") not in repr(result)


@pytest.mark.parametrize("case", _cases(), ids=lambda case: cast(str, case["id"]))
def test_all_25_negative_vectors_fail_at_the_exact_first_rule(case: dict[str, Any]) -> None:
    schema_validator = _ControlledSchemaValidator()
    validation_target = cast(ValidationTarget, case.get("validation_target", "final_envelope"))

    result = validate_policy_full(
        _ordered_source_bytes(case),
        validation_target=validation_target,
        policy_schema_bytes=_SCHEMA_BYTES,
        registry_bytes=_REGISTRY_BYTES,
        schema_validator=schema_validator,
    )

    assert result.accepted is False
    assert result.stage == case["expected_stage"]
    assert result.rule_id == case["expected_rule_id"]
    assert result.safe_error_code == case["expected_safe_error_code"]
    assert result.detail == "policy rejected by deterministic ordered validation rule"
    assert result.pre_hash_bytes is None
    assert result.pre_hash_sha256 is None
    assert result.validated_policy is None
    expected_calls = 0 if result.rule_id in {"POL-VAL-001", "POL-VAL-002", "POL-VAL-003"} else 1
    assert schema_validator.calls == expected_calls


def test_registry_bytes_mismatch_is_rule_005_after_schema() -> None:
    schema_validator = _ControlledSchemaValidator()

    result = validate_policy_full(
        _POSITIVE_BYTES,
        validation_target="final_envelope",
        policy_schema_bytes=_SCHEMA_BYTES,
        registry_bytes=_REGISTRY_BYTES + b" ",
        schema_validator=schema_validator,
    )

    assert result.rule_id == "POL-VAL-005"
    assert result.safe_error_code == "AI_POLICY_REGISTRY_MISMATCH"
    assert schema_validator.calls == 1


@pytest.mark.parametrize("failure_mode", ["raise", "non_bool"])
def test_schema_adapter_failure_is_a_fixed_gate_error(failure_mode: str) -> None:
    def broken_validator(
        _instance: JsonValue,
        _root_schema: Mapping[str, JsonValue],
    ) -> bool:
        if failure_mode == "raise":
            raise RuntimeError("candidate bytes must not escape")
        return cast(bool, 1)

    with pytest.raises(
        CompanionArtifactError,
        match="^policy schema validation adapter failed$",
    ) as raised:
        validate_policy_full(
            _POSITIVE_BYTES,
            validation_target="final_envelope",
            policy_schema_bytes=_SCHEMA_BYTES,
            registry_bytes=_REGISTRY_BYTES,
            schema_validator=cast(SchemaValidator, broken_validator),
        )

    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_schema_adapter_cannot_rewrite_the_candidate_for_later_rules() -> None:
    policy = json.loads(_POSITIVE_BYTES)
    policy["policy_hash"] = "0" * 64
    raw_policy_bytes = json.dumps(policy, separators=(",", ":")).encode("utf-8")

    def mutating_validator(
        instance: JsonValue,
        root_schema: Mapping[str, JsonValue],
    ) -> bool:
        assert isinstance(instance, dict)
        instance["policy_hash"] = _EXPECTED_PREHASH_SHA256
        assert isinstance(root_schema, dict)
        root_schema.clear()
        return True

    result = validate_policy_full(
        raw_policy_bytes,
        validation_target="final_envelope",
        policy_schema_bytes=_SCHEMA_BYTES,
        registry_bytes=_REGISTRY_BYTES,
        schema_validator=mutating_validator,
    )

    assert result.accepted is False
    assert result.stage == "hash"
    assert result.rule_id == "POL-VAL-006"
    assert result.safe_error_code == "AI_POLICY_HASH_MISMATCH"


@pytest.mark.parametrize(
    "legacy_ipv4",
    ["2130706433", "127.1", "0x7f000001", "0xffffffff"],
)
def test_legacy_ipv4_spellings_are_not_accepted_as_hostnames(
    legacy_ipv4: str,
) -> None:
    policy = json.loads(_POSITIVE_BYTES)
    profile = policy["profiles"]["embedding_primary"]
    profile["approved_hostnames"] = [legacy_ipv4]
    profile["base_url"] = f"http://{legacy_ipv4}:8003/v1"
    _refresh_hash(policy)

    result = validate_policy_full(
        json.dumps(policy, separators=(",", ":")).encode("utf-8"),
        validation_target="final_envelope",
        policy_schema_bytes=_SCHEMA_BYTES,
        registry_bytes=_REGISTRY_BYTES,
        schema_validator=_ControlledSchemaValidator(),
    )

    assert result.accepted is False
    assert result.stage == "cross_field"
    assert result.rule_id == "POL-VAL-009"
    assert result.safe_error_code == "AI_POLICY_HOST_INVALID"
