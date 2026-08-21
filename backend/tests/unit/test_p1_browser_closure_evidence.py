from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_PATH = PROJECT_ROOT / "tests" / "evaluation" / "local-p1-browser-closure-v1.json"


def _mapping(value: object) -> dict[str, object]:
    assert type(value) is dict
    return cast(dict[str, object], value)


def test_p1_browser_closure_evidence_binds_current_sources_and_cleanup() -> None:
    evidence = _mapping(json.loads(EVIDENCE_PATH.read_text(encoding="utf-8")))
    assert evidence["schema_version"] == "local-p1-browser-closure-v1"

    bindings = cast(list[object], evidence["source_binding"])
    for raw_binding in bindings:
        binding = _mapping(raw_binding)
        source = PROJECT_ROOT / str(binding["file"])
        payload = source.read_bytes()
        assert len(payload) == binding["bytes"]
        assert hashlib.sha256(payload).hexdigest().upper() == binding["sha256"]

    for gate_name in ("document_correction_gate", "policy_revocation_gate"):
        gate = _mapping(evidence[gate_name])
        assert gate["status"] == "passed"
        assert gate["console_warning_count"] == 0
        assert gate["console_error_count"] == 0

    cleanup = _mapping(evidence["cleanup"])
    assert cleanup["accepted_run_stale_temp_directory_delta"] == 0
    assert cleanup["document_gate_container_count"] == 0
    assert cleanup["document_gate_network_count"] == 0
    assert cleanup["document_gate_port_listener_count"] == 0
    assert cleanup["policy_gate_container_count"] == 0
    assert cleanup["policy_gate_network_count"] == 0
    assert cleanup["policy_gate_port_listener_count"] == 0
    assert cleanup["historical_failed_run_stale_auth_directory_count"] == 12
    assert cleanup["historical_stale_directory_removal"] == "blocked_by_host_filesystem_policy"

    offline = _mapping(evidence["offline_quality"])
    assert offline == {
        "backend_passed": 3136,
        "backend_skipped": 147,
        "backend_warning_count": 1,
        "frontend_module_count": 151,
        "frontend_test_count": 539,
        "frontend_test_file_count": 28,
        "mypy_source_count": 283,
        "ruff_file_count": 522,
        "status": "passed",
    }
