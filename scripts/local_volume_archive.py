from __future__ import annotations

import hashlib
import os
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol


class VolumeArchiveError(RuntimeError):
    pass


class _Digest(Protocol):
    def update(self, data: bytes) -> object: ...


def _require_absolute_directory(path: Path, *, empty: bool = False) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise VolumeArchiveError("VOLUME_DIRECTORY_INVALID")
    resolved = path.resolve(strict=True)
    if empty and any(resolved.iterdir()):
        raise VolumeArchiveError("VOLUME_DIRECTORY_NOT_EMPTY")
    return resolved


def _require_archive_path(path: Path, *, must_exist: bool) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise VolumeArchiveError("ARCHIVE_PATH_INVALID")
    parent = path.parent.resolve(strict=True)
    resolved = parent / path.name
    if must_exist:
        if not resolved.is_file() or resolved.is_symlink():
            raise VolumeArchiveError("ARCHIVE_PATH_INVALID")
    elif resolved.exists():
        raise VolumeArchiveError("ARCHIVE_ALREADY_EXISTS")
    return resolved


def _hash_stream(stream: BinaryIO, digest: _Digest) -> int:
    size = 0
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return size


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        _hash_stream(stream, digest)
    return digest.hexdigest()


def volume_digest(root: Path) -> tuple[str, int, int]:
    resolved = _require_absolute_directory(root)
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    for candidate in sorted(resolved.rglob("*"), key=lambda item: item.as_posix()):
        relative = candidate.relative_to(resolved).as_posix()
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise VolumeArchiveError("VOLUME_SYMLINK_NOT_ALLOWED")
        if stat.S_ISDIR(info.st_mode):
            digest.update(b"D\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            continue
        if not stat.S_ISREG(info.st_mode):
            raise VolumeArchiveError("VOLUME_ENTRY_TYPE_NOT_ALLOWED")
        digest.update(b"F\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with candidate.open("rb") as stream:
            size = _hash_stream(stream, digest)
        digest.update(b"\0")
        file_count += 1
        total_bytes += size
    return digest.hexdigest(), file_count, total_bytes


def _safe_tar_info(info: tarfile.TarInfo) -> tarfile.TarInfo:
    if not (info.isfile() or info.isdir()):
        raise VolumeArchiveError("VOLUME_ENTRY_TYPE_NOT_ALLOWED")
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def create_archive(root: Path, archive_path: Path) -> tuple[str, int, int, str]:
    resolved_root = _require_absolute_directory(root)
    resolved_archive = _require_archive_path(archive_path, must_exist=False)
    volume_sha256, file_count, total_bytes = volume_digest(resolved_root)
    with tarfile.open(resolved_archive, mode="x:gz", compresslevel=6) as archive:
        for candidate in sorted(resolved_root.iterdir(), key=lambda item: item.name):
            archive.add(
                candidate,
                arcname=candidate.name,
                recursive=True,
                filter=_safe_tar_info,
            )
    archive_sha256 = _file_sha256(resolved_archive)
    return volume_sha256, file_count, total_bytes, archive_sha256


def _validate_members(members: list[tarfile.TarInfo]) -> None:
    seen: set[str] = set()
    for member in members:
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise VolumeArchiveError("ARCHIVE_MEMBER_PATH_INVALID")
        if not (member.isfile() or member.isdir()):
            raise VolumeArchiveError("ARCHIVE_MEMBER_TYPE_NOT_ALLOWED")
        normalized = path.as_posix()
        if normalized in seen:
            raise VolumeArchiveError("ARCHIVE_MEMBER_DUPLICATE")
        seen.add(normalized)


def extract_archive(root: Path, archive_path: Path) -> tuple[str, int, int, str]:
    resolved_root = _require_absolute_directory(root, empty=True)
    resolved_archive = _require_archive_path(archive_path, must_exist=True)
    archive_sha256 = _file_sha256(resolved_archive)
    with tarfile.open(resolved_archive, mode="r:gz") as archive:
        members = archive.getmembers()
        _validate_members(members)
        archive.extractall(path=resolved_root, members=members)
    volume_sha256, file_count, total_bytes = volume_digest(resolved_root)
    return volume_sha256, file_count, total_bytes, archive_sha256


def main() -> int:
    try:
        if sys.argv != [sys.argv[0]]:
            raise VolumeArchiveError("ARGUMENTS_NOT_SUPPORTED")
        mode = os.environ.get("FINAUDIT_VOLUME_ARCHIVE_MODE")
        root_value = os.environ.get("FINAUDIT_VOLUME_ROOT")
        archive_value = os.environ.get("FINAUDIT_VOLUME_ARCHIVE")
        if mode not in {"create", "extract", "digest"} or not root_value:
            raise VolumeArchiveError("ARCHIVE_CONFIGURATION_INVALID")
        root = Path(root_value)
        if mode == "digest":
            volume_sha256, file_count, total_bytes = volume_digest(root)
            archive_sha256 = None
        else:
            if not archive_value:
                raise VolumeArchiveError("ARCHIVE_CONFIGURATION_INVALID")
            operation = create_archive if mode == "create" else extract_archive
            volume_sha256, file_count, total_bytes, archive_sha256 = operation(
                root,
                Path(archive_value),
            )
    except (OSError, tarfile.TarError, VolumeArchiveError):
        print("LOCAL_VOLUME_ARCHIVE=FAIL")
        return 1
    except Exception:
        print("LOCAL_VOLUME_ARCHIVE=FAIL")
        return 1

    print("LOCAL_VOLUME_ARCHIVE=PASS")
    print(f"LOCAL_VOLUME_ARCHIVE_MODE={mode.upper()}")
    print(f"LOCAL_VOLUME_FILES={file_count}")
    print(f"LOCAL_VOLUME_BYTES={total_bytes}")
    print(f"LOCAL_VOLUME_SHA256={volume_sha256}")
    if archive_sha256 is not None:
        print(f"LOCAL_ARCHIVE_SHA256={archive_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
