from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "smoke_live_bailian_knowledge_e2e.py"


def _run(*, confirmed: bool) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["EMBEDDING_API_KEY"] = ""
    environment.pop("FINAUDIT_REUSE_REPOSITORY_BAILIAN_KEY", None)
    if confirmed:
        environment["FINAUDIT_LIVE_BAILIAN_KNOWLEDGE_E2E"] = (
            "ALLOW_ONE_BOUNDED_BAILIAN_KNOWLEDGE_E2E_V1"
        )
    else:
        environment.pop("FINAUDIT_LIVE_BAILIAN_KNOWLEDGE_E2E", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )


def test_live_knowledge_e2e_requires_explicit_paid_run_confirmation() -> None:
    result = _run(confirmed=False)

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "code": "LIVE_BAILIAN_KNOWLEDGE_E2E_CONFIRMATION_REQUIRED",
        "status": "failed",
    }
    assert result.stderr == ""


def test_live_knowledge_e2e_requires_key_after_confirmation() -> None:
    result = _run(confirmed=True)

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "code": "EMBEDDING_API_KEY_REQUIRED",
        "status": "failed",
    }
    assert result.stderr == ""
