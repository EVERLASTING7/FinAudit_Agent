from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import smoke_local_worker_crash_recovery as subject  # noqa: E402


def test_crash_contract_docx_is_valid_and_run_scoped() -> None:
    run_id = "a" * 32

    payload = subject._crash_contract_docx(run_id)

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    assert subject._contract_no(run_id) == "CRASH-AAAAAAAAAAAA"
    assert "合同编号: CRASH-AAAAAAAAAAAA" in document
    assert "合同名称: Worker 崩溃恢复合同" in document
    assert "合同金额: 100000.00 CNY" in document


def test_crash_contract_docx_rejects_invalid_run_id() -> None:
    with pytest.raises(subject.CrashRecoveryError, match="RUN_ID_INVALID"):
        subject._crash_contract_docx("not-a-run-id")
