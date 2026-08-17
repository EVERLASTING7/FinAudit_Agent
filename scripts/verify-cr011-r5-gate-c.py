from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import os
import platform
import re
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn


class GateError(RuntimeError):
    """Fixed, non-sensitive Gate C failure."""


class CacheBlocked(GateError):
    """The approved offline cache is absent or incomplete."""


_LOCK_IDENTITY = (
    641,
    "0fa55932218f0603089dd4182a7eb1751dc682dac3176dee8b142b1b565ebd8c",
)
_WHEELS = (
    (
        "attrs",
        "26.1.0",
        "attrs-26.1.0-py3-none-any.whl",
        67_548,
        "c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309",
    ),
    (
        "jsonschema-specifications",
        "2025.9.1",
        "jsonschema_specifications-2025.9.1-py3-none-any.whl",
        18_437,
        "98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe",
    ),
    (
        "jsonschema",
        "4.26.0",
        "jsonschema-4.26.0-py3-none-any.whl",
        90_630,
        "d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce",
    ),
    (
        "referencing",
        "0.37.0",
        "referencing-0.37.0-py3-none-any.whl",
        26_766,
        "381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231",
    ),
    (
        "rpds-py",
        "0.30.0",
        "rpds_py-0.30.0-cp310-cp310-win_amd64.whl",
        235_823,
        "1726859cd0de969f88dc8673bdd954185b9104e05806be64bcd87badbe313169",
    ),
    (
        "typing-extensions",
        "4.16.0",
        "typing_extensions-4.16.0-py3-none-any.whl",
        45_571,
        "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
    ),
)
_RESOURCES = (
    (
        "ai-policy-v1.positive.json",
        9_708,
        "da229cdb14bc40df8f6a0731498b0f947ab1f4f28b97a69f28e0f88af27119bb",
    ),
    (
        "ai-policy-v1.schema.json",
        28_811,
        "8d583164b46cb2cfa6315efa86491bd6cdc17c818be79dd9c7c274903c9399e3",
    ),
    (
        "ai-policy-v1.companion-validator.json",
        9_071,
        "10b9b67042060905ad1c7eb0dcd678724be3b01117eb3963332b51b9c626bed3",
    ),
    (
        "ip-deny-cidrs-v1.json",
        5_874,
        "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34",
    ),
)
_RESOURCE_RELATIVE = Path("app/ai/artifacts/cr011_v1")
_APPROVED_POLICY_HASH = "db946ad109baf5ec84455a2d0a09ce5e29602c0d9f9ce8404901f5c63683443d"
_APPROVED_RAW_SHA256 = "da229cdb14bc40df8f6a0731498b0f947ab1f4f28b97a69f28e0f88af27119bb"
_FINAL_PASS = "CR011_R5_GATE_C=PASS"
_FOCUSED_NODEIDS = (
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[unc]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[extended-path]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[named-pipe]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[nt-dos-device]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[nt-device]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[drive-relative]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[root-relative]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[forward-slash]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[ads]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[reserved-nul]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[reserved-trailing-space]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[reserved-com-superscript]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[reserved-lpt-superscript]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[dotdot]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[trailing-space]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[empty-component]",
    "tests/unit/test_ai_policy_loader.py::test_lexical_rejections_perform_no_downstream_io[nul-character]",
    "tests/unit/test_ai_policy_loader.py::test_drive_root_classifier_rejects_nonlocal_roots_without_downstream_attempts[drive-remote]",
    "tests/unit/test_ai_policy_loader.py::test_drive_root_classifier_rejects_nonlocal_roots_without_downstream_attempts[mup-redirector]",
    "tests/unit/test_ai_policy_loader.py::test_drive_root_classifier_rejects_nonlocal_roots_without_downstream_attempts[lanman-redirector]",
    "tests/unit/test_ai_policy_loader.py::test_drive_root_classifier_rejects_nonlocal_roots_without_downstream_attempts[subst-to-unc]",
    "tests/unit/test_ai_policy_loader.py::test_drive_root_classifier_rejects_nonlocal_roots_without_downstream_attempts[unknown-no-root]",
    "tests/unit/test_ai_policy_loader.py::test_drive_root_classifier_rejects_nonlocal_roots_without_downstream_attempts[non-fixed-removable]",
    "tests/unit/test_ai_policy_loader.py::test_drive_root_classifier_rejects_nonlocal_roots_without_downstream_attempts[multiple-device-targets]",
    "tests/unit/test_ai_policy_loader.py::test_unvalidated_settings_instances_fail_before_path_io[model-construct]",
    "tests/unit/test_ai_policy_loader.py::test_unvalidated_settings_instances_fail_before_path_io[model-copy-app-env]",
    "tests/unit/test_ai_policy_loader.py::test_unvalidated_settings_instances_fail_before_path_io[model-copy-bool-version]",
    "tests/unit/test_ai_policy_loader.py::test_mutated_validated_settings_fail_before_path_io",
    "tests/unit/test_ai_policy_loader.py::test_mutated_settings_cannot_be_re_registered_without_full_validation",
    "tests/unit/test_ai_policy_loader.py::test_loader_provenance_check_does_not_read_secret_values",
    "tests/unit/test_ai_policy_loader.py::test_current_workspace_drive_is_fixed_local_physical_volume",
    "tests/unit/test_ai_policy_loader.py::test_reparse_metadata_is_rejected_without_open_or_traversal[file-symlink]",
    "tests/unit/test_ai_policy_loader.py::test_reparse_metadata_is_rejected_without_open_or_traversal[parent-symlink]",
    "tests/unit/test_ai_policy_loader.py::test_reparse_metadata_is_rejected_without_open_or_traversal[junction]",
    "tests/unit/test_ai_policy_loader.py::test_reparse_metadata_is_rejected_without_open_or_traversal[junction-to-unc]",
    "tests/unit/test_ai_policy_loader.py::test_real_local_junction_is_rejected_by_nonfollowing_metadata_gate",
    "tests/unit/test_ai_policy_loader.py::test_preopen_target_handle_identity_drift_fails_closed",
    "tests/unit/test_ai_policy_loader.py::test_postread_component_identity_drift_fails_closed[parent]",
    "tests/unit/test_ai_policy_loader.py::test_postread_component_identity_drift_fails_closed[target]",
    "tests/unit/test_ai_policy_loader.py::test_oversize_metadata_is_rejected_before_open_or_read",
    "tests/unit/test_ai_policy_loader.py::test_policy_read_uses_exact_bound_and_rejects_oversize",
    "tests/unit/test_ai_policy_loader.py::test_runtime_package_resources_match_the_frozen_identity",
    "tests/unit/test_ai_policy_loader.py::test_package_resource_hash_drift_fails_closed",
    "tests/unit/test_ai_policy_loader.py::test_package_resource_set_rejects_case_variant_json_suffix",
    "tests/unit/test_ai_policy_loader.py::test_utf8_bom_is_rejected_at_pol_val_001",
    "tests/unit/test_ai_policy_loader.py::test_invalid_utf8_is_rejected_at_pol_val_001",
    "tests/unit/test_ai_policy_loader.py::test_nul_byte_is_rejected_at_pol_val_001",
    "tests/unit/test_ai_policy_loader.py::test_duplicate_json_key_is_rejected_at_pol_val_001",
    "tests/unit/test_ai_policy_loader.py::test_full_loader_preserves_frozen_first_failure_stage_oracle[pol-val-001]",
    "tests/unit/test_ai_policy_loader.py::test_full_loader_preserves_frozen_first_failure_stage_oracle[pol-val-002]",
    "tests/unit/test_ai_policy_loader.py::test_full_loader_preserves_frozen_first_failure_stage_oracle[pol-val-003]",
    "tests/unit/test_ai_policy_loader.py::test_full_loader_preserves_frozen_first_failure_stage_oracle[pol-val-004]",
    "tests/unit/test_ai_policy_loader.py::test_full_loader_preserves_frozen_first_failure_stage_oracle[pol-val-006]",
    "tests/unit/test_ai_policy_loader.py::test_full_loader_preserves_frozen_first_failure_stage_oracle[pol-val-007]",
    "tests/unit/test_ai_policy_loader.py::test_full_loader_preserves_frozen_first_failure_stage_oracle[pol-val-008]",
    "tests/unit/test_ai_policy_loader.py::test_full_loader_preserves_frozen_first_failure_stage_oracle[pol-val-009]",
    "tests/unit/test_ai_policy_loader.py::test_full_loader_preserves_frozen_first_failure_stage_oracle[pol-val-010]",
    "tests/unit/test_ai_policy_loader.py::test_full_loader_preserves_frozen_first_failure_stage_oracle[pol-val-011]",
    "tests/unit/test_ai_policy_loader.py::test_registry_binding_failure_is_pol_val_005_after_package_precondition",
    "tests/unit/test_ai_policy_loader.py::test_approved_policy_loads_through_the_real_local_file_gate",
    "tests/unit/test_ai_policy_loader.py::test_semantically_valid_unapproved_raw_identity_reaches_only_the_pin",
    "tests/unit/test_ai_policy_loader.py::test_settings_mirror_mismatch_fails_after_the_approved_pin",
    "tests/unit/test_ai_policy_loader.py::test_startup_error_never_discloses_path_or_policy_sentinel",
    "tests/unit/test_ai_policy_loader.py::test_filesystem_error_traceback_suppresses_sensitive_path",
    "tests/unit/test_ai_policy_loader.py::test_validation_error_redacts_policy_config_and_secret_sentinels",
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_exact(path: Path, expected_bytes: int, expected_sha256: str, code: str) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise GateError(code) from error
    if len(raw) != expected_bytes or _sha256(raw) != expected_sha256:
        raise GateError(code)
    return raw


def _require_platform() -> None:
    if (
        sys.implementation.name != "cpython"
        or sys.version_info[:2] != (3, 10)
        or platform.system() != "Windows"
        or platform.machine().casefold() != "amd64"
    ):
        raise GateError("PLATFORM_MISMATCH")


def _canonical_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def _verify_wheelhouse(wheelhouse: Path) -> None:
    if not wheelhouse.is_dir():
        raise CacheBlocked("OFFLINE_VERIFIED_CACHE_MISSING")
    expected_names = {wheel[2] for wheel in _WHEELS}
    try:
        entries = tuple(wheelhouse.iterdir())
    except OSError as error:
        raise CacheBlocked("OFFLINE_VERIFIED_CACHE_UNREADABLE") from error
    if {entry.name for entry in entries} != expected_names or any(
        not entry.is_file() for entry in entries
    ):
        raise CacheBlocked("OFFLINE_VERIFIED_CACHE_SET_MISMATCH")
    for _name, _version, filename, raw_bytes, sha256 in _WHEELS:
        wheel_path = wheelhouse / filename
        try:
            _read_exact(wheel_path, raw_bytes, sha256, "OFFLINE_VERIFIED_CACHE_IDENTITY")
            with zipfile.ZipFile(wheel_path) as archive:
                if archive.testzip() is not None:
                    raise GateError("OFFLINE_VERIFIED_CACHE_ZIP")
        except (OSError, zipfile.BadZipFile) as error:
            raise CacheBlocked("OFFLINE_VERIFIED_CACHE_ZIP") from error


def _preflight(args: argparse.Namespace) -> None:
    _require_platform()
    project_root = Path(args.project_root).resolve(strict=True)
    lock_path = project_root / "scripts/requirements-cr011-gate-b.txt"
    _read_exact(lock_path, *_LOCK_IDENTITY, "RUNTIME_LOCK_IDENTITY")
    _verify_wheelhouse(Path(args.wheelhouse).resolve())
    print("CR011_R5_PLATFORM=CPYTHON_3_10_WINDOWS_AMD64")
    print("CR011_R5_DEPENDENCY_MODE=OFFLINE_VERIFIED_CACHE")
    print("CR011_R5_DEPENDENCY_ACQUISITION=NOT_RUN")
    print("CR011_R5_ACQUISITION_REQUESTS=0")
    print(f"CR011_R5_RUNTIME_LOCK={_LOCK_IDENTITY[0]}/{_LOCK_IDENTITY[1]}")
    print("CR011_R5_RUNTIME_WHEELS=6/6")
    print("CR011_R5_GATE_C_PREFLIGHT=PASS")


def _directory_resource_bytes(root: Path, code: str) -> dict[str, bytes]:
    resource_root = root / _RESOURCE_RELATIVE
    if not resource_root.is_dir():
        raise GateError(code)
    try:
        json_entries = tuple(
            path for path in resource_root.iterdir() if path.suffix.casefold() == ".json"
        )
    except OSError as error:
        raise GateError(code) from error
    if {path.name for path in json_entries} != {item[0] for item in _RESOURCES}:
        raise GateError(code)
    result: dict[str, bytes] = {}
    for name, raw_bytes, sha256 in _RESOURCES:
        result[name] = _read_exact(resource_root / name, raw_bytes, sha256, code)
    return result


def _wheel_resource_bytes(wheel: Path) -> tuple[dict[str, bytes], str]:
    prefix = _RESOURCE_RELATIVE.as_posix() + "/"
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = tuple(
                name
                for name in archive.namelist()
                if name.startswith(prefix) and name.casefold().endswith(".json")
            )
            expected = {prefix + item[0] for item in _RESOURCES}
            if set(names) != expected or len(names) != len(expected):
                raise GateError("WHEEL_RESOURCE_SET")
            result = {name.removeprefix(prefix): archive.read(name) for name in names}
            metadata_names = tuple(
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            )
            if len(metadata_names) != 1:
                raise GateError("APP_WHEEL_METADATA")
            metadata_text = archive.read(metadata_names[0]).decode("utf-8", errors="strict")
    except (OSError, UnicodeError, zipfile.BadZipFile) as error:
        raise GateError("APP_WHEEL_READ") from error
    for name, raw_bytes, sha256 in _RESOURCES:
        raw = result.get(name)
        if raw is None or len(raw) != raw_bytes or _sha256(raw) != sha256:
            raise GateError("WHEEL_RESOURCE_IDENTITY")
    if not re.search(r"(?mi)^Requires-Dist:\s*jsonschema\s*==\s*4\.26\.0\s*$", metadata_text):
        raise GateError("APP_WHEEL_RUNTIME_DEPENDENCY")
    return result, metadata_text


def _resource_set_selftest(args: argparse.Namespace) -> None:
    source_root = Path(args.source_root).resolve(strict=True)
    resources = _directory_resource_bytes(source_root, "RESOURCE_SELFTEST_SOURCE_BASELINE")
    negatives = 0
    with tempfile.TemporaryDirectory(prefix="finaudit-cr011-r5-resource-set-") as temporary:
        temporary_root = Path(temporary)
        directory_root = temporary_root / "source"
        directory_resources = directory_root / _RESOURCE_RELATIVE
        directory_resources.mkdir(parents=True)
        for name, raw in resources.items():
            (directory_resources / name).write_bytes(raw)
        (directory_resources / "forged-extra.JSON").write_bytes(b"{}\n")
        try:
            _directory_resource_bytes(directory_root, "RESOURCE_SET_CASEFOLD")
        except GateError as error:
            if str(error) != "RESOURCE_SET_CASEFOLD":
                raise
            negatives += 1
        else:
            raise GateError("RESOURCE_SET_CASEFOLD_SOURCE_BYPASS")

        wheel_path = temporary_root / "forged-extra-json.whl"
        prefix = _RESOURCE_RELATIVE.as_posix() + "/"
        with zipfile.ZipFile(wheel_path, "w") as archive:
            for name, raw in resources.items():
                archive.writestr(prefix + name, raw)
            archive.writestr(prefix + "forged-extra.JSON", b"{}\n")
            archive.writestr(
                "finaudit_backend-0.1.0.dist-info/METADATA",
                "Metadata-Version: 2.4\n"
                "Name: finaudit-backend\n"
                "Version: 0.1.0\n"
                "Requires-Dist: jsonschema==4.26.0\n",
            )
        try:
            _wheel_resource_bytes(wheel_path)
        except GateError as error:
            if str(error) != "WHEEL_RESOURCE_SET":
                raise
            negatives += 1
        else:
            raise GateError("RESOURCE_SET_CASEFOLD_WHEEL_BYPASS")
    if negatives != 2:
        raise GateError("RESOURCE_SET_CASEFOLD_COVERAGE")
    print("CR011_R5_RESOURCE_SET_CASEFOLD_NEGATIVES=2/2")


def _distributions_at(site: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        distributions = importlib.metadata.distributions(path=[str(site)])
        for distribution in distributions:
            name = distribution.metadata.get("Name")
            if not name or not distribution.version:
                raise GateError("DISTRIBUTION_METADATA")
            normalized = _canonical_distribution(name)
            if normalized in result:
                raise GateError("DISTRIBUTION_DUPLICATE")
            result[normalized] = distribution.version
    except (OSError, UnicodeError) as error:
        raise GateError("DISTRIBUTION_METADATA") from error
    return result


def _verify_artifacts(args: argparse.Namespace) -> None:
    _require_platform()
    source_root = Path(args.source_root).resolve(strict=True)
    app_site = Path(args.app_site).resolve(strict=True)
    runtime_site = Path(args.runtime_site).resolve(strict=True)
    app_wheel = Path(args.app_wheel).resolve(strict=True)

    expected_distributions = {
        _canonical_distribution(name): version for name, version, *_rest in _WHEELS
    }
    if _distributions_at(runtime_site) != expected_distributions:
        raise GateError("RUNTIME_DISTRIBUTION_CLOSURE")
    if _distributions_at(app_site) != {"finaudit-backend": "0.1.0"}:
        raise GateError("APP_WHEEL_INSTALL_CLOSURE")

    source_resources = _directory_resource_bytes(source_root, "SOURCE_RESOURCE_IDENTITY")
    wheel_resources, _metadata = _wheel_resource_bytes(app_wheel)
    installed_resources = _directory_resource_bytes(app_site, "INSTALLED_RESOURCE_IDENTITY")
    if source_resources != wheel_resources or source_resources != installed_resources:
        raise GateError("RESOURCE_FORM_DRIFT")

    sys.path.insert(0, str(runtime_site))
    try:
        jsonschema = importlib.import_module("jsonschema")
        validator = getattr(jsonschema, "Draft202012Validator", None)
        if validator is None or "2020-12" not in validator.META_SCHEMA.get("$schema", ""):
            raise GateError("RUNTIME_SCHEMA_ENGINE")
    finally:
        sys.path.pop(0)

    wheel_raw = app_wheel.read_bytes()
    print("CR011_R5_RUNTIME_DISTRIBUTIONS=6/6")
    print("CR011_R5_RUNTIME_SCHEMA_ENGINE=jsonschema@4.26.0-draft202012")
    print("CR011_R5_PACKAGE_RESOURCES_SOURCE=4/4")
    print("CR011_R5_PACKAGE_RESOURCES_WHEEL=4/4")
    print("CR011_R5_PACKAGE_RESOURCES_INSTALLED=4/4")
    print("CR011_R5_PACKAGE_RESOURCE_EXTRA_JSON=0")
    print(f"CR011_R5_APP_WHEEL_IDENTITY={app_wheel.name}/{len(wheel_raw)}/{_sha256(wheel_raw)}")
    print("CR011_R5_GATE_C_ARTIFACTS=PASS")


class _ZeroSocketViolation(RuntimeError):
    pass


class _ZeroSocketGuard:
    def __init__(self) -> None:
        import _socket
        import socket

        self._low_level_socket = _socket.socket
        self._socket_module = socket
        self._original_socket = socket.socket
        self._original_socket_type = socket.SocketType
        self.socket_attempts = 0
        self.dns_attempts = 0
        self.local_hostname_reads = 0
        self.last_attempt = "unknown"

    def _deny(self, name: str) -> NoReturn:
        self.last_attempt = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
        if any(token in name for token in ("addrinfo", "host", "nameinfo")):
            self.dns_attempts += 1
        else:
            self.socket_attempts += 1
        raise _ZeroSocketViolation("CR-011-R5 guarded CPython socket or DNS operation")

    def _blocked(self, name: str) -> Callable[..., NoReturn]:
        def blocked(*args: object, **kwargs: object) -> NoReturn:
            del args, kwargs
            self._deny(name)

        return blocked

    def install(self) -> None:
        guard = self
        original_socket = self._original_socket

        class BlockedSocket(original_socket):  # type: ignore[misc, valid-type]
            def __new__(cls, *args: object, **kwargs: object) -> BlockedSocket:
                del cls, args, kwargs
                guard._deny("socket.socket")

        def audit_hook(event: str, audit_args: tuple[object, ...]) -> None:
            del audit_args
            # Reading the local machine name is neither a socket creation nor DNS/peer I/O.
            if event == "socket.gethostname":
                guard.local_hostname_reads += 1
            elif event.startswith("socket."):
                guard._deny(f"audit:{event}")

        sys.addaudithook(audit_hook)
        self._socket_module.socket = BlockedSocket
        self._socket_module.SocketType = BlockedSocket
        for name in (
            "create_connection",
            "create_server",
            "fromfd",
            "fromshare",
            "getaddrinfo",
            "gethostbyaddr",
            "gethostbyname",
            "gethostbyname_ex",
            "getnameinfo",
            "socketpair",
        ):
            if hasattr(self._socket_module, name):
                setattr(self._socket_module, name, self._blocked(f"socket.{name}"))

    def selftest(self) -> None:
        import _socket

        probes: tuple[Callable[[], object], ...] = (
            lambda: self._socket_module.socket(),
            lambda: self._socket_module.SocketType(),
            lambda: self._original_socket(),
            lambda: self._original_socket_type(),
            lambda: _socket.socket(),
            lambda: self._socket_module.create_connection(("127.0.0.1", 9)),
            lambda: self._socket_module.getaddrinfo("localhost", 80),
            lambda: self._socket_module.gethostbyname("localhost"),
            lambda: self._socket_module.socketpair(),
        )
        for probe in probes:
            before = self.socket_attempts + self.dns_attempts
            try:
                probe()
            except _ZeroSocketViolation:
                pass
            else:
                raise GateError("ZERO_SOCKET_GUARD_BYPASS")
            if self.socket_attempts + self.dns_attempts != before + 1:
                raise GateError("ZERO_SOCKET_GUARD_COUNTER")
        if self.socket_attempts + self.dns_attempts != len(probes):
            raise GateError("ZERO_SOCKET_GUARD_COVERAGE")


def _guard_selftest(_args: argparse.Namespace) -> None:
    guard = _ZeroSocketGuard()
    guard.install()
    guard.selftest()
    print("CR011_R5_STARTUP_GUARD_SCOPE=CPYTHON_SOCKET_DNS_API_ONLY")
    print("CR011_R5_NATIVE_WINSOCK_NAMED_PIPE=NOT_CLAIMED")
    print("CR011_R5_CPYTHON_SOCKET_DNS_GUARD_SELFTEST=PASS")
    print(f"CR011_R5_CPYTHON_SOCKET_DNS_GUARD_DENIALS={guard.socket_attempts + guard.dns_attempts}")


def _clean_environment() -> dict[str, str]:
    allowed = {
        "comspec",
        "path",
        "pathext",
        "systemdrive",
        "systemroot",
        "temp",
        "tmp",
        "windir",
    }
    cleaned = {name: value for name, value in os.environ.items() if name.casefold() in allowed}
    cleaned.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
        }
    )
    return cleaned


