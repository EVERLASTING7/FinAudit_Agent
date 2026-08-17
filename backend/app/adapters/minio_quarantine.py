"""MinIO quarantine 对象的最小写入与补偿删除边界。"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import BinaryIO, Protocol, TypeAlias, cast
from urllib.parse import urlsplit
from uuid import UUID

from minio import Minio
from urllib3 import PoolManager, Retry, Timeout

from app.core.config import Settings, _is_validated_settings_instance

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
MEDIA_TYPE_PATTERN = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+\Z")
QUARANTINE_OBJECT_KEY_PATTERN = re.compile(
    r"organizations/[0-9a-f]{32}/files/[0-9a-f]{32}/source\Z"
)
SHA256_METADATA_KEY = "sha256"
_MINIO_CONNECT_TIMEOUT_SECONDS = 3
_MINIO_READ_TIMEOUT_SECONDS = 30
_MINIO_RETRY_TOTAL = 2
_MinioMetadata: TypeAlias = dict[str, str | list[str] | tuple[str]]


class _MinioClient(Protocol):
    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: _MinioMetadata | None = None,
    ) -> object: ...

    def remove_object(self, bucket_name: str, object_name: str) -> None: ...


@dataclass(frozen=True, slots=True)
class QuarantineObject:
    """由服务端标识生成、可写入数据库的 quarantine 定位信息。"""

    bucket_name: str
    object_key: str


class QuarantineStorageError(RuntimeError):
    """SDK 或存储失败的固定脱敏错误。"""

    def __init__(self) -> None:
        super().__init__("MinIO quarantine operation failed")


class QuarantineCleanupRequiredError(QuarantineStorageError):
    """补偿删除失败；错误文本脱敏，定位信息仅供内部编排读取。"""

    __slots__ = ("_locator",)

    def __init__(self, locator: QuarantineObject) -> None:
        RuntimeError.__init__(self, "MinIO quarantine cleanup required")
        self._locator = locator

    @property
    def locator(self) -> QuarantineObject:
        return self._locator


class _HashingExactLengthReader:
    """在 SDK 实际消费上传流时计量内容，不执行额外的预读哈希遍历。"""

    __slots__ = ("_bytes_read", "_digest", "_expected_length", "_source")

    def __init__(self, source: BinaryIO, *, expected_length: int) -> None:
        self._source = source
        self._expected_length = expected_length
        self._bytes_read = 0
        self._digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        chunk = self._source.read(size)
        if type(chunk) is not bytes:
            raise TypeError("upload stream must return bytes")
        self._bytes_read += len(chunk)
        self._digest.update(chunk)
        return chunk

    def verify(self, expected_sha256: str) -> None:
        trailing = self._source.read(1)
        if type(trailing) is not bytes:
            raise TypeError("upload stream must return bytes")
        if (
            self._bytes_read != self._expected_length
            or trailing
            or not hmac.compare_digest(self._digest.hexdigest(), expected_sha256)
        ):
            raise ValueError("upload content integrity mismatch")


def _build_http_client() -> PoolManager:
    return PoolManager(
        timeout=Timeout(
            connect=_MINIO_CONNECT_TIMEOUT_SECONDS,
            read=_MINIO_READ_TIMEOUT_SECONDS,
        ),
        maxsize=10,
        cert_reqs="CERT_REQUIRED",
        retries=Retry(
            total=_MINIO_RETRY_TOTAL,
            backoff_factor=0.2,
            status_forcelist=[500, 502, 503, 504],
        ),
    )


class MinioQuarantineAdapter:
    """仅写入和补偿删除 quarantine；不提供读取、列举或预签名能力。"""

    __slots__ = ("_bucket_name", "_client")

    def __init__(self, settings: Settings, *, client: _MinioClient | None = None) -> None:
        if type(settings) is not Settings or not _is_validated_settings_instance(settings):
            raise TypeError("validated Settings are required")

        self._bucket_name = settings.minio_bucket_quarantine
        if client is not None:
            self._client = client
            return

        parsed_endpoint = urlsplit(settings.minio_endpoint)
        initialization_failed = False
        sdk_client: Minio | None = None
        try:
            sdk_client = Minio(
                parsed_endpoint.netloc,
                access_key=settings.minio_access_key.get_secret_value(),
                secret_key=settings.minio_secret_key.get_secret_value(),
                secure=settings.minio_secure,
                http_client=_build_http_client(),
            )
        except Exception:
            initialization_failed = True
        if initialization_failed or sdk_client is None:
            raise QuarantineStorageError
        self._client = sdk_client

    def put_quarantine(
        self,
        *,
        organization_id: UUID,
        file_id: UUID,
        sha256: str,
        data: BinaryIO,
        length: int,
        content_type: str,
    ) -> QuarantineObject:
        if not isinstance(organization_id, UUID) or not isinstance(file_id, UUID):
            raise TypeError("organization_id and file_id must be UUID values")
        if SHA256_PATTERN.fullmatch(sha256) is None:
            raise ValueError("sha256 must be lowercase hexadecimal")
        if type(length) is not int or length <= 0:
            raise ValueError("length must be a positive integer")
        if MEDIA_TYPE_PATTERN.fullmatch(content_type) is None:
            raise ValueError("content_type must be a media type without parameters")

        locator = QuarantineObject(
            bucket_name=self._bucket_name,
            object_key=f"organizations/{organization_id.hex}/files/{file_id.hex}/source",
        )
        operation_failed = False
        put_completed = False
        put_outcome_unknown = False
        cleanup_failed = False
        reader = _HashingExactLengthReader(data, expected_length=length)
        try:
            if data.seek(0) != 0:
                raise OSError("upload stream rewind failed")
            try:
                self._client.put_object(
                    locator.bucket_name,
                    locator.object_key,
                    cast(BinaryIO, reader),
                    length,
                    content_type=content_type,
                    metadata={SHA256_METADATA_KEY: sha256},
                )
            except Exception:
                put_outcome_unknown = True
                raise
            put_completed = True
            reader.verify(sha256)
        except Exception:
            operation_failed = True
        try:
            if data.seek(0) != 0:
                raise OSError("upload stream rewind failed")
        except Exception:
            operation_failed = True
        if (put_completed or put_outcome_unknown) and operation_failed:
            try:
                self._client.remove_object(locator.bucket_name, locator.object_key)
            except Exception:
                cleanup_failed = True
        if put_outcome_unknown or cleanup_failed:
            raise QuarantineCleanupRequiredError(locator)
        if operation_failed:
            raise QuarantineStorageError
        return locator

    def delete_quarantine(self, locator: QuarantineObject) -> None:
        if (
            locator.bucket_name != self._bucket_name
            or QUARANTINE_OBJECT_KEY_PATTERN.fullmatch(locator.object_key) is None
        ):
            raise ValueError("quarantine locator is invalid for this adapter")

        operation_failed = False
        try:
            self._client.remove_object(self._bucket_name, locator.object_key)
        except Exception:
            operation_failed = True
        if operation_failed:
            raise QuarantineStorageError
