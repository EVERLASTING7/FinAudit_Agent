from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.approval_pre_meta import (
    _CURRENT_STATUS_MARKER,
    _SCHEMA_IDENTITIES,
    _SNAPSHOT_IDENTITIES,
    PreMetaVerificationError,
    _snapshot_preimage,
    _strict_json_bytes,
    _verify_schema_common,
    _verify_source_schema,
    main,
    verify_pre_meta,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_SCHEMA_PATH = _PROJECT_ROOT / _SCHEMA_IDENTITIES[0].relative_path


def _source_schema() -> dict[str, object]:
    parsed = json.loads(_SOURCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert type(parsed) is dict
    return parsed


def _assert_error(code: str, action: object) -> None:
    assert callable(action)
    with pytest.raises(PreMetaVerificationError) as captured:
        action()
    assert captured.value.code == code


def test_current_pre_meta_contract_passes() -> None:
    summary = verify_pre_meta(_PROJECT_ROOT)

    assert summary.schemas_verified == 3
    assert summary.snapshots_verified == 14
    assert summary.baselines_verified == 1
    assert {identity.relative_path for identity in _SNAPSHOT_IDENTITIES} == {
        "docs/change-requests/DEP-005-backup-restore-artifact-contract.md",
        "docs/change-requests/CR-003-privileged-auth-integrity-closure.md",
        "docs/change-requests/CR-004-reliability-contract-closure.md",
        "docs/change-requests/CR-005-document-integrity-contract-closure.md",
        "docs/change-requests/CR-006-operation-log-integrity-closure.md",
        "docs/change-requests/CR-007-file-knowledge-base-lifecycle-closure.md",
        "docs/change-requests/CR-008-operation-log-action-registry-closure.md",
        "docs/change-requests/CR-009-chunking-config-integrity-closure.md",
        "docs/change-requests/CR-010-scanner-registry-profile-closure.md",
        "docs/change-requests/CR-013-authentication-security-profile-closure.md",
        "docs/change-requests/CR-014-shared-approval-sync-successor-closure.md",
        "docs/change-requests/DEP-005-R2-backup-restore-artifact-contract.md",
        "docs/change-requests/CR-006-R2-operation-log-integrity-closure.md",
        "docs/change-requests/CR-008-R2-operation-log-action-registry-closure.md",
    }


def test_cli_reports_static_scope_without_claiming_approval(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--project-root", str(_PROJECT_ROOT)]) == 0

    output = capsys.readouterr().out.splitlines()
    assert output == [
        "APPROVAL_PRE_META_STATIC=PASS",
        "SNAPSHOTS_VERIFIED=14",
        "SCHEMAS_VERIFIED=3",
        "BASELINE_VERIFIED=1",
        "APPROVAL=OUT_OF_SCOPE_NOT_EVALUATED",
        "REGISTRY_PIN=OUT_OF_SCOPE_NOT_EVALUATED",
        "SIGNATURES=OUT_OF_SCOPE_NOT_EVALUATED",
        "REQUEST_SYNC=NOT_AUTHORIZED",
        "NETWORK=NOT_AUTHORIZED",
        "PRODUCTION=NOT_AUTHORIZED",
    ]


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"\xef\xbb\xbf{}", "PREMETA_RAW_INVALID"),
        (b'{"value":"a\x00b"}', "PREMETA_RAW_INVALID"),
        (b"{\r\n}", "PREMETA_RAW_INVALID"),
        (b"\xff", "PREMETA_RAW_INVALID"),
        ('{"value":"\ufffd"}'.encode(), "PREMETA_RAW_INVALID"),
        (b'{"value":1,"value":2}', "PREMETA_JSON_DUPLICATE_KEY"),
        (b'{"value":NaN}', "PREMETA_JSON_NONFINITE"),
        (b'{"value":Infinity}', "PREMETA_JSON_NONFINITE"),
        (b'{"value":-Infinity}', "PREMETA_JSON_NONFINITE"),
        (b'{"value":1e9999}', "PREMETA_JSON_NONFINITE"),
        (b'{"value":-1e9999}', "PREMETA_JSON_NONFINITE"),
    ],
)
def test_strict_json_rejects_invalid_raw_envelopes(raw: bytes, code: str) -> None:
    _assert_error(code, lambda: _strict_json_bytes(raw, "synthetic.json"))