def _install_synthetic_environment(environment: str, policy_file: Path) -> None:
    cleaned = _clean_environment()
    os.environ.clear()
    os.environ.update(cleaned)
    values = {
        "APP_ENV": environment,
        "AI_POLICY_FILE": str(policy_file),
        "SECRET_KEY": "test-signing-key-with-at-least-32-characters",
        "DATABASE_URL": "postgresql+psycopg://test:test-password@postgresql:5432/test",
        "REDIS_URL": "redis://:test-password@redis:6379/0",
        "CELERY_BROKER_URL": "redis://:test-password@redis:6379/0",
        "CELERY_RESULT_BACKEND": "redis://:test-password@redis:6379/1",
        "MINIO_ACCESS_KEY": "test-minio-access",
        "MINIO_SECRET_KEY": "test-minio-secret",
        "QDRANT_COLLECTION": "finaudit_policy_chunks_test_e1024_v1",
        "LLM_BASE_URL": "http://synthetic-extraction:8000/v1",
        "LLM_API_KEY": "test-llm-key",
        "LLM_EXTRACTION_MODEL": "synthetic-extraction-model",
        "LLM_GENERATION_MODEL": "synthetic-generation-model",
        "LLM_FALLBACK_MODEL": "synthetic-fallback-model",
        "EMBEDDING_BASE_URL": "http://synthetic-embedding:8003/v1",
        "EMBEDDING_API_KEY": "test-embedding-key",
        "EMBEDDING_MODEL": "synthetic-embedding-model",
        "METRICS_INTERNAL_TOKEN": "test-metrics-token",
        "AI_POLICY_VERSION": "1",
        "AI_PROVIDER_POLICY_SCHEMA_VERSION": "1",
        "AI_PROVIDER_CALLS_ENABLED": "false",
    }
    os.environ.update(values)


