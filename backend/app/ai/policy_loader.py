"""CR-011-R5 本地应用启动 Policy 的失败关闭加载器。"""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import stat
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal, NoReturn, TypeAlias, cast

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - exercised by the Linux container gate
    msvcrt = None  # type: ignore[assignment]

# jsonschema 4.26.0 未发布 PEP 561 类型标记；仅在第三方导入边界抑制该错误。
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from app.ai.live_policy import (
    LIVE_EMBEDDING_POLICY,
    LIVE_LLM_POLICY,
    LIVE_POLICY_HASH,
    LIVE_POLICY_ID,
    validate_live_policy_bytes,
)
from app.ai.policy_companion import (
    CompanionArtifactError,
    FrozenJsonValue,
    RejectedRuleId,
    validate_policy_full,
)
from app.ai.strict_json import JsonValue, parse_strict_json
from app.core.config import AppEnvironment, Settings, _is_validated_settings_instance

PolicyStartupCategory: TypeAlias = Literal[
    "settings",
    "environment",
    "path",
    "resource",
    "validation",
    "binding",
]
PolicyStartupStage: TypeAlias = Literal[
    "settings_validation",
    "environment_authorization",
    "path_lexical",
    "drive_root_locality",
    "package_resource_identity",
    "path_component_identity",
    "policy_read",
    "raw_parse",
    "source_number",
    "envelope_context",
    "schema",
    "registry_integrity",
    "hash",
    "cross_field",
    "network_registry",
    "approval_identity_pin",
    "settings_policy_binding",
]

_RESOURCE_PACKAGE = "app.ai.artifacts.cr011_v1"
_SCHEMA_ID = "urn:finaudit:schema:ai-policy-v1"
_APPROVED_POLICY_BYTES = 9_708
_APPROVED_POLICY_RAW_SHA256 = "da229cdb14bc40df8f6a0731498b0f947ab1f4f28b97a69f28e0f88af27119bb"
_APPROVED_POLICY_HASH = "db946ad109baf5ec84455a2d0a09ce5e29602c0d9f9ce8404901f5c63683443d"
_MAX_POLICY_BYTES = 1_048_576
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_LOCAL_POSIX_FILESYSTEMS = frozenset(
    {
        "btrfs",
        "erofs",
        "ext2",
        "ext3",
        "ext4",
        "f2fs",
        "overlay",
        "ramfs",
        "squashfs",
        "tmpfs",
        "xfs",
        "zfs",
    }
)

_COMPANION_ORDER = tuple(f"POL-VAL-{number:03d}" for number in range(1, 13))
_LOCAL_PHYSICAL_VOLUME = re.compile(r"^\\Device\\HarddiskVolume[0-9]+$", re.IGNORECASE)
_RATE_LIMIT_TEXT = re.compile(
    r"^(?P<concurrency>[1-9][0-9]*)/"
    r"(?P<rpm>[1-9][0-9]*)/"
    r"(?P<tpm>[1-9][0-9]*)/"
    r"(?P<burst>[1-9][0-9]*)$"
)
_RESERVED_DOS_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
    | {f"COM{number}" for number in "¹²³"}
    | {f"LPT{number}" for number in "¹²³"}
)


@dataclass(frozen=True, slots=True)
class ValidatedPolicySnapshot:
    """应用可采用的最小只读 Policy identity。"""

    policy_version: Literal[1, 2]
    policy_hash: str
    raw_sha256: str
    provider_calls_enabled: bool = False
    runtime_profile_id: str | None = None


class PolicyStartupError(RuntimeError):
    """不携带路径、原始 Policy 或配置值的稳定启动错误。"""

    __slots__ = ("category", "stage", "rule_id", "code")

    def __init__(
        self,
        *,
        category: PolicyStartupCategory,
        stage: PolicyStartupStage,
        code: str,
        rule_id: RejectedRuleId | None = None,
    ) -> None:
        self.category = category
        self.stage = stage
        self.rule_id = rule_id
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return (
            "PolicyStartupError("
            f"category={self.category!r}, stage={self.stage!r}, "
            f"rule_id={self.rule_id!r}, code={self.code!r})"
        )


