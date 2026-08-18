from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "smoke_live_bailian_embedding.py"


def _run(*, confirmed: bool) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["EMBEDDING_API_KEY"] = ""
    if confirmed:
        environment["FINAUDIT_LIVE_BAILIAN_SMOKE"] = "ALLOW_ONE_BOUNDED_BAILIAN_EMBEDDING_CALL"
    else:
        environment.pop("FINAUDIT_LIVE_BAILIAN_SMOKE", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )


def test_live_bailian_smoke_requires_explicit_paid_call_confirmation() -> None:
    result = _run(confirmed=False)

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "code": "LIVE_BAILIAN_SMOKE_CONFIRMATION_REQUIRED",
        "status": "failed",
    }
    assert result.stderr == ""


def test_live_bailian_smoke_requires_a_non_placeholder_key_after_confirmation() -> None:
    result = _run(confirmed=True)

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "code": "EMBEDDING_API_KEY_REQUIRED",
        "status": "failed",
    }
    assert result.stderr == ""
