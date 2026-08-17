from __future__ import annotations

import hashlib
import json
import socket
from collections.abc import Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

from app.ai.policy import canonicalize_jcs
from app.workers.handler_registry import (
    HandlerRegistryError,
    RawSchemaArtifact,
    ValidatedHandlerRegistry,
    load_handler_registry_bundle,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "handler_registry"
REGISTRY_SCHEMA_VERSION = "synthetic-registry-schema-v1"
REGISTRY_SCHEMA_SHA256 = "a2fb4e908c63393325ea527873ba0aa535bb3ded746b4dafda9d78caf31cc4f9"
REGISTRY_VERSION = "synthetic-registry-v1"
REGISTRY_SHA256 = "d0a18118cd3af4e873f9a0950e7de1c22b9b680867f8befba6e6fa629833003c"


def _raw(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _input_bundle() -> tuple[RawSchemaArtifact, ...]:
    return (
        RawSchemaArtifact(
            "synthetic.input.alpha.v1",
            _raw("input.synthetic_alpha.v1.schema.json"),
        ),
        RawSchemaArtifact(
            "synthetic.input.beta.v2",
            _raw("input.synthetic_beta.v2.schema.json"),
        ),
    )


def _summary_bundle() -> tuple[RawSchemaArtifact, ...]:
    return (
        RawSchemaArtifact(
            "synthetic.summary.common.v1",
            _raw("summary.synthetic_common.v1.schema.json"),
        ),
        RawSchemaArtifact(
            "synthetic.summary.final.v1",
            _raw("summary.synthetic_final.v1.schema.json"),
        ),
    )


def _registry() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_raw("registry.json")))


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _jcs_sha256(value: object) -> str:
    return hashlib.sha256(canonicalize_jcs(value)).hexdigest()


def _load(
    *,
    registry_raw: bytes | None = None,
    registry_schema_raw: bytes | None = None,
    input_bundle: Sequence[RawSchemaArtifact] | None = None,
    summary_bundle: Sequence[RawSchemaArtifact] | None = None,
    registry_sha256: str = REGISTRY_SHA256,
    registry_schema_sha256: str = REGISTRY_SCHEMA_SHA256,
    registry_version: str = REGISTRY_VERSION,
    registry_schema_version: str = REGISTRY_SCHEMA_VERSION,
    job_type: str = "synthetic_alpha",
    input_schema_version: int = 1,
) -> ValidatedHandlerRegistry:
    return load_handler_registry_bundle(
        _raw("registry.json") if registry_raw is None else registry_raw,
        _raw("registry.schema.json") if registry_schema_raw is None else registry_schema_raw,
        _input_bundle() if input_bundle is None else input_bundle,
        _summary_bundle() if summary_bundle is None else summary_bundle,
        expected_registry_schema_version=registry_schema_version,
        expected_registry_schema_sha256=registry_schema_sha256,
        expected_registry_version=registry_version,
        expected_registry_sha256=registry_sha256,
        expected_job_type=job_type,
        expected_input_schema_version=input_schema_version,
    )


def _load_mutated(registry: dict[str, Any]) -> ValidatedHandlerRegistry:
    return _load(registry_raw=_json_bytes(registry), registry_sha256=_jcs_sha256(registry))


def _load_with_replaced_schema(schema_kind: str, schema_raw: bytes) -> ValidatedHandlerRegistry:
    if schema_kind == "registry":
        return _load(
            registry_schema_raw=schema_raw,
            registry_schema_sha256=hashlib.sha256(schema_raw).hexdigest(),
        )
    if schema_kind == "input":
        bundle = list(_input_bundle())
        bundle[0] = RawSchemaArtifact(bundle[0].schema_id, schema_raw)
        registry = _registry()
        registry["handlers"][0]["input_schema_sha256"] = hashlib.sha256(schema_raw).hexdigest()
        return _load(
            registry_raw=_json_bytes(registry),
            registry_sha256=_jcs_sha256(registry),
            input_bundle=bundle,
        )
    if schema_kind == "summary":
        bundle = list(_summary_bundle())
        bundle[0] = RawSchemaArtifact(bundle[0].schema_id, schema_raw)
        schema_sha256 = hashlib.sha256(schema_raw).hexdigest()
        registry = _registry()
        registry["handlers"][0]["steps"][0]["summary_schema_sha256"] = schema_sha256
        registry["handlers"][1]["steps"][0]["summary_schema_sha256"] = schema_sha256
        return _load(
            registry_raw=_json_bytes(registry),
            registry_sha256=_jcs_sha256(registry),
            summary_bundle=bundle,
        )
    raise AssertionError("unknown synthetic schema kind")