def _startup_probe(args: argparse.Namespace) -> None:
    guard = _ZeroSocketGuard()
    guard.install()
    _install_synthetic_environment(args.environment, Path(args.policy_file).resolve(strict=True))
    app_site = Path(args.app_site).resolve(strict=True)
    runtime_site = Path(args.runtime_site).resolve(strict=True)
    sys.path[:0] = [str(runtime_site), str(app_site)]
    target = args.target
    framework = "fastapi" if target.startswith("fastapi") else "celery"
    outcome = "ADOPTED"
    try:
        if target == "fastapi-factory":
            application = importlib.import_module("app.bootstrap").create_app()
            snapshot = application.state.ai_policy_snapshot
        elif target == "fastapi-module":
            application = importlib.import_module("app.main").app
            snapshot = application.state.ai_policy_snapshot
        elif target == "worker-factory":
            application = importlib.import_module("app.workers.bootstrap").create_celery_app()
            snapshot = application._finaudit_policy_snapshot
        elif target == "worker-module":
            application = importlib.import_module("app.workers.celery_app").app
            snapshot = application._finaudit_policy_snapshot
        else:
            raise GateError("STARTUP_TARGET")
        if args.environment == "prod":
            raise GateError("PRODUCTION_EXPOSURE")
        if (
            snapshot.policy_version != 1
            or snapshot.policy_hash != _APPROVED_POLICY_HASH
            or snapshot.raw_sha256 != _APPROVED_RAW_SHA256
        ):
            raise GateError("STARTUP_SNAPSHOT_IDENTITY")
    except Exception as error:
        if isinstance(error, _ZeroSocketViolation):
            raise GateError(f"STARTUP_NETWORK_ATTEMPT_{guard.last_attempt.upper()}") from error
        if args.environment != "prod":
            if type(error).__name__ == "PolicyStartupError":
                stage = getattr(error, "stage", "")
                code = getattr(error, "code", "")
                if re.fullmatch(r"[a-z_]+", stage) and re.fullmatch(r"[A-Z0-9_]+", code):
                    raise GateError(f"STARTUP_POLICY_{stage}_{code}") from error
            if type(error).__name__ == "ValidationError" and hasattr(error, "errors"):
                details = error.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
                if details:
                    location = "_".join(str(item) for item in details[0].get("loc", ()))
                    error_kind = str(details[0].get("type", "invalid"))
                    safe_detail = re.sub(r"[^A-Za-z0-9]+", "_", f"{location}_{error_kind}").strip(
                        "_"
                    )
                    raise GateError(
                        f"STARTUP_APPLICATION_FAILURE_VALIDATIONERROR_{safe_detail.upper()}"
                    ) from error
            error_type = re.sub(r"[^A-Za-z0-9]+", "_", type(error).__name__).upper()
            raise GateError(f"STARTUP_APPLICATION_FAILURE_{error_type}") from error
        if (
            type(error).__name__ != "PolicyStartupError"
            or getattr(error, "category", None) != "environment"
            or getattr(error, "code", None) != "AI_POLICY_ENVIRONMENT_NOT_AUTHORIZED"
            or framework in sys.modules
        ):
            raise GateError("PRODUCTION_PRE_EXPOSURE_REJECTION") from error
        outcome = "REJECTED_PRE_EXPOSURE"
    if guard.socket_attempts != 0 or guard.dns_attempts != 0 or guard.local_hostname_reads != 1:
        raise GateError("STARTUP_NETWORK_ATTEMPT")
    print(f"CR011_R5_STARTUP_PROBE={args.form}:{args.environment}:{target}:{outcome}")
    print("CR011_R5_STARTUP_GUARD_SCOPE=CPYTHON_SOCKET_DNS_API_ONLY")
    print("CR011_R5_STARTUP_GUARDED_SOCKET_ATTEMPTS=0")
    print("CR011_R5_STARTUP_GUARDED_DNS_ATTEMPTS=0")
    print("CR011_R5_STARTUP_LOCAL_HOSTNAME_READS=1")
    print("CR011_R5_NATIVE_WINSOCK_NAMED_PIPE=NOT_CLAIMED")


