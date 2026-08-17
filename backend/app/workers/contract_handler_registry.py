"""包内合同提取 Handler Registry 的唯一运行时装载入口。"""

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

CONTRACT_HANDLER_REGISTRY_SCHEMA_VERSION = "handler-registry-schema-v1"
CONTRACT_HANDLER_REGISTRY_SCHEMA_HASH = (
    "9bef52684a93dd509abd30752af872b54df9a3329cb52137236eb6c51b9a349a"
)
CONTRACT_HANDLER_REGISTRY_VERSION = "contract-handler-registry-v1"
CONTRACT_HANDLER_REGISTRY_HASH = "20278b63f4e222c78a65638de8940d39725aaf9bd741bfdcd133c4e6ffdbcc8e"
CONTRACT_INPUT_SCHEMA_VERSION = 1

_PACKAGE = "app.workers.artifacts.contract_v1"
_SHARED_PACKAGE = "app.workers.artifacts.invoice_v1"
_REGISTRY_RESOURCE = "registry.json"
_REGISTRY_SCHEMA_RESOURCE = "registry.schema.json"
_INPUT_SCHEMA_RESOURCE = "input.contract_extract.v1.schema.json"
_INPUT_SCHEMA_ID = "contract_extract.input.v1"
_SUMMARY_SCHEMA_RESOURCE = "summary.contract_extract.v1.schema.json"
_SUMMARY_SCHEMA_ID = "contract_extract.summary.v1"


@dataclass(frozen=True, slots=True)
class ContractHandlerRuntime:
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
def _load_contract_handler() -> ContractHandlerRuntime:
    registry_raw = _read(_PACKAGE, _REGISTRY_RESOURCE)
    registry_schema_raw = _read(_SHARED_PACKAGE, _REGISTRY_SCHEMA_RESOURCE)
    input_raw = _read(_PACKAGE, _INPUT_SCHEMA_RESOURCE)
    summary_raw = _read(_PACKAGE, _SUMMARY_SCHEMA_RESOURCE)
    validated = load_handler_registry_bundle(
        registry_raw,
        registry_schema_raw,
        (RawSchemaArtifact(_INPUT_SCHEMA_ID, input_raw),),
        (RawSchemaArtifact(_SUMMARY_SCHEMA_ID, summary_raw),),
        expected_registry_schema_version=CONTRACT_HANDLER_REGISTRY_SCHEMA_VERSION,
        expected_registry_schema_sha256=CONTRACT_HANDLER_REGISTRY_SCHEMA_HASH,
        expected_registry_version=CONTRACT_HANDLER_REGISTRY_VERSION,
        expected_registry_sha256=CONTRACT_HANDLER_REGISTRY_HASH,
        expected_job_type="contract_extract",
        expected_input_schema_version=CONTRACT_INPUT_SCHEMA_VERSION,
    )
    return ContractHandlerRuntime(
        registry_version=validated.registry_version,
        registry_hash=validated.registry_sha256,
        handler=validated.handler,
        input_validator=Draft202012Validator(_schema(input_raw)),
        summary_validator=Draft202012Validator(_schema(summary_raw)),
    )


def load_contract_handler(registry_version: str | None = None) -> ContractHandlerRuntime:
    if registry_version not in {None, CONTRACT_HANDLER_REGISTRY_VERSION}:
        raise HandlerRegistryError
    return _load_contract_handler()


def contract_registry_artifact_hashes() -> dict[str, str]:
    return {
        _REGISTRY_RESOURCE: hashlib.sha256(_read(_PACKAGE, _REGISTRY_RESOURCE)).hexdigest(),
        _REGISTRY_SCHEMA_RESOURCE: hashlib.sha256(
            _read(_SHARED_PACKAGE, _REGISTRY_SCHEMA_RESOURCE)
        ).hexdigest(),
        _INPUT_SCHEMA_RESOURCE: hashlib.sha256(_read(_PACKAGE, _INPUT_SCHEMA_RESOURCE)).hexdigest(),
        _SUMMARY_SCHEMA_RESOURCE: hashlib.sha256(
            _read(_PACKAGE, _SUMMARY_SCHEMA_RESOURCE)
        ).hexdigest(),
    }


__all__ = [
    "CONTRACT_HANDLER_REGISTRY_HASH",
    "CONTRACT_HANDLER_REGISTRY_SCHEMA_HASH",
    "CONTRACT_HANDLER_REGISTRY_SCHEMA_VERSION",
    "CONTRACT_HANDLER_REGISTRY_VERSION",
    "CONTRACT_INPUT_SCHEMA_VERSION",
    "ContractHandlerRuntime",
    "contract_registry_artifact_hashes",
    "load_contract_handler",
]
