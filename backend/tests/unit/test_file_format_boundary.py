import io
import json
import lzma
import socket
import struct
import warnings
import zipfile
import zlib
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any

import pytest

from app.core.errors import AppError
from app.services import file_service
from app.services.file_service import validate_file_format

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "tests" / "fixtures" / "manifest.json"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCX_CORE_XML = {
    "[Content_Types].xml": b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
    "_rels/.rels": b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>""",
    "word/document.xml": b"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>""",
    "word/styles.xml": b"""<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>""",
}


def _binary_asset(asset_id: str) -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    matches = [asset for asset in manifest["binary_assets"] if asset["id"] == asset_id]
    assert len(matches) == 1
    return matches[0]


def _asset_path(asset: dict[str, Any]) -> Path:
    path = ROOT / asset["file"]
    assert path.is_file()
    return path


def _zip_bytes(*names: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name in names:
            archive.writestr(name, b"test")
    return stream.getvalue()


def _docx_bytes(
    *,
    replacements: dict[str, bytes] | None = None,
    duplicate_core_name: str | None = None,
    extra_entries: int = 0,
    omitted_members: frozenset[str] = frozenset(),
) -> bytes:
    members = DOCX_CORE_XML | (replacements or {})
    stream = io.BytesIO()
    with (
        warnings.catch_warnings(),
        zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive,
    ):
        warnings.simplefilter("ignore", UserWarning)
        for name, content in members.items():
            if name not in omitted_members:
                archive.writestr(name, content)
        if duplicate_core_name is not None:
            archive.writestr(duplicate_core_name, members[duplicate_core_name])
        for index in range(extra_entries):
            archive.writestr(f"extra/{index:04d}.txt", b"")
    return stream.getvalue()


def _mutate_eocd(payload: bytes, *, field_offset: int, value: int, size: int) -> bytes:
    result = bytearray(payload)
    eocd_offset = result.rfind(b"PK\x05\x06")
    assert eocd_offset >= 0
    if size == 2:
        struct.pack_into("<H", result, eocd_offset + field_offset, value)
    else:
        struct.pack_into("<I", result, eocd_offset + field_offset, value)
    return bytes(result)


@pytest.mark.parametrize(
    "asset_id",
    [
        "BIN-PDF-SCAN-C001",
        "BIN-DOCX-COMPLEX-C002",
        "BIN-DOCX-SUPPLEMENT-S001",
        "BIN-DOCX-POLICY-P001-V1",
        "BIN-DOCX-POLICY-PINJECT",
        "BIN-IMAGE-INVOICE-I001-CLEAR",
        "BIN-IMAGE-INVOICE-I002-BLURRED",
        "BIN-IMAGE-INVOICE-I003-ROTATED",
    ],
)
def test_validate_file_format_accepts_manifest_backed_supported_files(asset_id: str) -> None:
    asset = _binary_asset(asset_id)
    path = _asset_path(asset)

    with path.open("rb") as stream:
        validate_file_format(
            stream,
            file_name=path.name,
            declared_mime=asset["declared_mime"],
        )


@pytest.mark.parametrize("file_name", ["unsupported.txt", "missing-extension"])
def test_validate_file_format_rejects_unknown_or_missing_extension(file_name: str) -> None:
    stream = io.BytesIO(b"untrusted")
    stream.seek(3)

    with pytest.raises(AppError) as exc_info:
        validate_file_format(stream, file_name=file_name, declared_mime="application/pdf")

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "FILE_FORMAT_NOT_SUPPORTED"
    assert exc_info.value.message == "文件格式不支持"
    assert exc_info.value.details == []
    assert stream.tell() == 3


def test_validate_file_format_rejects_manifest_mime_spoof_without_echoing_input() -> None:
    asset = _binary_asset("BIN-PDF-MIME-SPOOF")
    path = _asset_path(asset)
    assert asset["expected_static_result"] == "reject_signature"

    with path.open("rb") as stream, pytest.raises(AppError) as exc_info:
        validate_file_format(
            stream,
            file_name=path.name,
            declared_mime=asset["declared_mime"],
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"
    assert exc_info.value.message == "文件签名不匹配"
    assert exc_info.value.details == []
    assert path.name not in exc_info.value.message


def test_validate_file_format_rejects_declared_mime_mismatch() -> None:
    asset = _binary_asset("BIN-PDF-SCAN-C001")
    path = _asset_path(asset)

    with path.open("rb") as stream, pytest.raises(AppError) as exc_info:
        validate_file_format(
            stream,
            file_name=path.name,
            declared_mime="application/octet-stream",
        )

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"


def test_validate_file_format_rejects_extension_and_detected_format_mismatch() -> None:
    asset = _binary_asset("BIN-IMAGE-INVOICE-I001-CLEAR")
    path = _asset_path(asset)

    with path.open("rb") as stream, pytest.raises(AppError) as exc_info:
        validate_file_format(
            stream,
            file_name="renamed.pdf",
            declared_mime="application/pdf",
        )

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"


def test_validate_file_format_rejects_plain_zip_as_docx() -> None:
    stream = io.BytesIO(_zip_bytes("plain.txt"))

    with pytest.raises(AppError) as exc_info:
        validate_file_format(
            stream,
            file_name="plain.docx",
            declared_mime=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
        )

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"


def test_validate_file_format_accepts_docx_without_optional_styles_part() -> None:
    stream = io.BytesIO(_docx_bytes(omitted_members=frozenset({"word/styles.xml"})))

    validate_file_format(
        stream,
        file_name="minimal.docx",
        declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def test_validate_file_format_accepts_docx_from_python_310_spooled_file() -> None:
    with SpooledTemporaryFile(mode="w+b") as stream:
        stream.write(_docx_bytes())
        stream.seek(0)

        assert (
            validate_file_format(
                stream,
                file_name="spooled.docx",
                declared_mime=DOCX_MIME,
            )
            == DOCX_MIME
        )
        assert stream.tell() == 0


def test_validate_file_format_rejects_5000_entry_zip_before_zipfile_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _docx_bytes(extra_entries=5000 - len(DOCX_CORE_XML))
    opened = False

    def fail_zipfile(*args: Any, **kwargs: Any) -> zipfile.ZipFile:
        nonlocal opened
        opened = True
        raise AssertionError("oversized directory must be rejected before ZipFile")

    monkeypatch.setattr(file_service.zipfile, "ZipFile", fail_zipfile)
    with pytest.raises(AppError) as exc_info:
        validate_file_format(io.BytesIO(payload), file_name="many.docx", declared_mime=DOCX_MIME)

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"
    assert opened is False


def test_validate_file_format_rejects_false_eocd_entry_count_before_zipfile_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = bytearray(_docx_bytes(extra_entries=4097 - len(DOCX_CORE_XML)))
    eocd_offset = payload.rfind(b"PK\x05\x06")
    assert eocd_offset >= 0
    struct.pack_into("<H", payload, eocd_offset + 8, 1)
    struct.pack_into("<H", payload, eocd_offset + 10, 1)
    opened = False

    def fail_zipfile(*args: Any, **kwargs: Any) -> zipfile.ZipFile:
        nonlocal opened
        opened = True
        raise AssertionError("mismatched entry count must be rejected before ZipFile")

    monkeypatch.setattr(file_service.zipfile, "ZipFile", fail_zipfile)
    with pytest.raises(AppError) as exc_info:
        validate_file_format(
            io.BytesIO(payload),
            file_name="false-count.docx",
            declared_mime=DOCX_MIME,
        )

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"
    assert opened is False


@pytest.mark.parametrize(
    ("core_name", "invalid_xml"),
    [
        (
            "[Content_Types].xml",
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        ),
        (
            "_rels/.rels",
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        ),
        (
            "word/document.xml",
            b'<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
        ),
    ],
)
def test_validate_file_format_rejects_invalid_core_xml_contract(
    core_name: str,
    invalid_xml: bytes,
) -> None:
    payload = _docx_bytes(replacements={core_name: invalid_xml})

    with pytest.raises(AppError) as exc_info:
        validate_file_format(io.BytesIO(payload), file_name="invalid.docx", declared_mime=DOCX_MIME)

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"


def test_validate_file_format_rejects_malformed_core_xml() -> None:
    payload = _docx_bytes(replacements={"word/document.xml": b"<broken"})

    with pytest.raises(AppError) as exc_info:
        validate_file_format(io.BytesIO(payload), file_name="broken.docx", declared_mime=DOCX_MIME)

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"


@pytest.mark.parametrize(
    "decompression_error",
    [zlib.error("synthetic corrupt deflate"), lzma.LZMAError("synthetic corrupt lzma")],
)
def test_validate_file_format_normalizes_decompression_errors(
    monkeypatch: pytest.MonkeyPatch,
    decompression_error: Exception,
) -> None:
    stream = io.BytesIO(_docx_bytes())
    stream.seek(3)

    def fail_read(*args: Any, **kwargs: Any) -> bytes:
        raise decompression_error

    monkeypatch.setattr(zipfile.ZipFile, "read", fail_read)
    with pytest.raises(AppError) as exc_info:
        validate_file_format(stream, file_name="corrupt.docx", declared_mime=DOCX_MIME)

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"
    assert stream.tell() == 3


def test_validate_file_format_rejects_32_mib_core_before_decompression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _docx_bytes(replacements={"word/document.xml": b"A" * (32 * 1024 * 1024)})
    opened = False

    def fail_open(*args: Any, **kwargs: Any) -> Any:
        nonlocal opened
        opened = True
        raise AssertionError("oversized core must not be decompressed")

    monkeypatch.setattr(zipfile.ZipFile, "open", fail_open)
    with pytest.raises(AppError) as exc_info:
        validate_file_format(io.BytesIO(payload), file_name="bomb.docx", declared_mime=DOCX_MIME)

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"
    assert opened is False


def test_validate_file_format_rejects_high_ratio_core_before_decompression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _docx_bytes(replacements={"word/document.xml": b"A" * (1024 * 1024)})
    opened = False

    def fail_open(*args: Any, **kwargs: Any) -> Any:
        nonlocal opened
        opened = True
        raise AssertionError("high-ratio core must not be decompressed")

    monkeypatch.setattr(zipfile.ZipFile, "open", fail_open)
    with pytest.raises(AppError) as exc_info:
        validate_file_format(io.BytesIO(payload), file_name="ratio.docx", declared_mime=DOCX_MIME)

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"
    assert opened is False


def test_validate_file_format_rejects_high_ratio_non_core_before_decompression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _docx_bytes(replacements={"word/media/huge.bin": b"A" * (1024 * 1024)})
    opened = False

    def fail_open(*args: Any, **kwargs: Any) -> Any:
        nonlocal opened
        opened = True
        raise AssertionError("high-ratio archive member must not be decompressed")

    monkeypatch.setattr(zipfile.ZipFile, "open", fail_open)
    with pytest.raises(AppError) as exc_info:
        validate_file_format(
            io.BytesIO(payload),
            file_name="non-core-bomb.docx",
            declared_mime=DOCX_MIME,
        )

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"
    assert opened is False


def test_validate_file_format_rejects_duplicate_core_member() -> None:
    payload = _docx_bytes(duplicate_core_name="word/document.xml")

    with pytest.raises(AppError) as exc_info:
        validate_file_format(
            io.BytesIO(payload), file_name="duplicate.docx", declared_mime=DOCX_MIME
        )

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"


@pytest.mark.parametrize(
    "payload",
    [
        _mutate_eocd(_docx_bytes(), field_offset=8, value=0xFFFF, size=2),
        _mutate_eocd(_docx_bytes(), field_offset=10, value=0xFFFF, size=2),
        _mutate_eocd(_docx_bytes(), field_offset=4, value=1, size=2),
        _mutate_eocd(_docx_bytes(), field_offset=12, value=4 * 1024 * 1024 + 1, size=4),
        _docx_bytes() + b"trailing-data",
    ],
)
def test_validate_file_format_rejects_zip64_multidisk_or_abnormal_eocd(payload: bytes) -> None:
    with pytest.raises(AppError) as exc_info:
        validate_file_format(io.BytesIO(payload), file_name="unsafe.docx", declared_mime=DOCX_MIME)

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"


@pytest.mark.parametrize(
    ("file_name", "declared_mime", "content"),
    [
        ("truncated.pdf", "application/pdf", b"%PDF"),
        ("truncated.png", "image/png", b"\x89PNG\r\n\x1a"),
        ("truncated.jpg", "image/jpeg", b"\xff\xd8"),
        (
            "truncated.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04",
        ),
    ],
)
def test_validate_file_format_rejects_truncated_signatures_or_container(
    file_name: str,
    declared_mime: str,
    content: bytes,
) -> None:
    with pytest.raises(AppError) as exc_info:
        validate_file_format(
            io.BytesIO(content),
            file_name=file_name,
            declared_mime=declared_mime,
        )

    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"


def test_validate_file_format_restores_cursor_after_success_and_failure() -> None:
    valid = io.BytesIO(b"%PDF-1.7-valid")
    valid.seek(6)
    validate_file_format(valid, file_name="valid.pdf", declared_mime="application/pdf")
    assert valid.tell() == 6

    invalid = io.BytesIO(b"prefix-not-a-pdf")
    invalid.seek(6)
    with pytest.raises(AppError):
        validate_file_format(invalid, file_name="invalid.pdf", declared_mime="application/pdf")
    assert invalid.tell() == 6


def test_validate_file_format_does_not_open_socket_or_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = _binary_asset("BIN-PDF-SCAN-C001")
    payload = _asset_path(asset).read_bytes()

    class ReadOnlyStream(io.BytesIO):
        def write(self, data: Any) -> int:
            raise AssertionError("format validation must not write")

        def truncate(self, size: int | None = None) -> int:
            raise AssertionError("format validation must not truncate")

    def fail_socket(*args: Any, **kwargs: Any) -> socket.socket:
        raise AssertionError("format validation must not open sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    stream = ReadOnlyStream(payload)
    validate_file_format(
        stream,
        file_name="offline.pdf",
        declared_mime="application/pdf",
    )
