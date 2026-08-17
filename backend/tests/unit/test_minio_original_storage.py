from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

import pytest

from app.adapters.minio_original_storage import (
    MinioOriginalStorageAdapter,
    OriginalObjectLocator,
    OriginalStorageError,
)
from tests.unit.test_minio_file_runtime import build_settings

ORGANIZATION_ID = UUID("71000000-0000-4000-8000-000000000001")
FILE_ID = UUID("71000000-0000-4000-8000-000000000002")
OBJECT_KEY = f"organizations/{ORGANIZATION_ID.hex}/files/{FILE_ID.hex}/source"
PAYLOAD = b"verified original payload"
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


@dataclass
class _Response:
    payload: bytes
    closed: bool = False
    released: bool = False

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class _Client:
    def __init__(self, payload: bytes = PAYLOAD) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []
        self.responses: list[_Response] = []

    def get_object(self, bucket_name: str, object_name: str) -> _Response:
        self.calls.append((bucket_name, object_name))
        response = _Response(self.payload)
        self.responses.append(response)
        return response


def _adapter(client: _Client) -> MinioOriginalStorageAdapter:
    return MinioOriginalStorageAdapter(build_settings(), client=client)


def test_original_reader_accepts_only_exact_locator_and_verifies_integrity() -> None:
    client = _Client()
    result = _adapter(client).read_verified(
        OriginalObjectLocator("originals", OBJECT_KEY),
        expected_size=len(PAYLOAD),
        expected_sha256=PAYLOAD_SHA256,
        max_bytes=1024,
    )

    assert result == PAYLOAD
    assert client.calls == [("originals", OBJECT_KEY)]
    assert client.responses[0].closed is True
    assert client.responses[0].released is True


@pytest.mark.parametrize(
    "locator,expected_size,expected_sha256,max_bytes",
    (
        (
            OriginalObjectLocator("quarantine", OBJECT_KEY),
            len(PAYLOAD),
            PAYLOAD_SHA256,
            1024,
        ),
        (
            OriginalObjectLocator("originals", "../source"),
            len(PAYLOAD),
            PAYLOAD_SHA256,
            1024,
        ),
        (OriginalObjectLocator("originals", OBJECT_KEY), len(PAYLOAD), "0" * 64, 1024),
        (OriginalObjectLocator("originals", OBJECT_KEY), len(PAYLOAD), PAYLOAD_SHA256, 1),
    ),
)
def test_original_reader_rejects_locator_or_integrity_drift_without_leaking(
    locator: OriginalObjectLocator,
    expected_size: int,
    expected_sha256: str,
    max_bytes: int,
) -> None:
    client = _Client()
    with pytest.raises(OriginalStorageError, match="original file storage operation failed"):
        _adapter(client).read_verified(
            locator,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            max_bytes=max_bytes,
        )

    if locator.bucket_name != "originals" or locator.object_key != OBJECT_KEY or max_bytes == 1:
        assert client.calls == []
