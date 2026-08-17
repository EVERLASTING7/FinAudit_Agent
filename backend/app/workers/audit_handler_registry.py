"""包内审核执行 Handler Registry 的唯一运行时装载入口。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from app.ai.strict_json import JsonValue, parse_strict_json
from app.workers.handler_registry import (
    HandlerMetadata,
    HandlerRegistryError,
    RawSchemaArtifact,
    load_handler_registry_bundle,
)

AUDIT_HANDLER_REGISTRY_SCHEMA_VERSION = "handler-registry-schema-v1"
AUDIT_HANDLER_REGISTRY_SCHEMA_HASH = (
    "9bef52684a93dd509abd30752af872b54df9a3329cb52137236eb6c51b9a349a"
)
AUDIT_HANDLER_REGISTRY_VERSION = "audit-handler-registry-v1"
AUDIT_HANDLER_REGISTRY_HASH = "82f5e0e67e0da28056e427f6c262d235e856734e6fa7f1568f438b432d4bdf0d"
AUDIT_INPUT_SCHEMA_VERSION = 1

_PACKAGE = "app.workers.artifacts.audit_v1"
_SCHEMA_PACKAGE = "app.workers.artifacts.file_v1"
_REGISTRY_RESOURCE = "registry.json"
_REGISTRY_SCHEMA_RESOURCE = "registry.schema.json"
_INPUT_RESOURCE = "input.audit_execute.v1.schema.json"
_SUMMARY_RESOURCE = "summary.audit_execute.v1.schema.json"
_INPUT_SCHEMA_ID = "audit_execute.input.v1"
_SUMMARY_SCHEMA_ID = "audit_execute.summary.v1"


@dataclass(frozen=True, slots=True)
class AuditHandlerRuntime:
    registry_version: str
    registry_hash: str
    handler: HandlerMetadata
    input_validator: Draft202012Validator
    summary_validator: Draft202012Validator

    def validate_input(self, value: dict[str, object]) -> None:
        if next(self.input_validator.iter_errors(value), None) is not None:
            raise HandlerRegistryError

    def validate_summary(self, value: dict[str, object]) -> None:
        if next(self.summary_validator.iter_errors(value), None) is not None:
            raise HandlerRegistryError


def _read(package: str, resource_name: str) -> bytes:
    try:
        raw = resources.files(package).joinpath(resource_name).read_bytes()
    except Exception:
        raise HandlerRegistryError from None
    if not raw:
        raise HandlerRegistryError
    return raw


def _schema(raw: bytes) -> dict[str, JsonValue]:
    try:
        value = parse_strict_json(raw).value
        if type(value) is not dict:
            raise ValueError
        Draft202012Validator.check_schema(value)
        return value
    except Exception:
        raise HandlerRegistryError from None


@lru_cache(maxsize=1)
def load_audit_handler() -> AuditHandlerRuntime:
    registry_raw = _read(_PACKAGE, _REGISTRY_RESOURCE)
    registry_schema_raw = _read(_SCHEMA_PACKAGE, _REGISTRY_SCHEMA_RESOURCE)
    input_raw = _read(_PACKAGE, _INPUT_RESOURCE)
    summary_raw = _read(_PACKAGE, _SUMMARY_RESOURCE)
    validated = load_handler_registry_bundle(
        registry_raw,
        registry_schema_raw,
        (RawSchemaArtifact(_INPUT_SCHEMA_ID, input_raw),),
        (RawSchemaArtifact(_SUMMARY_SCHEMA_ID, summary_raw),),
        expected_registry_schema_version=AUDIT_HANDLER_REGISTRY_SCHEMA_VERSION,
        expected_registry_schema_sha256=AUDIT_HANDLER_REGISTRY_SCHEMA_HASH,
        expected_registry_version=AUDIT_HANDLER_REGISTRY_VERSION,
        expected_registry_sha256=AUDIT_HANDLER_REGISTRY_HASH,
        expected_job_type="audit_execute",
        expected_input_schema_version=AUDIT_INPUT_SCHEMA_VERSION,
    )
    return AuditHandlerRuntime(
        registry_version=validated.registry_version,
        registry_hash=validated.registry_sha256,
        handler=validated.handler,
        input_validator=Draft202012Validator(_schema(input_raw)),
        summary_validator=Draft202012Validator(_schema(summary_raw)),
    )


def audit_registry_artifact_hashes() -> dict[str, str]:
    return {
        name: hashlib.sha256(_read(_PACKAGE, name)).hexdigest()
        for name in (_REGISTRY_RESOURCE, _INPUT_RESOURCE, _SUMMARY_RESOURCE)
    }


__all__ = [
    "AUDIT_HANDLER_REGISTRY_HASH",
    "AUDIT_HANDLER_REGISTRY_SCHEMA_HASH",
    "AUDIT_HANDLER_REGISTRY_SCHEMA_VERSION",
    "AUDIT_HANDLER_REGISTRY_VERSION",
    "AUDIT_INPUT_SCHEMA_VERSION",
    "AuditHandlerRuntime",
    "audit_registry_artifact_hashes",
    "load_audit_handler",
]
