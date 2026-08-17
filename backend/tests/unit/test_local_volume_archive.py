from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path
from types import ModuleType

import pytest


def _load_archive_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[3] / "scripts" / "local_volume_archive.py"
    spec = importlib.util.spec_from_file_location("finaudit_local_volume_archive", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("LOCAL_VOLUME_ARCHIVE_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_archive_module = _load_archive_module()
VolumeArchiveError = _archive_module.VolumeArchiveError
create_archive = _archive_module.create_archive
extract_archive = _archive_module.extract_archive
volume_digest = _archive_module.volume_digest


def test_archive_round_trip_preserves_volume_digest(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / ".minio.sys").mkdir()
    (source / ".minio.sys" / "config.json").write_bytes(b"system-state")
    (source / "reports").mkdir()
    (source / "reports" / "audit.pdf").write_bytes(b"%PDF-test")
    archive = tmp_path / "minio-data.tar.gz"

    created = create_archive(source, archive)

    target = tmp_path / "target"
    target.mkdir()
    extracted = extract_archive(target, archive)

    assert created == extracted
    assert volume_digest(source) == volume_digest(target)
    assert (target / "reports" / "audit.pdf").read_bytes() == b"%PDF-test"


def test_create_rejects_existing_archive(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    archive = tmp_path / "minio-data.tar.gz"
    archive.write_bytes(b"existing")

    with pytest.raises(VolumeArchiveError, match="ARCHIVE_ALREADY_EXISTS"):
        create_archive(source, archive)


def test_extract_rejects_non_empty_target(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "object").write_bytes(b"content")
    archive = tmp_path / "minio-data.tar.gz"
    create_archive(source, archive)
    target = tmp_path / "target"
    target.mkdir()
    (target / "existing").write_bytes(b"content")

    with pytest.raises(VolumeArchiveError, match="VOLUME_DIRECTORY_NOT_EMPTY"):
        extract_archive(target, archive)


def test_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "malicious.tar.gz"
    with tarfile.open(archive, mode="w:gz") as stream:
        member = tarfile.TarInfo("../outside")
        member.size = 7
        stream.addfile(member, io.BytesIO(b"blocked"))
    target = tmp_path / "target"
    target.mkdir()

    with pytest.raises(VolumeArchiveError, match="ARCHIVE_MEMBER_PATH_INVALID"):
        extract_archive(target, archive)


def test_digest_rejects_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "outside"
    target.write_bytes(b"content")
    link = source / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("当前平台不允许创建测试符号链接")

    with pytest.raises(VolumeArchiveError, match="VOLUME_SYMLINK_NOT_ALLOWED"):
        volume_digest(source)
