"""包内 file Job Handler Registry 的唯一运行时装载入口。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from app.ai.strict_json import JsonValue, parse_strict_json
from app.workers.handler_registry import (
    HandlerMetadata,
    HandlerRegistryError,
    RawSchemaArtifact,
    load_handler_registry_bundle,
)

FILE_HANDLER_REGISTRY_SCHEMA_VERSION = "handler-registry-schema-v1"
FILE_HANDLER_REGISTRY_SCHEMA_HASH = (
    "9bef52684a93dd509abd30752af872b54df9a3329cb52137236eb6c51b9a349a"
)
FILE_HANDLER_REGISTRY_VERSION = "file-handler-registry-v2"
FILE_HANDLER_REGISTRY_HASH = "9c89b5927099794614000047842ac8ba3e942bee68cef9e3f6fcb0684e5e27ea"
FILE_INPUT_SCHEMA_VERSION = 1

_PACKAGE = "app.workers.artifacts.file_v1"
_REGISTRY_RESOURCE = "registry.json"
_REGISTRY_SCHEMA_RESOURCE = "registry.schema.json"
_INPUT_SCHEMA_RESOURCE = "input.file.v1.schema.json"
_SCAN_SUMMARY_RESOURCE = "summary.file_scan.v1.schema.json"
_PARSE_SUMMARY_RESOURCE = "summary.file_parse.v1.schema.json"
_MARKDOWN_SUMMARY_RESOURCE = "summary.file_markdown.v1.schema.json"
_INPUT_SCHEMA_ID = "file.input.v1"
_SUMMARY_SCHEMA_RESOURCES = {
    "file.summary.markdown.v1": _MARKDOWN_SUMMARY_RESOURCE,
    "file.summary.parse.v1": _PARSE_SUMMARY_RESOURCE,
    "file.summary.scan.v1": _SCAN_SUMMARY_RESOURCE,
}

FileJobType = Literal["file_process", "file_scan"]


@dataclass(frozen=True, slots=True)
class FileHandlerRuntime:
    registry_version: str
    registry_hash: str
    handler: HandlerMetadata
    input_validator: Draft202012Validator
    summary_validators: dict[str, Draft202012Validator]

    def validate_input(self, value: dict[str, object]) -> None:
        if next(self.input_validator.iter_errors(value), None) is not None:
            raise HandlerRegistryError

    def validate_summary(self, step_code: str, value: dict[str, object]) -> None:
        validator = self.summary_validators.get(step_code)
        if validator is None or next(validator.iter_errors(value), None) is not None:
            raise HandlerRegistryError


def _read(resource_name: str) -> bytes:
    try:
        raw = resources.files(_PACKAGE).joinpath(resource_name).read_bytes()
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
        schema = value
        Draft202012Validator.check_schema(schema)
        return schema
    except Exception:
        raise HandlerRegistryError from None


@lru_cache(maxsize=2)
def load_file_handler(job_type: FileJobType) -> FileHandlerRuntime:
    if job_type not in {"file_process", "file_scan"}:
        raise HandlerRegistryError
    registry_raw = _read(_REGISTRY_RESOURCE)
    registry_schema_raw = _read(_REGISTRY_SCHEMA_RESOURCE)
    input_raw = _read(_INPUT_SCHEMA_RESOURCE)
    summaries = {
        schema_id: _read(resource_name)
        for schema_id, resource_name in _SUMMARY_SCHEMA_RESOURCES.items()
    }
    validated = load_handler_registry_bundle(
        registry_raw,
        registry_schema_raw,
        (RawSchemaArtifact(_INPUT_SCHEMA_ID, input_raw),),
        tuple(
            RawSchemaArtifact(schema_id, summaries[schema_id])
            for schema_id in sorted(summaries, key=lambda item: item.encode("utf-8"))
        ),
        expected_registry_schema_version=FILE_HANDLER_REGISTRY_SCHEMA_VERSION,
        expected_registry_schema_sha256=FILE_HANDLER_REGISTRY_SCHEMA_HASH,
        expected_registry_version=FILE_HANDLER_REGISTRY_VERSION,
        expected_registry_sha256=FILE_HANDLER_REGISTRY_HASH,
        expected_job_type=job_type,
        expected_input_schema_version=FILE_INPUT_SCHEMA_VERSION,
    )
    input_validator = Draft202012Validator(_schema(input_raw))
    summary_by_id = {
        schema_id: Draft202012Validator(_schema(raw)) for schema_id, raw in summaries.items()
    }
    return FileHandlerRuntime(
        registry_version=validated.registry_version,
        registry_hash=validated.registry_sha256,
        handler=validated.handler,
        input_validator=input_validator,
        summary_validators={
            step.step_code: summary_by_id[step.summary_schema_id]
            for step in validated.handler.steps
        },
    )


def file_registry_artifact_hashes() -> dict[str, str]:
    """返回不含正文的制品摘要，供启动门禁和诊断断言。"""

    return {
        resource_name: hashlib.sha256(_read(resource_name)).hexdigest()
        for resource_name in (
            _REGISTRY_RESOURCE,
            _REGISTRY_SCHEMA_RESOURCE,
            _INPUT_SCHEMA_RESOURCE,
            _SCAN_SUMMARY_RESOURCE,
            _PARSE_SUMMARY_RESOURCE,
            _MARKDOWN_SUMMARY_RESOURCE,
        )
    }


__all__ = [
    "FILE_HANDLER_REGISTRY_HASH",
    "FILE_HANDLER_REGISTRY_SCHEMA_HASH",
    "FILE_HANDLER_REGISTRY_SCHEMA_VERSION",
    "FILE_HANDLER_REGISTRY_VERSION",
    "FILE_INPUT_SCHEMA_VERSION",
    "FileHandlerRuntime",
    "FileJobType",
    "file_registry_artifact_hashes",
    "load_file_handler",
]
