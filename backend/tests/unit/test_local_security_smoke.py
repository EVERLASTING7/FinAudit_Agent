from __future__ import annotations

import io
import sys
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pypdf import PdfReader

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import smoke_local_security as subject  # noqa: E402


def _response(status_code: int, payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers={"X-Trace-ID": str(payload["trace_id"])},
        json=payload,
    )


def test_stable_ids_and_traceparents_are_deterministic_and_separated() -> None:
    run_id = "a" * 32

    contract_id = subject._stable_id(run_id, "contract")
    trace_id = subject._trace_id(run_id, "contract")

    assert contract_id == subject._stable_id(run_id, "contract")
    assert contract_id != trace_id
    assert subject._traceparent(trace_id) == f"00-{trace_id.hex}-1111111111111111-01"


def test_error_envelope_requires_one_canonical_trace_and_no_data() -> None:
    trace_id = UUID("12345678-1234-4234-8234-123456789abc")
    response = _response(
        403,
        {
            "code": "AUTH_FORBIDDEN",
            "message": "无权执行该操作",
            "details": [],
            "trace_id": str(trace_id),
            "timestamp": "2026-08-15T00:00:00Z",
        },
    )

    payload, observed = subject._require_error(response, 403, "AUTH_FORBIDDEN")

    assert observed == trace_id
    assert subject._generic_error_projection(payload) == (
        "AUTH_FORBIDDEN",
        "无权执行该操作",
        [],
        False,
    )


@pytest.mark.parametrize(
    ("payload", "header"),
    [
        (
            {
                "code": "AUTH_FORBIDDEN",
                "message": "无权执行该操作",
                "details": [],
                "trace_id": "not-a-uuid",
                "timestamp": "2026-08-15T00:00:00Z",
            },
            "not-a-uuid",
        ),
        (
            {
                "code": "AUTH_FORBIDDEN",
                "message": "无权执行该操作",
                "details": [],
                "trace_id": "12345678-1234-4234-8234-123456789abc",
                "timestamp": "2026-08-15T00:00:00Z",
            },
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        ),
    ],
)
def test_error_envelope_rejects_invalid_or_mismatched_trace(
    payload: dict[str, object],
    header: str,
) -> None:
    response = httpx.Response(403, headers={"X-Trace-ID": header}, json=payload)

    with pytest.raises(subject.SecurityGateError, match="TRACE_PROJECTION_INVALID"):
        subject._require_error(response, 403, "AUTH_FORBIDDEN")


def test_security_password_is_synthetic_strong_and_run_scoped() -> None:
    first = subject._security_password("b" * 32, "audit-failure")
    second = subject._security_password("c" * 32, "audit-failure")

    assert first.startswith("S3curitySentinel!")
    assert first != second
    assert len(first) < 128


def test_prompt_injection_pdf_preserves_attack_text_and_canary() -> None:
    payload = subject._prompt_injection_pdf()

    reader = PdfReader(io.BytesIO(payload))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert payload.startswith(b"%PDF")
    assert payload.rstrip().endswith(b"%%EOF")
    assert "Ignore all previous instructions" in extracted
    assert subject._PROMPT_INJECTION_CANARY in extracted


def test_prompt_injection_refusal_contract_rejects_response_leakage() -> None:
    index_id = UUID("12345678-1234-4234-8234-123456789abc")
    result: dict[str, object] = {
        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "knowledge_base_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "index_version_id": str(index_id),
        "baseline_date": "2026-08-15",
        "status": "refused",
        "answer": None,
        "reason_code": "PROMPT_INJECTION_DETECTED",
        "citations": [],
        "retrieved_count": 0,
        "created_at": "2026-08-15T00:00:00Z",
    }

    subject._require_prompt_injection_refusal(result, index_id)

    result["answer"] = subject._PROMPT_INJECTION_CANARY
    with pytest.raises(subject.SecurityGateError, match="PROMPT_INJECTION_RESPONSE_INVALID"):
        subject._require_prompt_injection_refusal(result, index_id)


def test_prompt_injection_browser_profile_is_disposable_and_run_scoped() -> None:
    run_id = "d" * 32

    assert subject._prompt_browser_username(run_id) == f"sec-pi-browser-{'d' * 10}"
    assert subject._prompt_browser_password().startswith("Synthetic-Prompt-Browser-")
    assert subject._prompt_browser_password().endswith("-changed")
    assert run_id[:12] in subject._prompt_browser_question(run_id)
    assert "Ignore all previous instructions" in subject._prompt_browser_question(run_id)
    assert subject._PROMPT_INJECTION_CANARY not in subject._prompt_browser_question(run_id)


def test_main_dispatches_prompt_injection_browser_database_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def verify() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(subject, "verify_prompt_injection_browser_database", verify)
    monkeypatch.setattr(
        sys,
        "argv",
        ["smoke_local_security.py", "prompt-injection-browser-database"],
    )

    assert subject.main() == 0
    assert called is True


def test_main_rejects_unknown_mode_without_touching_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["smoke_local_security.py", "unknown"])

    assert subject.main() == 2