def test_loads_exact_meta_bundle_and_returns_only_frozen_metadata() -> None:
    loaded = _load()

    assert loaded.registry_schema_version == REGISTRY_SCHEMA_VERSION
    assert loaded.registry_schema_sha256 == REGISTRY_SCHEMA_SHA256
    assert loaded.registry_version == REGISTRY_VERSION
    assert loaded.registry_sha256 == REGISTRY_SHA256
    assert loaded.handler.job_type == "synthetic_alpha"
    assert loaded.handler.input_schema_version == 1
    assert loaded.handler.logical_queue == "maintenance"
    assert [scope.scope_code for scope in loaded.handler.retry_scopes] == [
        "synthetic_all",
        "synthetic_tail",
    ]
    assert [step.step_code for step in loaded.handler.steps] == [
        "synthetic_prepare",
        "synthetic_finish",
    ]
    assert [item.schema_id for item in loaded.input_schemas] == [
        "synthetic.input.alpha.v1",
        "synthetic.input.beta.v2",
    ]
    assert [item.schema_id for item in loaded.summary_schemas] == [
        "synthetic.summary.common.v1",
        "synthetic.summary.final.v1",
    ]
    with pytest.raises(FrozenInstanceError):
        loaded.registry_version = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("registry_schema_version", "Synthetic"),
        ("registry_schema_sha256", "0" * 64),
        ("registry_version", "synthetic-registry-v2"),
        ("registry_sha256", "0" * 64),
        ("job_type", "synthetic_missing"),
        ("input_schema_version", True),
        ("input_schema_version", 2_147_483_648),
    ],
)
def test_rejects_every_expected_identity_mismatch(override: str, value: object) -> None:
    with pytest.raises(HandlerRegistryError, match="^HANDLER_REGISTRY_INVALID$"):
        _load(**{override: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "registry_raw",
    [
        b"\xef\xbb\xbf{}",
        b'{"registry_version":"\xff"}',
        b'{"registry_version":"a","registry_version":"b","handlers":[]}',
    ],
)
def test_registry_raw_parser_rejects_bom_invalid_utf8_and_duplicate_keys(
    registry_raw: bytes,
) -> None:
    with pytest.raises(HandlerRegistryError):
        _load(registry_raw=registry_raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_schema_version", True),
        ("input_schema_version", 1.0),
        ("input_schema_version", "1"),
        ("input_schema_version", 0),
        ("max_attempts", False),
        ("max_attempts", 1.0),
        ("max_attempts", 2_147_483_648),
        ("logical_queue", "synthetic"),
        ("job_type", "Synthetic_alpha"),
        ("handler_code_version", "synthetic handler"),
    ],
)
def test_rejects_non_strict_integer_range_enum_and_ascii_pattern(field: str, value: object) -> None:
    registry = _registry()
    registry["handlers"][0][field] = value
    with pytest.raises(HandlerRegistryError):
        _load_mutated(registry)


def test_rejects_unknown_missing_and_empty_layers() -> None:
    mutations = []
    registry = _registry()
    registry["unexpected"] = True
    mutations.append(registry)
    registry = _registry()
    del registry["handlers"][0]["steps"]
    mutations.append(registry)
    registry = _registry()
    registry["handlers"][0]["steps"][0]["unexpected"] = True
    mutations.append(registry)
    registry = _registry()
    registry["handlers"] = []
    mutations.append(registry)
    registry = _registry()
    registry["handlers"][0]["steps"] = []
    mutations.append(registry)

    for mutation in mutations:
        with pytest.raises(HandlerRegistryError):
            _load_mutated(mutation)


def test_rejects_handler_sorting_composite_duplicates_and_schema_id_hash_conflicts() -> None:
    mutations = []
    registry = _registry()
    registry["handlers"].reverse()
    mutations.append(registry)
    registry = _registry()
    registry["handlers"].insert(1, registry["handlers"][0].copy())
    mutations.append(registry)
    registry = _registry()
    registry["handlers"][1]["input_schema_id"] = registry["handlers"][0]["input_schema_id"]
    mutations.append(registry)

    for mutation in mutations:
        with pytest.raises(HandlerRegistryError):
            _load_mutated(mutation)


def test_rejects_step_and_scope_duplicates_sorting_and_missing_start_step() -> None:
    mutations = []
    registry = _registry()
    registry["handlers"][0]["steps"][1]["step_code"] = "synthetic_prepare"
    mutations.append(registry)
    registry = _registry()
    registry["handlers"][0]["retry_scopes"].reverse()
    mutations.append(registry)
    registry = _registry()
    registry["handlers"][0]["retry_scopes"][1]["scope_code"] = "synthetic_all"
    mutations.append(registry)
    registry = _registry()
    registry["handlers"][0]["retry_scopes"][0]["start_step_code"] = "synthetic_missing"
    mutations.append(registry)
    registry = _registry()
    registry["handlers"][1]["steps"][0]["summary_schema_sha256"] = "0" * 64
    mutations.append(registry)

    for mutation in mutations:
        with pytest.raises(HandlerRegistryError):
            _load_mutated(mutation)


