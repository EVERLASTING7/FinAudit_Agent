from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from app.ai.policy import canonicalize_jcs
from app.ai.policy_companion import (
    IsolatedOutcome,
    PrefixStatus,
    evaluate_isolated_rule,
    validate_policy_prefix,
)
from app.ai.strict_json import JsonValue, parse_strict_json

_ROOT = Path(__file__).parents[3]
_ARTIFACTS = _ROOT / "docs" / "change-requests" / "artifacts" / "CR-011"
_POSITIVE_BYTES = (_ARTIFACTS / "ai-policy-v1.positive.json").read_bytes()
_PREHASH_BYTES = (_ARTIFACTS / "ai-policy-v1.prehash.jcs.json").read_bytes()
_SCHEMA_BYTES = (_ARTIFACTS / "ai-policy-v1.schema.json").read_bytes()
_REGISTRY_BYTES = (_ARTIFACTS / "ip-deny-cidrs-v1.json").read_bytes()
_NEGATIVE_MANIFEST = json.loads(
    (_ARTIFACTS / "ai-policy-v1.negative-vectors.json").read_text(encoding="utf-8")
)

_PREFIX_IDS = {
    "NEG-POL-001-missing-hash",
    "NEG-POL-004-boolean-integer",
    "NEG-POL-005a-lexical-one-point-zero",
    "NEG-POL-005b-lexical-one-exponent-zero",
    "NEG-POL-005c-lexical-negative-zero",
    "NEG-POL-005d-over-safe-integer",
    "NEG-POL-018-duplicate-source-key",
}
_ISOLATED_IDS = {
    "NEG-POL-001b-self-referential-preimage",
    "NEG-POL-003-tampered-content",
    "NEG-POL-007-dangling-primary-profile",
    "NEG-POL-008-capability-mismatch",
    "NEG-POL-009-unreferenced-profile",
    "NEG-POL-010-duplicate-target-identity",
    "NEG-POL-012-hostname-mismatch",
    "NEG-POL-013-noncanonical-cidr",
    "NEG-POL-014-denied-cidr-overlap",
    "NEG-POL-015-unsorted-array",
}
_SCHEMA_NOT_RUN_IDS = {
    "NEG-POL-001a-empty-hash",
    "NEG-POL-002-uppercase-hash",
    "NEG-POL-005-unknown-field",
    "NEG-POL-006-forbidden-secret-value-field",
    "NEG-POL-011-external-http",
    "NEG-POL-016-provider-calls-enabled",
    "NEG-POL-016a-duplicate-array-member",
    "NEG-POL-017-registry-hash-mismatch",
}


def _cases() -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], _NEGATIVE_MANIFEST["cases"])


def _case(case_id: str) -> dict[str, Any]:
    return next(case for case in _cases() if case["id"] == case_id)


def _decode_pointer(pointer: str) -> list[str]:
    return [segment.replace("~1", "/").replace("~0", "~") for segment in pointer[1:].split("/")]


def _lookup(document: JsonValue, pointer: str) -> JsonValue:
    current = document
    for segment in _decode_pointer(pointer):
        current = current[int(segment)] if isinstance(current, list) else current[segment]
    return current


def _apply_mutation(document: JsonValue, mutation: dict[str, Any]) -> None:
    segments = _decode_pointer(cast(str, mutation["path"]))
    parent: JsonValue = document
    for segment in segments[:-1]:
        parent = parent[int(segment)] if isinstance(parent, list) else parent[segment]
    key = segments[-1]
    operation = mutation["op"]
    if operation == "remove":
        if isinstance(parent, list):
            parent.pop(int(key))
        else:
            del parent[key]
        return
    value = (
        deepcopy(_lookup(document, cast(str, mutation["value_from"])))
        if "value_from" in mutation
        else deepcopy(cast(JsonValue, mutation["value"]))
    )
    if isinstance(parent, list):
        if operation == "add":
            parent.insert(int(key), value)
        else:
            parent[int(key)] = value
    else:
        parent[key] = value


def _mutated_policy(case: dict[str, Any]) -> dict[str, JsonValue]:
    document = deepcopy(parse_strict_json(_POSITIVE_BYTES).value)
    assert isinstance(document, dict)
    mutations = case.get("mutations") or [case["mutation"]]
    for mutation in mutations:
        _apply_mutation(document, cast(dict[str, Any], mutation))
    return document


def _source_with_token(pointer: str, replacement_json_token: str) -> bytes:
    document = deepcopy(parse_strict_json(_POSITIVE_BYTES).value)
    sentinel = "__FROZEN_NUMBER_TOKEN_SENTINEL__"
    _apply_mutation(document, {"op": "replace", "path": pointer, "value": sentinel})
    serialized = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    serialized = serialized.replace(json.dumps(sentinel), replacement_json_token, 1)
    return serialized.encode("utf-8")


