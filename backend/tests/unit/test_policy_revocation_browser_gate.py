from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

from tests import manual_financial_read_browser as subject  # noqa: E402

REQUEST_ID = "7e000000-0000-4000-8000-000000000001"


def _manifest() -> dict[str, object]:
    return {
        "policy": {
            "id": str(subject._POLICY_REVOCATION_POLICY_ID),
            "status": "revoked",
            "row_version": 5,
            "revoked_by": str(subject.ADMIN_USER_ID),
            "revoked_at_present": True,
            "revoke_reason": subject._POLICY_REVOCATION_EXECUTION_REASON,
        },
        "approval_record_count": 5,
        "approval_actions": ["approve", "publish", "revoke", "revoke_request", "submit"],
        "request": {
            "id": REQUEST_ID,
            "actor_id": str(subject._POLICY_REVOCATION_REQUESTER_ID),
            "actor_role_code": "audit_reviewer",
            "reason": subject._POLICY_REVOCATION_REQUEST_REASON,
        },
        "execution": {
            "actor_id": str(subject.ADMIN_USER_ID),
            "actor_role_code": "system_admin",
            "reason": subject._POLICY_REVOCATION_EXECUTION_REASON,
            "related_record_id": REQUEST_ID,
        },
        "pending_count": 0,
        "action_codes": ["policy.revocation_requested", "policy.revoked"],
        "http_results": [
            {
                "method": "GET",
                "path": "/api/v1/policy-documents/revocation-requests",
                "status": 200,
            },
            {
                "method": "POST",
                "path": (
                    f"/api/v1/policy-documents/{subject._POLICY_REVOCATION_POLICY_ID}"
                    "/revocation-requests"
                ),
                "status": 201,
            },
            {
                "method": "POST",
                "path": (f"/api/v1/policy-documents/{subject._POLICY_REVOCATION_POLICY_ID}/revoke"),
                "status": 200,
            },
        ],
    }


def test_policy_revocation_manifest_accepts_two_role_browser_flow() -> None:
    subject._assert_policy_revocation_complete(_manifest())


@pytest.mark.parametrize(
    ("path", "value", "expected_code"),
    [
        (("policy", "status"), "published", "FACTS_INVALID"),
        (("execution", "actor_id"), str(subject._POLICY_REVOCATION_REQUESTER_ID), "FACTS_INVALID"),
        (("pending_count",), 1, "FACTS_INVALID"),
        (("http_results",), [], "HTTP_INCOMPLETE"),
    ],
)
def test_policy_revocation_manifest_rejects_incomplete_or_drifted_flow(
    path: tuple[str, ...],
    value: object,
    expected_code: str,
) -> None:
    manifest = deepcopy(_manifest())
    if len(path) == 1:
        manifest[path[0]] = value
    else:
        target = manifest[path[0]]
        assert isinstance(target, dict)
        target[path[1]] = value

    with pytest.raises(RuntimeError, match=f"BROWSER_GATE_POLICY_REVOCATION_{expected_code}"):
        subject._assert_policy_revocation_complete(manifest)


def test_policy_revocation_browser_mode_is_protected_and_reproducible() -> None:
    application = (_PROJECT_ROOT / "backend/tests/manual_financial_read_browser.py").read_text(
        encoding="utf-8"
    )
    shared_wrapper = (_PROJECT_ROOT / "scripts/verify-report-browser-gate.ps1").read_text(
        encoding="utf-8"
    )
    wrapper = (_PROJECT_ROOT / "scripts/verify-policy-revocation-browser-gate.ps1").read_text(
        encoding="utf-8"
    )
    runner = (_PROJECT_ROOT / "scripts/run-browser-gate.cjs").read_text(encoding="utf-8")

    assert "RUN_DISPOSABLE_POLICY_REVOCATION_BROWSER_V1" in application
    assert "COMPLETE_DISPOSABLE_POLICY_REVOCATION_BROWSER_V1" in application
    assert "/__finaudit_test__/policy-revocation-complete" in application
    assert "BROWSER_GATE_POLICY_REVOCATION_NOT_ACCEPTED" in application
    assert "'PolicyRevocation'" in shared_wrapper
    assert "POLICY_REVOCATION_BROWSER_GATE=PASS" in shared_wrapper
    assert "-Mode PolicyRevocation" in wrapper
    assert "policyRevocationFlow" in runner
    assert "BROWSER_POLICY_REQUEST_REFRESH_RECOVERY=PASS" in runner
    assert "BROWSER_POLICY_EXECUTION_REFRESH_RECOVERY=PASS" in runner