def test_schema_bundles_are_explicit_duplicate_free_and_exactly_referenced() -> None:
    input_bundle = _input_bundle()
    summary_bundle = _summary_bundle()
    cases: tuple[tuple[object, object], ...] = (
        (input_bundle[:-1], summary_bundle),
        (input_bundle + (input_bundle[0],), summary_bundle),
        (
            input_bundle + (RawSchemaArtifact("synthetic.input.extra.v1", input_bundle[0].raw),),
            summary_bundle,
        ),
        ({item.schema_id: item.raw for item in input_bundle}, summary_bundle),
        (input_bundle, summary_bundle[:-1]),
        (input_bundle, summary_bundle + (summary_bundle[0],)),
    )
    for candidate_input, candidate_summary in cases:
        with pytest.raises(HandlerRegistryError):
            _load(
                input_bundle=cast(Sequence[RawSchemaArtifact], candidate_input),
                summary_bundle=cast(Sequence[RawSchemaArtifact], candidate_summary),
            )


def test_rejects_schema_raw_hash_drift_and_strict_parse_failures() -> None:
    input_bundle = list(_input_bundle())
    input_bundle[0] = RawSchemaArtifact(input_bundle[0].schema_id, input_bundle[0].raw + b"\n")
    with pytest.raises(HandlerRegistryError):
        _load(input_bundle=input_bundle)

    input_bundle = list(_input_bundle())
    input_bundle[0] = RawSchemaArtifact(
        input_bundle[0].schema_id,
        b'{"$schema":"https://json-schema.org/draft/2020-12/schema",'
        b'"type":"object","type":"array"}',
    )
    with pytest.raises(HandlerRegistryError):
        _load(input_bundle=input_bundle)

    summary_bundle = list(_summary_bundle())
    summary_bundle[0] = RawSchemaArtifact(summary_bundle[0].schema_id, b"\xef\xbb\xbf{}")
    with pytest.raises(HandlerRegistryError):
        _load(summary_bundle=summary_bundle)


def test_rejects_non_draft_or_invalid_schema_and_open_registry_schema() -> None:
    input_bundle = list(_input_bundle())
    schema = json.loads(input_bundle[0].raw)
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    input_bundle[0] = RawSchemaArtifact(input_bundle[0].schema_id, _json_bytes(schema))
    with pytest.raises(HandlerRegistryError):
        _load(input_bundle=input_bundle)

    input_bundle = list(_input_bundle())
    schema = json.loads(input_bundle[0].raw)
    schema["type"] = "not-a-json-schema-type"
    input_bundle[0] = RawSchemaArtifact(input_bundle[0].schema_id, _json_bytes(schema))
    with pytest.raises(HandlerRegistryError):
        _load(input_bundle=input_bundle)

    registry_schema = json.loads(_raw("registry.schema.json"))
    registry_schema["additionalProperties"] = True
    raw = _json_bytes(registry_schema)
    with pytest.raises(HandlerRegistryError):
        _load(
            registry_schema_raw=raw,
            registry_schema_sha256=hashlib.sha256(raw).hexdigest(),
        )


@pytest.mark.parametrize("schema_type", [["object"], ["object", "null"]])
def test_registry_schema_object_union_cannot_bypass_closed_object_layers(
    schema_type: list[str],
) -> None:
    registry_schema = json.loads(_raw("registry.schema.json"))
    handler_schema = registry_schema["properties"]["handlers"]["items"]
    handler_schema["type"] = schema_type
    del handler_schema["additionalProperties"]
    if schema_type == ["object"]:
        del handler_schema["properties"]
    raw = _json_bytes(registry_schema)

    with pytest.raises(HandlerRegistryError, match="^HANDLER_REGISTRY_INVALID$"):
        _load(
            registry_schema_raw=raw,
            registry_schema_sha256=hashlib.sha256(raw).hexdigest(),
        )


def test_registry_schema_is_applied() -> None:
    registry_schema = json.loads(_raw("registry.schema.json"))
    registry_schema["properties"]["registry_version"]["const"] = "synthetic-other-v1"
    raw = _json_bytes(registry_schema)
    with pytest.raises(HandlerRegistryError):
        _load(
            registry_schema_raw=raw,
            registry_schema_sha256=hashlib.sha256(raw).hexdigest(),
        )


