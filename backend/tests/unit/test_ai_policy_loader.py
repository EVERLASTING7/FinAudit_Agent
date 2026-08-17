from __future__ import annotations

import json
import os
import stat
import subprocess
from dataclasses import FrozenInstanceError, replace
from importlib import resources
from pathlib import Path
from traceback import format_exception
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from app.ai import policy_companion, policy_loader
from app.ai.policy_loader import PolicyStartupError, load_validated_policy
from app.core.config import AppEnvironment, Settings
from tests.unit.test_ai_policy_companion import _case
from tests.unit.test_ai_policy_gate_b_python import _ordered_source_bytes

_POLICY_RESOURCE_PACKAGE = "app.ai.artifacts.cr011_v1"
_APPROVED_RAW_SHA256 = "da229cdb14bc40df8f6a0731498b0f947ab1f4f28b97a69f28e0f88af27119bb"
_APPROVED_POLICY_HASH = "db946ad109baf5ec84455a2d0a09ce5e29602c0d9f9ce8404901f5c63683443d"

_FROZEN_FIRST_FAILURE_CASES = (
    (
        "NEG-POL-018-duplicate-source-key",
        "raw_parse",
        "POL-VAL-001",
        "AI_POLICY_SOURCE_INVALID",
    ),
    (
        "NEG-POL-004-boolean-integer",
        "source_number",
        "POL-VAL-002",
        "AI_POLICY_INTEGER_TOKEN_INVALID",
    ),
    (
        "NEG-POL-001-missing-hash",
        "envelope_context",
        "POL-VAL-003",
        "AI_POLICY_ENVELOPE_INVALID",
    ),
    (
        "NEG-POL-005-unknown-field",
        "schema",
        "POL-VAL-004",
        "AI_POLICY_SCHEMA_INVALID",
    ),
    (
        "NEG-POL-003-tampered-content",
        "hash",
        "POL-VAL-006",
        "AI_POLICY_HASH_MISMATCH",
    ),
    (
        "NEG-POL-015-unsorted-array",
        "cross_field",
        "POL-VAL-007",
        "AI_POLICY_ARRAY_NOT_CANONICAL",
    ),
    (
        "NEG-POL-007-dangling-primary-profile",
        "cross_field",
        "POL-VAL-008",
        "AI_POLICY_ROUTE_GRAPH_INVALID",
    ),
    (
        "NEG-POL-012-hostname-mismatch",
        "cross_field",
        "POL-VAL-009",
        "AI_POLICY_HOST_INVALID",
    ),
    (
        "NEG-POL-013-noncanonical-cidr",
        "network_registry",
        "POL-VAL-010",
        "AI_POLICY_CIDR_NOT_CANONICAL",
    ),
    (
        "NEG-POL-014-denied-cidr-overlap",
        "network_registry",
        "POL-VAL-011",
        "AI_POLICY_NETWORK_SCOPE_INVALID",
    ),
)


def _approved_policy_bytes() -> bytes:
    return (
        resources.files(_POLICY_RESOURCE_PACKAGE)
        .joinpath("ai-policy-v1.positive.json")
        .read_bytes()
    )


def _write_policy(tmp_path: Path, raw: bytes | None = None) -> Path:
    policy_file = tmp_path / "ai-policy-v1.json"
    policy_file.write_bytes(_approved_policy_bytes() if raw is None else raw)
    return policy_file


def _load_error(tmp_path: Path, raw: bytes) -> PolicyStartupError:
    with pytest.raises(PolicyStartupError) as exc_info:
        load_validated_policy(_settings(str(_write_policy(tmp_path, raw))))
    return exc_info.value


def _synthetic_stat(
    *,
    mode: int,
    inode: int,
    size: int = 0,
    attributes: int = 0,
    reparse_tag: int = 0,
    reparse_target: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        st_dev=1,
        st_ino=inode,
        st_mode=mode,
        st_size=size,
        st_file_attributes=attributes,
        st_reparse_tag=reparse_tag,
        test_only_reparse_target=reparse_target,
    )