@dataclass(frozen=True, slots=True)
class _ResourceIdentity:
    name: str
    raw_bytes: int
    sha256: str


_RESOURCE_IDENTITIES = (
    _ResourceIdentity(
        "ai-policy-v1.positive.json",
        9_708,
        "da229cdb14bc40df8f6a0731498b0f947ab1f4f28b97a69f28e0f88af27119bb",
    ),
    _ResourceIdentity(
        "ai-policy-v1.schema.json",
        28_811,
        "8d583164b46cb2cfa6315efa86491bd6cdc17c818be79dd9c7c274903c9399e3",
    ),
    _ResourceIdentity(
        "ai-policy-v1.companion-validator.json",
        9_071,
        "10b9b67042060905ad1c7eb0dcd678724be3b01117eb3963332b51b9c626bed3",
    ),
    _ResourceIdentity(
        "ip-deny-cidrs-v1.json",
        5_874,
        "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34",
    ),
)


@dataclass(frozen=True, slots=True)
class _PolicyResources:
    schema_bytes: bytes = field(repr=False)
    registry_bytes: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class _LexicalPolicyPath:
    raw: str = field(repr=False)
    drive: str
    root: str = field(repr=False)
    components: tuple[str, ...] = field(repr=False)
    separator: Literal["\\", "/"] = "\\"


@dataclass(frozen=True, slots=True)
class _DriveRootInfo:
    drive_type: int
    device_targets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PosixMountInfo:
    mount_point: str = field(repr=False)
    filesystem_type: str


@dataclass(frozen=True, slots=True)
class _PathIdentity:
    device: int
    inode: int
    mode: int
    attributes: int
    reparse_tag: int


@dataclass(frozen=True, slots=True)
class _InspectedPath:
    target: str = field(repr=False)
    components: tuple[tuple[str, _PathIdentity], ...] = field(repr=False)


def _fail(
    *,
    category: PolicyStartupCategory,
    stage: PolicyStartupStage,
    code: str,
    rule_id: RejectedRuleId | None = None,
) -> NoReturn:
    raise PolicyStartupError(
        category=category,
        stage=stage,
        code=code,
        rule_id=rule_id,
    ) from None


def _revalidate_settings(value: object) -> Settings:
    if type(value) is not Settings or not _is_validated_settings_instance(value):
        _fail(
            category="settings",
            stage="settings_validation",
            code="AI_SETTINGS_INVALID",
        )
    return value


def _parse_windows_policy_path(value: str) -> _LexicalPolicyPath:
    components: tuple[str, ...] = ()
    valid = True
    try:
        if (
            type(value) is not str
            or len(value) < 4
            or not value[0].isascii()
            or not value[0].isalpha()
            or value[1:3] != ":\\"
            or "/" in value
            or ":" in value[2:]
            or any(
                character in '<>"|*?' or unicodedata.category(character).startswith("C")
                for character in value
            )
        ):
            raise ValueError

        components = tuple(value[3:].split("\\"))
        if not components or any(
            not component
            or component in {".", ".."}
            or component.rstrip(" .") != component
            or component.split(".", 1)[0].rstrip(" .").upper() in _RESERVED_DOS_NAMES
            for component in components
        ):
            raise ValueError

        # PureWindowsPath is used only after the exact lexical gate; it performs no I/O.
        parsed = PureWindowsPath(value)
        if not parsed.is_absolute() or parsed.drive.casefold() != value[:2].casefold():
            raise ValueError
    except (AttributeError, IndexError, TypeError, ValueError):
        valid = False

    if not valid:
        _fail(category="path", stage="path_lexical", code="AI_POLICY_PATH_INVALID")

    drive = value[:2].upper()
    return _LexicalPolicyPath(
        raw=value,
        drive=drive,
        root=f"{drive}\\",
        components=components,
    )


