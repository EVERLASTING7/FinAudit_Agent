from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

from tests import manual_financial_read_browser as subject  # noqa: E402

SOURCE_PARSE_ID = "63000000-0000-4000-8000-000000000001"
RESULT_PARSE_ID = "63000000-0000-4000-8000-000000000002"
EVIDENCE_BLOCK_ID = "63000000-0000-4000-8000-000000000003"


def _manifest() -> dict[str, object]:
    return {
        "evidence_block_id": EVIDENCE_BLOCK_ID,
        "source": {
            "id": SOURCE_PARSE_ID,
            "status": "superseded",
            "superseded_at_present": True,
        },
        "correction": {
            "id": "63000000-0000-4000-8000-000000000004",
            "source_block_id": EVIDENCE_BLOCK_ID,
            "result_parse_version_id": RESULT_PARSE_ID,
            "field_name": "text_content",
            "after_value": subject._DOCUMENT_CORRECTION_TEXT,
            "reason": subject._DOCUMENT_CORRECTION_REASON,
        },
        "result": {
            "id": RESULT_PARSE_ID,
            "status": "active",
            "parent_version_id": SOURCE_PARSE_ID,
            "activated_at_present": True,
            "block_texts": [subject._DOCUMENT_CORRECTION_TEXT],
            "active_markdown_count": 1,
        },
        "job": {
            "id": "63000000-0000-4000-8000-000000000005",
            "status": "succeeded",
            "attempt_no": 1,
            "max_attempts": 1,
            "steps": [
                {
                    "attempt_no": 1,
                    "step_code": "snapshot_rebuild",
                    "status": "succeeded",
                    "error_code": None,
                }
            ],
            "published_outbox_count": 1,
        },
        "action_codes": [
            "document_block.correction_requested",
            "document_parse.activated",
        ],
        "http_results": [
            {
                "method": "GET",
                "path": (
                    f"/api/v1/files/{subject._SUPPLEMENTARY_FILE_ID}/document-correction-blocks"
                ),
                "status": 200,
            },
            {
                "method": "POST",
                "path": f"/api/v1/document-blocks/{EVIDENCE_BLOCK_ID}/correct",
                "status": 202,
            },
            {
                "method": "POST",
                "path": f"/api/v1/document-parse-versions/{RESULT_PARSE_ID}/activate",
                "status": 200,
            },
        ],
    }


def test_document_correction_manifest_accepts_two_step_browser_flow() -> None:
    subject._assert_document_correction_complete(_manifest())


@pytest.mark.parametrize(
    ("path", "value", "expected_code"),
    [
        (("result", "status"), "succeeded", "FACTS_INVALID"),
        (("job", "status"), "failed", "FACTS_INVALID"),
        (("http_results",), [], "HTTP_INCOMPLETE"),
    ],
)
def test_document_correction_manifest_rejects_incomplete_or_drifted_flow(
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

    with pytest.raises(RuntimeError, match=f"BROWSER_GATE_DOCUMENT_CORRECTION_{expected_code}"):
        subject._assert_document_correction_complete(manifest)


def test_document_correction_browser_mode_is_protected_and_reproducible() -> None:
    application = (_PROJECT_ROOT / "backend/tests/manual_financial_read_browser.py").read_text(
        encoding="utf-8"
    )
    shared_wrapper = (_PROJECT_ROOT / "scripts/verify-report-browser-gate.ps1").read_text(
        encoding="utf-8"
    )
    wrapper = (_PROJECT_ROOT / "scripts/verify-document-correction-browser-gate.ps1").read_text(
        encoding="utf-8"
    )
    runner = (_PROJECT_ROOT / "scripts/run-browser-gate.cjs").read_text(encoding="utf-8")

    assert "RUN_DISPOSABLE_DOCUMENT_CORRECTION_BROWSER_V1" in application
    assert "COMPLETE_DISPOSABLE_DOCUMENT_CORRECTION_BROWSER_V1" in application
    assert "/__finaudit_test__/document-correction-complete" in application
    assert "BROWSER_GATE_DOCUMENT_CORRECTION_NOT_ACCEPTED" in application
    assert "'DocumentCorrection'" in shared_wrapper
    assert "DOCUMENT_CORRECTION_BROWSER_GATE=PASS" in shared_wrapper
    assert "$automatedBrowserMode" in shared_wrapper
    assert "-Mode DocumentCorrection" in wrapper
    assert "documentCorrectionFlow" in runner
    assert "BROWSER_DOCUMENT_REFRESH_RECOVERY=PASS" in runner
    assert "BROWSER_CONSOLE_ERRORS=0" in runner
