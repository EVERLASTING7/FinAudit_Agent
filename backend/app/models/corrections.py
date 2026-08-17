"""业务字段与关系人工修正的追加式事实。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

CORRECTION_TYPES = (
    "contract_field",
    "supplementary_agreement_changes",
    "invoice_field",
    "contract_invoice",
    "supplier_field",
    "audit_risk",
)


class UserCorrection(Base):
    """只追加、不覆盖的人工修正 before/after 事实。"""

    __tablename__ = "user_corrections"
    __table_args__ = (
        CheckConstraint(
            "correction_type IN ('contract_field', "
            "'supplementary_agreement_changes', 'invoice_field', 'contract_invoice', "
            "'supplier_field', 'audit_risk')",
            name="correction_type_allowed",
        ),
        CheckConstraint(
            "(object_type COLLATE \"C\") ~ '^[a-z][a-z0-9_]{0,59}$'",
            name="object_type_format",
        ),
        CheckConstraint(
            "(field_path COLLATE \"C\") ~ '^[a-z][a-z0-9_.]*$'",
            name="field_path_format",
        ),
        CheckConstraint(
            "before_value_json IS NOT NULL OR after_value_json IS NOT NULL",
            name="value_present",
        ),
        CheckConstraint(
            "(before_value_json IS NULL OR jsonb_typeof(before_value_json) = 'object') "
            "AND (after_value_json IS NULL OR jsonb_typeof(after_value_json) = 'object')",
            name="value_objects",
        ),
        CheckConstraint("btrim(reason) <> ''", name="reason_nonempty"),
        CheckConstraint(
            "actor_role_code IN ('system_admin', 'finance_reviewer', 'audit_reviewer', "
            "'contract_admin', 'read_only')",
            name="actor_role_code_allowed",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_user_corrections_organization_id_organizations"),
        nullable=False,
    )
    correction_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_type: Mapped[str] = mapped_column(String(60), nullable=False)
    object_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    field_path: Mapped[str] = mapped_column(String(300), nullable=False)
    before_value_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    after_value_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_user_corrections_actor_id_users"),
        nullable=False,
    )
    actor_role_code: Mapped[str] = mapped_column(String(40), nullable=False)
    related_execution_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "audit_task_executions.id",
            name="fk_user_corrections_related_execution_id_audit_task_executions",
        ),
    )
    caused_outdated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


__all__ = ["CORRECTION_TYPES", "UserCorrection"]
