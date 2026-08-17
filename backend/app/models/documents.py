"""文件与知识库的 PostgreSQL 权威生命周期模型。"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

FILE_STATUSES = ("uploaded", "validating", "stored", "rejected", "archived")
FILE_SECURITY_SCAN_STATUSES = (
    "pending",
    "clean",
    "infected",
    "scan_failed",
    "unsupported",
    "not_configured",
)
FILE_BUSINESS_TYPES = ("contract", "supplementary_agreement", "invoice", "policy")
KNOWLEDGE_BASE_STATUSES = ("active", "archived")


class KnowledgeBase(Base):
    """P0 制度知识库容器；检索参数固定为已批准的 Top-5/无阈值。"""

    __tablename__ = "knowledge_bases"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="status_allowed"),
        CheckConstraint("default_top_k = 5", name="default_top_k_fixed"),
        CheckConstraint(
            "default_score_threshold IS NULL",
            name="default_score_threshold_unset",
        ),
        CheckConstraint(
            "deleted_at IS NULL AND deleted_by IS NULL AND delete_reason IS NULL",
            name="soft_delete_disabled",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        Index(
            "uq_knowledge_bases_active_code",
            "organization_id",
            "code",
            unique=True,
            postgresql_where=text("status = 'active' AND deleted_at IS NULL"),
        ),
        Index("idx_knowledge_bases_org_status", "organization_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            name="fk_knowledge_bases_organization_id_organizations",
        ),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    default_top_k: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    default_score_threshold: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_knowledge_bases_created_by_users"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_knowledge_bases_updated_by_users"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_knowledge_bases_deleted_by_users"),
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)


class FileRecord(Base):
    """不可覆盖的上传文件身份及安全处理状态。"""

    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_lower_hex"),
        CheckConstraint(
            "status IN ('uploaded', 'validating', 'stored', 'rejected', 'archived')",
            name="status_allowed",
        ),
        CheckConstraint(
            "security_scan_status IN ('pending', 'clean', 'infected', 'scan_failed', "
            "'unsupported', 'not_configured')",
            name="security_scan_status_allowed",
        ),
        CheckConstraint(
            "intended_business_type IN "
            "('contract', 'supplementary_agreement', 'invoice', 'policy')",
            name="business_type_allowed",
        ),
        CheckConstraint(
            "(intended_business_type = 'policy') = (target_knowledge_base_id IS NOT NULL)",
            name="knowledge_base_target_matrix",
        ),
        CheckConstraint(
            "(status = 'uploaded' AND security_scan_status = 'pending' "
            "AND stored_at IS NULL AND archived_at IS NULL "
            "AND rejection_code IS NULL AND rejection_message IS NULL) OR "
            "(status = 'validating' AND security_scan_status IN "
            "('pending', 'scan_failed', 'not_configured') "
            "AND stored_at IS NULL AND archived_at IS NULL "
            "AND rejection_code IS NULL AND rejection_message IS NULL) OR "
            "(status = 'stored' AND security_scan_status = 'clean' "
            "AND stored_at IS NOT NULL AND archived_at IS NULL "
            "AND rejection_code IS NULL AND rejection_message IS NULL) OR "
            "(status = 'rejected' AND security_scan_status IN ('infected', 'unsupported') "
            "AND stored_at IS NULL AND archived_at IS NULL "
            "AND rejection_code IS NOT NULL AND rejection_message IS NULL) OR "
            "(status = 'archived' AND security_scan_status = 'clean' "
            "AND stored_at IS NOT NULL AND archived_at IS NOT NULL "
            "AND rejection_code IS NULL AND rejection_message IS NULL)",
            name="lifecycle_matrix",
        ),
        CheckConstraint(
            "rejection_code IS NULL OR rejection_code ~ '^[A-Z][A-Z0-9_]{0,79}$'",
            name="rejection_code_safe",
        ),
        CheckConstraint(
            "(original_minio_bucket IS NULL) = (original_minio_object_key IS NULL)",
            name="original_locator_null_matrix",
        ),
        CheckConstraint(
            "deleted_at IS NULL AND deleted_by IS NULL AND delete_reason IS NULL",
            name="soft_delete_disabled",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        Index(
            "uq_files_content_active",
            "organization_id",
            "sha256",
            "size_bytes",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_files_original_minio_object_key",
            "original_minio_object_key",
            unique=True,
            postgresql_where=text("original_minio_object_key IS NOT NULL"),
        ),
        Index(
            "idx_files_org_created",
            "organization_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index("idx_files_org_status", "organization_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_files_organization_id_organizations"),
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    detected_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    minio_bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    minio_object_key: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    original_minio_bucket: Mapped[str | None] = mapped_column(String(100))
    original_minio_object_key: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    intended_business_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_knowledge_base_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "knowledge_bases.id",
            name="fk_files_target_knowledge_base_id_knowledge_bases",
        ),
    )
    auto_process_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    security_scan_status: Mapped[str] = mapped_column(String(20), nullable=False)
    rejection_code: Mapped[str | None] = mapped_column(String(80))
    rejection_message: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_files_uploaded_by_users"),
        nullable=False,
    )
    stored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_files_created_by_users"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_files_updated_by_users"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_files_deleted_by_users"),
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)


class FilePrimaryBusinessObject(Base):
    """一个文件与唯一主业务对象之间的不可改绑关系。"""

    __tablename__ = "file_primary_business_objects"
    __table_args__ = (
        CheckConstraint(
            "business_type IN ('contract', 'supplementary_agreement', 'invoice', 'policy')",
            name="business_type_allowed",
        ),
        CheckConstraint(
            "(business_type = 'contract' AND contract_id IS NOT NULL "
            "AND invoice_id IS NULL AND supplementary_agreement_id IS NULL "
            "AND policy_document_id IS NULL) OR "
            "(business_type = 'invoice' AND contract_id IS NULL "
            "AND invoice_id IS NOT NULL AND supplementary_agreement_id IS NULL "
            "AND policy_document_id IS NULL) OR "
            "(business_type = 'supplementary_agreement' AND contract_id IS NULL "
            "AND invoice_id IS NULL AND supplementary_agreement_id IS NOT NULL "
            "AND policy_document_id IS NULL) OR "
            "(business_type = 'policy' AND contract_id IS NULL AND invoice_id IS NULL "
            "AND supplementary_agreement_id IS NULL AND policy_document_id IS NOT NULL)",
            name="business_object_matrix",
        ),
        UniqueConstraint("file_id", name="uq_file_primary_business_objects_file_id"),
        UniqueConstraint("contract_id", name="uq_file_primary_business_objects_contract_id"),
        UniqueConstraint("invoice_id", name="uq_file_primary_business_objects_invoice_id"),
        UniqueConstraint(
            "supplementary_agreement_id",
            name="uq_file_primary_business_objects_supplementary_agreement_id",
        ),
        UniqueConstraint(
            "policy_document_id",
            name="uq_file_primary_business_objects_policy_document_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    file_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("files.id", name="fk_file_primary_business_objects_file_id_files"),
        nullable=False,
    )
    business_type: Mapped[str] = mapped_column(String(40), nullable=False)
    contract_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "contracts.id",
            name="fk_file_primary_business_objects_contract_id_contracts",
        ),
    )
    invoice_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "invoices.id",
            name="fk_file_primary_business_objects_invoice_id_invoices",
        ),
    )
    supplementary_agreement_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "supplementary_agreements.id",
            name="fk_file_primary_business_objects_agreement",
        ),
    )
    policy_document_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "policy_documents.id",
            name="fk_file_primary_business_objects_policy_document",
        ),
    )
    bound_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    bound_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_file_primary_business_objects_bound_by_users"),
        nullable=False,
    )


__all__ = [
    "FILE_BUSINESS_TYPES",
    "FILE_SECURITY_SCAN_STATUSES",
    "FILE_STATUSES",
    "KNOWLEDGE_BASE_STATUSES",
    "FileRecord",
    "FilePrimaryBusinessObject",
    "KnowledgeBase",
]
