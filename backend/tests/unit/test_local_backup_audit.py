from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from audit_local_backups import BackupAuditError, audit_backups  # noqa: E402


def _write_backup(root: Path, project: str, created_at: datetime) -> Path:
    directory = root / project / created_at.strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True)
    database = b"synthetic-postgresql-dump"
    minio = b"synthetic-minio-archive"
    (directory / "postgresql.dump").write_bytes(database)
    (directory / "minio-data.tar.gz").write_bytes(minio)
    manifest = {
        "schemaVersion": "finaudit-local-authoritative-backup-v1",
        "backupId": str(uuid4()),
        "createdAtUtc": created_at.isoformat(),
        "sourceProjectName": project,
        "includesSecrets": False,
        "database": {
            "file": "postgresql.dump",
            "sha256": hashlib.sha256(database).hexdigest(),
            "bytes": len(database),
            "rows": {"organizations": 1},
        },
        "minio": {
            "file": "minio-data.tar.gz",
            "sha256": hashlib.sha256(minio).hexdigest(),
            "bytes": len(minio),
        },
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return directory


def test_audit_accepts_complete_fresh_backups_and_reports_retention(tmp_path: Path) -> None:
    now = datetime(2026, 8, 18, 2, tzinfo=timezone.utc)
    _write_backup(tmp_path, "finaudit-local", now - timedelta(days=40))
    _write_backup(tmp_path, "finaudit-local", now - timedelta(hours=2))

    result = audit_backups(
        tmp_path,
        "finaudit-local",
        now=now,
        max_age_hours=24,
        minimum_complete=2,
        retention_days=30,
    )

    assert result == {
        "schema": "finaudit-local-backup-audit-v1",
        "complete": 2,
        "newest_age_minutes": 120,
        "retention_candidates": 1,
    }


def test_audit_rejects_tampered_payload(tmp_path: Path) -> None:
    now = datetime(2026, 8, 18, 2, tzinfo=timezone.utc)
    directory = _write_backup(tmp_path, "finaudit-local", now - timedelta(hours=1))
    (directory / "postgresql.dump").write_bytes(b"tampered")

    with pytest.raises(BackupAuditError, match="integrity check failed"):
        audit_backups(
            tmp_path,
            "finaudit-local",
            now=now,
            max_age_hours=24,
            minimum_complete=1,
            retention_days=30,
        )


def test_audit_accepts_dotnet_seven_digit_utc_timestamp(tmp_path: Path) -> None:
    now = datetime(2026, 8, 18, 2, tzinfo=timezone.utc)
    directory = _write_backup(tmp_path, "finaudit-local", now - timedelta(hours=1))
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["createdAtUtc"] = "2026-08-18T01:00:00.1234567+00:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = audit_backups(
        tmp_path,
        "finaudit-local",
        now=now,
        max_age_hours=24,
        minimum_complete=1,
        retention_days=30,
    )

    assert result["newest_age_minutes"] == 59


@pytest.mark.parametrize("failure", ["incomplete", "stale"])
def test_audit_rejects_incomplete_or_stale_backups(tmp_path: Path, failure: str) -> None:
    now = datetime(2026, 8, 18, 2, tzinfo=timezone.utc)
    directory = _write_backup(tmp_path, "finaudit-local", now - timedelta(hours=30))
    if failure == "incomplete":
        (directory / ".finaudit-backup-incomplete").write_text("incomplete", encoding="utf-8")

    expected = "incomplete backup" if failure == "incomplete" else "newest complete backup is stale"
    with pytest.raises(BackupAuditError, match=expected):
        audit_backups(
            tmp_path,
            "finaudit-local",
            now=now,
            max_age_hours=24,
            minimum_complete=1,
            retention_days=30,
        )
