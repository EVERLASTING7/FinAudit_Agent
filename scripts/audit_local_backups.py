from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID


class BackupAuditError(RuntimeError):
    pass


_PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{2,39}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BackupAuditError(f"{label} must be an object")
    return value


def _payload_path(directory: Path, section: dict[str, Any], label: str) -> Path:
    name = section.get("file")
    if not isinstance(name, str) or Path(name).name != name:
        raise BackupAuditError(f"{label} file name is invalid")
    path = directory / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != directory.resolve():
        raise BackupAuditError(f"{label} payload is missing or escaped its backup")
    expected_bytes = section.get("bytes")
    expected_hash = section.get("sha256")
    if (
        not isinstance(expected_bytes, int)
        or isinstance(expected_bytes, bool)
        or expected_bytes < 0
        or not isinstance(expected_hash, str)
        or _SHA256.fullmatch(expected_hash) is None
    ):
        raise BackupAuditError(f"{label} metadata is invalid")
    if path.stat().st_size != expected_bytes or _sha256(path) != expected_hash:
        raise BackupAuditError(f"{label} payload integrity check failed")
    return path


def _created_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise BackupAuditError("createdAtUtc is invalid")
    normalized = re.sub(
        r"(\.\d{6})\d+(?=(?:Z|[+-]\d{2}:\d{2})$)",
        r"\1",
        value,
    )
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise BackupAuditError("createdAtUtc is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise BackupAuditError("createdAtUtc must use UTC")
    return parsed.astimezone(timezone.utc)


def audit_backups(
    backup_root: Path,
    project_name: str,
    *,
    now: datetime,
    max_age_hours: int,
    minimum_complete: int,
    retention_days: int,
) -> dict[str, int | str]:
    if _PROJECT_NAME.fullmatch(project_name) is None:
        raise BackupAuditError("project name is invalid")
    if max_age_hours <= 0 or minimum_complete <= 0 or retention_days <= 0:
        raise BackupAuditError("audit limits must be positive")
    if now.tzinfo is None:
        raise BackupAuditError("audit clock must be timezone-aware")
    now = now.astimezone(timezone.utc)

    root = backup_root.resolve(strict=True)
    project_directory = (root / project_name).resolve(strict=True)
    if project_directory.parent != root or not project_directory.is_dir():
        raise BackupAuditError("project backup directory escaped its approved root")

    backups: list[tuple[datetime, UUID]] = []
    for directory in sorted(project_directory.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or directory.is_symlink():
            raise BackupAuditError("project backup root contains an unexpected entry")
        if directory.resolve().parent != project_directory:
            raise BackupAuditError("backup directory escaped its project root")
        if (directory / ".finaudit-backup-incomplete").exists():
            raise BackupAuditError("an incomplete backup requires operator attention")
        manifest_path = directory / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise BackupAuditError("a backup manifest is missing")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupAuditError("a backup manifest is invalid") from exc
        manifest = _required_object(manifest, "manifest")
        if (
            manifest.get("schemaVersion") != "finaudit-local-authoritative-backup-v1"
            or manifest.get("sourceProjectName") != project_name
            or manifest.get("includesSecrets") is not False
        ):
            raise BackupAuditError("a backup manifest violates the local authority contract")
        try:
            backup_id = UUID(str(manifest.get("backupId")))
        except ValueError as exc:
            raise BackupAuditError("backupId is invalid") from exc
        created_at = _created_at(manifest.get("createdAtUtc"))
        if created_at > now + timedelta(minutes=5):
            raise BackupAuditError("a backup timestamp is in the future")

        database = _required_object(manifest.get("database"), "database")
        minio = _required_object(manifest.get("minio"), "minio")
        database_path = _payload_path(directory, database, "database")
        minio_path = _payload_path(directory, minio, "minio")
        expected_files = {"manifest.json", database_path.name, minio_path.name}
        entries = list(directory.iterdir())
        if any(not path.is_file() for path in entries):
            raise BackupAuditError("a backup contains an unexpected directory")
        actual_files = {path.name for path in entries}
        if actual_files != expected_files:
            raise BackupAuditError("a backup contains unexpected or missing files")
        backups.append((created_at, backup_id))

    if len(backups) < minimum_complete:
        raise BackupAuditError("not enough complete backups are available")
    if len({backup_id for _, backup_id in backups}) != len(backups):
        raise BackupAuditError("backupId values are not unique")

    newest = max(created_at for created_at, _ in backups)
    newest_age = now - newest
    if newest_age > timedelta(hours=max_age_hours):
        raise BackupAuditError("the newest complete backup is stale")
    retention_cutoff = now - timedelta(days=retention_days)
    retention_candidates = sum(created_at < retention_cutoff for created_at, _ in backups)
    return {
        "schema": "finaudit-local-backup-audit-v1",
        "complete": len(backups),
        "newest_age_minutes": max(0, int(newest_age.total_seconds() // 60)),
        "retention_candidates": retention_candidates,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit local authoritative backups without mutation."
    )
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--max-age-hours", type=int, default=24)
    parser.add_argument("--minimum-complete", type=int, default=1)
    parser.add_argument("--retention-days", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        result = audit_backups(
            args.backup_root,
            args.project_name,
            now=datetime.now(timezone.utc),
            max_age_hours=args.max_age_hours,
            minimum_complete=args.minimum_complete,
            retention_days=args.retention_days,
        )
    except (BackupAuditError, FileNotFoundError) as exc:
        print(f"LOCAL_BACKUP_AUDIT=FAIL reason={exc}", file=sys.stderr)
        return 1
    print(f"LOCAL_BACKUP_AUDIT_SCHEMA={result['schema']}")
    print(f"LOCAL_BACKUP_COMPLETE={result['complete']}")
    print(f"LOCAL_BACKUP_NEWEST_AGE_MINUTES={result['newest_age_minutes']}")
    print(f"LOCAL_BACKUP_RETENTION_CANDIDATES={result['retention_candidates']}")
    print("LOCAL_BACKUP_MUTATION=NONE")
    print("LOCAL_BACKUP_AUDIT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
