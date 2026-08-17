"""API 对已通过安全扫描原文件的受限完整性读取。"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit

from minio import Minio

from app.adapters.minio_quarantine import QUARANTINE_OBJECT_KEY_PATTERN, _build_http_client
from app.core.config import Settings, _is_validated_settings_instance


class OriginalStorageError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("original file storage operation failed")


class _ReadableResponse(Protocol):
    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class _MinioOriginalClient(Protocol):
    def get_object(self, bucket_name: str, object_name: str) -> _ReadableResponse: ...


@dataclass(frozen=True, slots=True)
class OriginalObjectLocator:
    bucket_name: str
    object_key: str


class MinioOriginalStorageAdapter:
    """只允许应用身份按数据库 locator 读取 originals，不列举或签名。"""

    __slots__ = ("_bucket_name", "_client")

    def __init__(
        self,
        settings: Settings,
        *,
        client: _MinioOriginalClient | None = None,
    ) -> None:
        if type(settings) is not Settings or not _is_validated_settings_instance(settings):
            raise TypeError("validated Settings are required")
        self._bucket_name = settings.minio_bucket_originals
        if client is not None:
            self._client = client
            return
        endpoint = urlsplit(settings.minio_endpoint)
        try:
            self._client = cast(
                _MinioOriginalClient,
                cast(
                    object,
                    Minio(
                        endpoint.netloc,
                        access_key=settings.minio_access_key.get_secret_value(),
                        secret_key=settings.minio_secret_key.get_secret_value(),
                        secure=settings.minio_secure,
                        http_client=_build_http_client(),
                    ),
                ),
            )
        except Exception:
            raise OriginalStorageError from None

    def read_verified(
        self,
        locator: OriginalObjectLocator,
        *,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes:
        if (
            type(locator) is not OriginalObjectLocator
            or locator.bucket_name != self._bucket_name
            or QUARANTINE_OBJECT_KEY_PATTERN.fullmatch(locator.object_key) is None
            or type(expected_size) is not int
            or expected_size <= 0
            or type(max_bytes) is not int
            or max_bytes <= 0
            or expected_size > max_bytes
            or type(expected_sha256) is not str
            or len(expected_sha256) != 64
            or any(character not in "0123456789abcdef" for character in expected_sha256)
        ):
            raise OriginalStorageError

        response: _ReadableResponse | None = None
        try:
            response = self._client.get_object(locator.bucket_name, locator.object_key)
            payload = response.read(expected_size + 1)
            if (
                type(payload) is not bytes
                or len(payload) != expected_size
                or not hmac.compare_digest(
                    hashlib.sha256(payload).hexdigest(),
                    expected_sha256,
                )
            ):
                raise ValueError
            return payload
        except Exception:
            raise OriginalStorageError from None
        finally:
            if response is not None:
                try:
                    response.close()
                    response.release_conn()
                except Exception:
                    pass


class MemoryOriginalStorageAdapter:
    """仅供测试注入。"""

    def __init__(self, objects: dict[OriginalObjectLocator, bytes] | None = None) -> None:
        self.objects = objects or {}

    def read_verified(
        self,
        locator: OriginalObjectLocator,
        *,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes:
        try:
            payload = self.objects[locator]
        except KeyError:
            raise OriginalStorageError from None
        if (
            len(payload) != expected_size
            or len(payload) > max_bytes
            or hashlib.sha256(payload).hexdigest() != expected_sha256
        ):
            raise OriginalStorageError
        return payload


__all__ = [
    "MemoryOriginalStorageAdapter",
    "MinioOriginalStorageAdapter",
    "OriginalObjectLocator",
    "OriginalStorageError",
]
