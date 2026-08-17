from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import importlib.metadata
import json
import os
import socket
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


EXPECTED_MANIFEST_BYTES = 5_128
EXPECTED_MANIFEST_SHA256 = (
    "f4249f6e9fa08f7503c8b3265807f8febfd3c820b7add10d158034597776f84c"
)
EXPECTED_PREHASH_BYTES = 7_569
EXPECTED_PREHASH_SHA256 = (
    "db946ad109baf5ec84455a2d0a09ce5e29602c0d9f9ce8404901f5c63683443d"
)
EXPECTED_REQUIREMENTS_SHA256 = (
    "0fa55932218f0603089dd4182a7eb1751dc682dac3176dee8b142b1b565ebd8c"
)
EXPECTED_PACKAGE_JSON_SHA256 = (
    "a254297290604f27111e2f31131e34fd2afa0a737875b701ebbeb5ec451ab296"
)
EXPECTED_PACKAGE_LOCK_SHA256 = (
    "fc253094c09531447eb0dc9f0082f8f02a297a2c3024f9133f861c53389ac2fa"
)
EXPECTED_NODE_VALIDATOR_SHA256 = (
    "88995877b5064b828d0c5fd229352b7f2c8d758ac75baab3b2b675a827c5c74e"
)
EXPECTED_NODE_GUARD_SHA256 = (
    "0a556afedc71f3a677e51cf6155d6dc9ca6fc0c1cff69f04742f16512c4c7a46"
)
EXPECTED_CASE_COUNT = 27
EXPECTED_NEGATIVE_COUNT = 25
EXPECTED_SCHEMA_CALLS = 20
EXPECTED_GUARD_PATCH_COUNT = 108
EXPECTED_GUARD_RESULTS = (
    "tcp",
    "dns_localhost",
    "dns_other_hostname",
    "udp",
    "windows_named_pipe",
    "local_socket_path",
)

PYTHON_WHEELS = {
    "attrs-26.1.0-py3-none-any.whl": "c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309",
    "jsonschema-4.26.0-py3-none-any.whl": "d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce",
    "jsonschema_specifications-2025.9.1-py3-none-any.whl": "98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe",
    "referencing-0.37.0-py3-none-any.whl": "381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231",
    "rpds_py-0.30.0-cp310-cp310-win_amd64.whl": "1726859cd0de969f88dc8673bdd954185b9104e05806be64bcd87badbe313169",
    "typing_extensions-4.16.0-py3-none-any.whl": "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
}
PYTHON_DISTRIBUTIONS = {
    "attrs": "26.1.0",
    "jsonschema": "4.26.0",
    "jsonschema-specifications": "2025.9.1",
    "referencing": "0.37.0",
    "rpds-py": "0.30.0",
    "typing-extensions": "4.16.0",
}
NODE_PACKAGES = {
    "ajv": {
        "version": "8.20.0",
        "resolved": "https://registry.npmjs.org/ajv/-/ajv-8.20.0.tgz",
        "integrity": (
            "sha512-Thbli+OlOj+iMPYFBVBfJ3OmCAnaSyNn4M1vz9T6Gka5Jt9ba/"
            "HIR56joy65tY6kx/FCF5VXNB819Y7/GUrBGA=="
        ),
    },
    "fast-deep-equal": {
        "version": "3.1.3",
        "resolved": (
            "https://registry.npmjs.org/fast-deep-equal/-/fast-deep-equal-3.1.3.tgz"
        ),
        "integrity": (
            "sha512-f3qQ9oQy9j2AhBe/H9VC91wLmKBCCU/gDOnKNAYG5hswO7BLKj09Hc5HYNz9cGI+"
            "+xlpDCIgDaitVs03ATR84Q=="
        ),
    },
    "fast-uri": {
        "version": "3.1.5",
        "resolved": "https://registry.npmjs.org/fast-uri/-/fast-uri-3.1.5.tgz",
        "integrity": (
            "sha512-gHwA1O9LDIcKunMKhObS/HimwtehO1nPUECKAu5TpKgaO19fcWEl4bliWe1jWxVF"
            "vIXztJjjQ4L8XQ1EU9f7Jw=="
        ),
    },
    "json-schema-traverse": {
        "version": "1.0.0",
        "resolved": (
            "https://registry.npmjs.org/json-schema-traverse/-/"
            "json-schema-traverse-1.0.0.tgz"
        ),
        "integrity": (
            "sha512-NM8/P9n3XjXhIZn1lLhkFaACTOURQXjWhV4BA/RnOv8xvgqtqpAX9IO4mRQxSx1R"
            "lo4tqzeqb0sOlruaOy3dug=="
        ),
    },
    "require-from-string": {
        "version": "2.0.2",
        "resolved": (
            "https://registry.npmjs.org/require-from-string/-/"
            "require-from-string-2.0.2.tgz"
        ),
        "integrity": (
            "sha512-Xf0nWe6RseziFMu+Ap9biiUbmplq6S9/p+7w7YXP/JBHhrUDDUhwa+vANyubuqfZ"
            "WTveU//DYVGsDG7RKL/vEw=="
        ),
    },
}


