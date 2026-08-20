"""Asset 安全重评的受限对象复制接口；当前仅实现隔离内存 double。"""

from __future__ import annotations

import hashlib
from typing import Protocol


class AssetRuntimeStorageError(RuntimeError):
    pass


class AssetRuntimeStorage(Protocol):
    def copy_verified(
        self,
        *,
        source_key: str,
        target_key: str,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes: ...

    def delete_compensation(self, target_key: str) -> None: ...


class MemoryAssetRuntimeStorage:
    """仅供 isolated test；不打开网络，不参与默认 Worker 构造。"""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)

    def copy_verified(
        self,
        *,
        source_key: str,
        target_key: str,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes:
        payload = self.objects.get(source_key)
        if (
            payload is None
            or not 1 <= len(payload) <= max_bytes
            or hashlib.sha256(payload).hexdigest() != expected_sha256
            or not target_key
            or target_key in self.objects
        ):
            raise AssetRuntimeStorageError
        self.objects[target_key] = payload
        return payload

    def delete_compensation(self, target_key: str) -> None:
        self.objects.pop(target_key, None)


__all__ = [
    "AssetRuntimeStorage",
    "AssetRuntimeStorageError",
    "MemoryAssetRuntimeStorage",
]
