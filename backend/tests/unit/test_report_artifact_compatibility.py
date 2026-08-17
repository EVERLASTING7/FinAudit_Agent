from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import verify_report_artifact_compatibility as subject  # noqa: E402


def test_formal_report_compatibility_fixture_is_stable_and_openable(tmp_path: Path) -> None:
    first = subject.generate_artifacts(tmp_path / "first")
    second = subject.generate_artifacts(tmp_path / "second")

    assert first.schema_version == "report-artifact-compatibility-v1"
    assert first.pdf == second.pdf
    assert first.xlsx == second.xlsx
    assert first.pdf.page_count >= 1
    assert first.xlsx.sheets == ("Summary", "Rules", "Risks")
    assert subject.inspect_artifacts(tmp_path / "first") == first
