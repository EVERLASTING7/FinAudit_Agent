"""Markdown、制度与结构分块的 PostgreSQL 事实模型。"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

MARKDOWN_VERSION_STATUSES = (
    "queued",
    "converting",
    "validating",
    "review_required",
    "ready",
    "active",
    "failed",
    "superseded",
    "archived",
)
POLICY_DOCUMENT_STATUSES = (
    "draft",
    "submitted",
    "business_approved",
    "published",
    "superseded",
    "revoked",
    "archived",
)
CHUNK_SET_STATUSES = ("building", "ready", "active", "failed", "superseded", "archived")


class DocumentBlockCorrection(Base):
    __tablename__ = "document_block_corrections"
    __table_args__ = (
        CheckConstraint(
            "field_name IN ('text_content','block_type','reading_order','bbox')",
            name="field_name_allowed",
        ),
        CheckConstraint("btrim(reason) <> ''", name="reason_nonempty"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    source_parse_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_parse_versions.id", name="fk_doc_block_correction_source_parse"),
        nullable=False,
    )
    source_block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_blocks.id", name="fk_doc_block_correction_source_block"),
        nullable=False,
    )
    result_parse_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("document_parse_versions.id", name="fk_doc_block_correction_result_parse"),
    )
    field_name: Mapped[str] = mapped_column(String(40), nullable=False)
    before_value_json: Mapped[object] = mapped_column(JSONB, nullable=False)
    after_value_json: Mapped[object] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_doc_block_correction_actor"),
        nullable=False,
    )
    corrected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class DocumentMarkdownVersion(Base):
    __tablename__ = "document_markdown_versions"
    __table_args__ = (
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint(
            "status IN ('queued','converting','validating','review_required','ready','active',"
            "'failed','superseded','archived')",
            name="status_allowed",
        ),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_format"),
        CheckConstraint("char_count = char_length(markdown_text)", name="char_count_matches"),
        CheckConstraint("token_count IS NULL OR token_count >= 0", name="token_count_nonnegative"),
        CheckConstraint("warning_count >= 0", name="warning_count_nonnegative"),
        CheckConstraint("blocking_issue_count >= 0", name="blocking_issue_count_nonnegative"),
        CheckConstraint(
            "jsonb_typeof(document_metadata_json) = 'object'",
            name="document_metadata_object",
        ),
        CheckConstraint("jsonb_typeof(quality_summary_json) = 'object'", name="quality_object"),
        CheckConstraint(
            "(status = 'active' AND activated_at IS NOT NULL AND superseded_at IS NULL "
            "AND failure_reason IS NULL AND blocking_issue_count = 0) OR "
            "(status = 'superseded' AND activated_at IS NOT NULL AND superseded_at IS NOT NULL "
            "AND superseded_at >= activated_at AND failure_reason IS NULL) OR "
            "(status = 'failed' AND activated_at IS NULL AND superseded_at IS NULL "
            "AND failure_reason IS NOT NULL) OR "
            "(status NOT IN ('active','superseded','failed') AND activated_at IS NULL "
            "AND superseded_at IS NULL)",
            name="lifecycle_matrix",
        ),
        UniqueConstraint("file_id", "version_no", name="uq_markdown_file_version"),
        UniqueConstraint(
            "parse_version_id",
            "converter_version",
            "schema_version",
            "content_sha256",
            name="uq_markdown_deterministic_result",
        ),
        Index(
            "uq_markdown_file_active",
            "file_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    file_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("files.id"), nullable=False
    )
    parse_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_parse_versions.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    converter_name: Mapped[str] = mapped_column(String(100), nullable=False)
    converter_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False)
    code_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    markdown_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    document_metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    quality_summary_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    blocking_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failure_reason: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class MarkdownSourceMapping(Base):
    __tablename__ = "markdown_source_mappings"
    __table_args__ = (
        CheckConstraint("mapping_type = 'source'", name="mapping_type_allowed"),
        CheckConstraint("md_char_start >= 0 AND md_char_end > md_char_start", name="char_range"),
        CheckConstraint("md_line_start > 0 AND md_line_end >= md_line_start", name="line_range"),
        CheckConstraint("coverage_status IN ('full','partial')", name="coverage_status_allowed"),
        CheckConstraint(
            "(bbox_json IS NULL) = (coordinate_unavailable_reason IS NOT NULL)",
            name="coordinate_matrix",
        ),
        CheckConstraint(
            "coordinate_unavailable_reason IS NULL OR coordinate_unavailable_reason IN "
            "('source_not_paginated','extractor_not_available')",
            name="coordinate_reason_allowed",
        ),
        UniqueConstraint(
            "markdown_version_id",
            "ast_node_id",
            "md_char_start",
            "md_char_end",
            "block_id",
            name="uq_markdown_source_mapping_identity",
        ),
        Index("idx_markdown_source_mapping_version", "markdown_version_id", "md_char_start"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    markdown_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_markdown_versions.id"), nullable=False
    )
    ast_node_id: Mapped[str] = mapped_column(String(200), nullable=False)
    mapping_type: Mapped[str] = mapped_column(String(30), nullable=False)
    md_char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    md_char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    md_line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    md_line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    page_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_pages.id"), nullable=False
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_blocks.id"), nullable=False
    )
    bbox_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    coverage_status: Mapped[str] = mapped_column(String(20), nullable=False)
    coordinate_unavailable_reason: Mapped[str | None] = mapped_column(Text)


class MarkdownValidationResult(Base):
    __tablename__ = "markdown_validation_results"
    __table_args__ = (
        CheckConstraint("severity IN ('info','warning','error')", name="severity_allowed"),
        CheckConstraint("btrim(validator_code) <> ''", name="validator_code_nonempty"),
        CheckConstraint("btrim(issue_code) <> ''", name="issue_code_nonempty"),
        CheckConstraint(
            "(md_char_start IS NULL AND md_char_end IS NULL) OR "
            "(md_char_start >= 0 AND md_char_end > md_char_start)",
            name="char_range",
        ),
        CheckConstraint("jsonb_typeof(details_json) = 'object'", name="details_object"),
        Index("idx_markdown_validation_version", "markdown_version_id", "is_blocking", "severity"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    markdown_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_markdown_versions.id"), nullable=False
    )
    validator_code: Mapped[str] = mapped_column(String(80), nullable=False)
    validator_version: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    issue_code: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    ast_node_id: Mapped[str | None] = mapped_column(String(200))
    md_char_start: Mapped[int | None] = mapped_column(Integer)
    md_char_end: Mapped[int | None] = mapped_column(Integer)
    source_block_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_blocks.id")
    )
    is_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PolicyDocument(Base):
    __tablename__ = "policy_documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','submitted','business_approved','published','superseded',"
            "'revoked','archived')",
            name="status_allowed",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from", name="effective_range"
        ),
        CheckConstraint("jsonb_typeof(scope_json) = 'object'", name="scope_object"),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        CheckConstraint(
            "(status IN ('published','superseded') AND business_approved_by IS NOT NULL "
            "AND business_approved_at IS NOT NULL AND technical_published_by IS NOT NULL "
            "AND technical_published_at IS NOT NULL) OR status NOT IN ('published','superseded')",
            name="publication_matrix",
        ),
        UniqueConstraint(
            "knowledge_base_id", "policy_code", "version", name="uq_policy_code_version"
        ),
        UniqueConstraint("source_file_id", name="uq_policy_source_file"),
        Index("idx_policy_effective_lookup", "knowledge_base_id", "policy_code", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False
    )
    source_file_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("files.id"), nullable=False
    )
    policy_code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    issuing_department: Mapped[str | None] = mapped_column(String(200))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    scope_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    access_scope: Mapped[str] = mapped_column(String(40), nullable=False, server_default="internal")
    allowed_role_codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    submitted_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    business_approved_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    business_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    technical_published_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    technical_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_policy_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("policy_documents.id")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    delete_reason: Mapped[str | None] = mapped_column(Text)


class PolicyApprovalRecord(Base):
    __tablename__ = "policy_approval_records"
    __table_args__ = (
        CheckConstraint("btrim(action) <> '' AND btrim(to_status) <> ''", name="action_nonempty"),
        CheckConstraint("btrim(actor_role_code) <> ''", name="role_nonempty"),
        Index("idx_policy_approval_timeline", "policy_document_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    policy_document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("policy_documents.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    actor_role_code: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class ChunkingConfig(Base):
    """应用内单一 Profile 的组织级不可变快照，不提供在线编辑入口。"""

    __tablename__ = "chunking_configs"
    __table_args__ = (
        CheckConstraint("profile_version = 'chunk-profile-v1'", name="profile_version_allowed"),
        CheckConstraint("profile_hash ~ '^[0-9a-f]{64}$'", name="profile_hash_format"),
        CheckConstraint("jsonb_typeof(parameters_json) = 'object'", name="parameters_object"),
        UniqueConstraint(
            "organization_id", "profile_version", "profile_hash", name="uq_chunk_profile_identity"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    profile_version: Mapped[str] = mapped_column(String(50), nullable=False)
    profile_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    parameters_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    code_version: Mapped[str] = mapped_column(String(100), nullable=False)


class DocumentChunkSet(Base):
    __tablename__ = "document_chunk_sets"
    __table_args__ = (
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint(
            "status IN ('building','ready','active','failed','superseded','archived')",
            name="status_allowed",
        ),
        CheckConstraint("profile_version = 'chunk-profile-v1'", name="profile_version_allowed"),
        CheckConstraint("profile_hash ~ '^[0-9a-f]{64}$'", name="profile_hash_format"),
        CheckConstraint("jsonb_typeof(profile_json) = 'object'", name="profile_object"),
        CheckConstraint("chunk_count >= 0", name="chunk_count_nonnegative"),
        CheckConstraint(
            "content_manifest_hash IS NULL OR content_manifest_hash ~ '^[0-9a-f]{64}$'",
            name="manifest_hash_format",
        ),
        CheckConstraint("jsonb_typeof(quality_summary_json) = 'object'", name="quality_object"),
        CheckConstraint("blocking_issue_count >= 0", name="blocking_issue_count_nonnegative"),
        UniqueConstraint("policy_document_id", "version_no", name="uq_policy_chunk_set_version"),
        UniqueConstraint(
            "policy_document_id", "markdown_version_id", "profile_hash", name="uq_chunk_set_input"
        ),
        Index(
            "uq_policy_active_chunk_set",
            "policy_document_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    policy_document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("policy_documents.id"), nullable=False
    )
    markdown_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_markdown_versions.id"), nullable=False
    )
    chunking_config_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("chunking_configs.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(50), nullable=False)
    profile_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    profile_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_manifest_hash: Mapped[str | None] = mapped_column(CHAR(64))
    quality_summary_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    blocking_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failure_reason: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="chunk_index_nonnegative"),
        CheckConstraint("btrim(content_text) <> ''", name="content_nonempty"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_hash_format"),
        CheckConstraint("cardinality(ast_node_ids) > 0", name="ast_nodes_nonempty"),
        CheckConstraint("md_char_start >= 0 AND md_char_end > md_char_start", name="char_range"),
        CheckConstraint("start_page_no > 0 AND end_page_no >= start_page_no", name="page_range"),
        CheckConstraint(
            "char_count = char_length(content_text) AND char_count > 0", name="char_count_matches"
        ),
        CheckConstraint("token_count IS NULL OR token_count >= 0", name="token_count_nonnegative"),
        UniqueConstraint("chunk_set_id", "chunk_index", name="uq_chunk_set_index"),
        Index("idx_document_chunks_content", "chunk_set_id", "content_sha256"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    chunk_set_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_chunk_sets.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    ast_node_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    md_char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    md_char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    start_page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    quality_flags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )


class DocumentChunkSource(Base):
    __tablename__ = "document_chunk_sources"
    __table_args__ = (
        CheckConstraint("source_seq > 0", name="source_seq_positive"),
        CheckConstraint("page_no > 0", name="page_no_positive"),
        CheckConstraint("quoted_text_sha256 ~ '^[0-9a-f]{64}$'", name="quoted_hash_format"),
        CheckConstraint(
            "(bbox_json IS NULL) = (coordinate_unavailable_reason IS NOT NULL)",
            name="coordinate_matrix",
        ),
        CheckConstraint(
            "coordinate_unavailable_reason IS NULL OR coordinate_unavailable_reason IN "
            "('source_not_paginated','extractor_not_available')",
            name="coordinate_reason_allowed",
        ),
        UniqueConstraint("chunk_id", "source_seq", name="uq_chunk_source_sequence"),
        UniqueConstraint(
            "chunk_id", "markdown_mapping_id", "block_id", name="uq_chunk_source_identity"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    chunk_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_chunks.id"), nullable=False
    )
    source_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    markdown_mapping_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("markdown_source_mappings.id"), nullable=False
    )
    parse_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_parse_versions.id"), nullable=False
    )
    page_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_pages.id"), nullable=False
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_blocks.id"), nullable=False
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    quoted_text_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    coordinate_unavailable_reason: Mapped[str | None] = mapped_column(Text)


__all__ = [
    "CHUNK_SET_STATUSES",
    "MARKDOWN_VERSION_STATUSES",
    "POLICY_DOCUMENT_STATUSES",
    "ChunkingConfig",
    "DocumentBlockCorrection",
    "DocumentChunk",
    "DocumentChunkSet",
    "DocumentChunkSource",
    "DocumentMarkdownVersion",
    "MarkdownSourceMapping",
    "MarkdownValidationResult",
    "PolicyApprovalRecord",
    "PolicyDocument",
]
