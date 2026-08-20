"""仅供隔离合成验证的无网络 Asset Scanner double。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from app.security.scanner_registry import (
    FIXED_TEST_ADAPTER_CODE,
    FIXED_TEST_DEFINITION_VERSION,
    FIXED_TEST_PROFILE_CLASS,
    FIXED_TEST_REGISTRY_HASH,
    FIXED_TEST_REGISTRY_VERSION,
    FIXED_TEST_SCANNER_VERSION,
    AssetScannerTarget,
)

AssetSecurityOutcome = Literal["clean", "infected", "scan_failed", "unsupported"]


@dataclass(frozen=True, slots=True)
class AssetSecurityScanResult:
    outcome: AssetSecurityOutcome
    error_code: str | None
    scanner_invoked: bool


class AssetSecurityScanner(Protocol):
    def scan(
        self,
        payload: bytes,
        *,
        mime_type: str,
        target: AssetScannerTarget,
    ) -> AssetSecurityScanResult: ...


class FixedTestAssetScanner:
    """不打开 socket；只接受冻结 fixed_test 身份和合成 PNG/JPEG。"""

    _MALWARE_MARKER = b"FIXED_TEST_MALWARE"

    def scan(
        self,
        payload: bytes,
        *,
        mime_type: str,
        target: AssetScannerTarget,
    ) -> AssetSecurityScanResult:
        expected = (
            FIXED_TEST_PROFILE_CLASS,
            FIXED_TEST_REGISTRY_VERSION,
            FIXED_TEST_REGISTRY_HASH,
            FIXED_TEST_ADAPTER_CODE,
            FIXED_TEST_SCANNER_VERSION,
            FIXED_TEST_DEFINITION_VERSION,
        )
        actual = (
            target.profile_class,
            target.registry_version,
            target.scanner_registry_hash,
            target.adapter_code,
            target.scanner_version,
            target.definition_version,
        )
        if actual != expected:
            raise ValueError("fixed-test scanner target is invalid")
        if not 1 <= len(payload) <= 20 * 1024 * 1024:
            return AssetSecurityScanResult("unsupported", "IMAGE_LIMIT_EXCEEDED", False)
        valid_magic = (mime_type == "image/png" and payload.startswith(b"\x89PNG\r\n\x1a\n")) or (
            mime_type == "image/jpeg"
            and payload.startswith(b"\xff\xd8\xff")
            and payload.endswith(b"\xff\xd9")
        )
        if mime_type not in {"image/png", "image/jpeg"}:
            return AssetSecurityScanResult("unsupported", "MEDIA_TYPE_UNSUPPORTED", False)
        if not valid_magic:
            return AssetSecurityScanResult("unsupported", "MAGIC_BYTES_MISMATCH", False)
        if self._MALWARE_MARKER in payload:
            return AssetSecurityScanResult("infected", "MALWARE_DETECTED", True)
        return AssetSecurityScanResult("clean", None, True)


__all__ = [
    "AssetSecurityScanResult",
    "AssetSecurityScanner",
    "FixedTestAssetScanner",
]
