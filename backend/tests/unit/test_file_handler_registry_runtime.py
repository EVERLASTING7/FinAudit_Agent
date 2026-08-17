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


def test_packaged_file_registry_loads_both_installed_handlers() -> None:
    process = load_file_handler("file_process")
    scan = load_file_handler("file_scan")

    assert process.registry_hash == scan.registry_hash == FILE_HANDLER_REGISTRY_HASH
    assert process.handler.logical_queue == scan.handler.logical_queue == "document"
    assert [step.step_code for step in process.handler.steps] == ["scan", "parse", "markdown"]
    assert [step.step_code for step in scan.handler.steps] == ["scan"]
    assert process.handler.max_attempts == scan.handler.max_attempts == 3


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
    assert len(hashes) == 6
