import hashlib
import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from app.ai.policy import canonicalize_jcs
from app.security.asset_runtime_storage import MemoryAssetRuntimeStorage
from app.security.fixed_test_asset_scanner import FixedTestAssetScanner
from app.security.scanner_registry import (
    FIXED_TEST_REGISTRY_HASH,
    select_asset_scanner_target,
    validate_scanner_profile_jcs,
)

PROFILE_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "security"
    / "artifacts"
    / "fixed-test-scanner-profile-v1.json"
)


def _profile_bytes() -> bytes:
    return PROFILE_PATH.read_bytes().removesuffix(b"\n")


def test_fixed_test_profile_has_exact_jcs_hash_and_unique_asset_target() -> None:
    raw = _profile_bytes()
    profile = validate_scanner_profile_jcs(raw)
    target = select_asset_scanner_target(profile)

    assert len(raw) == 366
    assert hashlib.sha256(raw).hexdigest() == FIXED_TEST_REGISTRY_HASH
    assert target.profile_class == "fixed_test"
    assert target.adapter_code == "fixed_test"
    assert target.definition_version == "fixed-test-definition-v1"


def test_scanner_profile_rejects_noncanonical_or_ambiguous_entries() -> None:
    raw = _profile_bytes()
    with pytest.raises(ValueError, match="canonical JCS"):
        validate_scanner_profile_jcs(raw + b"\n")

    profile = {
        "entries": [
            {
                "adapter_code": "fixed_test",
                "allowed_definition_versions": ["fixed-test-definition-v1"],
                "allowed_scan_outcomes": ["infected", "clean", "scan_failed"],
                "definition_version_mode": "required_exact",
                "scanner_version": "fixed-test-scanner-v1",
            }
        ],
        "profile_class": "fixed_test",
        "registry_version": "fixed-test-registry-v1",
        "schema_version": "scanner-registry-profile-v1",
    }
    with pytest.raises(ValueError, match="outcomes"):
        validate_scanner_profile_jcs(canonicalize_jcs(profile))


def test_fixed_test_scanner_and_storage_are_deterministic_and_open_no_socket() -> None:
    target = select_asset_scanner_target(validate_scanner_profile_jcs(_profile_bytes()))
    clean_payload = b"\x89PNG\r\n\x1a\nsynthetic-clean"
    infected_payload = clean_payload + b"FIXED_TEST_MALWARE"
    storage = MemoryAssetRuntimeStorage(
        {
            "source/clean": clean_payload,
            "source/infected": infected_payload,
        }
    )
    scanner = FixedTestAssetScanner()

    with patch.object(socket, "create_connection") as connect:
        copied = storage.copy_verified(
            source_key="source/clean",
            target_key="target/clean",
            expected_sha256=hashlib.sha256(clean_payload).hexdigest(),
            max_bytes=1024,
        )
        assert scanner.scan(copied, mime_type="image/png", target=target).outcome == "clean"
        infected = scanner.scan(infected_payload, mime_type="image/png", target=target)
        assert (infected.outcome, infected.error_code) == ("infected", "MALWARE_DETECTED")
        unsupported = scanner.scan(b"not-an-image", mime_type="image/png", target=target)
        assert (unsupported.outcome, unsupported.scanner_invoked) == ("unsupported", False)
        connect.assert_not_called()
