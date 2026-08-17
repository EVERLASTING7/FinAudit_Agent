"""Worker 对已登记文件对象的受限 MinIO 读取与 clean 后固化。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit

from minio import Minio

from app.adapters.minio_quarantine import _build_http_client
from app.core.config import Settings, _is_validated_settings_instance


class FileStorageError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("file storage operation failed")


class _ReadableResponse(Protocol):
    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class _MinioRuntimeClient(Protocol):
    def get_object(self, bucket_name: str, object_name: str) -> _ReadableResponse: ...

    def copy_object(self, bucket_name: str, object_name: str, source: object) -> object: ...

    def remove_object(self, bucket_name: str, object_name: str) -> None: ...


@dataclass(frozen=True, slots=True)
class StoredFileObject:
    bucket_name: str
    object_key: str


class MinioFileRuntimeAdapter:
    """只接受数据库提供的精确 locator；不列举、不解析用户路径。"""

    __slots__ = ("_client", "_originals_bucket", "_quarantine_bucket")

    def __init__(self, settings: Settings, *, client: _MinioRuntimeClient | None = None) -> None:
        if type(settings) is not Settings or not _is_validated_settings_instance(settings):
            raise TypeError("validated Settings are required")
        self._quarantine_bucket = settings.minio_bucket_quarantine
        self._originals_bucket = settings.minio_bucket_originals
        if client is not None:
            self._client = client
            return
        endpoint = urlsplit(settings.minio_endpoint)
        worker_access_key = settings.minio_worker_access_key
        worker_secret_key = settings.minio_worker_secret_key
        if worker_access_key is None or worker_secret_key is None:
            raise FileStorageError
        try:
            self._client = cast(
                _MinioRuntimeClient,
                cast(
                    object,
                    Minio(
                        endpoint.netloc,
                        access_key=worker_access_key.get_secret_value(),
                        secret_key=worker_secret_key.get_secret_value(),
                        secure=settings.minio_secure,
                        http_client=_build_http_client(),
                    ),
                ),
            )
        except Exception:
            raise FileStorageError from None

    def read_verified(
        self,
        *,
        bucket_name: str,
        object_key: str,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes:
        if (
            bucket_name not in {self._quarantine_bucket, self._originals_bucket}
            or not object_key
            or type(expected_size) is not int
            or expected_size <= 0
            or expected_size > max_bytes
        ):
            raise FileStorageError
        response: _ReadableResponse | None = None
        try:
            response = self._client.get_object(bucket_name, object_key)
            payload = response.read(expected_size + 1)
            if type(payload) is not bytes:
                raise TypeError
            if (
                len(payload) != expected_size
                or hashlib.sha256(payload).hexdigest() != expected_sha256
            ):
                raise ValueError
            return payload
        except Exception:
            raise FileStorageError from None
        finally:
            if response is not None:
                try:
                    response.close()
                    response.release_conn()
                except Exception:
                    pass

    def promote_clean(
        self,
        *,
        source_bucket: str,
        source_key: str,
        expected_size: int,
        expected_sha256: str,
    ) -> StoredFileObject:
        """复制并逐字节复验 originals；数据库提交前不删除 quarantine。"""

        if source_bucket == self._originals_bucket:
            return StoredFileObject(source_bucket, source_key)
        if source_bucket != self._quarantine_bucket:
            raise FileStorageError
        target_key = source_key
        try:
            from minio.commonconfig import CopySource

            self._client.copy_object(
                self._originals_bucket,
                target_key,
                CopySource(source_bucket, source_key),
            )
            self.read_verified(
                bucket_name=self._originals_bucket,
                object_key=target_key,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                max_bytes=expected_size,
            )
        except Exception:
            try:
                self._client.remove_object(self._originals_bucket, target_key)
            except Exception:
                pass
            raise FileStorageError from None
        return StoredFileObject(self._originals_bucket, target_key)

    def delete_quarantine_after_commit(self, object_key: str) -> None:
        try:
            self._client.remove_object(self._quarantine_bucket, object_key)
        except Exception:
            raise FileStorageError from None

    def delete_original_compensation(self, object_key: str) -> None:
        """只用于 originals 已复制但权威事务未提交的补偿。"""

        try:
            self._client.remove_object(self._originals_bucket, object_key)
        except Exception:
            raise FileStorageError from None


class MemoryFileRuntimeAdapter:
    """仅供单元/数据库集成测试注入，不参与 production 构造。"""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read_verified(self, **kwargs: object) -> bytes:
        del kwargs
        return self.payload

    def promote_clean(self, **kwargs: object) -> StoredFileObject:
        source_key = kwargs.get("source_key")
        if type(source_key) is not str:
            raise FileStorageError
        return StoredFileObject("originals", source_key)

    def delete_quarantine_after_commit(self, object_key: str) -> None:
        del object_key

    def delete_original_compensation(self, object_key: str) -> None:
        del object_key


__all__ = [
    "FileStorageError",
    "MemoryFileRuntimeAdapter",
    "MinioFileRuntimeAdapter",
    "StoredFileObject",
]