class GateError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GateCase:
    case_id: str
    raw_policy_bytes: bytes
    validation_target: str
    accepted: bool
    stage: str
    rule_id: str | None
    safe_error_code: str | None


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checked_bytes(path: Path, *, error_code: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise GateError(error_code) from error


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def reject_json_constant(value: str) -> None:
    del value
    raise ValueError("non-finite JSON number")


def checked_json_bytes(value: bytes, *, error_code: str) -> Any:
    try:
        return json.loads(
            value,
            object_pairs_hook=strict_object,
            parse_constant=reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise GateError(error_code) from error


def verify_artifact_manifest(artifact_root: Path) -> dict[str, bytes]:
    manifest_bytes = checked_bytes(
        artifact_root / "manifest.json",
        error_code="ARTIFACT_MANIFEST_MISSING",
    )
    if (
        len(manifest_bytes) != EXPECTED_MANIFEST_BYTES
        or sha256_bytes(manifest_bytes) != EXPECTED_MANIFEST_SHA256
    ):
        raise GateError("ARTIFACT_MANIFEST_IDENTITY")
    manifest = checked_json_bytes(manifest_bytes, error_code="ARTIFACT_MANIFEST_JSON")
    if not isinstance(manifest, dict) or manifest.get("artifact_set") != (
        "CR-011-R3-contract-offline-draft"
    ):
        raise GateError("ARTIFACT_MANIFEST_CONTRACT")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or len(entries) != 15:
        raise GateError("ARTIFACT_MANIFEST_LEAVES")

    artifacts: dict[str, bytes] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise GateError("ARTIFACT_MANIFEST_ENTRY")
        path_value = entry.get("path")
        if (
            not isinstance(path_value, str)
            or Path(path_value).name != path_value
            or path_value in artifacts
        ):
            raise GateError("ARTIFACT_MANIFEST_PATH")
        raw = checked_bytes(
            artifact_root / path_value, error_code="ARTIFACT_LEAF_MISSING"
        )
        if len(raw) != entry.get("byte_length") or sha256_bytes(raw) != entry.get(
            "sha256"
        ):
            raise GateError("ARTIFACT_LEAF_IDENTITY")
        artifacts[path_value] = raw

    actual_files = {path.name for path in artifact_root.iterdir() if path.is_file()}
    if actual_files != {"manifest.json", *artifacts}:
        raise GateError("ARTIFACT_DIRECTORY_CLOSURE")
    return artifacts


def verify_python_dependencies(project_root: Path, python_site: Path) -> None:
    requirements = checked_bytes(
        project_root / "scripts" / "requirements-cr011-gate-b.txt",
        error_code="PYTHON_REQUIREMENTS_MISSING",
    )
    if sha256_bytes(requirements) != EXPECTED_REQUIREMENTS_SHA256:
        raise GateError("PYTHON_REQUIREMENTS_IDENTITY")

    wheelhouse = (
        project_root / "build" / "cr011-gate-b-dependencies" / "python-wheelhouse"
    )
    if not wheelhouse.is_dir() or not python_site.is_dir():
        raise GateError("PYTHON_ISOLATED_DEPENDENCIES_MISSING")
    wheel_paths = {
        path.name: path for path in wheelhouse.glob("*.whl") if path.is_file()
    }
    if set(wheel_paths) != set(PYTHON_WHEELS):
        raise GateError("PYTHON_WHEEL_CLOSURE")
    for name, expected_hash in PYTHON_WHEELS.items():
        if sha256_bytes(
            checked_bytes(wheel_paths[name], error_code="PYTHON_WHEEL_MISSING")
        ) != (expected_hash):
            raise GateError("PYTHON_WHEEL_IDENTITY")

    installed: dict[str, str] = {}
    for distribution in importlib.metadata.distributions(path=[str(python_site)]):
        name = distribution.metadata.get("Name")
        if not isinstance(name, str) or not name:
            raise GateError("PYTHON_DISTRIBUTION_METADATA")
        installed[name.lower().replace("_", "-")] = distribution.version
    if installed != PYTHON_DISTRIBUTIONS:
        raise GateError("PYTHON_DISTRIBUTION_CLOSURE")


def verify_node_dependencies(
    node_root: Path,
    node_modules: Path,
    package_lock_path: Path,
    node_validator: Path,
    node_guard: Path,
) -> None:
    package_json_path = node_root / "package.json"
    package_json_bytes = checked_bytes(
        package_json_path, error_code="NODE_PACKAGE_JSON_MISSING"
    )
    package_lock_bytes = checked_bytes(
        package_lock_path, error_code="NODE_PACKAGE_LOCK_MISSING"
    )
    if sha256_bytes(package_json_bytes) != EXPECTED_PACKAGE_JSON_SHA256:
        raise GateError("NODE_PACKAGE_JSON_IDENTITY")
    if sha256_bytes(package_lock_bytes) != EXPECTED_PACKAGE_LOCK_SHA256:
        raise GateError("NODE_PACKAGE_LOCK_IDENTITY")
    if sha256_bytes(
        checked_bytes(node_validator, error_code="NODE_VALIDATOR_MISSING")
    ) != (EXPECTED_NODE_VALIDATOR_SHA256):
        raise GateError("NODE_VALIDATOR_IDENTITY")
    if sha256_bytes(checked_bytes(node_guard, error_code="NODE_GUARD_MISSING")) != (
        EXPECTED_NODE_GUARD_SHA256
    ):
        raise GateError("NODE_GUARD_IDENTITY")

    package_json = checked_json_bytes(
        package_json_bytes, error_code="NODE_PACKAGE_JSON_INVALID"
    )
    package_lock = checked_json_bytes(
        package_lock_bytes, error_code="NODE_PACKAGE_LOCK_INVALID"
    )
    if not isinstance(package_json, dict) or package_json.get("devDependencies") != {
        "ajv": "8.20.0"
    }:
        raise GateError("NODE_PACKAGE_CONTRACT")
    if not isinstance(package_lock, dict) or package_lock.get("lockfileVersion") != 3:
        raise GateError("NODE_LOCK_CONTRACT")
    locked = package_lock.get("packages")
    expected_keys = {"", *(f"node_modules/{name}" for name in NODE_PACKAGES)}
    if not isinstance(locked, dict) or set(locked) != expected_keys:
        raise GateError("NODE_LOCK_CLOSURE")
    for name, expected in NODE_PACKAGES.items():
        entry = locked.get(f"node_modules/{name}")
        if not isinstance(entry, dict) or any(
            entry.get(key) != value for key, value in expected.items()
        ):
            raise GateError("NODE_LOCK_IDENTITY")

    if not node_modules.is_dir():
        raise GateError("NODE_MODULES_MISSING")
    actual_modules = {path.name for path in node_modules.iterdir() if path.is_dir()}
    if actual_modules != set(NODE_PACKAGES):
        raise GateError("NODE_MODULES_CLOSURE")
    for name, expected in NODE_PACKAGES.items():
        metadata_bytes = checked_bytes(
            node_modules / name / "package.json",
            error_code="NODE_MODULE_METADATA_MISSING",
        )
        metadata = checked_json_bytes(
            metadata_bytes, error_code="NODE_MODULE_METADATA_INVALID"
        )
        if (
            not isinstance(metadata, dict)
            or metadata.get("version") != expected["version"]
        ):
            raise GateError("NODE_MODULE_VERSION")


def decode_pointer(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise GateError("VECTOR_POINTER")
    return [
        part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")
    ]


def lookup(document: Any, pointer: str) -> Any:
    current = document
    for part in decode_pointer(pointer):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def apply_mutation(document: Any, mutation: Mapping[str, Any]) -> None:
    path = mutation.get("path")
    operation = mutation.get("op")
    if not isinstance(path, str) or operation not in {"add", "remove", "replace"}:
        raise GateError("VECTOR_MUTATION")
    parts = decode_pointer(path)
    parent = document
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    key = parts[-1]
    if operation == "remove":
        parent.pop(int(key)) if isinstance(parent, list) else parent.pop(key)
        return
    value = (
        deepcopy(lookup(document, mutation["value_from"]))
        if "value_from" in mutation
        else deepcopy(mutation.get("value"))
    )
    if isinstance(parent, list):
        parent.insert(int(key), value) if operation == "add" else parent.__setitem__(
            int(key), value
        )
    else:
        parent[key] = value


def compact_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def source_with_token(positive: Any, source_mutation: Mapping[str, Any]) -> bytes:
    pointer = source_mutation.get("path")
    replacement = source_mutation.get("replacement_json_token")
    if not isinstance(pointer, str) or not isinstance(replacement, str):
        raise GateError("VECTOR_SOURCE_MUTATION")
    document = deepcopy(positive)
    sentinel = "__CR011_FROZEN_NUMBER_TOKEN__"
    apply_mutation(document, {"op": "replace", "path": pointer, "value": sentinel})
    source = compact_json(document)
    encoded_sentinel = json.dumps(sentinel).encode("ascii")
    if source.count(encoded_sentinel) != 1:
        raise GateError("VECTOR_SOURCE_SENTINEL")
    return source.replace(encoded_sentinel, replacement.encode("ascii"), 1)


def materialize_cases(
    artifacts: Mapping[str, bytes],
    negative_fixture_path: Path | None,
    canonicalize_jcs: Callable[[Any], bytes],
) -> list[GateCase]:
    positive_bytes = artifacts["ai-policy-v1.positive.json"]
    prehash_bytes = artifacts["ai-policy-v1.prehash.jcs.json"]
    if len(prehash_bytes) != EXPECTED_PREHASH_BYTES or sha256_bytes(prehash_bytes) != (
        EXPECTED_PREHASH_SHA256
    ):
        raise GateError("PREHASH_IDENTITY")
    positive = checked_json_bytes(positive_bytes, error_code="POSITIVE_JSON")
    authoritative_vectors = checked_json_bytes(
        artifacts["ai-policy-v1.negative-vectors.json"],
        error_code="NEGATIVE_VECTOR_JSON",
    )
    vector_bytes = (
        checked_bytes(negative_fixture_path, error_code="NEGATIVE_FIXTURE_MISSING")
        if negative_fixture_path is not None
        else artifacts["ai-policy-v1.negative-vectors.json"]
    )
    if vector_bytes != artifacts["ai-policy-v1.negative-vectors.json"]:
        raise GateError("NEGATIVE_VECTOR_IDENTITY")
    vectors = checked_json_bytes(vector_bytes, error_code="NEGATIVE_FIXTURE_JSON")
    if not isinstance(authoritative_vectors, dict) or not isinstance(vectors, dict):
        raise GateError("NEGATIVE_VECTOR_CONTRACT")
    authoritative_cases = authoritative_vectors.get("cases")
    negative_cases = vectors.get("cases")
    if (
        not isinstance(authoritative_cases, list)
        or len(authoritative_cases) != EXPECTED_NEGATIVE_COUNT
    ):
        raise GateError("AUTHORITATIVE_VECTOR_COUNT")
    if (
        not isinstance(negative_cases, list)
        or len(negative_cases) != EXPECTED_NEGATIVE_COUNT
    ):
        raise GateError("NEGATIVE_VECTOR_COUNT")
    expected_ids = [
        entry.get("id") for entry in authoritative_cases if isinstance(entry, dict)
    ]
    actual_ids = [
        entry.get("id") for entry in negative_cases if isinstance(entry, dict)
    ]
    if len(expected_ids) != EXPECTED_NEGATIVE_COUNT or actual_ids != expected_ids:
        raise GateError("NEGATIVE_VECTOR_IDENTITY")
    if len(set(actual_ids)) != EXPECTED_NEGATIVE_COUNT:
        raise GateError("NEGATIVE_VECTOR_UNIQUENESS")

    cases = [
        GateCase(
            case_id="POL-ENTRY-001-final-positive",
            raw_policy_bytes=positive_bytes,
            validation_target="final_envelope",
            accepted=True,
            stage="complete",
            rule_id=None,
            safe_error_code=None,
        ),
        GateCase(
            case_id="POL-ENTRY-002-prehash-positive",
            raw_policy_bytes=prehash_bytes,
            validation_target="pre_hash_payload",
            accepted=True,
            stage="complete",
            rule_id=None,
            safe_error_code=None,
        ),
    ]
    refresh = vectors.get("harness_semantics", {}).get(
        "hash_refresh_by_expected_stage", {}
    )
    if refresh != {"cross_field": True, "network_registry": True, "default": False}:
        raise GateError("NEGATIVE_VECTOR_HASH_REFRESH")

    for raw_case in negative_cases:
        if not isinstance(raw_case, dict):
            raise GateError("NEGATIVE_VECTOR_ENTRY")
        if "source_text" in raw_case:
            source_text = raw_case["source_text"]
            if not isinstance(source_text, str):
                raise GateError("NEGATIVE_VECTOR_SOURCE")
            raw = source_text.encode("utf-8")
        elif "source_mutation" in raw_case:
            source_mutation = raw_case["source_mutation"]
            if not isinstance(source_mutation, dict):
                raise GateError("NEGATIVE_VECTOR_SOURCE_MUTATION")
            raw = source_with_token(positive, source_mutation)
        else:
            document = deepcopy(positive)
            mutations = raw_case.get("mutations")
            if mutations is None:
                mutation = raw_case.get("mutation")
                mutations = [mutation] if isinstance(mutation, dict) else None
            if not isinstance(mutations, list) or not mutations:
                raise GateError("NEGATIVE_VECTOR_MUTATIONS")
            for mutation in mutations:
                if not isinstance(mutation, dict):
                    raise GateError("NEGATIVE_VECTOR_MUTATION")
                apply_mutation(document, mutation)
            expected_stage = raw_case.get("expected_stage")
            if expected_stage in {"cross_field", "network_registry"}:
                projection = dict(document)
                projection.pop("policy_hash", None)
                document["policy_hash"] = sha256_bytes(canonicalize_jcs(projection))
            raw = compact_json(document)

        expected = (
            raw_case.get("expected_stage"),
            raw_case.get("expected_rule_id"),
            raw_case.get("expected_safe_error_code"),
        )
        if not all(isinstance(value, str) for value in expected):
            raise GateError("NEGATIVE_VECTOR_EXPECTED")
        target = raw_case.get("validation_target", "final_envelope")
        if target not in {"final_envelope", "pre_hash_payload"}:
            raise GateError("NEGATIVE_VECTOR_TARGET")
        cases.append(
            GateCase(
                case_id=raw_case["id"],
                raw_policy_bytes=raw,
                validation_target=target,
                accepted=False,
                stage=expected[0],
                rule_id=expected[1],
                safe_error_code=expected[2],
            )
        )
    if len(cases) != EXPECTED_CASE_COUNT:
        raise GateError("CASE_COUNT")
    return cases


def expected_result(case: GateCase) -> tuple[bool, str, str | None, str | None]:
    return case.accepted, case.stage, case.rule_id, case.safe_error_code


def verify_result(
    case: GateCase,
    observed: tuple[bool, str, str | None, str | None],
    prehash_bytes: bytes | None,
    prehash_sha256: str | None,
) -> None:
    if observed != expected_result(case):
        raise GateError("CASE_RESULT_MISMATCH")
    if case.accepted:
        if (
            prehash_bytes is None
            or len(prehash_bytes) != EXPECTED_PREHASH_BYTES
            or prehash_bytes != _FROZEN_PREHASH
            or prehash_sha256 != EXPECTED_PREHASH_SHA256
        ):
            raise GateError("CASE_PREHASH_MISMATCH")
    elif prehash_bytes is not None or prehash_sha256 is not None:
        raise GateError("REJECTED_CASE_LEAKED_PREHASH")


def run_python_engine(
    cases: list[GateCase],
    schema_bytes: bytes,
    registry_bytes: bytes,
    schema_mode: str,
) -> list[tuple[bool, str, str | None, str | None]]:
    from app.ai.policy_companion import validate_policy_full
    from jsonschema.validators import Draft202012Validator

    root_schema = checked_json_bytes(schema_bytes, error_code="SCHEMA_JSON")
    try:
        Draft202012Validator.check_schema(root_schema)
        validator = Draft202012Validator(root_schema)
    except Exception as error:
        raise GateError("PYTHON_SCHEMA_COMPILE") from error
    schema_calls = 0

    def schema_validator(instance: Any, supplied_schema: Mapping[str, Any]) -> bool:
        nonlocal schema_calls
        schema_calls += 1
        if supplied_schema != root_schema:
            raise GateError("PYTHON_SCHEMA_CALLBACK_ARTIFACT")
        return True if schema_mode == "always-true" else validator.is_valid(instance)

    normalized: list[tuple[bool, str, str | None, str | None]] = []
    for case in cases:
        result = validate_policy_full(
            case.raw_policy_bytes,
            validation_target=case.validation_target,
            policy_schema_bytes=schema_bytes,
            registry_bytes=registry_bytes,
            schema_validator=schema_validator,
        )
        observed = (
            result.accepted,
            result.stage,
            result.rule_id,
            result.safe_error_code,
        )
        verify_result(
            case,
            observed,
            result.pre_hash_bytes,
            result.pre_hash_sha256,
        )
        normalized.append(observed)
    if schema_calls != EXPECTED_SCHEMA_CALLS:
        raise GateError("PYTHON_SCHEMA_CALL_COUNT")
    return normalized


def child_environment() -> dict[str, str]:
    blocked = {
        "ALL_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NODE_EXTRA_CA_CERTS",
        "NODE_OPTIONS",
        "NODE_PATH",
        "NO_PROXY",
        "NPM_CONFIG_CACHE",
        "NPM_CONFIG_PREFIX",
        "NPM_CONFIG_PROXY",
        "NPM_CONFIG_HTTPS_PROXY",
    }
    return {
        key: value for key, value in os.environ.items() if key.upper() not in blocked
    }


def run_child(command: list[str], *, stdin: bytes | None = None) -> bytes:
    try:
        completed = subprocess.run(
            command,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=child_environment(),
        )
    except OSError as error:
        raise GateError("NODE_PROCESS_START") from error
    if completed.returncode != 0 or completed.stderr:
        raise GateError("NODE_PROCESS_FAILED")
    return completed.stdout


def verify_node_guard(node_path: Path, node_guard: Path) -> None:
    output = run_child([str(node_path), str(node_guard), "--probe"])
    probe = checked_json_bytes(output, error_code="NODE_GUARD_PROBE_JSON")
    if (
        not isinstance(probe, dict)
        or set(probe) != {"passed", "attempts", "integrity", "patch_count", "results"}
        or probe.get("passed") is not True
        or type(probe.get("attempts")) is not int
        or probe.get("attempts") != len(EXPECTED_GUARD_RESULTS)
        or probe.get("integrity") is not True
        or type(probe.get("patch_count")) is not int
        or probe.get("patch_count") != EXPECTED_GUARD_PATCH_COUNT
        or not isinstance(probe.get("results"), list)
        or len(probe["results"]) != len(EXPECTED_GUARD_RESULTS)
    ):
        raise GateError("NODE_GUARD_PROBE")
    for expected_id, result in zip(
        EXPECTED_GUARD_RESULTS, probe["results"], strict=True
    ):
        if (
            not isinstance(result, dict)
            or set(result) != {"id", "denied", "code"}
            or result.get("id") != expected_id
            or result.get("denied") is not True
            or result.get("code") != "CR011_ZERO_SOCKET_DENIED"
        ):
            raise GateError("NODE_GUARD_PROBE_RESULT")


def verify_node_version(node_path: Path, node_guard: Path) -> None:
    source = (
        "const guard=globalThis.__CR011_ZERO_SOCKET_GUARD__;"
        "process.stdout.write(JSON.stringify({"
        "node_version:process.versions.node,guard_id:guard?.guard_id,"
        "patch_count:guard?.patch_count,socket_attempts:guard?.attempts,"
        "integrity:guard?.assertIntegrity?.()}));"
    )
    output = run_child(
        [str(node_path), "--require", str(node_guard), "--eval", source],
    )
    result = checked_json_bytes(output, error_code="NODE_VERSION_PROBE_JSON")
    if (
        not isinstance(result, dict)
        or set(result)
        != {"node_version", "guard_id", "patch_count", "socket_attempts", "integrity"}
        or result.get("node_version") != "20.19.0"
        or result.get("guard_id") != "cr011-zero-socket-guard-v1"
        or type(result.get("patch_count")) is not int
        or result.get("patch_count") != EXPECTED_GUARD_PATCH_COUNT
        or type(result.get("socket_attempts")) is not int
        or result.get("socket_attempts") != 0
        or result.get("integrity") is not True
    ):
        raise GateError("NODE_VERSION_IDENTITY")


def run_node_engine(
    node_path: Path,
    node_guard: Path,
    node_validator: Path,
    cases: list[GateCase],
    schema_bytes: bytes,
    registry_bytes: bytes,
) -> list[tuple[bool, str, str | None, str | None]]:
    protocol = {
        "schema_base64": base64.b64encode(schema_bytes).decode("ascii"),
        "registry_base64": base64.b64encode(registry_bytes).decode("ascii"),
        "cases": [
            {
                "id": case.case_id,
                "raw_policy_base64": base64.b64encode(case.raw_policy_bytes).decode(
                    "ascii"
                ),
                "validation_target": case.validation_target,
            }
            for case in cases
        ],
    }
    output = run_child(
        [str(node_path), "--require", str(node_guard), str(node_validator)],
        stdin=compact_json(protocol),
    )
    response = checked_json_bytes(output, error_code="NODE_RESPONSE_JSON")
    if not isinstance(response, dict) or set(response) != {
        "engine_id",
        "schema_calls",
        "results",
        "socket_attempts",
    }:
        raise GateError("NODE_RESPONSE_CONTRACT")
    if response.get("engine_id") != "ajv@8.20.0-draft2020":
        raise GateError("NODE_ENGINE_IDENTITY")
    if (
        type(response.get("schema_calls")) is not int
        or response.get("schema_calls") != EXPECTED_SCHEMA_CALLS
    ):
        raise GateError("NODE_SCHEMA_CALL_COUNT")
    if (
        type(response.get("socket_attempts")) is not int
        or response.get("socket_attempts") != 0
    ):
        raise GateError("NODE_SOCKET_ATTEMPT")
    results = response.get("results")
    if not isinstance(results, list) or len(results) != EXPECTED_CASE_COUNT:
        raise GateError("NODE_RESULT_COUNT")

    normalized: list[tuple[bool, str, str | None, str | None]] = []
    for case, result in zip(cases, results, strict=True):
        if not isinstance(result, dict) or set(result) != {
            "id",
            "accepted",
            "stage",
            "rule_id",
            "safe_error_code",
            "prehash_base64",
            "prehash_sha256",
        }:
            raise GateError("NODE_RESULT_CONTRACT")
        if result.get("id") != case.case_id:
            raise GateError("NODE_RESULT_ORDER")
        if (
            type(result.get("accepted")) is not bool
            or not isinstance(result.get("stage"), str)
            or not (
                result.get("rule_id") is None or isinstance(result.get("rule_id"), str)
            )
            or not (
                result.get("safe_error_code") is None
                or isinstance(result.get("safe_error_code"), str)
            )
            or not (
                result.get("prehash_sha256") is None
                or isinstance(result.get("prehash_sha256"), str)
            )
        ):
            raise GateError("NODE_RESULT_TYPES")
        observed = (
            result.get("accepted"),
            result.get("stage"),
            result.get("rule_id"),
            result.get("safe_error_code"),
        )
        prehash_text = result.get("prehash_base64")
        try:
            prehash = (
                base64.b64decode(prehash_text, validate=True)
                if prehash_text is not None
                else None
            )
        except (TypeError, ValueError) as error:
            raise GateError("NODE_PREHASH_ENCODING") from error
        verify_result(case, observed, prehash, result.get("prehash_sha256"))
        normalized.append(observed)
    return normalized


def install_python_socket_guard() -> list[str]:
    attempts: list[str] = []

    def audit(event: str, args: tuple[object, ...]) -> None:
        del args
        if event.startswith("socket."):
            attempts.append(event)
            raise GateError("PYTHON_SOCKET_DENIED")

    sys.addaudithook(audit)
    try:
        socket.socket()
    except GateError as error:
        if error.code != "PYTHON_SOCKET_DENIED" or attempts != ["socket.__new__"]:
            raise GateError("PYTHON_SOCKET_PROBE") from error
    else:
        raise GateError("PYTHON_SOCKET_PROBE")
    attempts.clear()
    return attempts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--node-path", type=Path, required=True)
    parser.add_argument("--python-site", type=Path)
    parser.add_argument("--node-modules", type=Path)
    parser.add_argument("--package-lock", type=Path)
    parser.add_argument("--node-validator", type=Path)
    parser.add_argument("--node-guard", type=Path)
    parser.add_argument("--negative-vector-fixture", type=Path)
    parser.add_argument(
        "--schema-mode", choices=("draft202012", "always-true"), default="draft202012"
    )
    return parser.parse_args()


def main() -> None:
    global _FROZEN_PREHASH
    args = parse_args()
    project_root = args.project_root.resolve()
    backend_root = project_root / "backend"
    node_root = project_root / "scripts" / "cr011-gate-b-node"
    python_site = (
        args.python_site
        or (project_root / "build" / "cr011-gate-b-dependencies" / "python-site")
    ).resolve()
    node_modules = (args.node_modules or node_root / "node_modules").resolve()
    package_lock = (args.package_lock or node_root / "package-lock.json").resolve()
    node_validator = (
        args.node_validator or node_root / "validate-policy.cjs"
    ).resolve()
    node_guard = (args.node_guard or node_root / "zero-socket-guard.cjs").resolve()
    node_path = args.node_path.resolve()
    if not backend_root.is_dir() or not node_path.is_file():
        raise GateError("RUNTIME_PATH")
    if (
        python_site
        != (
            project_root / "build" / "cr011-gate-b-dependencies" / "python-site"
        ).resolve()
    ):
        raise GateError("PYTHON_DEPENDENCY_BINDING")
    if (
        node_validator.parent != node_root
        or node_guard.parent != node_root
        or node_modules != (node_root / "node_modules").resolve()
        or package_lock != (node_root / "package-lock.json").resolve()
    ):
        raise GateError("NODE_DEPENDENCY_BINDING")

    attempts = install_python_socket_guard()
    artifact_root = project_root / "docs" / "change-requests" / "artifacts" / "CR-011"
    artifacts = verify_artifact_manifest(artifact_root)
    verify_python_dependencies(project_root, python_site)
    verify_node_dependencies(
        node_root, node_modules, package_lock, node_validator, node_guard
    )

    sys.path.insert(0, str(python_site))
    sys.path.insert(1, str(backend_root))
    jsonschema = importlib.import_module("jsonschema")
    module_path = Path(jsonschema.__file__).resolve()
    if not module_path.is_relative_to(python_site):
        raise GateError("PYTHON_ENGINE_NOT_ISOLATED")
    if importlib.metadata.version("jsonschema") != "4.26.0":
        raise GateError("PYTHON_ENGINE_IDENTITY")

    from app.ai.policy import canonicalize_jcs

    _FROZEN_PREHASH = artifacts["ai-policy-v1.prehash.jcs.json"]
    cases = materialize_cases(
        artifacts,
        args.negative_vector_fixture.resolve()
        if args.negative_vector_fixture
        else None,
        canonicalize_jcs,
    )
    python_results = run_python_engine(
        cases,
        artifacts["ai-policy-v1.schema.json"],
        artifacts["ip-deny-cidrs-v1.json"],
        args.schema_mode,
    )
    verify_node_version(node_path, node_guard)
    verify_node_guard(node_path, node_guard)
    node_results = run_node_engine(
        node_path,
        node_guard,
        node_validator,
        cases,
        artifacts["ai-policy-v1.schema.json"],
        artifacts["ip-deny-cidrs-v1.json"],
    )
    if python_results != node_results:
        raise GateError("ENGINE_RESULT_DIVERGENCE")
    if attempts:
        raise GateError("PYTHON_SOCKET_ATTEMPT")

    for marker in (
        "CR011_GATE_B_HARNESS=PASS",
        "CR011_GATE_B_CASES=27/27",
        "CR011_GATE_B_NEGATIVE_VECTORS=25/25",
        "CR011_GATE_B_PYTHON_SCHEMA_CALLS=20",
        "CR011_GATE_B_NODE_SCHEMA_CALLS=20",
        "CR011_GATE_B_PYTHON_ENGINE=jsonschema@4.26.0-draft202012",
        "CR011_GATE_B_NODE_ENGINE=ajv@8.20.0-draft2020",
        "CR011_ZERO_SOCKET_GUARD=PASS",
        "CR011_ZERO_SOCKET_ATTEMPTS=0",
    ):
        print(marker)


_FROZEN_PREHASH = b""

if __name__ == "__main__":
    try:
        main()
    except GateError as error:
        print(f"CR011_GATE_B_ERROR={error.code}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("CR011_GATE_B_ERROR=UNEXPECTED", file=sys.stderr)
        raise SystemExit(1) from None