def test_common_schema_rejects_remote_and_unresolved_refs() -> None:
    remote = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": "https://example.test/schema.json",
    }
    unresolved = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {},
        "$ref": "#/$defs/missing",
    }

    _assert_error("PREMETA_REMOTE_REF", lambda: _verify_schema_common(remote, "synthetic.json"))
    _assert_error(
        "PREMETA_SCHEMA_SHAPE_MISMATCH",
        lambda: _verify_schema_common(unresolved, "synthetic.json"),
    )


def test_common_schema_rejects_open_or_partial_typed_objects() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": [],
        "additionalProperties": False,
    }

    _assert_error(
        "PREMETA_SCHEMA_SHAPE_MISMATCH",
        lambda: _verify_schema_common(schema, "synthetic.json"),
    )


def test_source_schema_rejects_root_and_branch_drift() -> None:
    missing_root_key = _source_schema()
    properties = missing_root_key["properties"]
    assert type(properties) is dict
    properties.pop("safe_notes_code")

    reordered_branch = _source_schema()
    branches = reordered_branch["oneOf"]
    assert type(branches) is list
    branches[0], branches[1] = branches[1], branches[0]

    _assert_error(
        "PREMETA_SCHEMA_SHAPE_MISMATCH",
        lambda: _verify_source_schema(missing_root_key, "synthetic.json"),
    )
    _assert_error(
        "PREMETA_SCHEMA_SHAPE_MISMATCH",
        lambda: _verify_source_schema(reordered_branch, "synthetic.json"),
    )


def test_source_schema_rejects_reversed_decision_subsequence() -> None:
    schema = copy.deepcopy(_source_schema())
    definitions = schema["$defs"]
    assert type(definitions) is dict
    decision_array = definitions["Cr013ContractDecisionArray"]
    assert type(decision_array) is dict
    values = decision_array["enum"]
    assert type(values) is list
    longest = max(values, key=len)
    assert type(longest) is list
    longest.reverse()

    _assert_error(
        "PREMETA_SCHEMA_SHAPE_MISMATCH",
        lambda: _verify_source_schema(schema, "synthetic.json"),
    )


def test_source_schema_rejects_unpinned_branch_snapshot() -> None:
    schema = copy.deepcopy(_source_schema())
    definitions = schema["$defs"]
    assert type(definitions) is dict
    branch = definitions["Cr003ContractV2Branch"]
    assert type(branch) is dict
    properties = branch["properties"]
    assert type(properties) is dict
    properties["decision_snapshot_sha256"] = {"$ref": "#/$defs/Sha256"}

    _assert_error(
        "PREMETA_SCHEMA_SHAPE_MISMATCH",
        lambda: _verify_source_schema(schema, "synthetic.json"),
    )


def test_snapshot_normalizes_newlines_and_excludes_status_section() -> None:
    first = f"# Static\r\n\r\n{_CURRENT_STATUS_MARKER}\r\nstate one\r\n".encode()
    second = f"# Static\n\n{_CURRENT_STATUS_MARKER}\nstate two\n".encode()

    first_preimage = _snapshot_preimage(first, _CURRENT_STATUS_MARKER, "synthetic.md")
    second_preimage = _snapshot_preimage(second, _CURRENT_STATUS_MARKER, "synthetic.md")

    assert first_preimage == b"# Static\n"
    assert second_preimage == first_preimage
    assert hashlib.sha256(first_preimage).digest() == hashlib.sha256(second_preimage).digest()


def test_snapshot_rejects_missing_or_duplicate_marker() -> None:
    missing = b"# Static\n"
    duplicate = f"{_CURRENT_STATUS_MARKER}\nstate\n{_CURRENT_STATUS_MARKER}\n".encode()

    _assert_error(
        "PREMETA_SNAPSHOT_MARKER_INVALID",
        lambda: _snapshot_preimage(missing, _CURRENT_STATUS_MARKER, "synthetic.md"),
    )
    _assert_error(
        "PREMETA_SNAPSHOT_MARKER_INVALID",
        lambda: _snapshot_preimage(duplicate, _CURRENT_STATUS_MARKER, "synthetic.md"),
    )


def test_snapshot_static_change_changes_identity() -> None:
    original = f"# Static\n{_CURRENT_STATUS_MARKER}\nstate\n".encode()
    changed = f"# Changed\n{_CURRENT_STATUS_MARKER}\nstate\n".encode()

    original_hash = hashlib.sha256(
        _snapshot_preimage(original, _CURRENT_STATUS_MARKER, "synthetic.md")
    ).digest()
    changed_hash = hashlib.sha256(
        _snapshot_preimage(changed, _CURRENT_STATUS_MARKER, "synthetic.md")
    ).digest()

    assert changed_hash != original_hash
