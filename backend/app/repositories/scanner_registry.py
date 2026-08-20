"""Scanner Registry current/history 的锁定读取。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.scanner_registry import ScannerRegistryProfile
from app.security.scanner_registry import (
    FIXED_TEST_ADAPTER_CODE,
    FIXED_TEST_DEFINITION_VERSION,
    FIXED_TEST_PROFILE_CLASS,
    FIXED_TEST_REGISTRY_HASH,
    FIXED_TEST_REGISTRY_VERSION,
    FIXED_TEST_SCANNER_VERSION,
    AssetScannerTarget,
    select_asset_scanner_target,
    validate_scanner_profile_jcs,
)


class ScannerRegistryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def current_asset_target(self) -> AssetScannerTarget | None:
        row = self._session.execute(
            select(ScannerRegistryProfile)
            .where(
                ScannerRegistryProfile.activated_at.is_not(None),
                ScannerRegistryProfile.retired_at.is_(None),
            )
            .with_for_update(of=ScannerRegistryProfile, read=True)
        ).scalar_one_or_none()
        if row is None:
            return None
        try:
            profile = validate_scanner_profile_jcs(row.profile_jcs_bytes)
            if (
                row.profile_class != profile.profile_class
                or row.registry_version != profile.registry_version
                or row.scanner_registry_hash != profile.scanner_registry_hash
            ):
                return None
            target = select_asset_scanner_target(profile)
            if (
                target.profile_class,
                target.registry_version,
                target.scanner_registry_hash,
                target.adapter_code,
                target.scanner_version,
                target.definition_version,
            ) != (
                FIXED_TEST_PROFILE_CLASS,
                FIXED_TEST_REGISTRY_VERSION,
                FIXED_TEST_REGISTRY_HASH,
                FIXED_TEST_ADAPTER_CODE,
                FIXED_TEST_SCANNER_VERSION,
                FIXED_TEST_DEFINITION_VERSION,
            ):
                return None
            return target
        except ValueError:
            return None


__all__ = ["ScannerRegistryRepository"]
