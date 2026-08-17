"""包内发票提取 Handler Registry 的唯一运行时装载入口。"""

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

INVOICE_HANDLER_REGISTRY_SCHEMA_VERSION = "handler-registry-schema-v1"
INVOICE_HANDLER_REGISTRY_SCHEMA_HASH = (
    "9bef52684a93dd509abd30752af872b54df9a3329cb52137236eb6c51b9a349a"
)
INVOICE_HANDLER_REGISTRY_VERSION = "invoice-handler-registry-v2"
INVOICE_HANDLER_REGISTRY_HASH = "566d2ce64627f9d9df78ac0611f817568a88be1dd66ffdbc34b41a968d652ef8"
INVOICE_HANDLER_REGISTRY_V1_VERSION = "invoice-handler-registry-v1"
INVOICE_HANDLER_REGISTRY_V1_HASH = (
    "6f7f023eeee1cb3e8ed2efc937015b1c92fbed18e1b91597d0e547b80950da99"
)
INVOICE_INPUT_SCHEMA_VERSION = 1

_SHARED_PACKAGE = "app.workers.artifacts.invoice_v1"
_REGISTRY_RESOURCE = "registry.json"
_REGISTRY_SCHEMA_RESOURCE = "registry.schema.json"
_INPUT_SCHEMA_RESOURCE = "input.invoice_extract.v1.schema.json"
_INPUT_SCHEMA_ID = "invoice_extract.input.v1"
_BUNDLES = {
    INVOICE_HANDLER_REGISTRY_V1_VERSION: (
        "app.workers.artifacts.invoice_v1",
        "summary.invoice_extract.v1.schema.json",
        "invoice_extract.summary.v1",
        INVOICE_HANDLER_REGISTRY_V1_HASH,
    ),
    INVOICE_HANDLER_REGISTRY_VERSION: (
        "app.workers.artifacts.invoice_v2",
        "summary.invoice_extract.v2.schema.json",
        "invoice_extract.summary.v2",
        INVOICE_HANDLER_REGISTRY_HASH,
    ),
}


@dataclass(frozen=True, slots=True)
class InvoiceHandlerRuntime:
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


@lru_cache(maxsize=2)
def _load_invoice_handler(registry_version: str) -> InvoiceHandlerRuntime:
    try:
        package, summary_resource, summary_schema_id, registry_hash = _BUNDLES[registry_version]
    except KeyError:
        raise HandlerRegistryError from None
    registry_raw = _read(package, _REGISTRY_RESOURCE)
    registry_schema_raw = _read(_SHARED_PACKAGE, _REGISTRY_SCHEMA_RESOURCE)
    input_raw = _read(_SHARED_PACKAGE, _INPUT_SCHEMA_RESOURCE)
    summary_raw = _read(package, summary_resource)
    validated = load_handler_registry_bundle(
        registry_raw,
        registry_schema_raw,
        (RawSchemaArtifact(_INPUT_SCHEMA_ID, input_raw),),
        (RawSchemaArtifact(summary_schema_id, summary_raw),),
        expected_registry_schema_version=INVOICE_HANDLER_REGISTRY_SCHEMA_VERSION,
        expected_registry_schema_sha256=INVOICE_HANDLER_REGISTRY_SCHEMA_HASH,
        expected_registry_version=registry_version,
        expected_registry_sha256=registry_hash,
        expected_job_type="invoice_extract",
        expected_input_schema_version=INVOICE_INPUT_SCHEMA_VERSION,
    )
    return InvoiceHandlerRuntime(
        registry_version=validated.registry_version,
        registry_hash=validated.registry_sha256,
        handler=validated.handler,
        input_validator=Draft202012Validator(_schema(input_raw)),
        summary_validator=Draft202012Validator(_schema(summary_raw)),
    )


def load_invoice_handler(registry_version: str | None = None) -> InvoiceHandlerRuntime:
    return _load_invoice_handler(registry_version or INVOICE_HANDLER_REGISTRY_VERSION)


def invoice_registry_artifact_hashes(registry_version: str | None = None) -> dict[str, str]:
    selected_version = registry_version or INVOICE_HANDLER_REGISTRY_VERSION
    try:
        package, summary_resource, _summary_schema_id, _registry_hash = _BUNDLES[selected_version]
    except KeyError:
        raise HandlerRegistryError from None
    return {
        _REGISTRY_RESOURCE: hashlib.sha256(_read(package, _REGISTRY_RESOURCE)).hexdigest(),
        _REGISTRY_SCHEMA_RESOURCE: hashlib.sha256(
            _read(_SHARED_PACKAGE, _REGISTRY_SCHEMA_RESOURCE)
        ).hexdigest(),
        _INPUT_SCHEMA_RESOURCE: hashlib.sha256(
            _read(_SHARED_PACKAGE, _INPUT_SCHEMA_RESOURCE)
        ).hexdigest(),
        summary_resource: hashlib.sha256(_read(package, summary_resource)).hexdigest(),
    }


__all__ = [
    "INVOICE_HANDLER_REGISTRY_HASH",
    "INVOICE_HANDLER_REGISTRY_SCHEMA_HASH",
    "INVOICE_HANDLER_REGISTRY_SCHEMA_VERSION",
    "INVOICE_HANDLER_REGISTRY_V1_HASH",
    "INVOICE_HANDLER_REGISTRY_V1_VERSION",
    "INVOICE_HANDLER_REGISTRY_VERSION",
    "INVOICE_INPUT_SCHEMA_VERSION",
    "InvoiceHandlerRuntime",
    "invoice_registry_artifact_hashes",
    "load_invoice_handler",
]