def _parse_posix_policy_path(value: str) -> _LexicalPolicyPath:
    components: tuple[str, ...] = ()
    valid = True
    try:
        if (
            type(value) is not str
            or len(value) < 2
            or not value.startswith("/")
            or "\\" in value
            or any(unicodedata.category(character).startswith("C") for character in value)
        ):
            raise ValueError

        components = tuple(value[1:].split("/"))
        if not components or any(
            not component or component in {".", ".."} for component in components
        ):
            raise ValueError

        # PurePosixPath is used only after the exact lexical gate; it performs no I/O.
        parsed = PurePosixPath(value)
        if not parsed.is_absolute() or str(parsed) != value:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        valid = False

    if not valid:
        _fail(category="path", stage="path_lexical", code="AI_POLICY_PATH_INVALID")

    return _LexicalPolicyPath(
        raw=value,
        drive="",
        root="/",
        components=components,
        separator="/",
    )


def _parse_policy_path(value: str) -> _LexicalPolicyPath:
    if os.name == "nt":
        return _parse_windows_policy_path(value)
    return _parse_posix_policy_path(value)


def _query_drive_root(path: _LexicalPolicyPath) -> _DriveRootInfo:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = [ctypes.c_wchar_p]
    get_drive_type.restype = ctypes.c_uint
    query_dos_device = kernel32.QueryDosDeviceW
    query_dos_device.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
    query_dos_device.restype = ctypes.c_ulong

    drive_type = int(get_drive_type(path.root))
    buffer = ctypes.create_unicode_buffer(32_768)
    count = int(query_dos_device(path.drive, buffer, len(buffer)))
    if count == 0:
        raise OSError
    raw_targets = "".join(buffer[index] for index in range(count))
    targets = tuple(target for target in raw_targets.split("\x00") if target)
    return _DriveRootInfo(drive_type=drive_type, device_targets=targets)


def _decode_mountinfo_path(value: str) -> str:
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _query_posix_mount(path: _LexicalPolicyPath) -> _PosixMountInfo:
    selected: _PosixMountInfo | None = None
    with open("/proc/self/mountinfo", encoding="utf-8") as stream:
        for line in stream:
            before_separator, separator, after_separator = line.partition(" - ")
            before_fields = before_separator.split()
            after_fields = after_separator.split()
            if separator != " - " or len(before_fields) < 5 or not after_fields:
                raise OSError
            mount_point = _decode_mountinfo_path(before_fields[4])
            if path.raw != mount_point and not path.raw.startswith(mount_point.rstrip("/") + "/"):
                continue
            candidate = _PosixMountInfo(
                mount_point=mount_point,
                filesystem_type=after_fields[0],
            )
            if selected is None or len(candidate.mount_point) > len(selected.mount_point):
                selected = candidate
    if selected is None:
        raise OSError
    return selected


def _validate_drive_root(path: _LexicalPolicyPath) -> None:
    try:
        if path.separator == "\\":
            info = _query_drive_root(path)
            valid = (
                info.drive_type == 3  # DRIVE_FIXED
                and len(info.device_targets) == 1
                and _LOCAL_PHYSICAL_VOLUME.fullmatch(info.device_targets[0]) is not None
            )
        else:
            mount = _query_posix_mount(path)
            valid = mount.filesystem_type in _LOCAL_POSIX_FILESYSTEMS
    except (AttributeError, OSError, TypeError, ValueError):
        valid = False
    if not valid:
        _fail(
            category="path",
            stage="drive_root_locality",
            code="AI_POLICY_DRIVE_ROOT_NOT_LOCAL",
        )


def _as_mapping(value: object) -> Mapping[str, JsonValue] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return cast(dict[str, JsonValue], value)


def _read_resource_bytes(identity: _ResourceIdentity) -> bytes:
    resource = resources.files(_RESOURCE_PACKAGE).joinpath(identity.name)
    with resource.open("rb") as stream:
        return stream.read(identity.raw_bytes + 1)


