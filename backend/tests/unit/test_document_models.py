from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from app.models import (
    CONTENT_EXCLUSION_TYPES,
    DOCUMENT_ASSET_TYPES,
    DOCUMENT_BLOCK_TYPES,
    FILE_BUSINESS_TYPES,
    FILE_SECURITY_SCAN_STATUSES,
    FILE_STATUSES,
    KNOWLEDGE_BASE_STATUSES,
    PARSE_SOURCE_TYPES,
    PARSE_VERSION_STATUSES,
    Base,
    DocumentAsset,
    DocumentBlock,
    DocumentContentExclusion,
    DocumentPage,
    DocumentParseVersion,
    FileRecord,
    KnowledgeBase,
)


def _checks(table_name: str) -> dict[str, str]:
    table = Base.metadata.tables[table_name]
    return {
        str(constraint.name): str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _indexes(table_name: str) -> dict[str, Index]:
    return {
        str(index.name): index
        for index in Base.metadata.tables[table_name].indexes
        if index.name is not None
    }


def test_file_and_knowledge_base_enum_contracts_are_exact() -> None:
    assert FILE_STATUSES == ("uploaded", "validating", "stored", "rejected", "archived")
    assert FILE_SECURITY_SCAN_STATUSES == (
        "pending",
        "clean",
        "infected",
        "scan_failed",
        "unsupported",
        "not_configured",
    )
    assert FILE_BUSINESS_TYPES == (
        "contract",
        "supplementary_agreement",
        "invoice",
        "policy",
    )
    assert KNOWLEDGE_BASE_STATUSES == ("active", "archived")


def test_file_model_has_exact_identity_lifecycle_and_dedupe_shape() -> None:
    table = FileRecord.__table__
    assert list(table.c) == [
        table.c.id,
        table.c.organization_id,
        table.c.original_name,
        table.c.extension,
        table.c.mime_type,
        table.c.detected_mime_type,
        table.c.size_bytes,
        table.c.sha256,
        table.c.minio_bucket,
        table.c.minio_object_key,
        table.c.original_minio_bucket,
        table.c.original_minio_object_key,
        table.c.status,
        table.c.intended_business_type,
        table.c.target_knowledge_base_id,
        table.c.auto_process_requested,
        table.c.security_scan_status,
        table.c.rejection_code,
        table.c.rejection_message,
        table.c.uploaded_by,
        table.c.stored_at,
        table.c.archived_at,
        table.c.row_version,
        table.c.created_at,
        table.c.created_by,
        table.c.updated_at,
        table.c.updated_by,
        table.c.deleted_at,
        table.c.deleted_by,
        table.c.delete_reason,
    ]
    checks = _checks("files")
    assert set(checks) == {
        "ck_files_business_type_allowed",
        "ck_files_knowledge_base_target_matrix",
        "ck_files_lifecycle_matrix",
        "ck_files_original_locator_null_matrix",
        "ck_files_rejection_code_safe",
        "ck_files_row_version_positive",
        "ck_files_security_scan_status_allowed",
        "ck_files_sha256_lower_hex",
        "ck_files_size_bytes_positive",
        "ck_files_soft_delete_disabled",
        "ck_files_status_allowed",
    }
    indexes = _indexes("files")
    assert set(indexes) == {
        "idx_files_org_created",
        "idx_files_org_status",
        "uq_files_content_active",
        "uq_files_original_minio_object_key",
    }
    assert indexes["uq_files_content_active"].unique is True
    assert str(indexes["uq_files_content_active"].dialect_options["postgresql"]["where"]) == (
        "deleted_at IS NULL"
    )
    assert {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    } == {"uq_files_minio_object_key"}


def test_knowledge_base_model_fixes_retrieval_defaults_and_active_code_uniqueness() -> None:
    table = KnowledgeBase.__table__
    checks = _checks("knowledge_bases")
    assert set(checks) == {
        "ck_knowledge_bases_default_score_threshold_unset",
        "ck_knowledge_bases_default_top_k_fixed",
        "ck_knowledge_bases_row_version_positive",
        "ck_knowledge_bases_soft_delete_disabled",
        "ck_knowledge_bases_status_allowed",
    }
    assert str(table.c.default_top_k.server_default.arg) == "5"
    assert table.c.default_score_threshold.server_default is None
    indexes = _indexes("knowledge_bases")
    assert indexes["uq_knowledge_bases_active_code"].unique is True
    assert (
        str(indexes["uq_knowledge_bases_active_code"].dialect_options["postgresql"]["where"])
        == "status = 'active' AND deleted_at IS NULL"
    )


def test_document_processing_enum_contracts_are_exact() -> None:
    assert PARSE_VERSION_STATUSES == (
        "queued",
        "running",
        "succeeded",
        "manual_review_required",
        "active",
        "failed",
        "superseded",
    )
    assert PARSE_SOURCE_TYPES == (
        "parser",
        "ocr",
        "manual_correction",
        "security_revalidation",
    )
    assert DOCUMENT_BLOCK_TYPES == (
        "title",
        "paragraph",
        "list",
        "table",
        "quote",
        "asset",
        "other",
    )
    assert DOCUMENT_ASSET_TYPES == (
        "image",
        "signature",
        "seal",
        "complex_table",
        "attachment_fragment",
    )
    assert CONTENT_EXCLUSION_TYPES == (
        "header",
        "footer",
        "page_number",
        "watermark",
        "duplicate_region",
        "ocr_noise",
        "other",
    )


def test_document_processing_models_preserve_version_and_source_boundaries() -> None:
    assert DocumentParseVersion.__table__ is Base.metadata.tables["document_parse_versions"]
    assert DocumentPage.__table__ is Base.metadata.tables["document_pages"]
    assert DocumentAsset.__table__ is Base.metadata.tables["document_assets"]
    assert DocumentBlock.__table__ is Base.metadata.tables["document_blocks"]
    assert DocumentContentExclusion.__table__ is Base.metadata.tables["document_content_exclusions"]

    parse_checks = _checks("document_parse_versions")
    assert {
        "ck_document_parse_versions_lifecycle_matrix",
        "ck_document_parse_versions_ocr_identity_matrix",
        "ck_document_parse_versions_raw_text_locator_matrix",
        "ck_document_parse_versions_versions_nonempty",
    } <= set(parse_checks)
    parse_indexes = _indexes("document_parse_versions")
    assert parse_indexes["uq_parse_versions_file_active"].unique is True
    assert (
        str(parse_indexes["uq_parse_versions_file_active"].dialect_options["postgresql"]["where"])
        == "status = 'active' AND archived_at IS NULL"
    )

    assert "ck_document_pages_text_hash_matrix" in _checks("document_pages")
    assert "ck_document_assets_coordinate_reason_matrix" in _checks("document_assets")
    assert "ck_document_blocks_asset_reference_matrix" in _checks("document_blocks")
    assert "ck_document_content_exclusions_approval_matrix" in _checks(
        "document_content_exclusions"
    )