def _run_child(args: argparse.Namespace) -> None:
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        raise GateError("CHILD_COMMAND_MISSING")
    try:
        completed = subprocess.run(
            command,
            cwd=args.cwd,
            env=_clean_environment(),
            capture_output=True,
            check=False,
            timeout=args.timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GateError("CHILD_EXECUTION") from error
    if completed.returncode != 0:
        raise GateError("CHILD_NONZERO")
    try:
        stdout = completed.stdout.decode("utf-8", errors="strict")
        stderr = completed.stderr.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise GateError("CHILD_ENCODING") from error
    if stderr or "\x00" in stdout or stdout.startswith("\ufeff"):
        raise GateError("CHILD_OUTPUT_INVALID")
    lines = stdout.splitlines()
    if _FINAL_PASS in lines:
        raise GateError("CHILD_FORGED_FINAL_PASS")
    expected = list(args.expected)
    if args.exact:
        if lines != expected:
            raise GateError("CHILD_EXACT_MARKERS")
    else:
        indices: list[int] = []
        for marker in expected:
            matches = [index for index, line in enumerate(lines) if line == marker]
            if len(matches) != 1:
                raise GateError("CHILD_REQUIRED_MARKER")
            indices.append(matches[0])
        if indices != sorted(indices) or len(indices) != len(set(indices)):
            raise GateError("CHILD_MARKER_ORDER")
    for line in lines:
        print(line)


def _focused_manifest_raw() -> bytes:
    if not _FOCUSED_NODEIDS or len(set(_FOCUSED_NODEIDS)) != len(_FOCUSED_NODEIDS):
        raise GateError("FOCUSED_MANIFEST_INVALID")
    return ("\n".join(_FOCUSED_NODEIDS) + "\n").encode("utf-8")


def _focused_manifest(_args: argparse.Namespace) -> None:
    raw = _focused_manifest_raw()
    print(f"CR011_R5_FOCUSED_MANIFEST_COUNT={len(_FOCUSED_NODEIDS)}")
    print(f"CR011_R5_FOCUSED_MANIFEST_SHA256={_sha256(raw)}")
    for nodeid in _FOCUSED_NODEIDS:
        print(f"CR011_R5_FOCUSED_NODEID={nodeid}")


def _read_focused_output(path_value: str, code: str) -> list[str]:
    path = Path(path_value).resolve(strict=True)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise GateError(code) from error
    if (
        not raw
        or len(raw) > 2_000_000
        or not raw.endswith(b"\n")
        or b"\r" in raw
        or b"\x00" in raw
        or raw.startswith(b"\xef\xbb\xbf")
    ):
        raise GateError(code)
    try:
        return raw.decode("utf-8", errors="strict").splitlines()
    except UnicodeError as error:
        raise GateError(code) from error


def _verify_focused_evidence(args: argparse.Namespace) -> None:
    expected = list(_FOCUSED_NODEIDS)
    manifest_raw = _focused_manifest_raw()
    collected = [
        line
        for line in _read_focused_output(args.collected_output, "FOCUSED_COLLECT_OUTPUT")
        if line
    ]
    if len(collected) != len(expected) + 1 or collected[:-1] != expected:
        raise GateError("FOCUSED_COLLECT_NODEIDS")
    collected_summary = re.fullmatch(
        rf"{len(expected)} tests? collected in [0-9]+(?:\.[0-9]+)?s", collected[-1]
    )
    if collected_summary is None:
        raise GateError("FOCUSED_COLLECT_COUNT")

    result = [
        line for line in _read_focused_output(args.result_output, "FOCUSED_RESULT_OUTPUT") if line
    ]
    if (
        len(result) < 2
        or re.fullmatch(rf"{len(expected)} passed in [0-9]+(?:\.[0-9]+)?s", result[-1]) is None
    ):
        raise GateError("FOCUSED_RESULT_COUNT")
    progress_count = 0
    for line in result[:-1]:
        progress = re.sub(r"\s+\[\s*[0-9]+%\]$", "", line)
        if re.fullmatch(r"\.+", progress) is None:
            raise GateError("FOCUSED_RESULT_OUTPUT")
        progress_count += len(progress)
    if progress_count != len(expected):
        raise GateError("FOCUSED_RESULT_PROGRESS")
    print(f"CR011_R5_FOCUSED_MANIFEST={len(expected)}/{len(expected)}")
    print(f"CR011_R5_FOCUSED_MANIFEST_SHA256={_sha256(manifest_raw)}")
    print(f"CR011_R5_FOCUSED_TESTS={len(expected)}_PASSED")
    print("CR011_R5_FOCUSED_SKIP_XFAIL_XPASS=0")
    print("CR011_R5_FOCUSED_COVERAGE=PASS")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--project-root", required=True)
    preflight.add_argument("--wheelhouse", required=True)
    preflight.set_defaults(run=_preflight)

    artifacts = subparsers.add_parser("verify-artifacts")
    artifacts.add_argument("--source-root", required=True)
    artifacts.add_argument("--app-site", required=True)
    artifacts.add_argument("--runtime-site", required=True)
    artifacts.add_argument("--app-wheel", required=True)
    artifacts.set_defaults(run=_verify_artifacts)

    resource_set = subparsers.add_parser("resource-set-selftest")
    resource_set.add_argument("--source-root", required=True)
    resource_set.set_defaults(run=_resource_set_selftest)

    guard = subparsers.add_parser("guard-selftest")
    guard.set_defaults(run=_guard_selftest)

    startup = subparsers.add_parser("startup-probe")
    startup.add_argument("--app-site", required=True)
    startup.add_argument("--runtime-site", required=True)
    startup.add_argument("--policy-file", required=True)
    startup.add_argument("--form", choices=("source", "installed"), required=True)
    startup.add_argument("--environment", choices=("local", "test", "prod"), required=True)
    startup.add_argument(
        "--target",
        choices=(
            "fastapi-factory",
            "fastapi-module",
            "worker-factory",
            "worker-module",
        ),
        required=True,
    )
    startup.set_defaults(run=_startup_probe)

    child = subparsers.add_parser("run-child")
    child.add_argument("--cwd", required=True)
    child.add_argument("--timeout", type=int, default=600)
    child.add_argument("--exact", action="store_true")
    child.add_argument("--expected", action="append", default=[])
    child.add_argument("command", nargs=argparse.REMAINDER)
    child.set_defaults(run=_run_child)

    focused_manifest = subparsers.add_parser("focused-manifest")
    focused_manifest.set_defaults(run=_focused_manifest)

    focused_evidence = subparsers.add_parser("verify-focused-evidence")
    focused_evidence.add_argument("--collected-output", required=True)
    focused_evidence.add_argument("--result-output", required=True)
    focused_evidence.set_defaults(run=_verify_focused_evidence)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        args.run(args)
    except CacheBlocked as error:
        print(f"CR011_R5_GATE_C_CORE=BLOCKED_{error}", file=sys.stderr)
        return 4
    except GateError as error:
        print(f"CR011_R5_GATE_C_CORE=FAIL_{error}", file=sys.stderr)
        return 2
    except Exception:
        print("CR011_R5_GATE_C_CORE=FAIL_UNEXPECTED", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