def _source_bytes(case: dict[str, Any]) -> bytes:
    if "source_text" in case:
        return cast(str, case["source_text"]).encode("utf-8")
    if "source_mutation" in case:
        source_mutation = cast(dict[str, Any], case["source_mutation"])
        return _source_with_token(
            cast(str, source_mutation["path"]),
            cast(str, source_mutation["replacement_json_token"]),
        )
    return json.dumps(_mutated_policy(case), ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _refresh_hash(policy: dict[str, JsonValue]) -> None:
    projection = dict(policy)
    projection.pop("policy_hash", None)
    policy["policy_hash"] = hashlib.sha256(canonicalize_jcs(projection)).hexdigest()


def _integer_pointers(value: JsonValue, pointer: str = "") -> list[str]:
    if type(value) is int:
        return [pointer]
    if isinstance(value, dict):
        return [
            child_pointer
            for key, child in value.items()
            for child_pointer in _integer_pointers(
                child,
                f"{pointer}/{key.replace('~', '~0').replace('/', '~1')}",
            )
        ]
    if isinstance(value, list):
        return [
            child_pointer
            for index, child in enumerate(value)
            for child_pointer in _integer_pointers(child, f"{pointer}/{index}")
        ]
    return []


def test_fixed_25_vector_partition_is_explicit_and_exhaustive() -> None:
    manifest_ids = {cast(str, case["id"]) for case in _cases()}

    assert len(_PREFIX_IDS) == 7
    assert len(_ISOLATED_IDS) == 10
    assert len(_SCHEMA_NOT_RUN_IDS) == 8
    assert _PREFIX_IDS.isdisjoint(_ISOLATED_IDS)
    assert _PREFIX_IDS.isdisjoint(_SCHEMA_NOT_RUN_IDS)
    assert _ISOLATED_IDS.isdisjoint(_SCHEMA_NOT_RUN_IDS)
    assert _PREFIX_IDS | _ISOLATED_IDS | _SCHEMA_NOT_RUN_IDS == manifest_ids
    assert len(manifest_ids) == 25


def test_all_99_schema_integer_paths_reject_noncanonical_source_tokens() -> None:
    policy = parse_strict_json(_POSITIVE_BYTES).value
    pointers = _integer_pointers(policy)
    rate_limit_pointers = [pointer for pointer in pointers if pointer.startswith("/rate_limits/")]
    failures: list[str] = []

    assert len(pointers) == 99
    assert len(rate_limit_pointers) == 12
    for pointer in pointers:
        value = _lookup(policy, pointer)
        assert type(value) is int
        result = validate_policy_prefix(
            _source_with_token(pointer, f"{value}.0"),
            validation_target="final_envelope",
            policy_schema_bytes=_SCHEMA_BYTES,
        )
        if not (
            result.status is PrefixStatus.REJECTED
            and result.stage == "source_number"
            and result.rule_id == "POL-VAL-002"
            and result.safe_error_code == "AI_POLICY_INTEGER_TOKEN_INVALID"
        ):
            failures.append(pointer)

    assert failures == []


def test_very_long_integer_is_rule_002_not_a_raw_parse_error() -> None:
    result = validate_policy_prefix(
        _source_with_token("/policy_version", "9" * 5_000),
        validation_target="final_envelope",
        policy_schema_bytes=_SCHEMA_BYTES,
    )

    assert result.status is PrefixStatus.REJECTED
    assert result.stage == "source_number"
    assert result.rule_id == "POL-VAL-002"
    assert result.safe_error_code == "AI_POLICY_INTEGER_TOKEN_INVALID"


@pytest.mark.parametrize("case_id", sorted(_PREFIX_IDS))
def test_seven_prefix_vectors_fail_at_the_exact_first_rule(case_id: str) -> None:
    case = _case(case_id)
    result = validate_policy_prefix(
        _source_bytes(case),
        validation_target=cast(Any, case.get("validation_target", "final_envelope")),
        policy_schema_bytes=_SCHEMA_BYTES,
    )

    assert result.status is PrefixStatus.REJECTED
    assert result.stage == case["expected_stage"]
    assert result.rule_id == case["expected_rule_id"]
    assert result.safe_error_code == case["expected_safe_error_code"]


@pytest.mark.parametrize("case_id", sorted(_SCHEMA_NOT_RUN_IDS))
def test_eight_schema_vectors_are_not_run_without_a_draft_2020_engine(case_id: str) -> None:
    case = _case(case_id)
    result = validate_policy_prefix(
        _source_bytes(case),
        validation_target="final_envelope",
        policy_schema_bytes=_SCHEMA_BYTES,
    )

    assert result.status is PrefixStatus.BLOCKED_SCHEMA_ENGINE
    assert result.stage == "schema"
    assert result.rule_id == "POL-VAL-004"
    assert result.safe_error_code is None
    assert result.completed_rule_ids == ("POL-VAL-001", "POL-VAL-002", "POL-VAL-003")
    assert "NOT_RUN" in result.detail


@pytest.mark.parametrize("case_id", sorted(_ISOLATED_IDS))
def test_ten_post_schema_vectors_are_only_isolated_rule_evidence(case_id: str) -> None:
    case = _case(case_id)
    policy = _mutated_policy(case)
    rule_id = cast(Any, case["expected_rule_id"])
    if rule_id not in {"POL-VAL-006"}:
        _refresh_hash(policy)

    evidence = evaluate_isolated_rule(
        policy,
        rule_id=rule_id,
        validation_target="final_envelope",
        registry_bytes=_REGISTRY_BYTES,
    )

    assert evidence.evidence_scope == "ISOLATED_RULE_EVIDENCE"
    assert evidence.outcome is IsolatedOutcome.REJECTED
    assert evidence.stage == case["expected_stage"]
    assert evidence.rule_id == case["expected_rule_id"]
    assert evidence.safe_error_code == case["expected_safe_error_code"]


@pytest.mark.parametrize(
    ("raw_policy_bytes", "validation_target"),
    [(_POSITIVE_BYTES, "final_envelope"), (_PREHASH_BYTES, "pre_hash_payload")],
)
def test_positive_prefix_still_stops_before_schema(
    raw_policy_bytes: bytes, validation_target: Any
) -> None:
    result = validate_policy_prefix(
        raw_policy_bytes,
        validation_target=validation_target,
        policy_schema_bytes=_SCHEMA_BYTES,
    )

    assert result.status is PrefixStatus.BLOCKED_SCHEMA_ENGINE
    assert result.rule_id == "POL-VAL-004"
    assert "NOT_RUN" in result.detail


@pytest.mark.parametrize(
    "rule_id",
    [
        "POL-VAL-005",
        "POL-VAL-006",
        "POL-VAL-007",
        "POL-VAL-008",
        "POL-VAL-009",
        "POL-VAL-010",
        "POL-VAL-011",
    ],
)
def test_positive_post_schema_checks_only_produce_isolated_no_finding(rule_id: Any) -> None:
    policy = parse_strict_json(_POSITIVE_BYTES).value
    assert isinstance(policy, dict)

    evidence = evaluate_isolated_rule(
        policy,
        rule_id=rule_id,
        validation_target="final_envelope",
        registry_bytes=_REGISTRY_BYTES,
    )

    assert evidence.evidence_scope == "ISOLATED_RULE_EVIDENCE"
    assert evidence.outcome is IsolatedOutcome.NO_FINDING
    assert evidence.safe_error_code is None
    assert "ordered validation remains unavailable" in evidence.detail


def test_rule_012_cannot_be_executed_or_reported_as_acceptance() -> None:
    policy = parse_strict_json(_POSITIVE_BYTES).value
    assert isinstance(policy, dict)

    with pytest.raises(ValueError, match="only POL-VAL-005 through POL-VAL-011"):
        evaluate_isolated_rule(
            policy,
            rule_id=cast(Any, "POL-VAL-012"),
            validation_target="final_envelope",
            registry_bytes=_REGISTRY_BYTES,
        )


def test_rule_011_does_not_treat_the_mapped_ipv6_registry_range_as_native_ipv4_wildcard() -> None:
    policy = parse_strict_json(_POSITIVE_BYTES).value
    assert isinstance(policy, dict)
    profile = policy["profiles"]["llm_extraction_primary"]
    assert isinstance(profile, dict)
    profile["network_scope"] = "external_public"
    profile["allowed_cidrs"] = ["8.8.8.0/24"]

    evidence = evaluate_isolated_rule(
        policy,
        rule_id="POL-VAL-011",
        validation_target="final_envelope",
        registry_bytes=_REGISTRY_BYTES,
    )

    assert evidence.outcome is IsolatedOutcome.NO_FINDING


def test_all_stage_one_functions_complete_with_socket_access_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    def forbidden_socket(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("socket access is forbidden")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden_socket)

    prefix = validate_policy_prefix(
        _POSITIVE_BYTES,
        validation_target="final_envelope",
        policy_schema_bytes=_SCHEMA_BYTES,
    )
    policy = parse_strict_json(_POSITIVE_BYTES).value
    assert isinstance(policy, dict)
    for rule_id in (
        "POL-VAL-005",
        "POL-VAL-006",
        "POL-VAL-007",
        "POL-VAL-008",
        "POL-VAL-009",
        "POL-VAL-010",
        "POL-VAL-011",
    ):
        evaluate_isolated_rule(
            policy,
            rule_id=cast(Any, rule_id),
            validation_target="final_envelope",
            registry_bytes=_REGISTRY_BYTES,
        )

    assert prefix.status is PrefixStatus.BLOCKED_SCHEMA_ENGINE
