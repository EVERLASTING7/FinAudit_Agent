from copy import deepcopy

import pytest

from tests.manual_financial_read_browser import (
    _SYNTHETIC_SCAN_FAIL_ONCE_MARKER,
    _assert_file_capabilities_complete,
    _SyntheticClamdHandler,
    _SyntheticClamdServer,
)


def _complete_manifest() -> dict[str, object]:
    return {
        "scanner_profile": "synthetic-clamd-clean-v1",
        "items": [
            {
                "original_name": "browser-clean.pdf",
                "file_status": "archived",
                "security_scan_status": "clean",
                "job_status": "succeeded",
                "job_attempt_no": 1,
                "original_stored": True,
                "batch_upload_claimed": True,
                "action_codes": ["files.previewed", "files.archived"],
            },
            {
                "original_name": "browser-retry.pdf",
                "file_status": "stored",
                "security_scan_status": "clean",
                "job_status": "succeeded",
                "job_attempt_no": 2,
                "original_stored": True,
                "batch_upload_claimed": True,
                "action_codes": ["files.retry_queued", "files.previewed"],
            },
        ],
    }


def test_complete_file_capability_manifest_is_accepted() -> None:
    _assert_file_capabilities_complete(_complete_manifest())


@pytest.mark.parametrize(
    ("item_index", "field", "value", "expected_code"),
    (
        (0, "batch_upload_claimed", False, "BROWSER_GATE_FILE_BATCH_UPLOAD_INVALID"),
        (0, "action_codes", [], "BROWSER_GATE_FILE_ARCHIVE_INVALID"),
        (1, "job_attempt_no", 1, "BROWSER_GATE_FILE_RETRY_INVALID"),
    ),
)
def test_incomplete_file_capability_manifest_is_rejected(
    item_index: int,
    field: str,
    value: object,
    expected_code: str,
) -> None:
    manifest = deepcopy(_complete_manifest())
    items = manifest["items"]
    assert type(items) is list
    item = items[item_index]
    assert type(item) is dict
    item[field] = value

    with pytest.raises(RuntimeError, match=expected_code):
        _assert_file_capabilities_complete(manifest)


def test_synthetic_scanner_failure_marker_fails_only_once_per_payload() -> None:
    server = _SyntheticClamdServer(("127.0.0.1", 0), _SyntheticClamdHandler)
    try:
        marked = b"%PDF synthetic " + _SYNTHETIC_SCAN_FAIL_ONCE_MARKER
        assert server.should_fail_once(marked) is True
        assert server.should_fail_once(marked) is False
        assert server.should_fail_once(b"%PDF clean") is False
    finally:
        server.server_close()
