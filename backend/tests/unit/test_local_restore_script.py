from __future__ import annotations

from pathlib import Path


def test_restore_rebinds_bootstrap_identity_before_starting_application() -> None:
    project_root = Path(__file__).resolve().parents[3]
    source = (project_root / "scripts/restore-local-stack.ps1").read_text(encoding="utf-8")

    identity = source.index("Get-RestoredBootstrapIdentity $composeArguments")
    profile = source.index("BOOTSTRAP_ADMIN_USERNAME=$($restoredIdentity.adminUsername)")
    application = source.index("$composeArguments + @('up', '--detach')", profile)

    assert identity < profile < application
    assert "LOCAL_STACK_RESTORE_BOOTSTRAP_IDENTITY=VERIFIED_FROM_BACKUP" in source
    assert "LOCAL_STACK_RESTORE_PASSWORD=RESTORED_DATABASE_STATE" in source
    assert "USE_EXISTING_SOURCE_ADMIN_PASSWORD" not in source
