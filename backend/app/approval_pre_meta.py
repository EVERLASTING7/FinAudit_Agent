"""Verify pre-meta approval contract artifacts without evaluating approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, cast


@dataclass(frozen=True)
class FileIdentity:
    relative_path: str
    byte_length: int
    sha256: str


@dataclass(frozen=True)
class SnapshotIdentity:
    relative_path: str
    marker: str
    byte_length: int
    sha256: str


@dataclass(frozen=True)
class VerificationSummary:
    schemas_verified: int
    snapshots_verified: int
    baselines_verified: int


class PreMetaVerificationError(RuntimeError):
    """A safe, stable pre-meta verification failure."""

    def __init__(self, code: str, relative_path: str) -> None:
        super().__init__(code)
        self.code = code
        self.relative_path = relative_path


_SCHEMA_IDENTITIES = (
    FileIdentity(
        "docs/change-requests/artifacts/DEP-005/source-contract-approval-record-v2.schema.json",
        340_459,
        "4f3bd94ca2cfd21f805e3487666796ecacc565136766db8ca93df6f22015b866",
    ),
    FileIdentity(
        "docs/change-requests/artifacts/DEP-005/dep005-detached-approval-evidence-v1.schema.json",
        9_633,
        "cdd04ea8bed4a411f0bd0d5aeda56ad8adb9428e3a6f72f9297bf48be9956bac",
    ),
    FileIdentity(
        "docs/change-requests/artifacts/DEP-005/approval-signer-registry-v1.schema.json",
        5_981,
        "d6346eba93031ede42887fc6e031dd7a60b5b0ce5f8b8dd55a21f3725715063f",
    ),
)

_BASELINE_IDENTITY = FileIdentity(
    "docs/baseline-manifest.md",
    1_689,
    "a0d1f0581224e9ef1d90136872b92d4f510890ca80406592026a3e2f63c85ed3",
)

_CURRENT_STATUS_MARKER = "## 9. \u5f53\u524d\u72b6\u6001"
_CURRENT_DECISION_STATUS_MARKER = "## 11. \u5f53\u524d\u51b3\u7b56\u72b6\u6001"
_SECTION_6_STATUS_MARKER = "## 6. \u5f53\u524d\u72b6\u6001"
_SECTION_8_STATUS_MARKER = "## 8. \u5f53\u524d\u72b6\u6001"
_SECTION_10_STATUS_MARKER = "## 10. \u5f53\u524d\u72b6\u6001"
_SNAPSHOT_IDENTITIES = (
    SnapshotIdentity(
        "docs/change-requests/DEP-005-backup-restore-artifact-contract.md",
        _CURRENT_STATUS_MARKER,
        121_827,
        "d9ca9b855ebdb753cc3b46649d13164ea300079e931d1e94f873909683490110",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-006-operation-log-integrity-closure.md",
        _CURRENT_STATUS_MARKER,
        204_739,
        "180b8de06ecc445d97cb734ebd884d6736cd3443fdbc364c6e4a549f2663a4be",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-008-operation-log-action-registry-closure.md",
        _CURRENT_DECISION_STATUS_MARKER,
        96_741,
        "2f67b69bc1dc8967f7299919a33f7b6e7253b0108ba77e9466b1613d0183f9b8",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-013-authentication-security-profile-closure.md",
        _CURRENT_STATUS_MARKER,
        80_973,
        "a0a89eb6c6ab167ac3421e787a896a0cc0d35f2a498b464f6a021eb86b54aae8",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-003-privileged-auth-integrity-closure.md",
        _SECTION_6_STATUS_MARKER,
        24_270,
        "cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-004-reliability-contract-closure.md",
        _SECTION_6_STATUS_MARKER,
        40_544,
        "387ed8d9eafbddcf1ca768abb770b13d1383a5c751077194ea3b7ca63523e7c6",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-005-document-integrity-contract-closure.md",
        _SECTION_8_STATUS_MARKER,
        36_753,
        "739f2004bd6cc785d0a06a69445af2c35a373bbe1746d9ed1b194cb3f94dd029",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-007-file-knowledge-base-lifecycle-closure.md",
        _SECTION_8_STATUS_MARKER,
        49_225,
        "40a38d45aeab262c2b54d65b1b95e7e6bbcbcdf3d892900d9b4150fefcf2b98e",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-009-chunking-config-integrity-closure.md",
        _SECTION_10_STATUS_MARKER,
        43_784,
        "68d002c6f851c7d18a670b992dc4c03026c4d08a67e02797735a048e44e8a597",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-010-scanner-registry-profile-closure.md",
        _SECTION_8_STATUS_MARKER,
        29_213,
        "17877a4cef3ca0a145f32ac06acf44e7fb65b49c06dec710a04a6078aca319de",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-014-shared-approval-sync-successor-closure.md",
        _CURRENT_STATUS_MARKER,
        40_628,
        "a0a5c71cbdd1b881a6572ac994d76bca942191ba388f2a1b6e5c15c0d236c830",
    ),
    SnapshotIdentity(
        "docs/change-requests/DEP-005-R2-backup-restore-artifact-contract.md",
        _CURRENT_STATUS_MARKER,
        36_263,
        "68ac5dac456f1c28624b4002332b35422a351f1023584ee3f07933e414458eb0",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-006-R2-operation-log-integrity-closure.md",
        _CURRENT_STATUS_MARKER,
        15_030,
        "cf39c94ea4817de91114094630070d5934e444963e1ea77abbfd22094aa5fc0d",
    ),
    SnapshotIdentity(
        "docs/change-requests/CR-008-R2-operation-log-action-registry-closure.md",
        _CURRENT_STATUS_MARKER,
        13_985,
        "aa27ca424cb0b5065db214186aba9516c093619486fdf96217adaeacb3ad4165",
    ),
)

_ROOT_KEYS = (
    "approval_record_schema_version",
    "canonicalization_version",
    "hash_algorithm",
    "record_kind",
    "approval_record_id",
    "source_id",
    "source_revision",
    "approval_scope",
    "approver_id",
    "approver_name",
    "approver_role",
    "decision",
    "selected_decisions",
    "rejected_decisions",
    "decision_snapshot_marker",
    "decision_snapshot_sha256",
    "source_baseline_manifest_sha256",
    "approval_record_schema_sha256",
    "detached_approval_evidence_schema_sha256",
    "request_sync_authorization_schema_ref",
    "sync_evidence_schema_ref",
    "artifact_bindings",
    "deltas",
    "environment_scope",
    "network_scope",
    "production_release_scope",
    "decided_at",
    "evidence_ref",
    "evidence_sha256",
    "safe_notes_code",
)

_TOP_LEVEL_BRANCH_REFS = (
    "#/$defs/Dep005R1MetaBranch",
    "#/$defs/Dep005R1ApprovedArtifactBranch",
    "#/$defs/Cr003ContractV2Branch",
    "#/$defs/Cr005ContractV2Branch",
    "#/$defs/Cr007ContractV2Branch",
    "#/$defs/Cr009ContractV2Branch",
    "#/$defs/Dep005R2MetaBranch",
    "#/$defs/Dep005R2ApprovedArtifactBranch",
    "#/$defs/Cr013ContractBranch",
    "#/$defs/Cr013AuthKeyringArtifactBranch",
)

_ARTIFACT_BINDING_REFS = (
    "#/$defs/DepMetaArtifactBindings",
    "#/$defs/DepApprovedArtifactBindings",
    "#/$defs/SourceContractArtifactBindings",
    "#/$defs/DepR2MetaArtifactBindings",
    "#/$defs/DepR2ApprovedArtifactBindings",
    "#/$defs/Cr013ContractArtifactBindings",
    "#/$defs/Cr013AuthKeyringArtifactBindings",
)

_BRANCH_SNAPSHOT_IDENTITIES = {
    "Dep005R1MetaBranch": (
        _CURRENT_STATUS_MARKER,
        "d9ca9b855ebdb753cc3b46649d13164ea300079e931d1e94f873909683490110",
    ),
    "Dep005R1ApprovedArtifactBranch": (
        _CURRENT_STATUS_MARKER,
        "d9ca9b855ebdb753cc3b46649d13164ea300079e931d1e94f873909683490110",
    ),
    "Cr003ContractV2Branch": (
        _SECTION_6_STATUS_MARKER,
        "cbe087aeb13f149fe6961f4daa71791ef8dd62b5d43bd1b1bb03b17c64cb8045",
    ),
    "Cr005ContractV2Branch": (
        _SECTION_8_STATUS_MARKER,
        "739f2004bd6cc785d0a06a69445af2c35a373bbe1746d9ed1b194cb3f94dd029",
    ),
    "Cr007ContractV2Branch": (
        _SECTION_8_STATUS_MARKER,
        "40a38d45aeab262c2b54d65b1b95e7e6bbcbcdf3d892900d9b4150fefcf2b98e",
    ),
    "Cr009ContractV2Branch": (
        _SECTION_10_STATUS_MARKER,
        "68d002c6f851c7d18a670b992dc4c03026c4d08a67e02797735a048e44e8a597",
    ),
    "Dep005R2MetaBranch": (
        _CURRENT_STATUS_MARKER,
        "68ac5dac456f1c28624b4002332b35422a351f1023584ee3f07933e414458eb0",
    ),
    "Dep005R2ApprovedArtifactBranch": (
        _CURRENT_STATUS_MARKER,
        "68ac5dac456f1c28624b4002332b35422a351f1023584ee3f07933e414458eb0",
    ),
    "Cr013ContractBranch": (
        _CURRENT_STATUS_MARKER,
        "a0a89eb6c6ab167ac3421e787a896a0cc0d35f2a498b464f6a021eb86b54aae8",
    ),
    "Cr013AuthKeyringArtifactBranch": (
        _CURRENT_STATUS_MARKER,
        "a0a89eb6c6ab167ac3421e787a896a0cc0d35f2a498b464f6a021eb86b54aae8",
    ),
}

_DECISION_UNIVERSES = {
    "DepDecisionArray": tuple(f"DEP5-D-{number:03d}" for number in range(1, 10)),
    "Cr003DecisionArray": (
        "D-010=DECIDED_BY_STATE_CAS",
        "D-011=REVOKE_REASON",
        "D-012=GIST_HALF_OPEN_RANGE",
        "D-013=ENV_INDEPENDENT_SOD",
        "D-014=LONG_TERM_ADMIN_ONLY",
    ),
    "Cr005DecisionArray": (
        "DOC-D-001",
        "DOC-D-002",
        "DOC-D-003",
        "DOC-HANDLER-DOCUMENT-CORRECTION",
        "DOC-HANDLER-ASSET-SECURITY-REVALIDATION",
        "DOC-CR010-SCANNER-EVIDENCE-PROJECTION",
        "DOC-PARSE-006",
        "DOC-MIGRATION-DOWNGRADE",
    ),
    "Cr007DecisionArray": tuple(f"FILEKB-D-{number:03d}" for number in range(1, 9)),
    "Cr009DecisionArray": (
        "CHUNK-FIELDS-JCS",
        "CHUNK-STATE-MACHINE",
        "CHUNK-008-009-API",
        "CHUNK-IDEMPOTENCY-CAS",
        "CHUNK-CURSOR",
        "CHUNK-REVISION-OWNERSHIP",
        "CHUNK-DOWNGRADE",
    ),
    "Cr013ContractDecisionArray": (
        "AUTHSEC-D-001=PASSWORD_HASH_AND_POLICY_PROFILE_V1",
        "AUTHSEC-D-002=LOGIN_LOCKOUT_PROFILE_V1",
        "AUTHSEC-D-003=JWT_KEYRING_AND_CLAIMS_PROFILE_V1",
        "AUTHSEC-D-004=REFRESH_FAMILY_ROTATION_REPLAY_PROFILE_V1",
        "AUTHSEC-D-005=PASSWORD_CHANGE_LOGOUT_ERROR_PROFILE_V1",
        "AUTHSEC-D-006=P0_PERMISSION_DICTIONARY_ROLE_MAP_V1",
        "AUTHSEC-D-007=BROWSER_TOKEN_CUSTODY_PROFILE_V1",
        "AUTHSEC-D-008=MIGRATION_ROTATION_ROLLBACK_TEST_PROFILE_V1",
    ),
    "Cr013AuthKeyringDecisionArray": ("AUTHKEY-A-001=SCHEMA_AND_MANIFEST_APPROVED",),
}


class _DuplicateJsonKey(ValueError):
    pass


class _NonFiniteJsonNumber(ValueError):
    pass


def _fail(code: str, relative_path: str) -> NoReturn:
    raise PreMetaVerificationError(code, relative_path)


def _resolve_under_root(project_root: Path, relative_path: str) -> Path:
    try:
        resolved_root = project_root.resolve(strict=True)
        resolved_path = (resolved_root / relative_path).resolve(strict=True)
        resolved_path.relative_to(resolved_root)
    except (OSError, ValueError):
        _fail("PREMETA_RAW_INVALID", relative_path)
    if not resolved_path.is_file():
        _fail("PREMETA_RAW_INVALID", relative_path)
    return resolved_path


def _read_bytes(project_root: Path, relative_path: str) -> bytes:
    path = _resolve_under_root(project_root, relative_path)
    try:
        return path.read_bytes()
    except OSError:
        _fail("PREMETA_RAW_INVALID", relative_path)


def _verify_identity(raw: bytes, identity: FileIdentity, error_code: str) -> None:
    if len(raw) != identity.byte_length or hashlib.sha256(raw).hexdigest() != identity.sha256:
        _fail(error_code, identity.relative_path)


def _strict_utf8(raw: bytes, relative_path: str, *, reject_cr: bool) -> str:
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw or (reject_cr and b"\r" in raw):
        _fail("PREMETA_RAW_INVALID", relative_path)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail("PREMETA_RAW_INVALID", relative_path)
    if "\ufffd" in text:
        _fail("PREMETA_RAW_INVALID", relative_path)
    return text


def _strict_json_bytes(raw: bytes, relative_path: str) -> dict[str, object]:
    text = _strict_utf8(raw, relative_path, reject_cr=True)

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonKey
            result[key] = value
        return result

    def reject_non_finite(_: str) -> NoReturn:
        raise _NonFiniteJsonNumber

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite,
        )
    except _DuplicateJsonKey:
        _fail("PREMETA_JSON_DUPLICATE_KEY", relative_path)
    except _NonFiniteJsonNumber:
        _fail("PREMETA_JSON_NONFINITE", relative_path)
    except (json.JSONDecodeError, RecursionError):
        _fail("PREMETA_RAW_INVALID", relative_path)
    if _contains_non_finite(parsed):
        _fail("PREMETA_JSON_NONFINITE", relative_path)
    if type(parsed) is not dict:
        _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
    return cast(dict[str, object], parsed)


def _contains_non_finite(value: object) -> bool:
    if type(value) is float:
        return not math.isfinite(value)
    if type(value) is dict:
        return any(_contains_non_finite(child) for child in cast(dict[str, object], value).values())
    if type(value) is list:
        return any(_contains_non_finite(child) for child in cast(list[object], value))
    return False


def _walk_json(value: object) -> Iterator[dict[str, object]]:
    if type(value) is dict:
        mapping = cast(dict[str, object], value)
        yield mapping
        for child in mapping.values():
            yield from _walk_json(child)
    elif type(value) is list:
        for child in cast(list[object], value):
            yield from _walk_json(child)


def _resolve_json_pointer(root: dict[str, object], reference: str) -> object:
    if not reference.startswith("#/"):
        raise KeyError
    current: object = root
    for raw_segment in reference[2:].split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if type(current) is dict:
            current = cast(dict[str, object], current)[segment]
        elif type(current) is list:
            current = cast(list[object], current)[int(segment)]
        else:
            raise KeyError
    return current


def _verify_schema_common(schema: dict[str, object], relative_path: str) -> None:
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
    for node in _walk_json(schema):
        if "$comment" in node:
            _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
        reference = node.get("$ref")
        if reference is not None:
            if type(reference) is not str or not reference.startswith("#/"):
                _fail("PREMETA_REMOTE_REF", relative_path)
            try:
                _resolve_json_pointer(schema, reference)
            except (KeyError, IndexError, TypeError, ValueError):
                _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
        if node.get("type") == "object":
            properties = node.get("properties")
            required = node.get("required")
            if (
                type(properties) is not dict
                or type(required) is not list
                or node.get("additionalProperties") is not False
            ):
                _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
            property_keys = set(cast(dict[str, object], properties))
            required_keys = cast(list[object], required)
            if (
                not all(type(key) is str for key in required_keys)
                or len(required_keys) != len(set(required_keys))
                or set(required_keys) != property_keys
            ):
                _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)


def _refs(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        return ()
    references: list[str] = []
    for item in cast(list[object], value):
        if type(item) is not dict:
            return ()
        reference = cast(dict[str, object], item).get("$ref")
        if type(reference) is not str:
            return ()
        references.append(reference)
    return tuple(references)


def _ordered_subsets(universe: tuple[str, ...]) -> set[tuple[str, ...]]:
    return {
        tuple(value for index, value in enumerate(universe) if mask & (1 << index))
        for mask in range(1 << len(universe))
    }


def _verify_source_schema(schema: dict[str, object], relative_path: str) -> None:
    properties = schema.get("properties")
    required = schema.get("required")
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or type(properties) is not dict
        or type(required) is not list
        or set(cast(dict[str, object], properties)) != set(_ROOT_KEYS)
        or tuple(cast(list[object], required)) != _ROOT_KEYS
        or _refs(schema.get("oneOf")) != _TOP_LEVEL_BRANCH_REFS
    ):
        _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)

    artifact_bindings = cast(dict[str, object], properties).get("artifact_bindings")
    if (
        type(artifact_bindings) is not dict
        or _refs(cast(dict[str, object], artifact_bindings).get("oneOf")) != _ARTIFACT_BINDING_REFS
    ):
        _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)

    definitions = schema.get("$defs")
    if type(definitions) is not dict:
        _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
    for name, (marker, snapshot_sha256) in _BRANCH_SNAPSHOT_IDENTITIES.items():
        branch = cast(dict[str, object], definitions).get(name)
        if type(branch) is not dict:
            _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
        branch_properties = cast(dict[str, object], branch).get("properties")
        if type(branch_properties) is not dict:
            _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
        branch_properties = cast(dict[str, object], branch_properties)
        if branch_properties.get("decision_snapshot_marker") != {
            "const": marker
        } or branch_properties.get("decision_snapshot_sha256") != {"const": snapshot_sha256}:
            _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
    for name, universe in _DECISION_UNIVERSES.items():
        definition = cast(dict[str, object], definitions).get(name)
        if type(definition) is not dict:
            _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
        values = cast(dict[str, object], definition).get("enum")
        if type(values) is not list:
            _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
        actual: set[tuple[str, ...]] = set()
        for value in cast(list[object], values):
            if type(value) is not list or not all(
                type(item) is str for item in cast(list[object], value)
            ):
                _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)
            actual.add(tuple(cast(list[str], value)))
        expected = _ordered_subsets(universe)
        if len(values) != len(expected) or actual != expected:
            _fail("PREMETA_SCHEMA_SHAPE_MISMATCH", relative_path)


def _snapshot_preimage(raw: bytes, marker: str, relative_path: str) -> bytes:
    text = _strict_utf8(raw, relative_path, reject_cr=False)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    marker_indexes = [index for index, line in enumerate(lines) if line == marker]
    if len(marker_indexes) != 1:
        _fail("PREMETA_SNAPSHOT_MARKER_INVALID", relative_path)
    prefix = "\n".join(lines[: marker_indexes[0]])
    return (prefix.rstrip("\n") + "\n").encode("utf-8")


def _verify_snapshot(project_root: Path, identity: SnapshotIdentity) -> None:
    raw = _read_bytes(project_root, identity.relative_path)
    preimage = _snapshot_preimage(raw, identity.marker, identity.relative_path)
    if (
        len(preimage) != identity.byte_length
        or hashlib.sha256(preimage).hexdigest() != identity.sha256
    ):
        _fail("PREMETA_SNAPSHOT_IDENTITY_MISMATCH", identity.relative_path)


def verify_pre_meta(project_root: Path) -> VerificationSummary:
    """Verify only the static pre-meta artifact and snapshot identities."""

    for identity in _SCHEMA_IDENTITIES:
        raw = _read_bytes(project_root, identity.relative_path)
        _verify_identity(raw, identity, "PREMETA_SCHEMA_IDENTITY_MISMATCH")
        schema = _strict_json_bytes(raw, identity.relative_path)
        _verify_schema_common(schema, identity.relative_path)
        if identity is _SCHEMA_IDENTITIES[0]:
            _verify_source_schema(schema, identity.relative_path)

    baseline = _read_bytes(project_root, _BASELINE_IDENTITY.relative_path)
    _verify_identity(baseline, _BASELINE_IDENTITY, "PREMETA_BASELINE_IDENTITY_MISMATCH")

    for snapshot in _SNAPSHOT_IDENTITIES:
        _verify_snapshot(project_root, snapshot)

    return VerificationSummary(
        schemas_verified=len(_SCHEMA_IDENTITIES),
        snapshots_verified=len(_SNAPSHOT_IDENTITIES),
        baselines_verified=1,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify static pre-meta approval artifacts without evaluating approval."
    )
    parser.add_argument("--project-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        summary = verify_pre_meta(args.project_root)
    except PreMetaVerificationError as error:
        print("APPROVAL_PRE_META_STATIC=FAIL")
        print(f"ERROR={error.code}:{error.relative_path}")
        return 1

    print("APPROVAL_PRE_META_STATIC=PASS")
    print(f"SNAPSHOTS_VERIFIED={summary.snapshots_verified}")
    print(f"SCHEMAS_VERIFIED={summary.schemas_verified}")
    print(f"BASELINE_VERIFIED={summary.baselines_verified}")
    print("APPROVAL=OUT_OF_SCOPE_NOT_EVALUATED")
    print("REGISTRY_PIN=OUT_OF_SCOPE_NOT_EVALUATED")
    print("SIGNATURES=OUT_OF_SCOPE_NOT_EVALUATED")
    print("REQUEST_SYNC=NOT_AUTHORIZED")
    print("NETWORK=NOT_AUTHORIZED")
    print("PRODUCTION=NOT_AUTHORIZED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
