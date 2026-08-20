"""CR-010-R2 Scanner Profile 的严格解析与 Asset 唯一目标选择。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import cast

from app.ai.policy import canonicalize_jcs
from app.ai.strict_json import parse_strict_json

SCANNER_PROFILE_SCHEMA_VERSION = "scanner-registry-profile-v1"
FIXED_TEST_PROFILE_CLASS = "fixed_test"
FIXED_TEST_REGISTRY_VERSION = "fixed-test-registry-v1"
FIXED_TEST_REGISTRY_HASH = "4e53b4749ccafa9ac4812054244d8a908efdf77f7ac280b38cb6ea047e0ebc1a"
FIXED_TEST_ADAPTER_CODE = "fixed_test"
FIXED_TEST_SCANNER_VERSION = "fixed-test-scanner-v1"
FIXED_TEST_DEFINITION_VERSION = "fixed-test-definition-v1"

_PROFILE_CLASSES = ("contract", "local_offline", "fixed_test", "staging", "production")
_OUTCOME_ORDER = ("clean", "infected", "scan_failed", "unsupported", "not_configured")
_VERSION_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}\Z", re.ASCII)
_ADAPTER_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z", re.ASCII)
_DISALLOWED_TOKENS = {"current", "default", "latest", "unknown"}


@dataclass(frozen=True, slots=True)
class ScannerRegistryEntry:
    adapter_code: str
    scanner_version: str
    definition_version_mode: str
    allowed_definition_versions: tuple[str, ...]
    allowed_scan_outcomes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScannerRegistryProfile:
    profile_class: str
    registry_version: str
    scanner_registry_hash: str
    entries: tuple[ScannerRegistryEntry, ...]


@dataclass(frozen=True, slots=True)
class AssetScannerTarget:
    profile_class: str
    registry_version: str
    scanner_registry_hash: str
    adapter_code: str
    scanner_version: str
    definition_version: str


def _printable_ascii(value: object, *, maximum: int) -> str:
    if type(value) is not str or not 1 <= len(value) <= maximum or value != value.strip():
        raise ValueError("scanner registry string is invalid")
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in value):
        raise ValueError("scanner registry string is invalid")
    return value


def validate_scanner_profile_jcs(raw: bytes) -> ScannerRegistryProfile:
    if type(raw) is not bytes or not raw:
        raise ValueError("scanner registry profile is empty")
    parsed = parse_strict_json(raw).value
    if type(parsed) is not dict or set(parsed) != {
        "entries",
        "profile_class",
        "registry_version",
        "schema_version",
    }:
        raise ValueError("scanner registry profile shape is invalid")
    if parsed["schema_version"] != SCANNER_PROFILE_SCHEMA_VERSION:
        raise ValueError("scanner registry schema version is invalid")
    profile_class = parsed["profile_class"]
    registry_version = parsed["registry_version"]
    if type(profile_class) is not str or profile_class not in _PROFILE_CLASSES:
        raise ValueError("scanner registry profile class is invalid")
    if (
        type(registry_version) is not str
        or _VERSION_PATTERN.fullmatch(registry_version) is None
        or registry_version in _DISALLOWED_TOKENS
    ):
        raise ValueError("scanner registry version is invalid")
    raw_entries = parsed["entries"]
    if type(raw_entries) is not list:
        raise ValueError("scanner registry entries are invalid")
    entries: list[ScannerRegistryEntry] = []
    for raw_entry in raw_entries:
        if type(raw_entry) is not dict or set(raw_entry) != {
            "adapter_code",
            "allowed_definition_versions",
            "allowed_scan_outcomes",
            "definition_version_mode",
            "scanner_version",
        }:
            raise ValueError("scanner registry entry shape is invalid")
        adapter_code = raw_entry["adapter_code"]
        if (
            type(adapter_code) is not str
            or _ADAPTER_PATTERN.fullmatch(adapter_code) is None
            or adapter_code in _DISALLOWED_TOKENS
        ):
            raise ValueError("scanner adapter code is invalid")
        scanner_version = _printable_ascii(raw_entry["scanner_version"], maximum=100)
        if scanner_version in _DISALLOWED_TOKENS or "*" in scanner_version:
            raise ValueError("scanner version is invalid")
        mode = raw_entry["definition_version_mode"]
        definitions = raw_entry["allowed_definition_versions"]
        outcomes = raw_entry["allowed_scan_outcomes"]
        if mode not in {"required_exact", "null_only"}:
            raise ValueError("scanner definition mode is invalid")
        if type(definitions) is not list or type(outcomes) is not list or not outcomes:
            raise ValueError("scanner registry arrays are invalid")
        normalized_definitions = tuple(
            _printable_ascii(value, maximum=200) for value in definitions
        )
        if (
            normalized_definitions != tuple(sorted(set(normalized_definitions), key=str.encode))
            or any("*" in value for value in normalized_definitions)
            or (mode == "required_exact" and not normalized_definitions)
            or (mode == "null_only" and normalized_definitions)
        ):
            raise ValueError("scanner definitions are invalid")
        if any(
            type(value) is not str or value not in _OUTCOME_ORDER for value in outcomes
        ) or tuple(outcomes) != tuple(value for value in _OUTCOME_ORDER if value in set(outcomes)):
            raise ValueError("scanner outcomes are invalid")
        entries.append(
            ScannerRegistryEntry(
                adapter_code=adapter_code,
                scanner_version=scanner_version,
                definition_version_mode=mode,
                allowed_definition_versions=normalized_definitions,
                allowed_scan_outcomes=tuple(cast(list[str], outcomes)),
            )
        )
    identities = [(entry.adapter_code, entry.scanner_version) for entry in entries]
    if identities != sorted(
        set(identities),
        key=lambda value: (value[0].encode(), value[1].encode()),
    ):
        raise ValueError("scanner registry entries are not canonical")
    if canonicalize_jcs(parsed) != raw:
        raise ValueError("scanner registry bytes are not canonical JCS")
    return ScannerRegistryProfile(
        profile_class=profile_class,
        registry_version=registry_version,
        scanner_registry_hash=hashlib.sha256(raw).hexdigest(),
        entries=tuple(entries),
    )


def select_asset_scanner_target(profile: ScannerRegistryProfile) -> AssetScannerTarget:
    if profile.profile_class not in {"fixed_test", "production"}:
        raise ValueError("scanner profile class cannot produce asset terminal evidence")
    candidates = tuple(
        entry
        for entry in profile.entries
        if entry.definition_version_mode == "required_exact"
        and len(entry.allowed_definition_versions) == 1
        and {"clean", "infected", "scan_failed"}.issubset(entry.allowed_scan_outcomes)
    )
    if len(candidates) != 1:
        raise ValueError("scanner profile does not have one asset target")
    entry = candidates[0]
    return AssetScannerTarget(
        profile_class=profile.profile_class,
        registry_version=profile.registry_version,
        scanner_registry_hash=profile.scanner_registry_hash,
        adapter_code=entry.adapter_code,
        scanner_version=entry.scanner_version,
        definition_version=entry.allowed_definition_versions[0],
    )


__all__ = [
    "AssetScannerTarget",
    "FIXED_TEST_ADAPTER_CODE",
    "FIXED_TEST_DEFINITION_VERSION",
    "FIXED_TEST_PROFILE_CLASS",
    "FIXED_TEST_REGISTRY_HASH",
    "FIXED_TEST_REGISTRY_VERSION",
    "FIXED_TEST_SCANNER_VERSION",
    "ScannerRegistryEntry",
    "ScannerRegistryProfile",
    "select_asset_scanner_target",
    "validate_scanner_profile_jcs",
]