def _settings(policy_file: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "ai_policy_file": policy_file,
        "secret_key": "test-signing-key-with-at-least-32-characters",
        "database_url": "postgresql+psycopg://test:test-password@postgresql:5432/test",
        "redis_url": "redis://:test-password@redis:6379/0",
        "celery_broker_url": "redis://:test-password@redis:6379/0",
        "celery_result_backend": "redis://:test-password@redis:6379/1",
        "minio_access_key": "test-minio-access",
        "minio_secret_key": "test-minio-secret",
        "qdrant_collection": "finaudit_policy_chunks_test_e1024_v1",
        "llm_base_url": "http://synthetic-extraction:8000/v1",
        "llm_api_key": "test-llm-key",
        "llm_extraction_model": "synthetic-extraction-model",
        "llm_generation_model": "synthetic-generation-model",
        "llm_fallback_model": "synthetic-fallback-model",
        "embedding_base_url": "http://synthetic-embedding:8003/v1",
        "embedding_api_key": "test-embedding-key",
        "embedding_model": "synthetic-embedding-model",
        "metrics_internal_token": "test-metrics-token",
    }
    return Settings(_env_file=None, **(values | overrides))


@pytest.mark.parametrize(
    "invalid_path",
    [
        r"\\server\share\policy.json",
        r"\\?\C:\policy.json",
        r"\\.\pipe\policy",
        r"\??\C:\policy.json",
        r"\Device\HarddiskVolume1\policy.json",
        r"C:policy.json",
        r"\policy.json",
        r"C:/policy.json",
        r"C:\policy.json:stream",
        r"C:\NUL.json",
        r"C:\COM1 .txt",
        "C:\\COM¹.txt",
        "C:\\LPT³",
        r"C:\folder\..\policy.json",
        "C:\\folder\\policy.json ",
        "C:\\folder\\\\policy.json",
        "C:\\folder\\\x00policy.json",
    ],
    ids=[
        "unc",
        "extended-path",
        "named-pipe",
        "nt-dos-device",
        "nt-device",
        "drive-relative",
        "root-relative",
        "forward-slash",
        "ads",
        "reserved-nul",
        "reserved-trailing-space",
        "reserved-com-superscript",
        "reserved-lpt-superscript",
        "dotdot",
        "trailing-space",
        "empty-component",
        "nul-character",
    ],
)
def test_lexical_rejections_perform_no_downstream_io(
    invalid_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def unexpected(name: str) -> None:
        calls.append(name)
        raise AssertionError(name)

    monkeypatch.setattr(policy_loader, "_query_drive_root", lambda _path: unexpected("drive"))
    monkeypatch.setattr(policy_loader, "_load_package_resources", lambda: unexpected("resource"))
    monkeypatch.setattr(policy_loader, "_inspect_components", lambda _path: unexpected("metadata"))
    monkeypatch.setattr(policy_loader, "_read_external_policy", lambda _path: unexpected("read"))
    monkeypatch.setattr(
        policy_loader,
        "validate_policy_full",
        lambda *_args, **_kwargs: unexpected("validation"),
    )

    with pytest.raises(PolicyStartupError) as exc_info:
        load_validated_policy(_settings(invalid_path))

    assert exc_info.value.stage == "path_lexical"
    assert exc_info.value.code == "AI_POLICY_PATH_INVALID"
    assert calls == []


@pytest.mark.parametrize(
    "drive_info",
    [
        policy_loader._DriveRootInfo(4, (r"\Device\Mup\server\share",)),
        policy_loader._DriveRootInfo(3, (r"\Device\Mup\server\share",)),
        policy_loader._DriveRootInfo(3, (r"\Device\LanmanRedirector\server\share",)),
        policy_loader._DriveRootInfo(3, (r"\??\UNC\server\share",)),
        policy_loader._DriveRootInfo(0, ()),
        policy_loader._DriveRootInfo(2, (r"\Device\HarddiskVolume99",)),
        policy_loader._DriveRootInfo(
            3,
            (r"\Device\HarddiskVolume1", r"\Device\Mup\server\share"),
        ),
    ],
    ids=[
        "drive-remote",
        "mup-redirector",
        "lanman-redirector",
        "subst-to-unc",
        "unknown-no-root",
        "non-fixed-removable",
        "multiple-device-targets",
    ],
)
def test_drive_root_classifier_rejects_nonlocal_roots_without_downstream_attempts(
    drive_info: policy_loader._DriveRootInfo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downstream_attempts: list[str] = []

    def unexpected(name: str) -> None:
        downstream_attempts.append(name)
        raise AssertionError(name)

    monkeypatch.setattr(policy_loader, "_query_drive_root", lambda _path: drive_info)
    monkeypatch.setattr(
        policy_loader,
        "_load_package_resources",
        lambda: unexpected("package_resource"),
    )
    monkeypatch.setattr(
        policy_loader,
        "_inspect_components",
        lambda _path: unexpected("component_metadata"),
    )
    monkeypatch.setattr(
        policy_loader,
        "_read_external_policy",
        lambda _path: unexpected("open_or_read"),
    )
    monkeypatch.setattr(
        policy_loader,
        "validate_policy_full",
        lambda *_args, **_kwargs: unexpected("validation"),
    )

    with pytest.raises(PolicyStartupError) as exc_info:
        load_validated_policy(_settings(r"D:\synthetic\policy.json"))

    assert exc_info.value.stage == "drive_root_locality"
    assert exc_info.value.code == "AI_POLICY_DRIVE_ROOT_NOT_LOCAL"
    assert downstream_attempts == []


@pytest.mark.parametrize(
    "forged_settings",
    [
        Settings.model_construct(
            app_env=AppEnvironment.TEST,
            ai_policy_file=r"D:\synthetic\policy.json",
        ),
        _settings(r"D:\synthetic\policy.json").model_copy(update={"app_env": "test"}),
        _settings(r"D:\synthetic\policy.json").model_copy(update={"ai_policy_version": True}),
    ],
    ids=["model-construct", "model-copy-app-env", "model-copy-bool-version"],
)
def test_unvalidated_settings_instances_fail_before_path_io(
    forged_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path_attempts = 0

    def unexpected_path(_value: str) -> policy_loader._LexicalPolicyPath:
        nonlocal path_attempts
        path_attempts += 1
        raise AssertionError("path gate must not run")

    monkeypatch.setattr(policy_loader, "_parse_policy_path", unexpected_path)

    with pytest.raises(PolicyStartupError) as exc_info:
        load_validated_policy(forged_settings)

    assert exc_info.value.category == "settings"
    assert exc_info.value.stage == "settings_validation"
    assert exc_info.value.code == "AI_SETTINGS_INVALID"
    assert path_attempts == 0


def test_mutated_validated_settings_fail_before_path_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(r"D:\synthetic\policy.json")
    settings.celery_task_time_limit_seconds = 1
    path_attempts = 0

    def unexpected_path(_value: str) -> policy_loader._LexicalPolicyPath:
        nonlocal path_attempts
        path_attempts += 1
        raise AssertionError("path gate must not run")

    monkeypatch.setattr(policy_loader, "_parse_policy_path", unexpected_path)

    with pytest.raises(PolicyStartupError) as exc_info:
        load_validated_policy(settings)

    assert exc_info.value.stage == "settings_validation"
    assert exc_info.value.code == "AI_SETTINGS_INVALID"
    assert path_attempts == 0


def test_mutated_settings_cannot_be_re_registered_without_full_validation() -> None:
    settings = _settings(r"D:\synthetic\policy.json")
    settings.db_pool_size = 0

    with pytest.raises(ValueError):
        Settings.model_validate(settings)


def test_loader_provenance_check_does_not_read_secret_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(str(_write_policy(tmp_path)))
    secret_reads = 0

    def forbidden_secret_read(_value: SecretStr) -> str:
        nonlocal secret_reads
        secret_reads += 1
        raise AssertionError("loader must not read secret values")

    monkeypatch.setattr(SecretStr, "get_secret_value", forbidden_secret_read)

    snapshot = load_validated_policy(settings)

    assert snapshot.policy_hash == _APPROVED_POLICY_HASH
    assert secret_reads == 0


def test_current_workspace_drive_is_fixed_local_physical_volume(tmp_path: Path) -> None:
    lexical_path = policy_loader._parse_policy_path(str(tmp_path / "policy.json"))

    policy_loader._validate_drive_root(lexical_path)


def test_posix_policy_path_uses_canonical_absolute_components() -> None:
    lexical_path = policy_loader._parse_posix_policy_path("/app/config/ai-policy-v1.json")

    assert lexical_path.drive == ""
    assert lexical_path.root == "/"
    assert lexical_path.components == ("app", "config", "ai-policy-v1.json")
    assert lexical_path.separator == "/"


@pytest.mark.parametrize(
    "value",
    [
        "app/config/ai-policy-v1.json",
        "/app//ai-policy-v1.json",
        "/app/../ai-policy-v1.json",
        "/app/./ai-policy-v1.json",
        "/app/config/",
        "/app\\config\\ai-policy-v1.json",
    ],
)
def test_posix_policy_path_rejects_noncanonical_or_relative_values(value: str) -> None:
    with pytest.raises(PolicyStartupError) as exc_info:
        policy_loader._parse_posix_policy_path(value)

    assert exc_info.value.stage == "path_lexical"
    assert exc_info.value.code == "AI_POLICY_PATH_INVALID"


def test_posix_remote_mount_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    lexical_path = policy_loader._parse_posix_policy_path("/app/config/ai-policy-v1.json")
    monkeypatch.setattr(
        policy_loader,
        "_query_posix_mount",
        lambda _path: policy_loader._PosixMountInfo(
            mount_point="/app/config",
            filesystem_type="nfs4",
        ),
    )

    with pytest.raises(PolicyStartupError) as exc_info:
        policy_loader._validate_drive_root(lexical_path)

    assert exc_info.value.stage == "drive_root_locality"
    assert exc_info.value.code == "AI_POLICY_DRIVE_ROOT_NOT_LOCAL"


@pytest.mark.parametrize(
    ("reparse_index", "reparse_tag", "synthetic_target"),
    [
        (2, 0xA000000C, r"D:\other\policy.json"),
        (1, 0xA000000C, r"D:\other-parent"),
        (1, 0xA0000003, r"D:\local-junction-target"),
        (1, 0xA0000003, r"\\server\share\forbidden-target"),
    ],
    ids=["file-symlink", "parent-symlink", "junction", "junction-to-unc"],
)
def test_reparse_metadata_is_rejected_without_open_or_traversal(
    reparse_index: int,
    reparse_tag: int,
    synthetic_target: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lexical_path = policy_loader._parse_policy_path(r"D:\parent\policy.json")
    metadata = [
        _synthetic_stat(mode=stat.S_IFDIR | 0o555, inode=1),
        _synthetic_stat(mode=stat.S_IFDIR | 0o555, inode=2),
        _synthetic_stat(mode=stat.S_IFREG | 0o444, inode=3, size=100),
    ]
    metadata[reparse_index].st_file_attributes = policy_loader._FILE_ATTRIBUTE_REPARSE_POINT
    metadata[reparse_index].st_reparse_tag = reparse_tag
    metadata[reparse_index].test_only_reparse_target = synthetic_target
    metadata_iter = iter(metadata)
    lstat_attempts: list[str] = []
    open_attempts = 0

    def synthetic_lstat(candidate: str) -> SimpleNamespace:
        lstat_attempts.append(candidate)
        return next(metadata_iter)

    def forbidden_open(_path: str) -> int:
        nonlocal open_attempts
        open_attempts += 1
        raise AssertionError("reparse target must not be opened")

    monkeypatch.setattr(policy_loader, "_lstat", synthetic_lstat)
    monkeypatch.setattr(policy_loader, "_open_no_follow", forbidden_open)

    with pytest.raises(PolicyStartupError) as exc_info:
        policy_loader._inspect_components(lexical_path)

    assert exc_info.value.stage == "path_component_identity"
    assert exc_info.value.code == "AI_POLICY_PATH_IDENTITY_INVALID"
    assert len(lstat_attempts) == reparse_index + 1
    assert open_attempts == 0


def test_real_local_junction_is_rejected_by_nonfollowing_metadata_gate(tmp_path: Path) -> None:
    target_dir = tmp_path / "junction-target"
    junction = tmp_path / "junction"
    target_dir.mkdir()
    _write_policy(target_dir)
    creation = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target_dir)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if creation.returncode != 0:
        pytest.skip("local junction creation is unavailable")

    try:
        lexical_path = policy_loader._parse_policy_path(str(junction / "ai-policy-v1.json"))
        with pytest.raises(PolicyStartupError) as exc_info:
            policy_loader._inspect_components(lexical_path)
        assert exc_info.value.stage == "path_component_identity"
        assert exc_info.value.code == "AI_POLICY_PATH_IDENTITY_INVALID"
    finally:
        if os.path.lexists(junction):
            os.rmdir(junction)


def test_preopen_target_handle_identity_drift_fails_closed(tmp_path: Path) -> None:
    policy_file = _write_policy(tmp_path)
    current_identity = policy_loader._path_identity(os.lstat(policy_file))
    inspected = policy_loader._InspectedPath(
        target=str(policy_file),
        components=(
            (
                str(policy_file),
                replace(current_identity, inode=current_identity.inode + 1),
            ),
        ),
    )

    with pytest.raises(PolicyStartupError) as exc_info:
        policy_loader._read_external_policy(inspected)

    assert exc_info.value.stage == "policy_read"
    assert exc_info.value.code == "AI_POLICY_READ_INVALID"


@pytest.mark.parametrize("drift_component", ["parent", "target"], ids=["parent", "target"])
def test_postread_component_identity_drift_fails_closed(
    drift_component: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_file = _write_policy(tmp_path)
    parent_identity = policy_loader._path_identity(os.lstat(tmp_path))
    target_identity = policy_loader._path_identity(os.lstat(policy_file))
    inspected = policy_loader._InspectedPath(
        target=str(policy_file),
        components=((str(tmp_path), parent_identity), (str(policy_file), target_identity)),
    )
    original_lstat = policy_loader._lstat

    def drifted_lstat(candidate: str) -> os.stat_result | SimpleNamespace:
        current = original_lstat(candidate)
        selected = str(tmp_path) if drift_component == "parent" else str(policy_file)
        if candidate != selected:
            return current
        identity = policy_loader._path_identity(current)
        return _synthetic_stat(
            mode=identity.mode,
            inode=identity.inode + 1,
            attributes=identity.attributes,
            reparse_tag=identity.reparse_tag,
        )

    monkeypatch.setattr(policy_loader, "_lstat", drifted_lstat)

    with pytest.raises(PolicyStartupError) as exc_info:
        policy_loader._read_external_policy(inspected)

    assert exc_info.value.stage == "policy_read"
    assert exc_info.value.code == "AI_POLICY_READ_INVALID"


def test_oversize_metadata_is_rejected_before_open_or_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lexical_path = policy_loader._parse_policy_path(r"D:\parent\policy.json")
    metadata = iter(
        (
            _synthetic_stat(mode=stat.S_IFDIR | 0o555, inode=1),
            _synthetic_stat(mode=stat.S_IFDIR | 0o555, inode=2),
            _synthetic_stat(
                mode=stat.S_IFREG | 0o444,
                inode=3,
                size=policy_loader._MAX_POLICY_BYTES + 1,
            ),
        )
    )
    open_attempts = 0

    def forbidden_open(_path: str) -> int:
        nonlocal open_attempts
        open_attempts += 1
        raise AssertionError("oversize policy must not be opened")

    monkeypatch.setattr(policy_loader, "_lstat", lambda _path: next(metadata))
    monkeypatch.setattr(policy_loader, "_open_no_follow", forbidden_open)

    with pytest.raises(PolicyStartupError) as exc_info:
        policy_loader._inspect_components(lexical_path)

    assert exc_info.value.stage == "path_component_identity"
    assert exc_info.value.code == "AI_POLICY_PATH_IDENTITY_INVALID"
    assert open_attempts == 0


def test_policy_read_uses_exact_bound_and_rejects_oversize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = _synthetic_stat(mode=stat.S_IFREG | 0o444, inode=9, size=100)
    expected_identity = policy_loader._path_identity(metadata)
    inspected = policy_loader._InspectedPath(
        target=r"D:\synthetic\policy.json",
        components=((r"D:\synthetic\policy.json", expected_identity),),
    )
    read_sizes: list[int] = []

    class BoundedStream:
        def __enter__(self) -> BoundedStream:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            read_sizes.append(size)
            return b"x" * size

    monkeypatch.setattr(policy_loader, "_open_no_follow", lambda _path: 41)
    monkeypatch.setattr(policy_loader.os, "fdopen", lambda *_args, **_kwargs: BoundedStream())
    monkeypatch.setattr(policy_loader.os, "fstat", lambda _descriptor: metadata)

    with pytest.raises(PolicyStartupError) as exc_info:
        policy_loader._read_external_policy(inspected)

    assert exc_info.value.stage == "policy_read"
    assert exc_info.value.code == "AI_POLICY_READ_INVALID"
    assert read_sizes == [policy_loader._MAX_POLICY_BYTES + 1]


def test_runtime_package_resources_match_the_frozen_identity() -> None:
    bundle = policy_loader._load_package_resources()

    assert len(bundle.schema_bytes) == 28_811
    assert len(bundle.registry_bytes) == 5_874


def test_package_resource_hash_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    identities = policy_loader._RESOURCE_IDENTITIES
    downstream_attempts: list[str] = []

    def unexpected(name: str) -> None:
        downstream_attempts.append(name)
        raise AssertionError(name)

    monkeypatch.setattr(
        policy_loader,
        "_RESOURCE_IDENTITIES",
        (replace(identities[0], sha256="0" * 64),) + identities[1:],
    )
    monkeypatch.setattr(policy_loader, "_validate_drive_root", lambda _path: None)
    monkeypatch.setattr(
        policy_loader,
        "_inspect_components",
        lambda _path: unexpected("component_metadata"),
    )
    monkeypatch.setattr(
        policy_loader,
        "_read_external_policy",
        lambda _path: unexpected("open_or_read"),
    )
    monkeypatch.setattr(
        policy_loader,
        "validate_policy_full",
        lambda *_args, **_kwargs: unexpected("validation"),
    )

    with pytest.raises(PolicyStartupError) as exc_info:
        load_validated_policy(_settings(r"D:\synthetic\policy.json"))

    assert exc_info.value.stage == "package_resource_identity"
    assert exc_info.value.code == "AI_POLICY_RESOURCE_IDENTITY_INVALID"
    assert downstream_attempts == []


def test_package_resource_set_rejects_case_variant_json_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = resources.files(_POLICY_RESOURCE_PACKAGE)
    for identity in policy_loader._RESOURCE_IDENTITIES:
        (tmp_path / identity.name).write_bytes(source_root.joinpath(identity.name).read_bytes())
    (tmp_path / "forged-extra.JSON").write_bytes(b"{}\n")
    monkeypatch.setattr(policy_loader.resources, "files", lambda _package: tmp_path)

    with pytest.raises(PolicyStartupError) as exc_info:
        policy_loader._load_package_resources()

    assert exc_info.value.stage == "package_resource_identity"
    assert exc_info.value.code == "AI_POLICY_RESOURCE_IDENTITY_INVALID"


def test_utf8_bom_is_rejected_at_pol_val_001(tmp_path: Path) -> None:
    error = _load_error(tmp_path, b"\xef\xbb\xbf" + _approved_policy_bytes())

    assert error.stage == "raw_parse"
    assert error.rule_id == "POL-VAL-001"
    assert error.code == "AI_POLICY_SOURCE_INVALID"


def test_invalid_utf8_is_rejected_at_pol_val_001(tmp_path: Path) -> None:
    error = _load_error(tmp_path, b"\xff" + _approved_policy_bytes())

    assert error.stage == "raw_parse"
    assert error.rule_id == "POL-VAL-001"
    assert error.code == "AI_POLICY_SOURCE_INVALID"


def test_nul_byte_is_rejected_at_pol_val_001(tmp_path: Path) -> None:
    error = _load_error(tmp_path, _approved_policy_bytes() + b"\x00")

    assert error.stage == "raw_parse"
    assert error.rule_id == "POL-VAL-001"
    assert error.code == "AI_POLICY_SOURCE_INVALID"


def test_duplicate_json_key_is_rejected_at_pol_val_001(tmp_path: Path) -> None:
    raw = _ordered_source_bytes(_case("NEG-POL-018-duplicate-source-key"))
    error = _load_error(tmp_path, raw)

    assert error.stage == "raw_parse"
    assert error.rule_id == "POL-VAL-001"
    assert error.code == "AI_POLICY_SOURCE_INVALID"


@pytest.mark.parametrize(
    ("case_id", "expected_stage", "expected_rule_id", "expected_code"),
    _FROZEN_FIRST_FAILURE_CASES,
    ids=[case[2].lower() for case in _FROZEN_FIRST_FAILURE_CASES],
)
def test_full_loader_preserves_frozen_first_failure_stage_oracle(
    case_id: str,
    expected_stage: str,
    expected_rule_id: str,
    expected_code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_attempts = 0
    original_validate = policy_loader.validate_policy_full

    def counting_validate(*args: Any, **kwargs: Any) -> Any:
        nonlocal validation_attempts
        validation_attempts += 1
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(policy_loader, "validate_policy_full", counting_validate)
    error = _load_error(tmp_path, _ordered_source_bytes(_case(case_id)))

    assert error.stage == expected_stage
    assert error.rule_id == expected_rule_id
    assert error.code == expected_code
    assert validation_attempts == 1


def test_registry_binding_failure_is_pol_val_005_after_package_precondition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = policy_loader._load_package_resources()
    drifted_bundle = policy_loader._PolicyResources(
        schema_bytes=bundle.schema_bytes,
        registry_bytes=bundle.registry_bytes + b" ",
    )
    monkeypatch.setattr(policy_loader, "_load_package_resources", lambda: drifted_bundle)

    error = _load_error(tmp_path, _approved_policy_bytes())

    assert error.stage == "registry_integrity"
    assert error.rule_id == "POL-VAL-005"
    assert error.code == "AI_POLICY_REGISTRY_MISMATCH"


def test_approved_policy_loads_through_the_real_local_file_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(str(_write_policy(tmp_path)))
    validation_attempts = 0
    binding_attempts = 0
    original_validate = policy_loader.validate_policy_full
    original_bind = policy_loader._cross_bind_settings

    def counting_validate(*args: Any, **kwargs: Any) -> Any:
        nonlocal validation_attempts
        validation_attempts += 1
        return original_validate(*args, **kwargs)

    def counting_bind(*args: Any, **kwargs: Any) -> None:
        nonlocal binding_attempts
        binding_attempts += 1
        original_bind(*args, **kwargs)

    monkeypatch.setattr(policy_loader, "validate_policy_full", counting_validate)
    monkeypatch.setattr(policy_loader, "_cross_bind_settings", counting_bind)

    snapshot = load_validated_policy(settings)

    assert snapshot.policy_version == 1
    assert snapshot.policy_hash == _APPROVED_POLICY_HASH
    assert snapshot.raw_sha256 == _APPROVED_RAW_SHA256
    assert validation_attempts == 1
    assert binding_attempts == 1
    with pytest.raises(FrozenInstanceError):
        snapshot.__setattr__("policy_hash", "0" * 64)


def test_semantically_valid_unapproved_raw_identity_reaches_only_the_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_file = _write_policy(tmp_path, b" " + _approved_policy_bytes())
    canonicalize_attempts = 0
    original_canonicalize = policy_companion.canonicalize_jcs

    def counting_canonicalize(value: Any) -> bytes:
        nonlocal canonicalize_attempts
        canonicalize_attempts += 1
        return original_canonicalize(value)

    monkeypatch.setattr(policy_companion, "canonicalize_jcs", counting_canonicalize)

    with pytest.raises(PolicyStartupError) as exc_info:
        load_validated_policy(_settings(str(policy_file)))

    assert exc_info.value.stage == "approval_identity_pin"
    assert exc_info.value.rule_id is None
    assert exc_info.value.code == "AI_POLICY_IDENTITY_NOT_APPROVED"
    assert canonicalize_attempts == 1


def test_settings_mirror_mismatch_fails_after_the_approved_pin(tmp_path: Path) -> None:
    settings = _settings(
        str(_write_policy(tmp_path)),
        llm_generation_model="mismatched-generation-model",
    )

    with pytest.raises(PolicyStartupError) as exc_info:
        load_validated_policy(settings)

    assert exc_info.value.stage == "settings_policy_binding"
    assert exc_info.value.rule_id is None
    assert exc_info.value.code == "AI_POLICY_SETTINGS_MISMATCH"


def test_startup_error_never_discloses_path_or_policy_sentinel() -> None:
    sentinel = "private-policy-path-sentinel"
    settings = _settings(f"C:\\{sentinel}\\..\\policy.json")

    with pytest.raises(PolicyStartupError) as exc_info:
        load_validated_policy(settings)

    rendered = "|".join(
        (
            str(exc_info.value),
            repr(exc_info.value),
            repr(exc_info.value.args),
            "".join(format_exception(exc_info.value)),
        )
    )
    assert sentinel not in rendered
    assert "policy.json" not in rendered
    assert rendered.count("AI_POLICY_PATH_INVALID") >= 1


def test_filesystem_error_traceback_suppresses_sensitive_path(tmp_path: Path) -> None:
    sentinel = "loader-trace-path-sentinel"
    missing_path = tmp_path / sentinel / "policy.json"

    with pytest.raises(PolicyStartupError) as exc_info:
        load_validated_policy(_settings(str(missing_path)))

    rendered = "".join(format_exception(exc_info.value))
    assert sentinel not in rendered
    assert "policy.json" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert exc_info.value.__suppress_context__ is True


def test_validation_error_redacts_policy_config_and_secret_sentinels(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy_sentinel = "private-policy-body-sentinel"
    config_sentinel = "private-config-value-sentinel"
    secret_sentinel = "private-secret-value-sentinel"
    raw = json.dumps({"candidate": policy_sentinel}, separators=(",", ":")).encode()
    settings = _settings(
        str(_write_policy(tmp_path, raw)),
        llm_generation_model=config_sentinel,
        llm_api_key=secret_sentinel,
    )

    with pytest.raises(PolicyStartupError) as exc_info:
        load_validated_policy(settings)

    error = exc_info.value
    rendered = "|".join(
        (
            str(error),
            repr(error),
            repr(error.args),
            "".join(format_exception(error)),
            json.dumps(
                {
                    "category": error.category,
                    "stage": error.stage,
                    "rule_id": error.rule_id,
                    "code": error.code,
                },
                sort_keys=True,
            ),
            caplog.text,
        )
    )
    assert error.stage == "envelope_context"
    assert error.rule_id == "POL-VAL-003"
    for sentinel in (policy_sentinel, config_sentinel, secret_sentinel):
        assert sentinel not in rendered
