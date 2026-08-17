from __future__ import annotations

import re

import pytest

from app.audit.rule_catalog import (
    BUILTIN_AUDIT_RULES,
    PREDICATE_ALLOWLIST,
    RULE_CATALOG_CODES,
    RuleCatalogError,
    build_catalog,
)


def test_builtin_catalog_is_complete_static_and_strict() -> None:
    catalog = build_catalog("0.1.0", 1)

    assert tuple(rule.rule_code for rule in catalog) == RULE_CATALOG_CODES
    assert len(catalog) == 15
    assert len({rule.category for rule in catalog}) == 7
    assert len({rule.catalog_manifest_sha256 for rule in catalog}) == 1
    assert re.fullmatch(r"[0-9a-f]{64}", catalog[0].catalog_manifest_sha256)
    assert tuple(rule.implementation_key for rule in catalog) == tuple(PREDICATE_ALLOWLIST)
    assert all(re.fullmatch(r"[0-9a-f]{64}", rule.implementation_hash) for rule in catalog)
    assert all(rule.input_schema_json["additionalProperties"] is False for rule in catalog)
    assert all(
        rule.input_schema_json["required"] == list(rule.input_schema_json["properties"])
        for rule in catalog
    )
    assert sum(rule.requires_policy_citation for rule in catalog) == 1
    assert catalog[12].rule_code == "RULE-013"
    assert catalog[12].requires_policy_citation is True


def test_manifest_binds_release_version_and_static_semantics() -> None:
    version_one = build_catalog("0.1.0", 1)
    repeated = build_catalog("0.1.0", 1)
    version_two = build_catalog("0.1.0", 2)
    next_release = build_catalog("0.1.1", 1)

    assert version_one == repeated
    assert version_one[0].catalog_manifest_sha256 != version_two[0].catalog_manifest_sha256
    assert version_one[0].catalog_manifest_sha256 != next_release[0].catalog_manifest_sha256
    assert tuple(rule.predicate for rule in BUILTIN_AUDIT_RULES) == tuple(
        PREDICATE_ALLOWLIST.values()
    )


@pytest.mark.parametrize(
    ("release", "version"),
    (("", 1), (" release", 1), ("release/1", 1), ("release", 0), ("release", True)),
)
def test_catalog_rejects_invalid_identity(release: str, version: int) -> None:
    with pytest.raises(RuleCatalogError):
        build_catalog(release, version)
