"""文档解析、页面、结构块、资源与排除事实模型。"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

PARSE_VERSION_STATUSES = (
    "queued",
    "running",
    "succeeded",
    "manual_review_required",
    "active",
    "failed",
    "superseded",
)
PARSE_SOURCE_TYPES = ("parser", "ocr", "manual_correction", "security_revalidation")
DOCUMENT_BLOCK_TYPES = ("title", "paragraph", "list", "table", "quote", "asset", "other")
DOCUMENT_ASSET_TYPES = ("image", "signature", "seal", "complex_table", "attachment_fragment")
CONTENT_EXCLUSION_TYPES = (
    "header",
    "footer",
    "page_number",
    "watermark",
    "duplicate_region",
    "ocr_noise",
    "other",
)


class DocumentParseVersion(Base):
    __tablename__ = "document_parse_versions"
    __table_args__ = (
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint(
            "source_type IN ('parser','ocr','manual_correction','security_revalidation')",
            name="source_type_allowed",
        ),
        CheckConstraint(
            "status IN ('queued','running','succeeded','manual_review_required',"
            "'active','failed','superseded')",
            name="status_allowed",
        ),
        CheckConstraint("page_count >= 0", name="page_count_nonnegative"),
        CheckConstraint(
            "average_confidence IS NULL OR (average_confidence >= 0 AND average_confidence <= 1)",
            name="average_confidence_range",
        ),
        CheckConstraint(
            "raw_text_sha256 IS NULL OR raw_text_sha256 ~ '^[0-9a-f]{64}$'",
            name="raw_text_sha256_format",
        ),
        CheckConstraint(
            "(raw_text_object_key IS NULL) = (raw_text_sha256 IS NULL)",
            name="raw_text_locator_matrix",
        ),
        CheckConstraint(
            "btrim(parser_name) <> '' AND btrim(parser_version) <> '' "
            "AND btrim(code_version) <> ''",
            name="versions_nonempty",
        ),
        CheckConstraint(
            "source_type <> 'ocr' OR (ocr_name IS NOT NULL AND ocr_version IS NOT NULL "
            "AND btrim(ocr_name) <> '' AND btrim(ocr_version) <> '')",
            name="ocr_identity_matrix",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,79}$'",
            name="error_code_safe",
        ),
        CheckConstraint(
            "(status IN ('queued','running') AND page_count = 0 "
            "AND raw_text_object_key IS NULL AND raw_text_sha256 IS NULL "
            "AND average_confidence IS NULL AND error_code IS NULL "
            "AND error_message IS NULL AND activated_at IS NULL AND superseded_at IS NULL) OR "
            "(status IN ('succeeded','manual_review_required') AND page_count > 0 "
            "AND error_code IS NULL AND activated_at IS NULL AND superseded_at IS NULL) OR "
            "(status = 'active' AND page_count > 0 AND error_code IS NULL "
            "AND activated_at IS NOT NULL AND superseded_at IS NULL) OR "
            "(status = 'failed' AND page_count = 0 "
            "AND raw_text_object_key IS NULL AND raw_text_sha256 IS NULL "
            "AND average_confidence IS NULL AND error_code IS NOT NULL "
            "AND activated_at IS NULL AND superseded_at IS NULL) OR "
            "(status = 'superseded' AND page_count > 0 AND error_code IS NULL "
            "AND activated_at IS NOT NULL AND superseded_at IS NOT NULL "
            "AND superseded_at >= activated_at)",
            name="lifecycle_matrix",
        ),
        UniqueConstraint("file_id", "version_no", name="uq_parse_versions_file_version"),
        Index(
            "uq_parse_versions_file_active",
            "file_id",
            unique=True,
            postgresql_where=text("status = 'active' AND archived_at IS NULL"),
        ),
        Index(
            "uq_parse_security_revalidation_in_progress",
            "file_id",
            "parent_version_id",
            unique=True,
            postgresql_where=text(
                "source_type = 'security_revalidation' AND status IN ('queued','running')"
            ),
        ),
        Index("idx_parse_versions_file_created", "file_id", text("created_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    file_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("files.id", name="fk_doc_parse_file"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "document_parse_versions.id",
            name="fk_doc_parse_parent",
        ),
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    ocr_name: Mapped[str | None] = mapped_column(String(100))
    ocr_version: Mapped[str | None] = mapped_column(String(100))
    code_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    raw_text_object_key: Mapped[str | None] = mapped_column(String(1000))
    raw_text_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    average_confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_doc_parse_created_by"),
    )
    trace_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        CheckConstraint("page_no > 0", name="page_no_positive"),
        CheckConstraint("width IS NULL OR width > 0", name="width_positive"),
        CheckConstraint("height IS NULL OR height > 0", name="height_positive"),
        CheckConstraint("unit IN ('pixel','point','unknown')", name="unit_allowed"),
        CheckConstraint(
            "text_sha256 IS NULL OR text_sha256 ~ '^[0-9a-f]{64}$'",
            name="text_sha256_format",
        ),
        CheckConstraint(
            "(page_text IS NULL) = (text_sha256 IS NULL)",
            name="text_hash_matrix",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint("jsonb_typeof(metadata_json) = 'object'", name="metadata_object"),
        UniqueConstraint("parse_version_id", "page_no", name="uq_document_pages_parse_page"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    parse_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_parse_versions.id", name="fk_doc_page_parse"),
        nullable=False,
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    height: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    page_text: Mapped[str | None] = mapped_column(Text)
    text_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    preview_object_key: Mapped[str | None] = mapped_column(String(1000))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class DocumentAsset(Base):
    __tablename__ = "document_assets"
    __table_args__ = (
        CheckConstraint("page_no > 0", name="page_no_positive"),
        CheckConstraint(
            "asset_type IN ('image','signature','seal','complex_table','attachment_fragment')",
            name="asset_type_allowed",
        ),
        CheckConstraint(
            "(bbox_json IS NULL) = (coordinate_unavailable_reason IS NOT NULL)",
            name="coordinate_reason_matrix",
        ),
        CheckConstraint(
            "coordinate_unavailable_reason IS NULL OR "
            "coordinate_unavailable_reason IN "
            "('source_not_paginated','extractor_not_available')",
            name="coordinate_reason_allowed",
        ),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        CheckConstraint(
            "security_status IN ('pending','clean','infected','scan_failed',"
            "'unsupported','not_configured')",
            name="security_status_allowed",
        ),
        CheckConstraint(
            "security_policy_version='asset-security-v1' AND "
            "security_policy_hash='b074e9cb6af5e20b57cb14f042977417bcf6f9d9eb35c47abf6a13de3823efe0'",
            name="security_policy_identity",
        ),
        CheckConstraint(
            "(security_status='pending' AND security_checked_at IS NULL "
            "AND security_error_code IS NULL AND security_scanner_invoked IS NULL) OR "
            "(security_status='clean' AND security_checked_at IS NOT NULL "
            "AND security_error_code IS NULL AND security_scanner_invoked IS TRUE) OR "
            "(security_status='infected' AND security_checked_at IS NOT NULL "
            "AND security_error_code IN ('ACTIVE_CONTENT_DETECTED','MALWARE_DETECTED') "
            "AND security_scanner_invoked IS TRUE) OR "
            "(security_status='scan_failed' AND security_checked_at IS NOT NULL "
            "AND security_error_code IN ('OBJECT_READ_TRANSIENT','SCANNER_TIMEOUT',"
            "'SCANNER_UNAVAILABLE') AND security_scanner_invoked IS NOT NULL) OR "
            "(security_status='unsupported' AND security_checked_at IS NOT NULL "
            "AND security_error_code IN ('IMAGE_DECODE_INVALID','IMAGE_LIMIT_EXCEEDED',"
            "'MAGIC_BYTES_MISMATCH','MEDIA_TYPE_UNSUPPORTED') "
            "AND security_scanner_invoked IS FALSE) OR "
            "(security_status='not_configured' AND security_checked_at IS NOT NULL "
            "AND security_error_code='SCANNER_NOT_CONFIGURED' "
            "AND security_scanner_invoked IS FALSE)",
            name="security_error_matrix",
        ),
        CheckConstraint("jsonb_typeof(metadata_json) = 'object'", name="metadata_object"),
        UniqueConstraint("minio_object_key", name="uq_document_assets_minio_object_key"),
        Index("idx_document_assets_parse_page", "parse_version_id", "page_no"),
        Index(
            "uq_document_assets_parse_source",
            "parse_version_id",
            "source_asset_id",
            unique=True,
            postgresql_where=text("source_asset_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    file_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("files.id", name="fk_doc_asset_file"), nullable=False
    )
    parse_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_parse_versions.id", name="fk_doc_asset_parse"),
        nullable=False,
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    bbox_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    coordinate_unavailable_reason: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    minio_object_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    security_status: Mapped[str] = mapped_column(String(20), nullable=False)
    security_policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    security_policy_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    security_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    security_error_code: Mapped[str | None] = mapped_column(String(80))
    security_scanner_profile_class: Mapped[str | None] = mapped_column(String(20))
    security_scanner_registry_version: Mapped[str | None] = mapped_column(String(100))
    security_scanner_registry_hash: Mapped[str | None] = mapped_column(CHAR(64))
    security_scanner_adapter_code: Mapped[str | None] = mapped_column(String(64))
    security_scanner_version: Mapped[str | None] = mapped_column(String(100))
    security_scanner_definition_version: Mapped[str | None] = mapped_column(Text)
    security_scanner_invoked: Mapped[bool | None] = mapped_column(Boolean)
    source_asset_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_assets.id", name="fk_document_assets_source_asset"),
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", name="fk_doc_asset_created_by")
    )
    trace_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentBlock(Base):
    __tablename__ = "document_blocks"
    __table_args__ = (
        CheckConstraint("block_index >= 0", name="block_index_nonnegative"),
        CheckConstraint("reading_order >= 0", name="reading_order_nonnegative"),
        CheckConstraint(
            "block_type IN ('title','paragraph','list','table','quote','asset','other')",
            name="block_type_allowed",
        ),
        CheckConstraint(
            "text_sha256 IS NULL OR text_sha256 ~ '^[0-9a-f]{64}$'",
            name="text_sha256_format",
        ),
        CheckConstraint(
            "(text_content IS NULL) = (text_sha256 IS NULL)",
            name="text_hash_matrix",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint(
            "(bbox_json IS NULL) = (coordinate_unavailable_reason IS NOT NULL)",
            name="coordinate_reason_matrix",
        ),
        CheckConstraint(
            "coordinate_unavailable_reason IS NULL OR "
            "coordinate_unavailable_reason IN "
            "('source_not_paginated','extractor_not_available')",
            name="coordinate_reason_allowed",
        ),
        CheckConstraint(
            "(block_type = 'asset') = (asset_id IS NOT NULL)",
            name="asset_reference_matrix",
        ),
        CheckConstraint("jsonb_typeof(metadata_json) = 'object'", name="metadata_object"),
        UniqueConstraint("parse_version_id", "block_index", name="uq_document_blocks_parse_block"),
        Index(
            "idx_document_blocks_parse_page_order",
            "parse_version_id",
            "page_id",
            "reading_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    parse_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_parse_versions.id", name="fk_doc_block_parse"),
        nullable=False,
    )
    page_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_pages.id", name="fk_doc_block_page"),
        nullable=False,
    )
    block_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(String(30), nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text)
    text_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    bbox_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    coordinate_unavailable_reason: Mapped[str | None] = mapped_column(Text)
    reading_order: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    asset_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_assets.id", name="fk_doc_block_asset")
    )
    is_effective_content: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class DocumentContentExclusion(Base):
    __tablename__ = "document_content_exclusions"
    __table_args__ = (
        CheckConstraint(
            "exclusion_type IN ('header','footer','page_number','watermark',"
            "'duplicate_region','ocr_noise','other')",
            name="exclusion_type_allowed",
        ),
        CheckConstraint(
            "review_status IN ('pending','approved','rejected')",
            name="review_status_allowed",
        ),
        CheckConstraint(
            "(review_status = 'approved') = (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="approval_matrix",
        ),
        CheckConstraint("btrim(reason) <> ''", name="reason_nonempty"),
        UniqueConstraint(
            "parse_version_id", "block_id", "exclusion_type", name="uq_content_exclusions_target"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    parse_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_parse_versions.id", name="fk_doc_exclusion_parse"),
        nullable=False,
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_blocks.id", name="fk_doc_exclusion_block"),
        nullable=False,
    )
    exclusion_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str | None] = mapped_column(String(100))
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    submitted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", name="fk_doc_exclusion_submitted_by")
    )
    approved_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", name="fk_doc_exclusion_approved_by")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", name="fk_doc_exclusion_created_by")
    )
    trace_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = [
    "CONTENT_EXCLUSION_TYPES",
    "DOCUMENT_ASSET_TYPES",
    "DOCUMENT_BLOCK_TYPES",
    "PARSE_SOURCE_TYPES",
    "PARSE_VERSION_STATUSES",
    "DocumentAsset",
    "DocumentBlock",
    "DocumentContentExclusion",
    "DocumentPage",
    "DocumentParseVersion",
]
