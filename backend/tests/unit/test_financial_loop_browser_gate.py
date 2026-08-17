from __future__ import annotations

from copy import deepcopy

import pytest

from tests.manual_financial_read_browser import _assert_financial_loop_complete

CONTRACT_ID = "10000000-0000-4000-8000-000000000001"
INVOICE_ID = "10000000-0000-4000-8000-000000000002"
TASK_ID = "10000000-0000-4000-8000-000000000003"
EXECUTION_ID = "10000000-0000-4000-8000-000000000004"
SUPPLIER_ID = "10000000-0000-4000-8000-000000000007"
ROLE_MATRIX_LOGIN_ACTOR_IDS = [
    "7a000000-0000-4000-8000-000000000008",
    "7b000000-0000-4000-8000-000000000001",
    "7b000000-0000-4000-8000-000000000003",
    "7b000000-0000-4000-8000-000000000005",
    "7b000000-0000-4000-8000-000000000007",
]


def _complete_manifest() -> dict[str, object]:
    return {
        "scanner_profile": "synthetic-clamd-clean-v1",
        "files": [
            {
                "id": "10000000-0000-4000-8000-000000000005",
                "business_type": "contract",
                "status": "stored",
                "security_scan_status": "clean",
            },
            {
                "id": "10000000-0000-4000-8000-000000000006",
                "business_type": "invoice",
                "status": "stored",
                "security_scan_status": "clean",
            },
        ],
        "bindings": [
            {
                "business_type": "contract",
                "contract_id": CONTRACT_ID,
                "invoice_id": None,
            },
            {
                "business_type": "invoice",
                "contract_id": None,
                "invoice_id": INVOICE_ID,
            },
        ],
        "contracts": [
            {
                "id": CONTRACT_ID,
                "contract_no": "SYNTH-CONTRACT-001",
                "confirmation_status": "confirmed",
                "status": "active",
                "supplier_id": SUPPLIER_ID,
            }
        ],
        "invoices": [
            {
                "id": INVOICE_ID,
                "invoice_number": "000001",
                "confirmation_status": "confirmed",
                "duplicate_status": "unique",
                "status": "confirmed",
                "supplier_id": SUPPLIER_ID,
            }
        ],
        "relations": [
            {
                "contract_id": CONTRACT_ID,
                "invoice_id": INVOICE_ID,
                "status": "confirmed_primary",
            }
        ],
        "suppliers": [
            {
                "id": SUPPLIER_ID,
                "standard_name": "测试供应商（浏览器已确认）",
                "source_type": "contract",
                "source_contract_id": CONTRACT_ID,
                "source_invoice_id": None,
                "confirmation_status": "confirmed",
                "status": "active",
            }
        ],
        "supplier_corrections": [
            {
                "object_id": SUPPLIER_ID,
                "field_path": "supplier",
                "before_keys": [
                    "confirmation_status",
                    "source_supplier_id",
                    "standard_name",
                    "status",
                ],
                "after_keys": [
                    "confirmation_status",
                    "source_supplier_id",
                    "standard_name",
                    "status",
                ],
            }
        ],
        "supplier_action_codes": ["supplier.resolve", "supplier.update", "supplier.resolve"],
        "role_matrix_login_actor_ids": ROLE_MATRIX_LOGIN_ACTOR_IDS,
        "tasks": [
            {
                "id": TASK_ID,
                "status": "completed",
                "current_execution_id": EXECUTION_ID,
                "items": [
                    {
                        "item_type": "contract",
                        "contract_id": CONTRACT_ID,
                        "invoice_id": None,
                    },
                    {
                        "item_type": "invoice",
                        "contract_id": None,
                        "invoice_id": INVOICE_ID,
                    },
                ],
            }
        ],
        "executions": [{"id": EXECUTION_ID, "task_id": TASK_ID, "status": "completed"}],
        "reports": [
            {
                "execution_id": EXECUTION_ID,
                "status": "ready",
                "pdf_stored": True,
                "xlsx_stored": True,
                "pdf_size_bytes": 1024,
                "xlsx_size_bytes": 2048,
            }
        ],
    }


def test_complete_financial_loop_manifest_is_accepted() -> None:
    _assert_financial_loop_complete(_complete_manifest())


@pytest.mark.parametrize(
    ("key", "expected_code"),
    [
        ("relations", "BROWSER_GATE_FINANCIAL_LOOP_RELATION_INVALID"),
        ("suppliers", "BROWSER_GATE_FINANCIAL_LOOP_SUPPLIER_INVALID"),
        ("supplier_corrections", "BROWSER_GATE_FINANCIAL_LOOP_SUPPLIER_AUDIT_INVALID"),
        ("tasks", "BROWSER_GATE_FINANCIAL_LOOP_TASK_NOT_COMPLETED"),
        ("executions", "BROWSER_GATE_FINANCIAL_LOOP_EXECUTION_NOT_COMPLETED"),
        ("reports", "BROWSER_GATE_FINANCIAL_LOOP_REPORT_NOT_READY"),
    ],
)
def test_incomplete_financial_loop_manifest_is_rejected(
    key: str,
    expected_code: str,
) -> None:
    manifest = deepcopy(_complete_manifest())
    manifest[key] = []

    with pytest.raises(RuntimeError, match=expected_code):
        _assert_financial_loop_complete(manifest)


@pytest.mark.parametrize(
    ("key", "expected_code"),
    [
        ("supplier_action_codes", "BROWSER_GATE_FINANCIAL_LOOP_SUPPLIER_AUDIT_INVALID"),
        ("role_matrix_login_actor_ids", "BROWSER_GATE_FINANCIAL_LOOP_ROLE_MATRIX_INCOMPLETE"),
    ],
)
def test_incomplete_financial_loop_scalar_evidence_is_rejected(
    key: str,
    expected_code: str,
) -> None:
    manifest = deepcopy(_complete_manifest())
    manifest[key] = []

    with pytest.raises(RuntimeError, match=expected_code):
        _assert_financial_loop_complete(manifest)