@pytest.mark.parametrize("schema_kind", ["registry", "input", "summary"])
@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
def test_all_schema_types_reject_remote_references_without_retrieval(
    monkeypatch: pytest.MonkeyPatch,
    schema_kind: str,
    keyword: str,
) -> None:
    attempts = 0

    def forbid_socket(*_args: object, **_kwargs: object) -> socket.socket:
        nonlocal attempts
        attempts += 1
        raise AssertionError("schema retrieval is forbidden")

    monkeypatch.setattr(socket, "create_connection", forbid_socket)
    if schema_kind == "registry":
        schema = json.loads(_raw("registry.schema.json"))
        schema["properties"]["handlers"][keyword] = "https://invalid.example/schema"
    elif schema_kind == "input":
        schema = json.loads(_input_bundle()[0].raw)
        schema[keyword] = "https://invalid.example/schema"
    else:
        schema = json.loads(_summary_bundle()[0].raw)
        schema[keyword] = "https://invalid.example/schema"

    with pytest.raises(HandlerRegistryError, match="^HANDLER_REGISTRY_INVALID$"):
        _load_with_replaced_schema(schema_kind, _json_bytes(schema))
    assert attempts == 0


@pytest.mark.parametrize("schema_kind", ["registry", "input", "summary"])
@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
def test_all_schema_types_reject_dangling_local_references(schema_kind: str, keyword: str) -> None:
    if schema_kind == "registry":
        schema = json.loads(_raw("registry.schema.json"))
    elif schema_kind == "input":
        schema = json.loads(_input_bundle()[0].raw)
    else:
        schema = json.loads(_summary_bundle()[0].raw)
    schema[keyword] = "#/$defs/synthetic_missing"

    with pytest.raises(HandlerRegistryError, match="^HANDLER_REGISTRY_INVALID$"):
        _load_with_replaced_schema(schema_kind, _json_bytes(schema))


def test_local_pointer_anchor_and_dynamic_anchor_are_resolved_without_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def forbid_socket(*_args: object, **_kwargs: object) -> socket.socket:
        nonlocal attempts
        attempts += 1
        raise AssertionError("schema retrieval is forbidden")

    monkeypatch.setattr(socket, "create_connection", forbid_socket)
    schema = json.loads(_input_bundle()[0].raw)
    schema["$defs"] = {
        "synthetic/a~b": {"$anchor": "syntheticAnchor", "type": "string"},
        "syntheticDynamic": {"$dynamicAnchor": "syntheticDynamic", "type": "string"},
        "syntheticNested": {
            "$id": "synthetic-nested",
            "$defs": {
                "target": {"$anchor": "nestedAnchor", "type": "string"},
            },
            "allOf": [{"$ref": "#nestedAnchor"}],
        },
    }
    schema["properties"]["synthetic_value"] = {
        "allOf": [
            {"$ref": "#/$defs/synthetic~1a~0b"},
            {"$ref": "#syntheticAnchor"},
            {"$dynamicRef": "#syntheticDynamic"},
            {"$ref": "#/$defs/syntheticNested"},
        ]
    }
    schema["properties"]["ordinary_json"] = {
        "const": {"$ref": "this-is-data-not-a-schema-reference"}
    }

    loaded = _load_with_replaced_schema("input", _json_bytes(schema))

    assert loaded.handler.input_schema_id == "synthetic.input.alpha.v1"
    assert attempts == 0


def test_invalid_local_json_pointer_escape_is_rejected_with_aligned_hashes() -> None:
    schema = json.loads(_input_bundle()[0].raw)
    schema["$defs"] = {"synthetic/a": {"type": "string"}}
    schema["properties"]["synthetic_value"] = {"$ref": "#/$defs/synthetic~2a"}

    with pytest.raises(HandlerRegistryError, match="^HANDLER_REGISTRY_INVALID$"):
        _load_with_replaced_schema("input", _json_bytes(schema))


def test_errors_are_fixed_redacted_and_have_no_nested_untrusted_exception() -> None:
    marker = "DO_NOT_ECHO_PAYLOAD_OR_SCHEMA_ERROR"
    with pytest.raises(HandlerRegistryError) as captured:
        _load(registry_raw=("{not-json-" + marker).encode())

    error = captured.value
    assert str(error) == "HANDLER_REGISTRY_INVALID"
    assert repr(error) == "HandlerRegistryError('HANDLER_REGISTRY_INVALID')"
    assert marker not in str(error)
    assert marker not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert repr(RawSchemaArtifact(marker, b"secret")) == (
        f"RawSchemaArtifact(schema_id='{marker}')"
    )
