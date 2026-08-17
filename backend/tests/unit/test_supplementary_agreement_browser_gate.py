from __future__ import annotations

from copy import deepcopy

import pytest

from tests.manual_financial_read_browser import (
    _ROLE_MATRIX_USER_IDS,
    _SUPPLEMENTARY_CONFIRM_REASON,
    _SUPPLEMENTARY_CONTRACT_ACTOR_ID,
    _SUPPLEMENTARY_QUOTE,
    _SUPPLEMENTARY_REJECT_AGREEMENT_ID,
    _SUPPLEMENTARY_REJECT_REASON,
    _SUPPLEMENTARY_REPLACE_REASON,
    AGREEMENT_ID,
    CONTRACT_ID,
    _assert_supplementary_complete,
)

EVIDENCE_BLOCK_ID = "7c000000-0000-4000-8000-000000000003"


def _complete_manifest() -> dict[str, object]:
    return {
        "expected_evidence_block_id": EVIDENCE_BLOCK_ID,
        "agreement": {
            "id": str(AGREEMENT_ID),
            "status": "confirmed",
            "confirmation_status": "confirmed",
            "confirmation_reason": _SUPPLEMENTARY_CONFIRM_REASON,
            "confirmed_by": str(_SUPPLEMENTARY_CONTRACT_ACTOR_ID),
            "row_version": 3,
        },
        "rejected_agreement": {
            "id": str(_SUPPLEMENTARY_REJECT_AGREEMENT_ID),
            "status": "rejected",
            "confirmation_status": "rejected",
            "confirmation_reason": _SUPPLEMENTARY_REJECT_REASON,
            "confirmed_by": str(_SUPPLEMENTARY_CONTRACT_ACTOR_ID),
            "row_version": 2,
        },
        "changes": [
            {
                "field_code": "amount",
                "value_type": "number",
                "old_value": "100.25",
                "new_value": "120.50",
                "evidence_block_id": EVIDENCE_BLOCK_ID,
                "page_no": 1,
                "quote_text": _SUPPLEMENTARY_QUOTE,
                "confirmation_status": "confirmed",
                "confirmed_by": str(_SUPPLEMENTARY_CONTRACT_ACTOR_ID),
            }
        ],
        "rejected_changes": [
            {
                "field_code": "payment_terms",
                "value_type": "string",
                "old_value": "30 days",
                "new_value": "45 days",
                "evidence_block_id": None,
                "page_no": None,
                "quote_text": None,
                "confirmation_status": "rejected",
                "confirmed_by": str(_SUPPLEMENTARY_CONTRACT_ACTOR_ID),
            }
        ],
        "corrections": [
            {
                "reason": _SUPPLEMENTARY_REPLACE_REASON,
                "field_path": "changes",
                "caused_outdated": False,
            }
        ],
        "action_codes": [
            "supplementary_agreements.changes_replaced",
            "supplementary_agreements.confirmed",
        ],
        "rejected_action_codes": ["supplementary_agreements.rejected"],
        "idempotency": [
            {
                "key_has_expected_prefix": True,
                "request_method": "PUT",
                "response_status": 200,
                "resource_id": str(AGREEMENT_ID),
            },
            {
                "key_has_expected_prefix": True,
                "request_method": "POST",
                "response_status": 200,
                "resource_id": str(AGREEMENT_ID),
            },
            {
                "key_has_expected_prefix": True,
                "request_method": "POST",
                "response_status": 200,
                "resource_id": str(_SUPPLEMENTARY_REJECT_AGREEMENT_ID),
            },
        ],
        "write_http_results": [
            {
                "method": "PUT",
                "path": (
                    f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/"
                    f"{AGREEMENT_ID}/changes"
                ),
                "status": 200,
            },
            {
                "method": "PUT",
                "path": (
                    f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/"
                    f"{AGREEMENT_ID}/changes"
                ),
                "status": 409,
            },
            {
                "method": "POST",
                "path": (
                    f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/"
                    f"{AGREEMENT_ID}/decision"
                ),
                "status": 200,
            },
            {
                "method": "POST",
                "path": (
                    f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/"
                    f"{_SUPPLEMENTARY_REJECT_AGREEMENT_ID}/decision"
                ),
                "status": 200,
            },
        ],
        "role_matrix_login_actor_ids": sorted(str(item) for item in _ROLE_MATRIX_USER_IDS),
    }


def test_complete_supplementary_manifest_is_accepted() -> None:
    _assert_supplementary_complete(_complete_manifest())


@pytest.mark.parametrize(
    ("key", "expected_code"),
    (
        ("agreement", "BROWSER_GATE_SUPPLEMENTARY_AGREEMENT_INVALID"),
        ("rejected_agreement", "BROWSER_GATE_SUPPLEMENTARY_REJECTION_INVALID"),
        ("changes", "BROWSER_GATE_SUPPLEMENTARY_CHANGE_INVALID"),
        ("rejected_changes", "BROWSER_GATE_SUPPLEMENTARY_REJECTION_INVALID"),
        ("corrections", "BROWSER_GATE_SUPPLEMENTARY_CORRECTION_INVALID"),
        ("action_codes", "BROWSER_GATE_SUPPLEMENTARY_AUDIT_INVALID"),
        ("rejected_action_codes", "BROWSER_GATE_SUPPLEMENTARY_REJECTION_INVALID"),
        ("idempotency", "BROWSER_GATE_SUPPLEMENTARY_IDEMPOTENCY_INVALID"),
        ("write_http_results", "BROWSER_GATE_SUPPLEMENTARY_HTTP_MATRIX_INVALID"),
        ("role_matrix_login_actor_ids", "BROWSER_GATE_SUPPLEMENTARY_ROLE_MATRIX_INCOMPLETE"),
    ),
)
def test_incomplete_supplementary_manifest_is_rejected(
    key: str,
    expected_code: str,
) -> None:
    manifest = deepcopy(_complete_manifest())
    manifest[key] = []

    with pytest.raises(RuntimeError, match=expected_code):
        _assert_supplementary_complete(manifest)