def _load_package_resources() -> _PolicyResources:
    raw_by_name: dict[str, bytes] = {}
    failed = False
    try:
        package_root = resources.files(_RESOURCE_PACKAGE)
        actual_json_names = {
            child.name
            for child in package_root.iterdir()
            if child.is_file() and child.name.casefold().endswith(".json")
        }
        expected_names = {identity.name for identity in _RESOURCE_IDENTITIES}
        if actual_json_names != expected_names:
            raise ValueError

        parsed_by_name: dict[str, Mapping[str, JsonValue]] = {}
        for identity in _RESOURCE_IDENTITIES:
            raw = _read_resource_bytes(identity)
            if len(raw) != identity.raw_bytes or hashlib.sha256(raw).hexdigest() != identity.sha256:
                raise ValueError
            document = parse_strict_json(raw)
            parsed = _as_mapping(document.value)
            if parsed is None:
                raise ValueError
            raw_by_name[identity.name] = raw
            parsed_by_name[identity.name] = parsed

        schema = parsed_by_name["ai-policy-v1.schema.json"]
        companion = parsed_by_name["ai-policy-v1.companion-validator.json"]
        if schema.get("$id") != _SCHEMA_ID or companion.get("execution_order") != list(
            _COMPANION_ORDER
        ):
            raise ValueError
        Draft202012Validator.check_schema(schema)
    except Exception:
        failed = True

    if failed:
        _fail(
            category="resource",
            stage="package_resource_identity",
            code="AI_POLICY_RESOURCE_IDENTITY_INVALID",
        )

    return _PolicyResources(
        schema_bytes=raw_by_name["ai-policy-v1.schema.json"],
        registry_bytes=raw_by_name["ip-deny-cidrs-v1.json"],
    )


def _path_identity(info: os.stat_result) -> _PathIdentity:
    return _PathIdentity(
        device=info.st_dev,
        inode=info.st_ino,
        mode=info.st_mode,
        attributes=int(getattr(info, "st_file_attributes", 0)),
        reparse_tag=int(getattr(info, "st_reparse_tag", 0)),
    )


def _lstat(path: str) -> os.stat_result:
    return os.lstat(path)


def _inspect_components(path: _LexicalPolicyPath) -> _InspectedPath:
    inspected: list[tuple[str, _PathIdentity]] = []
    current = path.root
    failed = False
    candidates = (path.root,) + tuple(
        path.root + path.separator.join(path.components[: index + 1])
        for index in range(len(path.components))
    )
    try:
        for index, current in enumerate(candidates):
            info = _lstat(current)
            identity = _path_identity(info)
            is_target = index == len(candidates) - 1
            if identity.attributes & _FILE_ATTRIBUTE_REPARSE_POINT or stat.S_ISLNK(identity.mode):
                raise OSError
            if is_target:
                if not stat.S_ISREG(identity.mode) or info.st_size > _MAX_POLICY_BYTES:
                    raise OSError
            elif not stat.S_ISDIR(identity.mode):
                raise OSError
            inspected.append((current, identity))
    except (AttributeError, OSError, TypeError, ValueError):
        failed = True

    if failed:
        _fail(
            category="path",
            stage="path_component_identity",
            code="AI_POLICY_PATH_IDENTITY_INVALID",
        )
    return _InspectedPath(target=current, components=tuple(inspected))


