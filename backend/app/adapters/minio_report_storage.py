"""正式报告 PDF/XLSX 的受限 MinIO 持久化与完整性读取。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID

from minio import Minio

from app.adapters.minio_quarantine import _build_http_client
from app.core.config import Settings, _is_validated_settings_instance

_OBJECT_KEY = re.compile(
    r"^organizations/[0-9a-f]{32}/reports/[0-9a-f]{32}/v[1-9]\d*/"
    r"(?:report\.pdf|risks\.xlsx)$"
)


class ReportStorageError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("report storage operation failed")


class ReportStorageOutcomeUnknownError(ReportStorageError):
    def __init__(self, locator: ReportObjectLocator) -> None:
        super().__init__()
        self._locator = locator

    @property
    def locator(self) -> ReportObjectLocator:
        return self._locator


class _ReadableResponse(Protocol):
    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class _MinioReportClient(Protocol):
    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BytesIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> object: ...

    def get_object(self, bucket_name: str, object_name: str) -> _ReadableResponse: ...

    def remove_object(self, bucket_name: str, object_name: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ReportObjectLocator:
    bucket_name: str
    object_key: str


def report_object_locators(
    *,
    organization_id: UUID,
    report_id: UUID,
    report_version: int,
    reports_bucket: str,
    exports_bucket: str,
) -> tuple[ReportObjectLocator, ReportObjectLocator]:
    if (
        type(organization_id) is not UUID
        or type(report_id) is not UUID
        or type(report_version) is not int
        or report_version <= 0
    ):
        raise ValueError("report object identity is invalid")
    prefix = f"organizations/{organization_id.hex}/reports/{report_id.hex}/v{report_version}"
    return (
        ReportObjectLocator(reports_bucket, f"{prefix}/report.pdf"),
        ReportObjectLocator(exports_bucket, f"{prefix}/risks.xlsx"),
    )


class MinioReportStorageAdapter:
    """仅允许服务端生成的报告 locator；不列举、不签名、不接受用户路径。"""

    __slots__ = ("_client", "_exports_bucket", "_reports_bucket", "_writable")

    def __init__(
        self,
        settings: Settings,
        *,
        credential_scope: Literal["api", "worker"],
        client: _MinioReportClient | None = None,
    ) -> None:
        if type(settings) is not Settings or not _is_validated_settings_instance(settings):
            raise TypeError("validated Settings are required")
        self._reports_bucket = settings.minio_bucket_reports
        self._exports_bucket = settings.minio_bucket_exports
        self._writable = credential_scope == "worker"
        if credential_scope not in {"api", "worker"}:
            raise ValueError("invalid report storage credential scope")
        if client is not None:
            self._client = client
            return
        if credential_scope == "worker":
            access_key = settings.minio_worker_access_key
            secret_key = settings.minio_worker_secret_key
            if access_key is None or secret_key is None:
                raise ReportStorageError
        else:
            access_key = settings.minio_access_key
            secret_key = settings.minio_secret_key
        endpoint = urlsplit(settings.minio_endpoint)
        try:
            self._client = cast(
                _MinioReportClient,
                cast(
                    object,
                    Minio(
                        endpoint.netloc,
                        access_key=access_key.get_secret_value(),
                        secret_key=secret_key.get_secret_value(),
                        secure=settings.minio_secure,
                        http_client=_build_http_client(),
                    ),
                ),
            )
        except Exception:
            raise ReportStorageError from None

    @property
    def reports_bucket(self) -> str:
        return self._reports_bucket

    @property
    def exports_bucket(self) -> str:
        return self._exports_bucket

    def put_verified(
        self,
        locator: ReportObjectLocator,
        payload: bytes,
        *,
        expected_sha256: str,
        content_type: str,
        max_bytes: int,
    ) -> None:
        self._validate_request(
            locator,
            expected_size=len(payload),
            expected_sha256=expected_sha256,
            max_bytes=max_bytes,
        )
        if not self._writable or type(payload) is not bytes or not payload:
            raise ReportStorageError
        try:
            self._client.put_object(
                locator.bucket_name,
                locator.object_key,
                BytesIO(payload),
                len(payload),
                content_type=content_type,
                metadata={"sha256": expected_sha256},
            )
            observed = self.read_verified(
                locator,
                expected_size=len(payload),
                expected_sha256=expected_sha256,
                max_bytes=max_bytes,
            )
            if observed != payload:
                raise ValueError
        except Exception:
            try:
                self._client.remove_object(locator.bucket_name, locator.object_key)
            except Exception:
                raise ReportStorageOutcomeUnknownError(locator) from None
            raise ReportStorageError from None

    def read_verified(
        self,
        locator: ReportObjectLocator,
        *,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes:
        self._validate_request(
            locator,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            max_bytes=max_bytes,
        )
        response: _ReadableResponse | None = None
        try:
            response = self._client.get_object(locator.bucket_name, locator.object_key)
            payload = response.read(expected_size + 1)
            if (
                type(payload) is not bytes
                or len(payload) != expected_size
                or hashlib.sha256(payload).hexdigest() != expected_sha256
            ):
                raise ValueError
            return payload
        except Exception:
            raise ReportStorageError from None
        finally:
            if response is not None:
                try:
                    response.close()
                    response.release_conn()
                except Exception:
                    pass

    def delete_compensation(self, locator: ReportObjectLocator) -> None:
        if not self._writable:
            raise ReportStorageError
        self._validate_locator(locator)
        try:
            self._client.remove_object(locator.bucket_name, locator.object_key)
        except Exception:
            raise ReportStorageOutcomeUnknownError(locator) from None

    def _validate_request(
        self,
        locator: ReportObjectLocator,
        *,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int,
    ) -> None:
        self._validate_locator(locator)
        if (
            type(expected_size) is not int
            or expected_size <= 0
            or type(max_bytes) is not int
            or max_bytes <= 0
            or expected_size > max_bytes
            or type(expected_sha256) is not str
            or len(expected_sha256) != 64
            or any(character not in "0123456789abcdef" for character in expected_sha256)
        ):
            raise ReportStorageError

    def _validate_locator(self, locator: ReportObjectLocator) -> None:
        if (
            type(locator) is not ReportObjectLocator
            or _OBJECT_KEY.fullmatch(locator.object_key) is None
        ):
            raise ReportStorageError
        if locator.object_key.endswith("/report.pdf"):
            expected_bucket = self._reports_bucket
        elif locator.object_key.endswith("/risks.xlsx"):
            expected_bucket = self._exports_bucket
        else:  # pragma: no cover - regex closes this branch.
            raise ReportStorageError
        if locator.bucket_name != expected_bucket:
            raise ReportStorageError


class MemoryReportStorageAdapter:
    """仅供测试注入；保持与 MinIO Adapter 相同的完整性边界。"""

    def __init__(self, reports_bucket: str = "reports", exports_bucket: str = "exports") -> None:
        self.reports_bucket = reports_bucket
        self.exports_bucket = exports_bucket
        self.objects: dict[ReportObjectLocator, bytes] = {}

    def put_verified(
        self,
        locator: ReportObjectLocator,
        payload: bytes,
        *,
        expected_sha256: str,
        content_type: str,
        max_bytes: int,
    ) -> None:
        del content_type
        if (
            type(payload) is not bytes
            or not payload
            or len(payload) > max_bytes
            or hashlib.sha256(payload).hexdigest() != expected_sha256
        ):
            raise ReportStorageError
        self.objects[locator] = payload

    def read_verified(
        self,
        locator: ReportObjectLocator,
        *,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes:
        try:
            payload = self.objects[locator]
        except KeyError:
            raise ReportStorageError from None
        if (
            len(payload) != expected_size
            or len(payload) > max_bytes
            or hashlib.sha256(payload).hexdigest() != expected_sha256
        ):
            raise ReportStorageError
        return payload

    def delete_compensation(self, locator: ReportObjectLocator) -> None:
        self.objects.pop(locator, None)


__all__ = [
    "MemoryReportStorageAdapter",
    "MinioReportStorageAdapter",
    "ReportObjectLocator",
    "ReportStorageError",
    "ReportStorageOutcomeUnknownError",
    "report_object_locators",
]
