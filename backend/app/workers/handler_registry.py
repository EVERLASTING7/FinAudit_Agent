"""CR-004-R2 meta-only Handler Registry bundle validation."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import NoReturn, Protocol

# jsonschema 4.26.0 does not publish PEP 561 type information.
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

# Use jsonschema's public Draft 2020-12 reference implementation with no retrieval callback.
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from app.ai.policy import canonicalize_jcs
from app.ai.strict_json import JsonValue, parse_strict_json

_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$", re.ASCII)
_JOB_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,59}$", re.ASCII)
_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$", re.ASCII)
_SCHEMA_ID_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,159}$", re.ASCII)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_LOGICAL_QUEUES = frozenset(
    {"document", "extraction", "knowledge", "evaluation", "audit", "report", "maintenance"}
)
_OBJECT_SCHEMA_KEYWORDS = frozenset(
    {
        "properties",
        "patternProperties",
        "additionalProperties",
        "unevaluatedProperties",
        "required",
        "propertyNames",
        "minProperties",
        "maxProperties",
        "dependentRequired",
        "dependentSchemas",
    }
)
_MAX_INTEGER = 2_147_483_647
_REGISTRY_KEYS = frozenset({"registry_version", "handlers"})
_HANDLER_KEYS = frozenset(
    {
        "job_type",
        "input_schema_version",
        "input_schema_id",
        "input_schema_sha256",
        "handler_code_version",
        "logical_queue",
        "max_attempts",
        "retry_scopes",
        "steps",
    }
)
_RETRY_SCOPE_KEYS = frozenset({"scope_code", "start_step_code"})
_STEP_KEYS = frozenset({"step_code", "summary_schema_id", "summary_schema_sha256"})


class HandlerRegistryError(ValueError):
    """A fixed, redacted failure for every untrusted bundle error."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__("HANDLER_REGISTRY_INVALID")

    def __repr__(self) -> str:
        return "HandlerRegistryError('HANDLER_REGISTRY_INVALID')"


class _InvalidBundle(ValueError):
    pass


class _Resolver(Protocol):
    def in_subresource(self, subresource: Resource[dict[str, JsonValue]]) -> _Resolver: ...

    def lookup(self, reference: str) -> object: ...


@dataclass(frozen=True, slots=True)
class RawSchemaArtifact:
    """One explicitly identified raw Schema in a caller-provided bundle."""

    schema_id: str
    raw: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class SchemaIdentity:
    schema_id: str
    raw_sha256: str


@dataclass(frozen=True, slots=True)
class RetryScopeMetadata:
    scope_code: str
    start_step_code: str


@dataclass(frozen=True, slots=True)
class StepMetadata:
    step_code: str
    summary_schema_id: str
    summary_schema_sha256: str


@dataclass(frozen=True, slots=True)
class HandlerMetadata:
    job_type: str
    input_schema_version: int
    input_schema_id: str
    input_schema_sha256: str
    handler_code_version: str
    logical_queue: str
    max_attempts: int
    retry_scopes: tuple[RetryScopeMetadata, ...]
    steps: tuple[StepMetadata, ...]


@dataclass(frozen=True, slots=True)
class ValidatedHandlerRegistry:
    """Immutable identities and metadata only; it contains no callable or runtime hook."""

    registry_schema_version: str
    registry_schema_sha256: str
    registry_version: str
    registry_sha256: str
    handler: HandlerMetadata
    input_schemas: tuple[SchemaIdentity, ...]
    summary_schemas: tuple[SchemaIdentity, ...]


def _invalid() -> NoReturn:
    raise _InvalidBundle


def _mapping(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict) or not all(type(key) is str for key in value):
        _invalid()
    return value


def _array(value: JsonValue) -> list[JsonValue]:
    if not isinstance(value, list):
        _invalid()
    return value


