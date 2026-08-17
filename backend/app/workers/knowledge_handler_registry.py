"""知识索引与检索评测 Handler Registry 的唯一运行时装载入口。"""

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

KNOWLEDGE_HANDLER_REGISTRY_SCHEMA_VERSION = "handler-registry-schema-v1"
KNOWLEDGE_HANDLER_REGISTRY_SCHEMA_HASH = (
    "9bef52684a93dd509abd30752af872b54df9a3329cb52137236eb6c51b9a349a"
)
KNOWLEDGE_HANDLER_REGISTRY_VERSION = "knowledge-handler-registry-v1"
KNOWLEDGE_HANDLER_REGISTRY_HASH = "474cc9fe8eb719a5893aefb6c08795660c313d77271544860e08e2065556f4c5"
KNOWLEDGE_INPUT_SCHEMA_VERSION = 1

KnowledgeJobType = Literal["knowledge_index_build", "retrieval_eval"]
_PACKAGE = "app.workers.artifacts.knowledge_v1"
_SCHEMA_PACKAGE = "app.workers.artifacts.file_v1"
_REGISTRY_RESOURCE = "registry.json"
_REGISTRY_SCHEMA_RESOURCE = "registry.schema.json"
_INPUT_RESOURCES = {
    "knowledge_index_build.input.v1": "input.knowledge_index_build.v1.schema.json",
    "retrieval_eval.input.v1": "input.retrieval_eval.v1.schema.json",
}
_SUMMARY_RESOURCES = {
    "knowledge_index_build.summary.v1": "summary.knowledge_index_build.v1.schema.json",
    "retrieval_eval.summary.v1": "summary.retrieval_eval.v1.schema.json",
}


@dataclass(frozen=True, slots=True)
class KnowledgeHandlerRuntime:
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
def load_knowledge_handler(job_type: KnowledgeJobType) -> KnowledgeHandlerRuntime:
    if job_type not in {"knowledge_index_build", "retrieval_eval"}:
        raise HandlerRegistryError
    registry_raw = _read(_PACKAGE, _REGISTRY_RESOURCE)
    registry_schema_raw = _read(_SCHEMA_PACKAGE, _REGISTRY_SCHEMA_RESOURCE)
    input_artifacts = tuple(
        RawSchemaArtifact(schema_id, _read(_PACKAGE, resource_name))
        for schema_id, resource_name in _INPUT_RESOURCES.items()
    )
    summary_artifacts = tuple(
        RawSchemaArtifact(schema_id, _read(_PACKAGE, resource_name))
        for schema_id, resource_name in _SUMMARY_RESOURCES.items()
    )
    validated = load_handler_registry_bundle(
        registry_raw,
        registry_schema_raw,
        input_artifacts,
        summary_artifacts,
        expected_registry_schema_version=KNOWLEDGE_HANDLER_REGISTRY_SCHEMA_VERSION,
        expected_registry_schema_sha256=KNOWLEDGE_HANDLER_REGISTRY_SCHEMA_HASH,
        expected_registry_version=KNOWLEDGE_HANDLER_REGISTRY_VERSION,
        expected_registry_sha256=KNOWLEDGE_HANDLER_REGISTRY_HASH,
        expected_job_type=job_type,
        expected_input_schema_version=KNOWLEDGE_INPUT_SCHEMA_VERSION,
    )
    input_raw = dict((artifact.schema_id, artifact.raw) for artifact in input_artifacts)[
        validated.handler.input_schema_id
    ]
    summary_id = validated.handler.steps[0].summary_schema_id
    summary_raw = dict((artifact.schema_id, artifact.raw) for artifact in summary_artifacts)[
        summary_id
    ]
    return KnowledgeHandlerRuntime(
        registry_version=validated.registry_version,
        registry_hash=validated.registry_sha256,
        handler=validated.handler,
        input_validator=Draft202012Validator(_schema(input_raw)),
        summary_validator=Draft202012Validator(_schema(summary_raw)),
    )


def knowledge_registry_artifact_hashes() -> dict[str, str]:
    names = (_REGISTRY_RESOURCE, *_INPUT_RESOURCES.values(), *_SUMMARY_RESOURCES.values())
    return {name: hashlib.sha256(_read(_PACKAGE, name)).hexdigest() for name in names}


__all__ = [
    "KNOWLEDGE_HANDLER_REGISTRY_HASH",
    "KNOWLEDGE_HANDLER_REGISTRY_SCHEMA_HASH",
    "KNOWLEDGE_HANDLER_REGISTRY_SCHEMA_VERSION",
    "KNOWLEDGE_HANDLER_REGISTRY_VERSION",
    "KNOWLEDGE_INPUT_SCHEMA_VERSION",
    "KnowledgeHandlerRuntime",
    "KnowledgeJobType",
    "knowledge_registry_artifact_hashes",
    "load_knowledge_handler",
]