def _open_no_follow(path: str) -> int:
    if os.name != "nt":
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise OSError
        return os.open(
            path,
            os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    handle = create_file(
        path,
        0x80000000,  # GENERIC_READ
        0x00000001,  # FILE_SHARE_READ; write/delete replacement remains blocked
        None,
        3,  # OPEN_EXISTING
        0x00200000 | 0x08000000,  # OPEN_REPARSE_POINT | SEQUENTIAL_SCAN
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in (None, invalid_handle):
        raise OSError
    try:
        if msvcrt is None:
            raise OSError
        return msvcrt.open_osfhandle(cast(int, handle), os.O_RDONLY | os.O_BINARY)
    except (OSError, OverflowError):
        close_handle(handle)
        raise


def _read_external_policy(inspected: _InspectedPath) -> bytes:
    expected_target_identity = inspected.components[-1][1]
    raw = b""
    failed = False
    try:
        descriptor = _open_no_follow(inspected.target)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            if _path_identity(os.fstat(descriptor)) != expected_target_identity:
                raise OSError
            raw = stream.read(_MAX_POLICY_BYTES + 1)
            if len(raw) > _MAX_POLICY_BYTES:
                raise OSError
            if _path_identity(os.fstat(descriptor)) != expected_target_identity:
                raise OSError

        for component, expected_identity in inspected.components:
            if _path_identity(_lstat(component)) != expected_identity:
                raise OSError
    except (AttributeError, OSError, TypeError, ValueError):
        failed = True

    if failed:
        _fail(category="path", stage="policy_read", code="AI_POLICY_READ_INVALID")
    return raw


def _draft202012_schema_validator(
    instance: JsonValue,
    schema: Mapping[str, JsonValue],
) -> bool:
    validator = Draft202012Validator(schema)
    return next(validator.iter_errors(instance), None) is None


def _required_mapping(
    value: FrozenJsonValue | None,
) -> Mapping[str, FrozenJsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError
    return value


def _rate_limit_tuple(value: str) -> tuple[int, int, int, int]:
    match = _RATE_LIMIT_TEXT.fullmatch(value)
    if match is None:
        raise ValueError
    return (
        int(match.group("concurrency")),
        int(match.group("rpm")),
        int(match.group("tpm")),
        int(match.group("burst")),
    )


def _cross_bind_settings(settings: Settings, policy: Mapping[str, FrozenJsonValue]) -> None:
    try:
        profiles = _required_mapping(policy.get("profiles"))
        operations = _required_mapping(policy.get("operations"))
        retry = _required_mapping(policy.get("retry"))
        breaker = _required_mapping(policy.get("breaker"))
        rate_limits = _required_mapping(policy.get("rate_limits"))
        outbound = _required_mapping(policy.get("outbound_limits"))
        extraction = _required_mapping(profiles.get("llm_extraction_primary"))
        generation = _required_mapping(profiles.get("llm_generation_primary"))
        fallback = _required_mapping(profiles.get("llm_fallback"))
        embedding = _required_mapping(profiles.get("embedding_primary"))

        operation_by_id = {
            operation_id: _required_mapping(operations.get(operation_id))
            for operation_id in (
                "contract_field_extraction",
                "invoice_field_extraction",
                "risk_explanation",
                "rag_answer",
                "report_draft",
                "embedding",
            )
        }
        llm_operation_ids = (
            "contract_field_extraction",
            "invoice_field_extraction",
            "risk_explanation",
            "rag_answer",
            "report_draft",
        )
        generation_operation_ids = llm_operation_ids[:-1]
        report = operation_by_id["report_draft"]

        rate_setting_by_pool = {
            "rag": settings.ai_rag_limits,
            "async_generation": settings.ai_async_generation_limits,
            "embedding": settings.ai_embedding_limits,
        }
        expected_deadlines = {
            "contract_field_extraction": settings.ai_contract_extraction_deadline_seconds,
            "invoice_field_extraction": settings.ai_invoice_extraction_deadline_seconds,
            "risk_explanation": settings.ai_risk_explanation_deadline_seconds,
            "rag_answer": settings.ai_rag_answer_deadline_seconds,
            "report_draft": settings.ai_report_draft_deadline_seconds,
            "embedding": settings.ai_embedding_deadline_seconds,
        }

        matches = (
            type(settings.ai_policy_version) is int
            and settings.ai_policy_version == policy.get("policy_version") == 1
            and type(settings.ai_provider_policy_schema_version) is int
            and settings.ai_provider_policy_schema_version == 1
            and settings.ai_provider_calls_enabled is policy.get("provider_calls_enabled") is False
            and settings.llm_base_url == extraction.get("base_url")
            and settings.llm_extraction_model == extraction.get("model_id")
            and settings.llm_generation_model == generation.get("model_id")
            and settings.llm_fallback_model == fallback.get("model_id")
            and settings.embedding_base_url == embedding.get("base_url")
            and settings.embedding_model == embedding.get("model_id")
            and settings.qdrant_vector_size
            == settings.embedding_vector_size
            == embedding.get("embedding_dimension")
            and all(
                operation.get("connect_timeout_seconds") == settings.llm_connect_timeout_seconds
                for operation in operation_by_id.values()
            )
            and all(
                operation_by_id[operation_id].get("max_attempts")
                == settings.llm_max_attempts_per_generation
                for operation_id in generation_operation_ids
            )
            and all(
                operation_by_id[operation_id].get("max_same_target_attempts")
                == settings.llm_max_same_target_attempts
                for operation_id in llm_operation_ids
            )
            and all(
                operation_by_id[operation_id].get("max_provider_attempts_per_business_operation")
                == settings.ai_max_provider_attempts_per_operation
                for operation_id in llm_operation_ids
            )
            and all(
                operation_by_id[operation_id].get("max_model_repairs")
                == settings.ai_max_model_repairs
                for operation_id in llm_operation_ids
            )
            and report.get("report_use_fallback") is settings.llm_report_draft_use_fallback
            and report.get("max_attempts") == (3 if settings.llm_report_draft_use_fallback else 2)
            and all(
                operation_by_id[operation_id].get("deadline_seconds") == deadline
                for operation_id, deadline in expected_deadlines.items()
            )
            and retry.get("backoff_base_seconds") == settings.ai_retry_backoff_base_seconds
            and retry.get("backoff_multiplier") == settings.ai_retry_backoff_multiplier
            and retry.get("backoff_max_seconds") == settings.ai_retry_backoff_max_seconds
            and retry.get("jitter_ratio") == settings.ai_retry_jitter_ratio
            and breaker.get("failures") == settings.ai_breaker_failures
            and breaker.get("window_seconds") == settings.ai_breaker_window_seconds
            and breaker.get("open_seconds") == settings.ai_breaker_open_seconds
            and breaker.get("half_open_probes") == settings.ai_breaker_half_open_probes
            and all(
                _rate_limit_tuple(setting)
                == tuple(
                    _required_mapping(rate_limits.get(pool_id)).get(field_name)
                    for field_name in ("concurrency", "rpm", "tpm", "burst")
                )
                for pool_id, setting in rate_setting_by_pool.items()
            )
            and outbound.get("max_request_bytes") == settings.ai_max_request_bytes
            and outbound.get("max_response_header_bytes") == settings.ai_max_response_header_bytes
            and outbound.get("max_chat_decompressed_bytes")
            == settings.ai_max_chat_decompressed_bytes
            and outbound.get("max_embedding_decompressed_bytes")
            == settings.ai_max_embedding_decompressed_bytes
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        matches = False
    if not matches:
        _fail(
            category="binding",
            stage="settings_policy_binding",
            code="AI_POLICY_SETTINGS_MISMATCH",
        )


def load_validated_policy(settings: Settings) -> ValidatedPolicySnapshot:
    """加载批准的离线或本地真实 Provider Policy，并返回不可变 identity。"""

    settings = _revalidate_settings(settings)
    if settings.app_env is not AppEnvironment.LOCAL and settings.app_env is not AppEnvironment.TEST:
        _fail(
            category="environment",
            stage="environment_authorization",
            code="AI_POLICY_ENVIRONMENT_NOT_AUTHORIZED",
        )

    path = _parse_policy_path(settings.ai_policy_file)
    _validate_drive_root(path)
    policy_resources = _load_package_resources()
    inspected = _inspect_components(path)
    raw_policy = _read_external_policy(inspected)
    raw_sha256 = hashlib.sha256(raw_policy).hexdigest()

    if settings.ai_provider_calls_enabled:
        if not validate_live_policy_bytes(raw_policy):
            _fail(
                category="validation",
                stage="approval_identity_pin",
                code="AI_POLICY_IDENTITY_NOT_APPROVED",
            )
        if (
            settings.llm_base_url != LIVE_LLM_POLICY.base_url
            or settings.llm_extraction_model != LIVE_LLM_POLICY.model_id
            or settings.llm_generation_model != LIVE_LLM_POLICY.model_id
            or settings.llm_fallback_model not in {None, LIVE_LLM_POLICY.model_id}
            or settings.embedding_base_url != LIVE_EMBEDDING_POLICY.base_url
            or settings.embedding_api_key is None
            or settings.embedding_model != LIVE_EMBEDDING_POLICY.model_id
            or settings.embedding_vector_size != LIVE_EMBEDDING_POLICY.embedding_dimension
            or settings.qdrant_vector_size != LIVE_EMBEDDING_POLICY.embedding_dimension
            or settings.embedding_batch_size != LIVE_EMBEDDING_POLICY.operation.max_batch_size
            or settings.ai_embedding_deadline_seconds
            != LIVE_EMBEDDING_POLICY.operation.deadline_seconds
            or settings.ai_max_request_bytes != LIVE_EMBEDDING_POLICY.max_request_bytes
            or settings.ai_max_response_header_bytes
            != LIVE_EMBEDDING_POLICY.max_response_header_bytes
            or settings.ai_max_embedding_decompressed_bytes
            != LIVE_EMBEDDING_POLICY.max_response_body_bytes
        ):
            _fail(
                category="binding",
                stage="settings_policy_binding",
                code="AI_POLICY_SETTINGS_MISMATCH",
            )
        return ValidatedPolicySnapshot(
            policy_version=2,
            policy_hash=LIVE_POLICY_HASH,
            raw_sha256=raw_sha256,
            provider_calls_enabled=True,
            runtime_profile_id=LIVE_POLICY_ID,
        )

    validation = None
    try:
        validation = validate_policy_full(
            raw_policy,
            validation_target="final_envelope",
            policy_schema_bytes=policy_resources.schema_bytes,
            registry_bytes=policy_resources.registry_bytes,
            schema_validator=_draft202012_schema_validator,
        )
    except CompanionArtifactError:
        pass
    if validation is None:
        _fail(
            category="validation",
            stage="schema",
            code="AI_POLICY_VALIDATOR_INTERNAL_FAILURE",
        )
    if not validation.accepted:
        if validation.rule_id is None or validation.safe_error_code is None:
            _fail(
                category="validation",
                stage="schema",
                code="AI_POLICY_VALIDATOR_INTERNAL_FAILURE",
            )
        if validation.stage == "complete":
            _fail(
                category="validation",
                stage="schema",
                code="AI_POLICY_VALIDATOR_INTERNAL_FAILURE",
            )
        _fail(
            category="validation",
            stage=validation.stage,
            code=validation.safe_error_code,
            rule_id=validation.rule_id,
        )

    policy = validation.validated_policy
    policy_hash = policy.get("policy_hash") if policy is not None else None
    if (
        len(raw_policy) != _APPROVED_POLICY_BYTES
        or raw_sha256 != _APPROVED_POLICY_RAW_SHA256
        or policy_hash != _APPROVED_POLICY_HASH
        or validation.pre_hash_sha256 != _APPROVED_POLICY_HASH
    ):
        _fail(
            category="validation",
            stage="approval_identity_pin",
            code="AI_POLICY_IDENTITY_NOT_APPROVED",
        )
    if policy is None:
        _fail(
            category="validation",
            stage="approval_identity_pin",
            code="AI_POLICY_IDENTITY_NOT_APPROVED",
        )

    _cross_bind_settings(settings, policy)
    return ValidatedPolicySnapshot(
        policy_version=1,
        policy_hash=_APPROVED_POLICY_HASH,
        raw_sha256=_APPROVED_POLICY_RAW_SHA256,
        provider_calls_enabled=False,
        runtime_profile_id=None,
    )
