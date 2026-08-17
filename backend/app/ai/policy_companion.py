"""Offline validation for the CR-011 AI policy companion contract.

The Stage 1 entrypoint deliberately stops before Schema validation. The full entrypoint
accepts an explicit Draft 2020-12 validator port shared by the Gate B harness and the
approved R5 local runtime adapter.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from types import MappingProxyType
from typing import Literal, TypeAlias, cast
from urllib.parse import urlsplit

from app.ai.policy import canonicalize_jcs
from app.ai.strict_json import JsonNumberToken, JsonValue, StrictJsonDocument, parse_strict_json

ValidationTarget: TypeAlias = Literal["final_envelope", "pre_hash_payload"]
ValidationStage: TypeAlias = Literal[
    "raw_parse",
    "source_number",
    "envelope_context",
    "schema",
    "registry_integrity",
    "hash",
    "cross_field",
    "network_registry",
    "complete",
]
RejectedRuleId: TypeAlias = Literal[
    "POL-VAL-001",
    "POL-VAL-002",
    "POL-VAL-003",
    "POL-VAL-004",
    "POL-VAL-005",
    "POL-VAL-006",
    "POL-VAL-007",
    "POL-VAL-008",
    "POL-VAL-009",
    "POL-VAL-010",
    "POL-VAL-011",
]
IsolatedRuleId: TypeAlias = Literal[
    "POL-VAL-005",
    "POL-VAL-006",
    "POL-VAL-007",
    "POL-VAL-008",
    "POL-VAL-009",
    "POL-VAL-010",
    "POL-VAL-011",
]
SchemaValidator: TypeAlias = Callable[[JsonValue, Mapping[str, JsonValue]], bool]
FrozenJsonScalar: TypeAlias = None | bool | int | float | str
FrozenJsonValue: TypeAlias = (
    FrozenJsonScalar | tuple["FrozenJsonValue", ...] | Mapping[str, "FrozenJsonValue"]
)

_INTEGER_TOKEN = re.compile(r"^(?:0|[1-9][0-9]*)$")
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_LEGACY_IPV4_LABEL = re.compile(r"^(?:[0-9]+|0x[0-9a-f]+)$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MISSING = object()

_FAILURES: dict[RejectedRuleId, tuple[ValidationStage, str]] = {
    "POL-VAL-001": ("raw_parse", "AI_POLICY_SOURCE_INVALID"),
    "POL-VAL-002": ("source_number", "AI_POLICY_INTEGER_TOKEN_INVALID"),
    "POL-VAL-003": ("envelope_context", "AI_POLICY_ENVELOPE_INVALID"),
    "POL-VAL-004": ("schema", "AI_POLICY_SCHEMA_INVALID"),
    "POL-VAL-005": ("registry_integrity", "AI_POLICY_REGISTRY_MISMATCH"),
    "POL-VAL-006": ("hash", "AI_POLICY_HASH_MISMATCH"),
    "POL-VAL-007": ("cross_field", "AI_POLICY_ARRAY_NOT_CANONICAL"),
    "POL-VAL-008": ("cross_field", "AI_POLICY_ROUTE_GRAPH_INVALID"),
    "POL-VAL-009": ("cross_field", "AI_POLICY_HOST_INVALID"),
    "POL-VAL-010": ("network_registry", "AI_POLICY_CIDR_NOT_CANONICAL"),
    "POL-VAL-011": ("network_registry", "AI_POLICY_NETWORK_SCOPE_INVALID"),
}


class CompanionArtifactError(ValueError):
    """A fixed-detail error for malformed explicitly injected contract artifacts."""


class PrefixStatus(str, Enum):
    REJECTED = "REJECTED"
    BLOCKED_SCHEMA_ENGINE = "BLOCKED_SCHEMA_ENGINE"


class IsolatedOutcome(str, Enum):
    REJECTED = "ISOLATED_RULE_REJECTED"
    NO_FINDING = "ISOLATED_RULE_NO_FINDING"


@dataclass(frozen=True, slots=True)
class PrefixValidationResult:
    status: PrefixStatus
    stage: ValidationStage
    rule_id: str
    safe_error_code: str | None
    completed_rule_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class IsolatedRuleEvidence:
    """One-rule evidence that is never equivalent to ordered policy acceptance."""

    evidence_scope: Literal["ISOLATED_RULE_EVIDENCE"]
    outcome: IsolatedOutcome
    stage: ValidationStage
    rule_id: IsolatedRuleId
    safe_error_code: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class PolicyValidationResult:
    """Safe result of the complete POL-VAL-001 through POL-VAL-012 entrypoint."""

    accepted: bool
    stage: ValidationStage
    rule_id: RejectedRuleId | None
    safe_error_code: str | None
    detail: str
    pre_hash_bytes: bytes | None = dataclass_field(repr=False)
    pre_hash_sha256: str | None
    validated_policy: Mapping[str, FrozenJsonValue] | None = dataclass_field(repr=False)


@dataclass(frozen=True, slots=True)
class _HashEvidence:
    pre_hash_bytes: bytes = dataclass_field(repr=False)
    pre_hash_sha256: str


def _ordered_rejection(rule_id: RejectedRuleId) -> PolicyValidationResult:
    stage, code = _FAILURES[rule_id]
    return PolicyValidationResult(
        accepted=False,
        stage=stage,
        rule_id=rule_id,
        safe_error_code=code,
        detail="policy rejected by deterministic ordered validation rule",
        pre_hash_bytes=None,
        pre_hash_sha256=None,
        validated_policy=None,
    )


def _rejection(
    rule_id: Literal["POL-VAL-001", "POL-VAL-002", "POL-VAL-003"],
) -> PrefixValidationResult:
    stage, code = _FAILURES[rule_id]
    completed = {
        "POL-VAL-001": (),
        "POL-VAL-002": ("POL-VAL-001",),
        "POL-VAL-003": ("POL-VAL-001", "POL-VAL-002"),
    }[rule_id]
    return PrefixValidationResult(
        status=PrefixStatus.REJECTED,
        stage=stage,
        rule_id=rule_id,
        safe_error_code=code,
        completed_rule_ids=completed,
        detail="policy rejected by deterministic Stage 1 prefix rule",
    )


def _as_mapping(value: object) -> Mapping[str, JsonValue] | None:
    if not isinstance(value, dict):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return cast(dict[str, JsonValue], value)


def _as_sequence(value: object) -> Sequence[JsonValue] | None:
    if not isinstance(value, list):
        return None
    return cast(list[JsonValue], value)


def _resolve_local_ref(root_schema: Mapping[str, JsonValue], ref: str) -> Mapping[str, JsonValue]:
    if not ref.startswith("#/"):
        raise CompanionArtifactError("policy schema artifact is invalid")
    current: JsonValue = cast(JsonValue, root_schema)
    for raw_segment in ref[2:].split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        current_mapping = _as_mapping(current)
        if current_mapping is None or segment not in current_mapping:
            raise CompanionArtifactError("policy schema artifact is invalid")
        current = current_mapping[segment]
    resolved = _as_mapping(current)
    if resolved is None:
        raise CompanionArtifactError("policy schema artifact is invalid")
    return resolved


def _selected_schema(
    root_schema: Mapping[str, JsonValue], validation_target: ValidationTarget
) -> Mapping[str, JsonValue]:
    definitions = _as_mapping(root_schema.get("$defs"))
    if definitions is None:
        raise CompanionArtifactError("policy schema artifact is invalid")
    definition_name = "finalPolicy" if validation_target == "final_envelope" else "preHashPayload"
    selected = _as_mapping(definitions.get(definition_name))
    if selected is None:
        raise CompanionArtifactError("policy schema artifact is invalid")
    return selected


def _pointer_child(pointer: str, segment: str) -> str:
    escaped = segment.replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{escaped}"


def _node_declares_integer(node: Mapping[str, JsonValue]) -> bool:
    if node.get("type") == "integer":
        return True
    constant = node.get("const", _MISSING)
    return type(constant) is int


def _integer_value_is_valid(value: JsonValue, token: JsonNumberToken | None) -> bool:
    if type(value) is not int or token is None:
        return False
    return bool(_INTEGER_TOKEN.fullmatch(token.lexeme)) and value <= _MAX_SAFE_INTEGER


def _integer_tokens_are_valid(
    document: StrictJsonDocument,
    root_schema: Mapping[str, JsonValue],
    selected_schema: Mapping[str, JsonValue],
) -> bool:
    tokens = {token.pointer: token for token in document.number_tokens}
    visited: set[tuple[int, int, str]] = set()
    valid = True

    def condition_matches(instance: JsonValue, node: Mapping[str, JsonValue]) -> bool:
        ref = node.get("$ref")
        if isinstance(ref, str) and not condition_matches(
            instance, _resolve_local_ref(root_schema, ref)
        ):
            return False
        constant = node.get("const", _MISSING)
        if constant is not _MISSING and (
            type(instance) is not type(constant) or instance != constant
        ):
            return False
        enum_values = _as_sequence(node.get("enum"))
        if enum_values is not None and not any(
            type(instance) is type(candidate) and instance == candidate for candidate in enum_values
        ):
            return False
        required = _as_sequence(node.get("required"))
        instance_mapping = _as_mapping(instance)
        if required is not None:
            if instance_mapping is None or not all(
                isinstance(key, str) and key in instance_mapping for key in required
            ):
                return False
        properties = _as_mapping(node.get("properties"))
        if properties is not None and instance_mapping is not None:
            for key, child_schema_value in properties.items():
                child_schema = _as_mapping(child_schema_value)
                if (
                    key in instance_mapping
                    and child_schema is not None
                    and not condition_matches(instance_mapping[key], child_schema)
                ):
                    return False
        for keyword in ("allOf", "anyOf", "oneOf"):
            branches = _as_sequence(node.get(keyword))
            if branches is None:
                continue
            outcomes = [
                condition_matches(instance, branch)
                for value in branches
                if (branch := _as_mapping(value)) is not None
            ]
            if keyword == "allOf" and not all(outcomes):
                return False
            if keyword == "anyOf" and not any(outcomes):
                return False
            if keyword == "oneOf" and sum(outcomes) != 1:
                return False
        return True

    def walk(instance: JsonValue, node: Mapping[str, JsonValue], pointer: str) -> None:
        nonlocal valid
        visit_key = (id(instance), id(node), pointer)
        if visit_key in visited or not valid:
            return
        visited.add(visit_key)

        ref = node.get("$ref")
        if isinstance(ref, str):
            walk(instance, _resolve_local_ref(root_schema, ref), pointer)

        # A nullable integer branch contributes no source-number token when the
        # selected instance value is null; Draft 2020-12 decides nullability later.
        if (
            instance is not None
            and _node_declares_integer(node)
            and not _integer_value_is_valid(instance, tokens.get(pointer))
        ):
            valid = False
            return

        constant = node.get("const", _MISSING)
        instance_mapping = _as_mapping(instance)
        constant_mapping = _as_mapping(constant)
        if instance_mapping is not None and constant_mapping is not None:
            for key, child_constant in constant_mapping.items():
                if key in instance_mapping:
                    walk(
                        instance_mapping[key],
                        {"const": child_constant},
                        _pointer_child(pointer, key),
                    )
        instance_sequence = _as_sequence(instance)
        constant_sequence = _as_sequence(constant)
        if instance_sequence is not None and constant_sequence is not None:
            for index, (child, child_constant) in enumerate(
                zip(instance_sequence, constant_sequence, strict=False)
            ):
                walk(child, {"const": child_constant}, _pointer_child(pointer, str(index)))

        for keyword in ("allOf", "anyOf", "oneOf"):
            branches = _as_sequence(node.get(keyword))
            if branches is not None:
                for branch in branches:
                    branch_mapping = _as_mapping(branch)
                    if branch_mapping is not None:
                        walk(instance, branch_mapping, pointer)
        condition = _as_mapping(node.get("if"))
        if condition is not None:
            keyword = "then" if condition_matches(instance, condition) else "else"
            branch_mapping = _as_mapping(node.get(keyword))
            if branch_mapping is not None:
                walk(instance, branch_mapping, pointer)

        if instance_mapping is not None:
            properties = _as_mapping(node.get("properties"))
            for key, child in instance_mapping.items():
                child_schema = _as_mapping(properties.get(key)) if properties is not None else None
                if child_schema is not None:
                    walk(child, child_schema, _pointer_child(pointer, key))
                    continue
                additional = _as_mapping(node.get("additionalProperties"))
                if additional is not None:
                    walk(child, additional, _pointer_child(pointer, key))

        item_schema = _as_mapping(node.get("items"))
        if instance_sequence is not None and item_schema is not None:
            for index, child in enumerate(instance_sequence):
                walk(child, item_schema, _pointer_child(pointer, str(index)))

    walk(document.value, selected_schema, "")
    return valid


def validate_policy_prefix(
    raw_policy_bytes: bytes,
    *,
    validation_target: ValidationTarget,
    policy_schema_bytes: bytes,
) -> PrefixValidationResult:
    """Run POL-VAL-001..003, then fail closed at the absent Schema engine."""

    if validation_target not in ("final_envelope", "pre_hash_payload"):
        raise ValueError("unsupported validation target")
    try:
        policy_document = parse_strict_json(raw_policy_bytes)
    except (TypeError, ValueError):
        return _rejection("POL-VAL-001")

    try:
        schema_document = parse_strict_json(policy_schema_bytes)
        root_schema = _as_mapping(schema_document.value)
        if root_schema is None:
            raise CompanionArtifactError("policy schema artifact is invalid")
        selected = _selected_schema(root_schema, validation_target)
    except (TypeError, ValueError) as error:
        raise CompanionArtifactError("policy schema artifact is invalid") from error

    if not _integer_tokens_are_valid(policy_document, root_schema, selected):
        return _rejection("POL-VAL-002")

    policy = _as_mapping(policy_document.value)
    has_hash = policy is not None and "policy_hash" in policy
    envelope_valid = has_hash if validation_target == "final_envelope" else not has_hash
    if not envelope_valid:
        return _rejection("POL-VAL-003")

    return PrefixValidationResult(
        status=PrefixStatus.BLOCKED_SCHEMA_ENGINE,
        stage="schema",
        rule_id="POL-VAL-004",
        safe_error_code=None,
        completed_rule_ids=("POL-VAL-001", "POL-VAL-002", "POL-VAL-003"),
        detail="Draft 2020-12 schema validation is NOT_RUN in Stage 1",
    )


def _profiles(policy: Mapping[str, JsonValue]) -> Mapping[str, JsonValue] | None:
    return _as_mapping(policy.get("profiles"))


def _operations(policy: Mapping[str, JsonValue]) -> Mapping[str, JsonValue] | None:
    return _as_mapping(policy.get("operations"))


def _registry_matches(policy: Mapping[str, JsonValue], registry_bytes: bytes) -> bool:
    try:
        registry = _as_mapping(parse_strict_json(registry_bytes).value)
    except (TypeError, ValueError):
        return False
    if registry is None:
        return False
    registry_version = registry.get("registry_version")
    outbound = _as_mapping(policy.get("outbound_limits"))
    profiles = _profiles(policy)
    if not isinstance(registry_version, str) or outbound is None or profiles is None:
        return False
    if outbound.get("ip_deny_registry_version") != registry_version:
        return False
    if outbound.get("ip_deny_registry_sha256") != hashlib.sha256(registry_bytes).hexdigest():
        return False
    return all(
        (profile := _as_mapping(value)) is not None
        and profile.get("address_policy_version") == registry_version
        for value in profiles.values()
    )


def _hash_evidence(
    policy: Mapping[str, JsonValue], validation_target: ValidationTarget
) -> _HashEvidence | None:
    expected_hash: str | None = None
    if validation_target == "pre_hash_payload":
        if "policy_hash" in policy:
            return None
    else:
        candidate_hash = policy.get("policy_hash")
        if not isinstance(candidate_hash, str):
            return None
        expected_hash = candidate_hash
    projection = dict(policy)
    projection.pop("policy_hash", None)
    try:
        pre_hash_bytes = canonicalize_jcs(projection)
    except (TypeError, ValueError):
        return None
    pre_hash_sha256 = hashlib.sha256(pre_hash_bytes).hexdigest()
    if expected_hash is not None and expected_hash != pre_hash_sha256:
        return None
    return _HashEvidence(
        pre_hash_bytes=pre_hash_bytes,
        pre_hash_sha256=pre_hash_sha256,
    )


def _hash_matches(policy: Mapping[str, JsonValue], validation_target: ValidationTarget) -> bool:
    return _hash_evidence(policy, validation_target) is not None


def _freeze_json(value: JsonValue) -> FrozenJsonValue:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(child) for child in value)
    return value


def _utf16_sort_key(value: str) -> bytes:
    return value.encode("utf-16-be")


def _canonical_arrays(policy: Mapping[str, JsonValue]) -> bool:
    profiles = _profiles(policy)
    if profiles is None:
        return False
    for profile_value in profiles.values():
        profile = _as_mapping(profile_value)
        if profile is None:
            return False
        for field in ("allowed_response_model_ids", "approved_hostnames", "capabilities"):
            values = _as_sequence(profile.get(field))
            if values is None or not values or not all(isinstance(value, str) for value in values):
                return False
            strings = cast(list[str], list(values))
            if len(strings) != len(set(strings)) or strings != sorted(strings, key=_utf16_sort_key):
                return False
    return True


_ADAPTER_MAPPING = {
    "openai-chat-completions-v1": "openai_chat_completions_v1",
    "openai-embeddings-v1": "openai_embeddings_v1",
}
_OPERATION_CAPABILITIES = {
    "contract_field_extraction": "llm_extraction",
    "embedding": "embedding",
    "invoice_field_extraction": "llm_extraction",
    "rag_answer": "llm_generation",
    "report_draft": "llm_generation",
    "risk_explanation": "llm_generation",
}


def _route_graph_matches(policy: Mapping[str, JsonValue]) -> bool:
    profiles = _profiles(policy)
    operations = _operations(policy)
    if profiles is None or operations is None or set(operations) != set(_OPERATION_CAPABILITIES):
        return False

    profile_mappings: dict[str, Mapping[str, JsonValue]] = {}
    target_tuples: set[tuple[str, str, str]] = set()
    for profile_id, value in profiles.items():
        profile = _as_mapping(value)
        if profile is None:
            return False
        profile_type = profile.get("profile_type")
        adapter_id = profile.get("adapter_id")
        endpoint_id = profile.get("endpoint_id")
        model_id = profile.get("model_id")
        if (
            not isinstance(profile_type, str)
            or _ADAPTER_MAPPING.get(profile_type) != adapter_id
            or not isinstance(adapter_id, str)
            or not isinstance(endpoint_id, str)
            or not isinstance(model_id, str)
        ):
            return False
        target = (adapter_id, endpoint_id, model_id)
        if target in target_tuples:
            return False
        target_tuples.add(target)
        profile_mappings[profile_id] = profile

    referenced: set[str] = set()
    for operation_id, required_capability in _OPERATION_CAPABILITIES.items():
        operation = _as_mapping(operations.get(operation_id))
        if operation is None:
            return False
        primary_id = operation.get("primary_profile_id")
        fallback_id = operation.get("fallback_profile_id")
        if not isinstance(primary_id, str) or primary_id not in profile_mappings:
            return False
        route_ids = [primary_id]
        if fallback_id is not None:
            if not isinstance(fallback_id, str) or fallback_id == primary_id:
                return False
            route_ids.append(fallback_id)
        for profile_id in route_ids:
            profile = profile_mappings.get(profile_id)
            capabilities = (
                _as_sequence(profile.get("capabilities")) if profile is not None else None
            )
            if capabilities is None or required_capability not in capabilities:
                return False
            referenced.add(profile_id)

    report = _as_mapping(operations.get("report_draft"))
    if report is None:
        return False
    report_fallback = report.get("report_use_fallback")
    fallback_id = report.get("fallback_profile_id")
    max_attempts = report.get("max_attempts")
    if report_fallback is False and (fallback_id is not None or max_attempts != 2):
        return False
    if report_fallback is True and (not isinstance(fallback_id, str) or max_attempts != 3):
        return False
    if type(report_fallback) is not bool:
        return False
    return referenced == set(profile_mappings)


def _hostname_is_canonical(hostname: str) -> bool:
    if len(hostname) > 253 or hostname.endswith("."):
        return False
    try:
        hostname.encode("ascii")
    except UnicodeEncodeError:
        return False
    if hostname != hostname.lower():
        return False
    labels = hostname.split(".")
    if not labels or any(not label or label.startswith("xn--") for label in labels):
        return False
    if any(_HOST_LABEL.fullmatch(label) is None for label in labels):
        return False
    # URL stacks also recognize one-part, abbreviated, octal-like, and hexadecimal
    # IPv4 spellings. They are IP literals even when ``ipaddress`` rejects them.
    if all(_LEGACY_IPV4_LABEL.fullmatch(label) is not None for label in labels):
        return False
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return False


def _raw_url_host(netloc: str) -> str | None:
    if not netloc or "@" in netloc or netloc.startswith("["):
        return None
    if ":" not in netloc:
        return netloc
    host, port_text = netloc.rsplit(":", 1)
    if not port_text.isdigit():
        return None
    return host


def _host_bindings_match(policy: Mapping[str, JsonValue]) -> bool:
    profiles = _profiles(policy)
    if profiles is None:
        return False
    for value in profiles.values():
        profile = _as_mapping(value)
        if profile is None:
            return False
        base_url = profile.get("base_url")
        scope = profile.get("network_scope")
        approved = _as_sequence(profile.get("approved_hostnames"))
        if (
            not isinstance(base_url, str)
            or not isinstance(scope, str)
            or approved is None
            or not approved
            or not all(isinstance(host, str) for host in approved)
        ):
            return False
        approved_hosts = cast(list[str], list(approved))
        if not all(_hostname_is_canonical(host) for host in approved_hosts):
            return False
        try:
            parsed = urlsplit(base_url)
            port = parsed.port
        except ValueError:
            return False
        raw_host = _raw_url_host(parsed.netloc)
        if (
            raw_host is None
            or not _hostname_is_canonical(raw_host)
            or parsed.hostname != raw_host
            or raw_host not in approved_hosts
            or parsed.path != "/v1"
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            or (port is not None and not 1 <= port <= 65535)
        ):
            return False
        if scope == "external_public" and parsed.scheme != "https":
            return False
        if scope == "internal_service" and parsed.scheme not in ("http", "https"):
            return False
        if scope not in ("external_public", "internal_service"):
            return False
    return True


IpNetwork: TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network


def _parse_network(value: str) -> IpNetwork | None:
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError:
        return None
    return network if str(network) == value else None


def _network_sort_key(network: IpNetwork) -> tuple[int, int, int]:
    return network.version, int(network.network_address), network.prefixlen


def _networks_overlap(left: IpNetwork, right: IpNetwork) -> bool:
    return left.version == right.version and left.overlaps(right)


def _network_is_subnet(left: IpNetwork, right: IpNetwork) -> bool:
    if isinstance(left, ipaddress.IPv4Network) and isinstance(right, ipaddress.IPv4Network):
        return left.subnet_of(right)
    if isinstance(left, ipaddress.IPv6Network) and isinstance(right, ipaddress.IPv6Network):
        return left.subnet_of(right)
    return False


def _canonical_cidr_sets(policy: Mapping[str, JsonValue]) -> bool:
    profiles = _profiles(policy)
    if profiles is None:
        return False
    for value in profiles.values():
        profile = _as_mapping(value)
        cidr_values = _as_sequence(profile.get("allowed_cidrs")) if profile is not None else None
        if (
            cidr_values is None
            or not cidr_values
            or not all(isinstance(cidr, str) for cidr in cidr_values)
        ):
            return False
        strings = cast(list[str], list(cidr_values))
        networks = [_parse_network(cidr) for cidr in strings]
        if any(network is None for network in networks):
            return False
        parsed = cast(list[IpNetwork], networks)
        if any(network.prefixlen == 0 for network in parsed):
            return False
        if len(strings) != len(set(strings)) or parsed != sorted(parsed, key=_network_sort_key):
            return False
        for index, network in enumerate(parsed):
            if any(_networks_overlap(network, other) for other in parsed[index + 1 :]):
                return False
    return True


def _normalize_mapped_network(network: IpNetwork) -> IpNetwork:
    if isinstance(network, ipaddress.IPv6Network) and network.prefixlen >= 96:
        mapped = network.network_address.ipv4_mapped
        if mapped is not None:
            return ipaddress.IPv4Network((mapped, network.prefixlen - 96), strict=True)
    return network


def _registry_entries(
    registry_bytes: bytes,
) -> list[tuple[IpNetwork, frozenset[str]]] | None:
    try:
        registry = _as_mapping(parse_strict_json(registry_bytes).value)
    except (TypeError, ValueError):
        return None
    entries = _as_sequence(registry.get("entries")) if registry is not None else None
    if entries is None:
        return None
    result: list[tuple[IpNetwork, frozenset[str]]] = []
    for value in entries:
        entry = _as_mapping(value)
        categories = _as_sequence(entry.get("categories")) if entry is not None else None
        cidr = entry.get("cidr") if entry is not None else None
        if (
            not isinstance(cidr, str)
            or categories is None
            or not all(isinstance(category, str) for category in categories)
        ):
            return None
        try:
            # Registry bytes are separately pinned by POL-VAL-005. Rule 011
            # needs strict network semantics but must not re-specify Rule 010's
            # policy-input serialization check for the frozen registry text.
            network = ipaddress.ip_network(cidr, strict=True)
        except ValueError:
            return None
        result.append(
            (
                network,
                frozenset(cast(list[str], list(categories))),
            )
        )
    return result


def _network_scope_matches(policy: Mapping[str, JsonValue], registry_bytes: bytes) -> bool:
    entries = _registry_entries(registry_bytes)
    profiles = _profiles(policy)
    if entries is None or profiles is None:
        return False
    forbidden_internal = {"loopback", "link_local", "metadata"}
    for value in profiles.values():
        profile = _as_mapping(value)
        scope = profile.get("network_scope") if profile is not None else None
        cidrs = _as_sequence(profile.get("allowed_cidrs")) if profile is not None else None
        if not isinstance(scope, str) or cidrs is None or not cidrs:
            return False
        networks: list[IpNetwork] = []
        for cidr in cidrs:
            if not isinstance(cidr, str):
                return False
            parsed = _parse_network(cidr)
            if parsed is None or parsed.prefixlen == 0:
                return False
            networks.append(_normalize_mapped_network(parsed))
        for network in networks:
            if scope == "external_public":
                if any(
                    _networks_overlap(network, registry_network) for registry_network, _ in entries
                ):
                    return False
                continue
            if scope != "internal_service":
                return False
            eligible = any(
                _network_is_subnet(network, registry_network)
                and "app_network_eligible" in categories
                for registry_network, categories in entries
            )
            denied = any(
                _networks_overlap(network, registry_network)
                and bool(categories & forbidden_internal)
                for registry_network, categories in entries
            )
            if not eligible or denied:
                return False
    return True


def evaluate_isolated_rule(
    policy: Mapping[str, JsonValue],
    *,
    rule_id: IsolatedRuleId,
    validation_target: ValidationTarget,
    registry_bytes: bytes,
) -> IsolatedRuleEvidence:
    """Evaluate exactly one post-Schema rule without implying ordered acceptance."""

    if validation_target not in ("final_envelope", "pre_hash_payload"):
        raise ValueError("unsupported validation target")
    checks = {
        "POL-VAL-005": lambda: _registry_matches(policy, registry_bytes),
        "POL-VAL-006": lambda: _hash_matches(policy, validation_target),
        "POL-VAL-007": lambda: _canonical_arrays(policy),
        "POL-VAL-008": lambda: _route_graph_matches(policy),
        "POL-VAL-009": lambda: _host_bindings_match(policy),
        "POL-VAL-010": lambda: _canonical_cidr_sets(policy),
        "POL-VAL-011": lambda: _network_scope_matches(policy, registry_bytes),
    }
    check = checks.get(rule_id)
    if check is None:
        raise ValueError("only POL-VAL-005 through POL-VAL-011 are available as isolated evidence")
    stage, failure_code = _FAILURES[rule_id]
    matches = check()
    return IsolatedRuleEvidence(
        evidence_scope="ISOLATED_RULE_EVIDENCE",
        outcome=IsolatedOutcome.NO_FINDING if matches else IsolatedOutcome.REJECTED,
        stage=stage,
        rule_id=rule_id,
        safe_error_code=None if matches else failure_code,
        detail=(
            "isolated rule produced no finding; ordered validation remains unavailable"
            if matches
            else "isolated rule rejected the supplied policy"
        ),
    )


def validate_policy_full(
    raw_policy_bytes: bytes,
    *,
    validation_target: ValidationTarget,
    policy_schema_bytes: bytes,
    registry_bytes: bytes,
    schema_validator: SchemaValidator,
) -> PolicyValidationResult:
    """Execute POL-VAL-001 through POL-VAL-012 in the normative fixed order."""

    if validation_target not in ("final_envelope", "pre_hash_payload"):
        raise ValueError("unsupported validation target")
    try:
        policy_document = parse_strict_json(raw_policy_bytes)
    except (TypeError, ValueError):
        return _ordered_rejection("POL-VAL-001")

    try:
        schema_document = parse_strict_json(policy_schema_bytes)
        root_schema = _as_mapping(schema_document.value)
        if root_schema is None:
            raise CompanionArtifactError("policy schema artifact is invalid")
        selected = _selected_schema(root_schema, validation_target)
    except (TypeError, ValueError):
        raise CompanionArtifactError("policy schema artifact is invalid") from None

    if not _integer_tokens_are_valid(policy_document, root_schema, selected):
        return _ordered_rejection("POL-VAL-002")

    policy = _as_mapping(policy_document.value)
    has_hash = policy is not None and "policy_hash" in policy
    envelope_valid = has_hash if validation_target == "final_envelope" else not has_hash
    if not envelope_valid:
        return _ordered_rejection("POL-VAL-003")

    schema_result: object
    try:
        # The test-only Schema adapter is an untrusted boundary.  It may inspect
        # the parsed instance and Schema, but it must not rewrite the values that
        # the ordered companion rules validate after POL-VAL-004.
        schema_result = schema_validator(
            deepcopy(policy_document.value),
            deepcopy(root_schema),
        )
    except Exception:
        schema_result = _MISSING
    if type(schema_result) is not bool:
        raise CompanionArtifactError("policy schema validation adapter failed") from None
    if schema_result is False:
        return _ordered_rejection("POL-VAL-004")
    if policy is None:
        raise CompanionArtifactError("policy schema validation adapter failed") from None

    if not _registry_matches(policy, registry_bytes):
        return _ordered_rejection("POL-VAL-005")
    hash_evidence = _hash_evidence(policy, validation_target)
    if hash_evidence is None:
        return _ordered_rejection("POL-VAL-006")

    ordered_checks: tuple[tuple[RejectedRuleId, Callable[[], bool]], ...] = (
        ("POL-VAL-007", lambda: _canonical_arrays(policy)),
        ("POL-VAL-008", lambda: _route_graph_matches(policy)),
        ("POL-VAL-009", lambda: _host_bindings_match(policy)),
        ("POL-VAL-010", lambda: _canonical_cidr_sets(policy)),
        ("POL-VAL-011", lambda: _network_scope_matches(policy, registry_bytes)),
    )
    for rule_id, check in ordered_checks:
        if not check():
            return _ordered_rejection(rule_id)

    frozen_policy = _freeze_json(cast(JsonValue, dict(policy)))
    if not isinstance(frozen_policy, Mapping):
        raise CompanionArtifactError("policy canonicalization gate failed") from None
    return PolicyValidationResult(
        accepted=True,
        stage="complete",
        rule_id=None,
        safe_error_code=None,
        detail="policy accepted by complete ordered validation",
        pre_hash_bytes=hash_evidence.pre_hash_bytes,
        pre_hash_sha256=hash_evidence.pre_hash_sha256,
        validated_policy=frozen_policy,
    )
