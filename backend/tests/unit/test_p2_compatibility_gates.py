from __future__ import annotations

import hashlib
import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_report_browser_gate_requires_verified_native_download() -> None:
    application = (_PROJECT_ROOT / "backend/tests/manual_financial_read_browser.py").read_text(
        encoding="utf-8"
    )
    wrapper = (_PROJECT_ROOT / "scripts/verify-report-browser-gate.ps1").read_text(encoding="utf-8")
    runner = (_PROJECT_ROOT / "scripts/run-browser-gate.cjs").read_text(encoding="utf-8")
    assert "COMPLETE_DISPOSABLE_REPORT_BROWSER_V1" in application
    assert "/__finaudit_test__/report-complete" in application
    assert "BROWSER_GATE_REPORT_NOT_ACCEPTED" in application
    assert "$reportMode" in wrapper
    assert "$automatedBrowserMode = $reportMode" in wrapper
    assert "Browser.setDownloadBehavior" in runner
    assert "Browser.downloadWillBegin" in runner
    assert "Browser.downloadProgress" in runner
    assert "BROWSER_REPORT_NATIVE_DOWNLOAD=PASS" in runner
    assert "BROWSER_REPORT_DOWNLOADED_SHA256" in runner


def test_libreoffice_gate_uses_isolated_profile_timeout_and_output_contract() -> None:
    wrapper = (_PROJECT_ROOT / "scripts/verify-report-artifact-compatibility.ps1").read_text(
        encoding="utf-8"
    )

    assert "RequireLibreOffice" in wrapper
    assert "UserInstallation" in wrapper
    assert "SAL_DISABLE_OPENCL" in wrapper
    assert "WaitForExit" in wrapper
    assert "LIBREOFFICE_OPEN_HOST=PASS" in wrapper
    assert "LIBREOFFICE_OPEN_CONTAINER=PASS" in wrapper
    assert "Summary|Rules|Risks" in wrapper


def test_accessibility_gate_requires_edge_route_matrix_and_assistive_technology() -> None:
    wrapper = (_PROJECT_ROOT / "scripts/verify-report-browser-gate.ps1").read_text(encoding="utf-8")
    runner = (_PROJECT_ROOT / "scripts/run-browser-gate.cjs").read_text(encoding="utf-8")
    narrator_etw = (_PROJECT_ROOT / "scripts/narrator-accessibility-etw.ps1").read_text(
        encoding="utf-8"
    )
    edge_focus = (_PROJECT_ROOT / "scripts/focus-accessibility-edge.ps1").read_text(
        encoding="utf-8"
    )

    assert "'Accessibility'" in wrapper
    assert "ACCESSIBILITY_BROWSER_GATE=PASS" in wrapper
    assert r"Microsoft\\Edge\\Application\\msedge.exe" in runner
    assert "Accessibility.getFullAXTree" in runner
    assert "Input.dispatchKeyEvent" in runner
    assert "BROWSER_ACCESSIBILITY_ROUTE_MATRIX=PASS" in runner
    assert "BROWSER_ACCESSIBILITY_EXPECTED_HTTP_ERRORS=5" in runner
    assert "BROWSER_ACCESSIBILITY_NARRATOR_FOCUS_SEQUENCE=PASS" in runner
    assert "FINAUDIT_NARRATOR_MARKER_PATH" in runner
    assert "BROWSER_ACCESSIBILITY_EDGE_FOREGROUND=PASS" in runner
    assert "Start-FinAuditNarratorEtw" in wrapper
    assert "Stop-FinAuditNarratorEtw" in wrapper
    assert "EDGE_NARRATOR_SCREEN_READER_GATE=PASS" in wrapper
    for event_name in (
        "UiaFocusEventReceived",
        "ProcessFocusChange",
        "InitiateSpeaking",
        "SapiTextSpeak",
        "GenerateAudioStream",
        "AudioPlayBackCompleted",
    ):
        assert event_name in narrator_etw
    assert "NarratorProcessIds" in narrator_etw
    assert "focus_started_utc" in narrator_etw
    assert "focus_completed_utc" in narrator_etw
    assert "Chrome_WidgetWin_1" in edge_focus
    assert "finaudit-browser-gate-" in edge_focus
    assert "SetForegroundWindow" in edge_focus


def test_local_p2_evidence_is_current_and_keeps_acceptance_boundaries() -> None:
    evidence_path = _PROJECT_ROOT / "tests/evaluation/local-p2-experience-compatibility-v1.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert evidence["schema_version"] == "local-p2-experience-compatibility-v1"
    assert evidence["report_download"]["status"] == "passed"
    assert evidence["report_download"]["download_will_begin_observed"] is True
    assert evidence["report_download"]["download_progress_completed"] is True
    assert evidence["report_download"]["size_and_sha256_match_database"] is True
    assert evidence["artifact_compatibility"]["status"] == "passed"
    assert evidence["artifact_compatibility"]["worksheets"] == [
        "Summary",
        "Rules",
        "Risks",
    ]

    accessibility = evidence["accessibility"]
    assert accessibility["status"] == "passed"
    assert accessibility["p0_route_matrix"]["status"] == "passed"
    assert accessibility["p0_route_matrix"]["route_count"] == 20
    assert len(accessibility["p0_route_matrix"]["routes"]) == 20
    assert len(accessibility["expected_http_boundaries"]) == 5
    assert accessibility["narrator"]["status"] == "passed"
    assert accessibility["narrator"]["event_counts"] == {
        "audio_playback_completed": 2,
        "generate_audio_stream": 19,
        "initiate_speaking": 19,
        "process_focus_change": 13,
        "sapi_text_speak": 18,
        "uia_focus_event_received": 13,
    }
    assert accessibility["narrator"]["raw_etl_retained"] is False
    assert accessibility["narrator"]["audio_or_transcript_retained"] is False

    cleanup = evidence["cleanup"]
    assert cleanup == {
        "dedicated_minio_running": False,
        "narrator_process_count": 0,
        "raw_trace_artifact_count": 0,
        "remaining_accessibility_container_count": 0,
        "remaining_edge_profile_process_count": 0,
        "remaining_report_container_count": 0,
        "remaining_trace_session_count": 0,
        "test_port_listener_count": 0,
    }
    assert evidence["acceptance_boundary"] == {
        "formal_human_accessibility_acceptance": False,
        "is_formal_ac_acceptance": False,
        "local_test_p2_accessibility_coverage_closed": True,
        "local_test_p2_report_compatibility_closed": True,
        "production_ready": False,
    }
    assert evidence["verification"] == {
        "backend": {"passed": 3165, "skipped": 147, "warning_count": 1},
        "frontend": {
            "build_module_count": 151,
            "test_count": 539,
            "test_file_count": 28,
            "typecheck": "passed",
        },
        "local_offline_quality": "passed",
        "mypy_source_count": 283,
        "ruff_file_count": 528,
    }

    for source in evidence["source_binding"]:
        source_path = _PROJECT_ROOT / source["path"]
        content = source_path.read_bytes()
        assert len(content) == source["bytes"]
        assert hashlib.sha256(content).hexdigest() == source["sha256"]

    serialized = json.dumps(evidence, sort_keys=True).lower()
    for forbidden in (
        "password_value",
        "api_key_value",
        "access_token",
        "document_content",
        "speech_text",
    ):
        assert forbidden not in serialized
