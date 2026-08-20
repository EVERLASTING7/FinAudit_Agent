from uuid import uuid4

import pytest

from app.workers.file_handler_registry import (
    FILE_HANDLER_REGISTRY_HASH,
    FILE_HANDLER_REGISTRY_SCHEMA_HASH,
    file_registry_artifact_hashes,
    load_file_handler,
)
from app.workers.handler_registry import HandlerRegistryError


def valid_input(*, auto_process: bool) -> dict[str, object]:
    return {
        "auto_process_requested": auto_process,
        "file_id": str(uuid4()),
        "intended_business_type": "contract",
        "processing_scope": "full" if auto_process else "scan_only",
        "target_knowledge_base_id": None,
    }


def test_packaged_file_registry_loads_all_installed_handlers() -> None:
    asset = load_file_handler("asset_security_revalidation")
    process = load_file_handler("file_process")
    scan = load_file_handler("file_scan")
    correction = load_file_handler("manual_correction_snapshot")

    assert (
        process.registry_hash
        == scan.registry_hash
        == correction.registry_hash
        == asset.registry_hash
    )
    assert correction.registry_hash == FILE_HANDLER_REGISTRY_HASH
    assert process.handler.logical_queue == scan.handler.logical_queue == "document"
    assert correction.handler.logical_queue == "document"
    assert asset.handler.logical_queue == "document"
    assert [step.step_code for step in process.handler.steps] == ["scan", "parse", "markdown"]
    assert [step.step_code for step in scan.handler.steps] == ["scan"]
    assert [step.step_code for step in correction.handler.steps] == ["snapshot_rebuild"]
    assert [step.step_code for step in asset.handler.steps] == ["asset_security_revalidation"]
    assert process.handler.max_attempts == scan.handler.max_attempts == 3
    assert correction.handler.max_attempts == 1
    assert asset.handler.max_attempts == 1


def test_file_registry_validates_input_and_step_summaries() -> None:
    handler = load_file_handler("file_process")
    handler.validate_input(valid_input(auto_process=True))
    handler.validate_summary(
        "scan",
        {
            "outcome": "clean",
            "scanner_invoked": True,
            "adapter_code": "clamav-instream-v1",
            "scanner_version": "1.4.3",
            "definition_version": "synthetic-definition",
        },
    )

    correction = load_file_handler("manual_correction_snapshot")
    correction_id = str(uuid4())
    result_parse_version_id = str(uuid4())
    correction.validate_input(
        {
            "file_id": str(uuid4()),
            "source_parse_version_id": str(uuid4()),
            "result_parse_version_id": result_parse_version_id,
            "correction_id": correction_id,
            "handler_code_version": "manual-correction-snapshot-v1",
            "handler_registry_version": correction.registry_version,
            "handler_registry_hash": correction.registry_hash,
        }
    )
    correction.validate_summary(
        "snapshot_rebuild",
        {
            "correction_id": correction_id,
            "result_parse_version_id": result_parse_version_id,
            "page_count": 1,
            "block_count": 1,
        },
    )
    asset = load_file_handler("asset_security_revalidation")
    result_parse_id = str(uuid4())
    asset.validate_input(
        {
            "file_id": str(uuid4()),
            "source_parse_version_id": str(uuid4()),
            "result_parse_version_id": result_parse_id,
            "security_policy_version": "asset-security-v1",
            "security_policy_hash": (
                "b074e9cb6af5e20b57cb14f042977417bcf6f9d9eb35c47abf6a13de3823efe0"
            ),
            "handler_code_version": "asset-security-revalidation-v1",
            "handler_registry_version": asset.registry_version,
            "handler_registry_hash": asset.registry_hash,
            "scanner_profile_class": "fixed_test",
            "scanner_registry_version": "fixed-test-registry-v1",
            "scanner_registry_hash": (
                "4e53b4749ccafa9ac4812054244d8a908efdf77f7ac280b38cb6ea047e0ebc1a"
            ),
            "scanner_adapter_code": "fixed_test",
            "scanner_version": "fixed-test-scanner-v1",
            "scanner_definition_version": "fixed-test-definition-v1",
        }
    )
    asset.validate_summary(
        "asset_security_revalidation",
        {
            "result_parse_version_id": result_parse_id,
            "page_count": 1,
            "block_count": 1,
            "asset_count": 1,
            "clean_count": 1,
            "non_clean_count": 0,
            "status": "succeeded",
        },
    )
    handler.validate_summary(
        "parse",
        {
            "parse_version_id": str(uuid4()),
            "page_count": 1,
            "parser_name": "pypdf",
            "parser_version": "6.13.0",
            "ocr_name": None,
            "ocr_version": None,
        },
    )
    handler.validate_summary(
        "markdown",
        {
            "outcome": "active",
            "parse_version_id": str(uuid4()),
            "markdown_version_id": str(uuid4()),
            "version_no": 1,
            "content_sha256": "a" * 64,
            "char_count": 10,
            "source_mapping_count": 1,
        },
    )
    handler.validate_summary(
        "markdown",
        {
            "outcome": "review_required",
            "parse_version_id": str(uuid4()),
            "markdown_version_id": None,
            "version_no": None,
            "content_sha256": None,
            "char_count": None,
            "source_mapping_count": 0,
        },
    )


@pytest.mark.parametrize(
    ("step_code", "summary"),
    [
        ("unknown", {}),
        ("scan", {"outcome": "clean"}),
        ("parse", {"page_count": 0}),
        ("markdown", {"outcome": "active"}),
    ],
)
def test_file_registry_rejects_unknown_or_invalid_summaries(
    step_code: str,
    summary: dict[str, object],
) -> None:
    with pytest.raises(HandlerRegistryError, match="HANDLER_REGISTRY_INVALID"):
        load_file_handler("file_process").validate_summary(step_code, summary)


def test_file_registry_artifact_hashes_match_pinned_identities() -> None:
    hashes = file_registry_artifact_hashes()

    assert hashes["registry.schema.json"] == FILE_HANDLER_REGISTRY_SCHEMA_HASH
    assert hashes["input.file.v1.schema.json"] == (
        "b36720ab2c3cd6d312ebf961164179cd3c59ea117a036cf0ed58647b6914e81b"
    )
    assert hashes["summary.file_markdown.v1.schema.json"] == (
        "73b5c54c05de69be77fde010e653603479e2526f32ea4b872bd887da09aa2cc7"
    )
    assert hashes["input.manual_correction_snapshot.v1.schema.json"] == (
        "011200c148f92a147aab179d2b63a635c1bd29ba0c33821752fda53ed9957002"
    )
    assert hashes["summary.manual_correction_snapshot.v1.schema.json"] == (
        "5ae66666fac90c705b64a362e2d8bb503622745f9381da6df0ce95ef8865c25b"
    )
    assert hashes["input.asset_security_revalidation.v1.schema.json"] == (
        "7907a8639233a9c9435cc2e3d7e6b35cc20c17e15bed51e1ced764d6f72d57f5"
    )
    assert hashes["summary.asset_security_revalidation.v1.schema.json"] == (
        "c73d98a60319cdc77bb0db64df28da45d79226bad08b98edec210093a0c667cf"
    )
    assert len(hashes) == 10
