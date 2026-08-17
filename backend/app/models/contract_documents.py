"""合同与支持文件的可追溯关联。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ContractDocument(Base):
    __tablename__ = "contract_documents"
    __table_args__ = (
        CheckConstraint(
            "document_role IN ('attachment','evidence','other')", name="document_role_allowed"
        ),
        CheckConstraint(
            "(unlinked_at IS NULL AND unlink_reason IS NULL) OR "
            "(unlinked_at IS NOT NULL AND unlink_reason IS NOT NULL "
            "AND btrim(unlink_reason) <> '')",
            name="unlink_matrix",
        ),
        Index(
            "uq_contract_document_active",
            "contract_id",
            "file_id",
            "document_role",
            unique=True,
            postgresql_where=text("unlinked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    contract_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False
    )
    file_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("files.id"), nullable=False
    )
    document_role: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    linked_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    unlinked_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unlink_reason: Mapped[str | None] = mapped_column(Text)


__all__ = ["ContractDocument"]
