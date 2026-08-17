"""文件服务的纯合同判断。"""

from __future__ import annotations

import hashlib
import lzma
import struct
import xml.etree.ElementTree as ElementTree
import zipfile
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, BinaryIO, Final, cast

from pydantic import ValidationError

from app.core.errors import AppError
from app.core.permissions import RoleCode
from app.schemas.files import FileUploadIntent, IntendedBusinessType, SecurityScanStatus

if TYPE_CHECKING:
    from app.services.auth import AuthenticatedActor

_MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
_DOCX_CORE_PARTS = frozenset(
    {
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
    }
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_DOCX_MAX_ENTRY_COUNT = 4096
_DOCX_MAX_CENTRAL_DIRECTORY_BYTES = 4 * 1024 * 1024
_DOCX_MAX_CORE_PART_BYTES = 8 * 1024 * 1024
_DOCX_MAX_TOTAL_CORE_PART_BYTES = 16 * 1024 * 1024
_DOCX_MAX_COMPRESSION_RATIO = 100
_ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP_EOCD_SIZE = 22
_ZIP_MAX_COMMENT_BYTES = 65535
_ZIP_CENTRAL_FILE_HEADER_SIGNATURE = b"PK\x01\x02"
_ZIP_CENTRAL_FILE_HEADER_SIZE = 46

_CONTENT_TYPES_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELATIONSHIPS_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE_DOCUMENT_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
_WORDPROCESSING_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD_DOCUMENT_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
_UPLOAD_ROLES_BY_BUSINESS_TYPE: Final[dict[IntendedBusinessType, frozenset[RoleCode]]] = {
    IntendedBusinessType.CONTRACT: frozenset({"finance_reviewer", "contract_admin"}),
    IntendedBusinessType.SUPPLEMENTARY_AGREEMENT: frozenset({"contract_admin"}),
    IntendedBusinessType.INVOICE: frozenset({"finance_reviewer"}),
    IntendedBusinessType.POLICY: frozenset({"audit_reviewer"}),
}


@dataclass(frozen=True, slots=True)
class UploadContentMetadata:
    """上传内容的一次遍历计量结果。"""

    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class QuarantineIntakeFacts:
    """写入隔离区前已验证、但尚未完成安全扫描的文件事实。"""

    size_bytes: int
    sha256: str
    extension: str
    declared_mime: str
    detected_mime: str
    security_scan_status: SecurityScanStatus = field(
        default=SecurityScanStatus.PENDING,
        init=False,
    )


class _ZipReadableAdapter:
    """为 Python 3.10 的 SpooledTemporaryFile 补齐 zipfile 所需接口。"""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._stream.seek(offset, whence)

    def tell(self) -> int:
        return self._stream.tell()

    @staticmethod
    def seekable() -> bool:
        return True


def validate_file_format(
    stream: BinaryIO,
    *,
    file_name: str,
    declared_mime: str,
) -> str:
    """联合校验扩展名、声明 MIME 和浅层文件签名，并恢复输入游标。"""

    original_position = stream.tell()
    try:
        expected_mime = _MIME_BY_EXTENSION.get(Path(file_name).suffix.lower())
        if expected_mime is None:
            raise AppError(
                status_code=400,
                code="FILE_FORMAT_NOT_SUPPORTED",
                message="文件格式不支持",
            )

        detected_mime = _detect_file_mime(stream)
        if declared_mime != expected_mime or detected_mime != expected_mime:
            raise AppError(
                status_code=400,
                code="FILE_SIGNATURE_MISMATCH",
                message="文件签名不匹配",
            )
        return detected_mime
    finally:
        stream.seek(original_position)


def _detect_file_mime(stream: BinaryIO) -> str | None:
    stream.seek(0)
    signature = stream.read(len(_PNG_SIGNATURE))
    if signature.startswith(b"%PDF-"):
        return "application/pdf"
    if signature == _PNG_SIGNATURE:
        return "image/png"
    if signature.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if signature.startswith(b"PK\x03\x04") and _has_docx_core_parts(stream):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return None


def _has_docx_core_parts(stream: BinaryIO) -> bool:
    if not _has_bounded_zip_central_directory(stream):
        return False

    stream.seek(0)
    try:
        with zipfile.ZipFile(_ZipReadableAdapter(stream)) as archive:
            archive_infos = archive.infolist()
            if not _docx_archive_entries_are_safe(archive_infos):
                return False

            core_infos: dict[str, zipfile.ZipInfo] = {}
            for name in _DOCX_CORE_PARTS:
                matches = [info for info in archive_infos if info.filename == name]
                if len(matches) != 1:
                    return False
                core_infos[name] = matches[0]

            if not _docx_core_sizes_are_safe(core_infos.values()):
                return False

            core_xml = {name: archive.read(info) for name, info in core_infos.items()}
            return _docx_core_xml_is_valid(core_xml)
    except (
        EOFError,
        KeyError,
        lzma.LZMAError,
        NotImplementedError,
        OSError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        zlib.error,
    ):
        return False


def _has_bounded_zip_central_directory(stream: BinaryIO) -> bool:
    try:
        stream.seek(0, 2)
        archive_size = stream.tell()
        tail_size = min(archive_size, _ZIP_EOCD_SIZE + _ZIP_MAX_COMMENT_BYTES)
        stream.seek(archive_size - tail_size)
        tail = stream.read(tail_size)
    except (OSError, ValueError):
        return False

    relative_offset = tail.rfind(_ZIP_EOCD_SIGNATURE)
    if relative_offset < 0 or relative_offset + _ZIP_EOCD_SIZE > len(tail):
        return False

    try:
        (
            disk_number,
            central_directory_disk,
            disk_entry_count,
            total_entry_count,
            central_directory_size,
            central_directory_offset,
            comment_size,
        ) = struct.unpack_from("<4H2IH", tail, relative_offset + 4)
    except struct.error:
        return False

    eocd_offset = archive_size - tail_size + relative_offset
    header_is_safe = bool(
        eocd_offset + _ZIP_EOCD_SIZE + comment_size == archive_size
        and disk_number == 0
        and central_directory_disk == 0
        and disk_entry_count == total_entry_count
        and total_entry_count != 0xFFFF
        and central_directory_size != 0xFFFFFFFF
        and central_directory_offset != 0xFFFFFFFF
        and total_entry_count <= _DOCX_MAX_ENTRY_COUNT
        and central_directory_size <= _DOCX_MAX_CENTRAL_DIRECTORY_BYTES
        and central_directory_offset + central_directory_size == eocd_offset
    )
    return header_is_safe and _central_directory_entry_count_matches(
        stream,
        offset=central_directory_offset,
        size=central_directory_size,
        expected_count=total_entry_count,
    )


def _central_directory_entry_count_matches(
    stream: BinaryIO,
    *,
    offset: int,
    size: int,
    expected_count: int,
) -> bool:
    try:
        stream.seek(offset)
        directory = stream.read(size)
    except (OSError, ValueError):
        return False
    if len(directory) != size:
        return False

    cursor = 0
    actual_count = 0
    while cursor < len(directory):
        if (
            cursor + _ZIP_CENTRAL_FILE_HEADER_SIZE > len(directory)
            or directory[cursor : cursor + 4] != _ZIP_CENTRAL_FILE_HEADER_SIGNATURE
        ):
            return False
        try:
            file_name_size, extra_size, comment_size, disk_number = struct.unpack_from(
                "<4H", directory, cursor + 28
            )
        except struct.error:
            return False
        if disk_number != 0:
            return False

        cursor += _ZIP_CENTRAL_FILE_HEADER_SIZE + file_name_size + extra_size + comment_size
        actual_count += 1
        if cursor > len(directory) or actual_count > _DOCX_MAX_ENTRY_COUNT:
            return False

    return actual_count == expected_count


def _docx_archive_entries_are_safe(infos: Iterable[zipfile.ZipInfo]) -> bool:
    for info in infos:
        if info.flag_bits & 0x1:
            return False
        if info.is_dir() or info.file_size == 0:
            continue
        if info.compress_size <= 0:
            return False
        if info.file_size > info.compress_size * _DOCX_MAX_COMPRESSION_RATIO:
            return False
    return True


def _docx_core_sizes_are_safe(infos: Iterable[zipfile.ZipInfo]) -> bool:
    total_size = 0
    for info in infos:
        if info.is_dir() or info.flag_bits & 0x1:
            return False
        if info.file_size > _DOCX_MAX_CORE_PART_BYTES or info.compress_size <= 0:
            return False
        if info.file_size > info.compress_size * _DOCX_MAX_COMPRESSION_RATIO:
            return False
        total_size += info.file_size
        if total_size > _DOCX_MAX_TOTAL_CORE_PART_BYTES:
            return False
    return True


def _docx_core_xml_is_valid(core_xml: dict[str, bytes]) -> bool:
    try:
        content_types = ElementTree.fromstring(core_xml["[Content_Types].xml"])
        relationships = ElementTree.fromstring(core_xml["_rels/.rels"])
        document = ElementTree.fromstring(core_xml["word/document.xml"])
    except (ElementTree.ParseError, KeyError):
        return False

    content_type_override = any(
        child.tag == f"{{{_CONTENT_TYPES_NAMESPACE}}}Override"
        and child.get("PartName") == "/word/document.xml"
        and child.get("ContentType") == _WORD_DOCUMENT_CONTENT_TYPE
        for child in content_types
    )
    office_document_relationship = any(
        child.tag == f"{{{_RELATIONSHIPS_NAMESPACE}}}Relationship"
        and child.get("Type") == _OFFICE_DOCUMENT_RELATIONSHIP
        and child.get("Target") == "word/document.xml"
        and child.get("TargetMode") in (None, "Internal")
        for child in relationships
    )
    return (
        content_types.tag == f"{{{_CONTENT_TYPES_NAMESPACE}}}Types"
        and content_type_override
        and relationships.tag == f"{{{_RELATIONSHIPS_NAMESPACE}}}Relationships"
        and office_document_relationship
        and document.tag == f"{{{_WORDPROCESSING_NAMESPACE}}}document"
    )


def measure_upload_stream(
    chunks: Iterable[bytes],
    *,
    max_size_bytes: int,
) -> UploadContentMetadata:
    """单次遍历计算上传内容大小和 SHA-256，超限时停止消费输入。"""

    if type(max_size_bytes) is not int or max_size_bytes <= 0:
        raise ValueError("max_size_bytes must be a positive integer")

    total_size = 0
    digest = hashlib.sha256()
    for chunk in chunks:
        if type(chunk) is not bytes:
            raise TypeError("upload chunks must be bytes")
        total_size += len(chunk)
        if total_size > max_size_bytes:
            raise AppError(
                status_code=413,
                code="FILE_TOO_LARGE",
                message="上传文件超过允许大小",
            )
        digest.update(chunk)

    if total_size == 0:
        raise AppError(
            status_code=400,
            code="FILE_SIGNATURE_MISMATCH",
            message="文件签名不匹配",
        )

    return UploadContentMetadata(size_bytes=total_size, sha256=digest.hexdigest())


def prepare_quarantine_intake(
    stream: BinaryIO,
    *,
    file_name: str,
    declared_mime: str,
    max_size_bytes: int,
) -> QuarantineIntakeFacts:
    """验证 seekable 上传流并将游标恢复到起点，供后续隔离区写入。"""

    if type(file_name) is not str or type(declared_mime) is not str:
        raise _request_validation_error()

    extension = Path(file_name).suffix.lower()
    normalized_declared_mime = declared_mime.strip().lower()
    try:
        stream.seek(0)
        metadata = measure_upload_stream(
            _read_upload_chunks(stream),
            max_size_bytes=max_size_bytes,
        )
        detected_mime = validate_file_format(
            stream,
            file_name=file_name,
            declared_mime=normalized_declared_mime,
        )
        return QuarantineIntakeFacts(
            size_bytes=metadata.size_bytes,
            sha256=metadata.sha256,
            extension=extension,
            declared_mime=normalized_declared_mime,
            detected_mime=detected_mime,
        )
    finally:
        stream.seek(0)


def _read_upload_chunks(stream: BinaryIO) -> Iterator[bytes]:
    while True:
        chunk = stream.read(_UPLOAD_READ_CHUNK_BYTES)
        if type(chunk) is not bytes:
            raise TypeError("upload chunks must be bytes")
        if not chunk:
            return
        yield chunk


def validate_file_batch_count(
    file_count: int,
    *,
    max_batch_file_count: int,
) -> None:
    """校验单批文件数量，不在服务层固化环境配置默认值。"""

    if type(max_batch_file_count) is not int or max_batch_file_count <= 0:
        raise ValueError("max_batch_file_count must be a positive integer")
    if type(file_count) is not int or file_count <= 0:
        raise ValueError("file_count must be a positive integer")
    if file_count > max_batch_file_count:
        raise AppError(
            status_code=413,
            code="BATCH_LIMIT_EXCEEDED",
            message="超过单批文件数",
        )


def require_file_upload_scope(
    actor: AuthenticatedActor,
    business_type: IntendedBusinessType,
) -> None:
    """同时校验 files.upload capability 与业务分类角色范围。"""

    if "files.upload" not in actor.permissions:
        raise _file_upload_forbidden()
    if type(business_type) is not IntendedBusinessType:
        raise _file_upload_forbidden()
    allowed_roles = _UPLOAD_ROLES_BY_BUSINESS_TYPE[business_type]
    if allowed_roles.isdisjoint(actor.roles):
        raise _file_upload_forbidden()


def is_parsing_allowed(status: object) -> bool:
    """仅允许已校验的 clean 枚举实例进入解析。"""

    return status is SecurityScanStatus.CLEAN


def validate_single_file_upload(
    intent: FileUploadIntent,
    chunks: Iterable[bytes],
    *,
    file_name: str,
    declared_mime: str,
    max_size_bytes: int,
    security_scan_status: SecurityScanStatus,
) -> UploadContentMetadata:
    """组合单文件上传意图、内容计量、格式校验与扫描准入。"""

    _revalidate_upload_intent(intent)
    if type(max_size_bytes) is not int or max_size_bytes <= 0:
        raise ValueError("max_size_bytes must be a positive integer")

    spool_memory_limit = min(max_size_bytes, 1024 * 1024)
    with SpooledTemporaryFile(max_size=spool_memory_limit, mode="w+b") as buffered:

        def capture_chunks() -> Iterator[bytes]:
            for chunk in chunks:
                yield chunk
                buffered.write(chunk)

        metadata = measure_upload_stream(capture_chunks(), max_size_bytes=max_size_bytes)
        validate_file_format(
            cast(BinaryIO, buffered),
            file_name=file_name,
            declared_mime=declared_mime,
        )

    if not is_parsing_allowed(security_scan_status):
        raise _request_validation_error()
    return metadata


def _revalidate_upload_intent(intent: FileUploadIntent) -> None:
    if type(intent) is not FileUploadIntent:
        raise _request_validation_error()

    payload = intent.model_dump(mode="python", warnings=False)
    try:
        validated = FileUploadIntent.model_validate(payload, strict=True)
    except ValidationError:
        raise _request_validation_error() from None
    if validated.model_dump(mode="python", warnings=False) != payload:
        raise _request_validation_error()


def _request_validation_error() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
    )


def _file_upload_forbidden() -> AppError:
    return AppError(
        status_code=403,
        code="FILE_UPLOAD_FORBIDDEN",
        message="无权执行文件上传",
    )