def _string(value: JsonValue, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _invalid()
    return value


def _integer(value: JsonValue) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_INTEGER:
        _invalid()
    return value


def _exact_keys(value: Mapping[str, JsonValue], expected: frozenset[str]) -> None:
    if frozenset(value) != expected:
        _invalid()


def _parse_schema(raw: bytes) -> dict[str, JsonValue]:
    schema = _mapping(parse_strict_json(raw).value)
    if schema.get("$schema") != _DRAFT_2020_12:
        _invalid()
    _validate_local_schema_references(schema)
    Draft202012Validator.check_schema(schema)
    return schema


def _validate_local_schema_references(schema: dict[str, JsonValue]) -> None:
    root = Resource.from_contents(schema, default_specification=DRAFT202012)
    base_uri = root.id() or "urn:finaudit:synthetic-schema-root"
    registry = Registry().with_resource(base_uri, root).crawl()

    def walk(resource: Resource[dict[str, JsonValue]], resolver: _Resolver) -> None:
        contents = resource.contents
        if isinstance(contents, dict):
            for keyword in ("$ref", "$dynamicRef"):
                if keyword in contents:
                    reference = contents[keyword]
                    if type(reference) is not str or not reference.startswith("#"):
                        _invalid()
                    resolver.lookup(reference)
        for subresource in resource.subresources():
            walk(subresource, resolver.in_subresource(subresource))

    walk(root, registry.resolver(base_uri))


def _walk_registry_schema(value: JsonValue) -> None:
    if not isinstance(value, dict):
        _invalid()
    root = Resource.from_contents(value, default_specification=DRAFT202012)

    def walk(resource: Resource[dict[str, JsonValue]]) -> None:
        contents = resource.contents
        schema_type = contents.get("type") if isinstance(contents, dict) else None
        has_object_type = schema_type == "object" or (
            isinstance(schema_type, list) and "object" in schema_type
        )
        if (
            isinstance(contents, dict)
            and (has_object_type or not _OBJECT_SCHEMA_KEYWORDS.isdisjoint(contents))
            and contents.get("additionalProperties") is not False
        ):
            _invalid()
        for subresource in resource.subresources():
            walk(subresource)

    walk(root)


def _closed_object_schema(
    value: JsonValue,
    expected_properties: frozenset[str],
) -> dict[str, JsonValue]:
    schema = _mapping(value)
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        _invalid()
    properties = _mapping(schema.get("properties"))
    required = _array(schema.get("required"))
    if (
        frozenset(properties) != expected_properties
        or len(required) != len(expected_properties)
        or any(type(item) is not str for item in required)
        or frozenset(required) != expected_properties
    ):
        _invalid()
    return properties


def _array_items_schema(value: JsonValue, *, require_non_empty: bool) -> JsonValue:
    schema = _mapping(value)
    if schema.get("type") != "array" or "items" not in schema:
        _invalid()
    min_items = schema.get("minItems")
    if require_non_empty and (type(min_items) is not int or min_items != 1):
        _invalid()
    if (
        not require_non_empty
        and "minItems" in schema
        and (type(min_items) is not int or min_items != 0)
    ):
        _invalid()
    return schema["items"]


def _validate_registry_schema_shape(schema: dict[str, JsonValue]) -> None:
    root_properties = _closed_object_schema(schema, _REGISTRY_KEYS)
    handler_items = _array_items_schema(root_properties["handlers"], require_non_empty=True)
    handler_properties = _closed_object_schema(handler_items, _HANDLER_KEYS)
    retry_scope_items = _array_items_schema(
        handler_properties["retry_scopes"], require_non_empty=False
    )
    _closed_object_schema(retry_scope_items, _RETRY_SCOPE_KEYS)
    step_items = _array_items_schema(handler_properties["steps"], require_non_empty=True)
    _closed_object_schema(step_items, _STEP_KEYS)


def _schema_bundle(
    artifacts: Sequence[RawSchemaArtifact],
) -> dict[str, tuple[str, dict[str, JsonValue]]]:
    if isinstance(artifacts, (str, bytes, bytearray, memoryview)) or not isinstance(
        artifacts, Sequence
    ):
        _invalid()
    by_id: dict[str, tuple[str, dict[str, JsonValue]]] = {}
    for artifact in artifacts:
        if type(artifact) is not RawSchemaArtifact:
            _invalid()
        schema_id = _string(artifact.schema_id, _SCHEMA_ID_PATTERN)
        if type(artifact.raw) is not bytes or schema_id in by_id:
            _invalid()
        schema = _parse_schema(artifact.raw)
        by_id[schema_id] = (hashlib.sha256(artifact.raw).hexdigest(), schema)
    return by_id


def _validate_registry(
    registry: dict[str, JsonValue],
) -> tuple[str, tuple[HandlerMetadata, ...], dict[str, str], dict[str, str]]:
    _exact_keys(registry, _REGISTRY_KEYS)
    registry_version = _string(registry["registry_version"], _VERSION_PATTERN)
    handlers_raw = _array(registry["handlers"])
    if not handlers_raw:
        _invalid()

    handlers: list[HandlerMetadata] = []
    input_hashes: dict[str, str] = {}
    summary_hashes: dict[str, str] = {}
    previous_key: tuple[bytes, int] | None = None
    seen_handler_keys: set[tuple[str, int]] = set()

    for raw_handler in handlers_raw:
        handler = _mapping(raw_handler)
        _exact_keys(
            handler,
            _HANDLER_KEYS,
        )
        job_type = _string(handler["job_type"], _JOB_TYPE_PATTERN)
        input_schema_version = _integer(handler["input_schema_version"])
        input_schema_id = _string(handler["input_schema_id"], _SCHEMA_ID_PATTERN)
        input_schema_sha256 = _string(handler["input_schema_sha256"], _SHA256_PATTERN)
        handler_code_version = _string(handler["handler_code_version"], _VERSION_PATTERN)
        logical_queue = handler["logical_queue"]
        if type(logical_queue) is not str or logical_queue not in _LOGICAL_QUEUES:
            _invalid()
        max_attempts = _integer(handler["max_attempts"])

        handler_key = (job_type, input_schema_version)
        sort_key = (job_type.encode("utf-8"), input_schema_version)
        if handler_key in seen_handler_keys or (
            previous_key is not None and sort_key <= previous_key
        ):
            _invalid()
        seen_handler_keys.add(handler_key)
        previous_key = sort_key
        previous_input_hash = input_hashes.setdefault(input_schema_id, input_schema_sha256)
        if previous_input_hash != input_schema_sha256:
            _invalid()

        steps_raw = _array(handler["steps"])
        if not steps_raw:
            _invalid()
        steps: list[StepMetadata] = []
        step_codes: set[str] = set()
        for raw_step in steps_raw:
            step = _mapping(raw_step)
            _exact_keys(
                step,
                _STEP_KEYS,
            )
            step_code = _string(step["step_code"], _CODE_PATTERN)
            summary_schema_id = _string(step["summary_schema_id"], _SCHEMA_ID_PATTERN)
            summary_schema_sha256 = _string(step["summary_schema_sha256"], _SHA256_PATTERN)
            if step_code in step_codes:
                _invalid()
            step_codes.add(step_code)
            previous_summary_hash = summary_hashes.setdefault(
                summary_schema_id, summary_schema_sha256
            )
            if previous_summary_hash != summary_schema_sha256:
                _invalid()
            steps.append(
                StepMetadata(
                    step_code=step_code,
                    summary_schema_id=summary_schema_id,
                    summary_schema_sha256=summary_schema_sha256,
                )
            )

        scopes_raw = _array(handler["retry_scopes"])
        scopes: list[RetryScopeMetadata] = []
        previous_scope: bytes | None = None
        for raw_scope in scopes_raw:
            scope = _mapping(raw_scope)
            _exact_keys(scope, _RETRY_SCOPE_KEYS)
            scope_code = _string(scope["scope_code"], _CODE_PATTERN)
            start_step_code = _string(scope["start_step_code"], _CODE_PATTERN)
            scope_sort_key = scope_code.encode("utf-8")
            if (
                previous_scope is not None
                and scope_sort_key <= previous_scope
                or start_step_code not in step_codes
            ):
                _invalid()
            previous_scope = scope_sort_key
            scopes.append(
                RetryScopeMetadata(
                    scope_code=scope_code,
                    start_step_code=start_step_code,
                )
            )

        handlers.append(
            HandlerMetadata(
                job_type=job_type,
                input_schema_version=input_schema_version,
                input_schema_id=input_schema_id,
                input_schema_sha256=input_schema_sha256,
                handler_code_version=handler_code_version,
                logical_queue=logical_queue,
                max_attempts=max_attempts,
                retry_scopes=tuple(scopes),
                steps=tuple(steps),
            )
        )

    return registry_version, tuple(handlers), input_hashes, summary_hashes


def _validate_exact_bundle(
    actual: Mapping[str, tuple[str, dict[str, JsonValue]]],
    expected: Mapping[str, str],
) -> tuple[SchemaIdentity, ...]:
    if frozenset(actual) != frozenset(expected):
        _invalid()
    identities: list[SchemaIdentity] = []
    for schema_id in sorted(expected, key=lambda item: item.encode("utf-8")):
        raw_sha256, _schema = actual[schema_id]
        if raw_sha256 != expected[schema_id]:
            _invalid()
        identities.append(SchemaIdentity(schema_id=schema_id, raw_sha256=raw_sha256))
    return tuple(identities)


def _load_handler_registry_bundle(
    registry_raw: bytes,
    registry_schema_raw: bytes,
    input_schema_bundle: Sequence[RawSchemaArtifact],
    summary_schema_bundle: Sequence[RawSchemaArtifact],
    *,
    expected_registry_schema_version: str,
    expected_registry_schema_sha256: str,
    expected_registry_version: str,
    expected_registry_sha256: str,
    expected_job_type: str,
    expected_input_schema_version: int,
) -> ValidatedHandlerRegistry:
    if type(registry_raw) is not bytes or type(registry_schema_raw) is not bytes:
        _invalid()
    schema_version = _string(expected_registry_schema_version, _VERSION_PATTERN)
    schema_sha256 = _string(expected_registry_schema_sha256, _SHA256_PATTERN)
    registry_version_expected = _string(expected_registry_version, _VERSION_PATTERN)
    registry_sha256_expected = _string(expected_registry_sha256, _SHA256_PATTERN)
    job_type_expected = _string(expected_job_type, _JOB_TYPE_PATTERN)
    input_schema_version_expected = _integer(expected_input_schema_version)

    registry_schema = _parse_schema(registry_schema_raw)
    _walk_registry_schema(registry_schema)
    _validate_registry_schema_shape(registry_schema)
    if hashlib.sha256(registry_schema_raw).hexdigest() != schema_sha256:
        _invalid()

    registry = _mapping(parse_strict_json(registry_raw).value)
    validator = Draft202012Validator(registry_schema)
    if next(validator.iter_errors(registry), None) is not None:
        _invalid()

    registry_version, handlers, input_hashes, summary_hashes = _validate_registry(registry)
    if registry_version != registry_version_expected:
        _invalid()
    registry_sha256 = hashlib.sha256(canonicalize_jcs(registry)).hexdigest()
    if registry_sha256 != registry_sha256_expected:
        _invalid()

    input_schemas = _validate_exact_bundle(_schema_bundle(input_schema_bundle), input_hashes)
    summary_schemas = _validate_exact_bundle(_schema_bundle(summary_schema_bundle), summary_hashes)
    matching_handlers = tuple(
        handler
        for handler in handlers
        if handler.job_type == job_type_expected
        and handler.input_schema_version == input_schema_version_expected
    )
    if len(matching_handlers) != 1:
        _invalid()

    return ValidatedHandlerRegistry(
        registry_schema_version=schema_version,
        registry_schema_sha256=schema_sha256,
        registry_version=registry_version,
        registry_sha256=registry_sha256,
        handler=matching_handlers[0],
        input_schemas=input_schemas,
        summary_schemas=summary_schemas,
    )


def load_handler_registry_bundle(
    registry_raw: bytes,
    registry_schema_raw: bytes,
    input_schema_bundle: Sequence[RawSchemaArtifact],
    summary_schema_bundle: Sequence[RawSchemaArtifact],
    *,
    expected_registry_schema_version: str,
    expected_registry_schema_sha256: str,
    expected_registry_version: str,
    expected_registry_sha256: str,
    expected_job_type: str,
    expected_input_schema_version: int,
) -> ValidatedHandlerRegistry:
    """Validate one fully bound synthetic meta bundle without I/O or runtime resolution."""

    failed = False
    try:
        return _load_handler_registry_bundle(
            registry_raw,
            registry_schema_raw,
            input_schema_bundle,
            summary_schema_bundle,
            expected_registry_schema_version=expected_registry_schema_version,
            expected_registry_schema_sha256=expected_registry_schema_sha256,
            expected_registry_version=expected_registry_version,
            expected_registry_sha256=expected_registry_sha256,
            expected_job_type=expected_job_type,
            expected_input_schema_version=expected_input_schema_version,
        )
    except Exception:
        failed = True
    if failed:
        raise HandlerRegistryError
    raise AssertionError("unreachable")
