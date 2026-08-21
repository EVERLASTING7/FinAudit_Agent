from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

from tests import manual_financial_read_browser as subject  # noqa: E402


def _manifest() -> dict[str, object]:
    return {
        "source": {
            "id": str(subject.INVOICE_ID),
            "invoice_code": "INV-CODE-INTEGRATION",
            "invoice_number": "INV-NUMBER-INTEGRATION",
            "seller_tax_no": "SYNTH-SELLER-TAX",
            "duplicate_status": "unique",
            "status": "confirmed",
        },
        "candidate": {
            "id": str(subject.DUPLICATE_INVOICE_ID),
            "invoice_code": "INV-CODE-INTEGRATION",
            "invoice_number": "INV-NUMBER-INTEGRATION",
            "seller_tax_no": "SYNTH-SELLER-TAX",
            "duplicate_status": "suspected",
            "status": "archived",
        },
        "http_results": [
            {
                "method": "GET",
                "path": f"/api/v1/invoices/{subject.INVOICE_ID}/duplicate-candidates",
                "status": 200,
            },
            {
                "method": "GET",
                "path": (
                    f"/api/v1/invoices/{subject.INVOICE_ID}/duplicate-candidates/"
                    f"{subject.DUPLICATE_INVOICE_ID}"
                ),
                "status": 200,
            },
        ],
    }


def test_invoice_duplicate_manifest_accepts_exact_read_only_path() -> None:
    subject._assert_invoice_duplicate_complete(_manifest())


@pytest.mark.parametrize(
    "case",
    ["missing_http", "source_status_drift", "candidate_identity_drift"],
)
def test_invoice_duplicate_manifest_rejects_missing_or_drifted_evidence(case: str) -> None:
    manifest = _manifest()
    http_results = manifest["http_results"]
    source = manifest["source"]
    candidate = manifest["candidate"]
    assert isinstance(http_results, list)
    assert isinstance(source, dict)
    assert isinstance(candidate, dict)
    if case == "missing_http":
        http_results.pop()
    elif case == "source_status_drift":
        source["duplicate_status"] = "suspected"
    else:
        candidate["invoice_number"] = "drifted"

    with pytest.raises(RuntimeError, match="BROWSER_GATE_INVOICE_DUPLICATE_"):
        subject._assert_invoice_duplicate_complete(manifest)


def test_invoice_duplicate_browser_mode_is_protected_and_reproducible() -> None:
    application = (_PROJECT_ROOT / "backend/tests/manual_financial_read_browser.py").read_text(
        encoding="utf-8"
    )
    shared_wrapper = (_PROJECT_ROOT / "scripts/verify-report-browser-gate.ps1").read_text(
        encoding="utf-8"
    )
    wrapper = (_PROJECT_ROOT / "scripts/verify-invoice-duplicate-browser-gate.ps1").read_text(
        encoding="utf-8"
    )
    runner = (_PROJECT_ROOT / "scripts/run-browser-gate.cjs").read_text(encoding="utf-8")

    assert "RUN_DISPOSABLE_INVOICE_DUPLICATE_BROWSER_V1" in application
    assert "COMPLETE_DISPOSABLE_INVOICE_DUPLICATE_BROWSER_V1" in application
    assert "/__finaudit_test__/invoice-duplicate-complete" in application
    assert "BROWSER_GATE_INVOICE_DUPLICATE_NOT_ACCEPTED" in application
    assert "'InvoiceDuplicate'" in shared_wrapper
    assert "INVOICE_DUPLICATE_BROWSER_GATE=PASS" in shared_wrapper
    assert "-Mode InvoiceDuplicate" in wrapper
    assert "invoiceDuplicateFlow" in runner


def test_invoice_duplicate_browser_evidence_is_bounded_and_source_bound() -> None:
    evidence = json.loads(
        (_PROJECT_ROOT / "tests/evaluation/local-invoice-duplicate-browser-v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert evidence["schema_version"] == "local-invoice-duplicate-browser-v1"
    assert evidence["acceptance_boundary"] == {
        "business_representative": False,
        "formal_ac": False,
        "production": False,
        "provider": False,
    }
    assert evidence["browser"] == {
        "candidate_heading_visible": True,
        "candidate_id_visible": True,
        "console_warning_error_count": 0,
        "pair_heading_visible": True,
        "shared_identity_visible": True,
        "source_id_visible": True,
        "surface": "google_chrome_cdp",
        "write_action_enabled": False,
    }
    assert evidence["http_evidence"] == {
        "completion_status": "accepted",
        "distinct_required_read_count": 2,
        "list_status": 200,
        "pair_status": 200,
    }
    assert all(value == "passed" for value in evidence["gates"].values())
    assert evidence["cleanup"]["browser_process_count_after_run"] == 0
    assert evidence["cleanup"]["port_listener_count_after_run"] == 0
    assert evidence["cleanup"]["managed_postgresql_cleanup"] == "passed_at_gate_exit"
    assert evidence["cleanup"]["docker_current_recheck"] == "passed_after_daemon_restart"
    assert evidence["cleanup"]["managed_container_count_after_restart"] == 0
    assert evidence["cleanup"]["managed_network_count_after_restart"] == 0
    assert evidence["cleanup"]["managed_volume_count_after_restart"] == 0
    for key in (
        "runner",
        "browser_runner",
        "shared_wrapper",
        "entry_wrapper",
        "frontend_view",
    ):
        path = _PROJECT_ROOT / evidence["source_binding"][f"{key}_path"]
        payload = path.read_bytes()
        assert len(payload) == evidence["source_binding"][f"{key}_bytes"]
        assert hashlib.sha256(payload).hexdigest() == evidence["source_binding"][f"{key}_sha256"]
