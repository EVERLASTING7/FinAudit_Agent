"""BASE-005 身份核心模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, ExcludeConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

ROLE_CODES = (
    "system_admin",
    "finance_reviewer",
    "audit_reviewer",
    "contract_admin",
    "read_only",
)
BREAK_GLASS_REQUEST_STATUSES = ("pending", "approved", "rejected", "revoked", "expired")
USER_ROLE_ASSIGNMENT_SOURCES = ("bootstrap", "user", "break_glass")


class Organization(Base):
    """P0 唯一企业主体。"""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("singleton_key = 1", name="singleton_key_is_one"),
        CheckConstraint("status IN ('active', 'inactive')", name="status_allowed"),
        CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        UniqueConstraint("singleton_key", name="uq_organizations_singleton"),
        UniqueConstraint(
            "unified_social_credit_code",
            name="uq_organizations_unified_social_credit_code",
        ),
        UniqueConstraint("tax_number", name="uq_organizations_tax_number"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    singleton_key: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    unified_social_credit_code: Mapped[str] = mapped_column(String(32), nullable=False)
    tax_number: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_organizations_created_by_users", use_alter=True),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_organizations_updated_by_users", use_alter=True),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_organizations_deleted_by_users", use_alter=True),
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)


class User(Base):
    """组织内用户与强制换密状态。"""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled', 'locked')", name="status_allowed"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_nonnegative"),
        CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        Index(
            "uq_users_username_active",
            "organization_id",
            "username",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_users_email_active",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_users_organization_id_organizations"),
        nullable=False,
    )
    username: Mapped[str] = mapped_column(CITEXT, nullable=False)
    email: Mapped[str | None] = mapped_column(CITEXT)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    force_change_on_login: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    token_invalid_before: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_users_created_by_users"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_users_updated_by_users"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_users_deleted_by_users"),
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)


class Role(Base):
    """由迁移幂等写入的五个固定角色。"""

    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint(
            "code IN ('system_admin', 'finance_reviewer', 'audit_reviewer', "
            "'contract_admin', 'read_only')",
            name="code_allowed",
        ),
        UniqueConstraint("code", name="uq_roles_code"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system_role: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BreakGlassRequest(Base):
    """双人控制的限时特权授权请求事实。"""

    __tablename__ = "break_glass_requests"
    __table_args__ = (
        CheckConstraint(
            "target_role_code IN ('system_admin', 'finance_reviewer', "
            "'audit_reviewer', 'contract_admin')",
            name="target_role_code_allowed",
        ),
        CheckConstraint(
            "requested_duration_seconds BETWEEN 1 AND 14400",
            name="requested_duration_bounds",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'revoked', 'expired')",
            name="status_allowed",
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_nonempty"),
        CheckConstraint(
            "decision_reason IS NULL OR length(btrim(decision_reason)) > 0",
            name="decision_reason_nonempty",
        ),
        CheckConstraint(
            "revoke_reason IS NULL OR length(btrim(revoke_reason)) > 0",
            name="revoke_reason_nonempty",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        CheckConstraint(
            """
            (status = 'pending'
                AND effective_from IS NULL AND expires_at IS NULL
                AND decided_by IS NULL AND decision_at IS NULL
                AND decision_reason IS NULL AND revoked_by IS NULL
                AND revoked_at IS NULL AND revoke_reason IS NULL)
            OR (status = 'approved'
                AND effective_from IS NOT NULL AND expires_at IS NOT NULL
                AND decided_by IS NOT NULL AND decision_at IS NOT NULL
                AND decision_reason IS NOT NULL AND revoked_by IS NULL
                AND revoked_at IS NULL AND revoke_reason IS NULL)
            OR (status = 'rejected'
                AND effective_from IS NULL AND expires_at IS NULL
                AND decided_by IS NOT NULL AND decision_at IS NOT NULL
                AND decision_reason IS NOT NULL AND revoked_by IS NULL
                AND revoked_at IS NULL AND revoke_reason IS NULL)
            OR (status = 'revoked'
                AND effective_from IS NOT NULL AND expires_at IS NOT NULL
                AND decided_by IS NOT NULL AND decision_at IS NOT NULL
                AND decision_reason IS NOT NULL AND revoked_by IS NOT NULL
                AND revoked_at IS NOT NULL AND revoke_reason IS NOT NULL)
            OR (status = 'expired'
                AND effective_from IS NOT NULL AND expires_at IS NOT NULL
                AND decided_by IS NOT NULL AND decision_at IS NOT NULL
                AND decision_reason IS NOT NULL AND revoked_by IS NULL
                AND revoked_at IS NULL AND revoke_reason IS NULL)
            """,
            name="state_field_matrix",
        ),
        CheckConstraint(
            """
            created_at <= updated_at AND (
                (status = 'pending' AND updated_at = created_at)
                OR (status = 'approved'
                    AND created_at <= decision_at
                    AND decision_at = effective_from
                    AND effective_from < expires_at
                    AND expires_at = effective_from
                        + requested_duration_seconds * interval '1 second'
                    AND updated_at = decision_at)
                OR (status = 'rejected'
                    AND created_at <= decision_at
                    AND updated_at = decision_at)
                OR (status = 'revoked'
                    AND created_at <= decision_at
                    AND decision_at = effective_from
                    AND effective_from < expires_at
                    AND expires_at = effective_from
                        + requested_duration_seconds * interval '1 second'
                    AND effective_from <= revoked_at
                    AND revoked_at < expires_at
                    AND updated_at = revoked_at)
                OR (status = 'expired'
                    AND created_at <= decision_at
                    AND decision_at = effective_from
                    AND effective_from < expires_at
                    AND expires_at = effective_from
                        + requested_duration_seconds * interval '1 second'
                    AND updated_at >= expires_at)
            )
            """,
            name="time_matrix",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            name="fk_break_glass_requests_organization_id_organizations",
        ),
        nullable=False,
    )
    target_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_break_glass_requests_target_user_id_users"),
        nullable=False,
    )
    target_role_code: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_break_glass_requests_requested_by_users"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_break_glass_requests_decided_by_users"),
    )
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    revoked_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_break_glass_requests_revoked_by_users"),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class UserRole(Base):
    """不可复活的长期或 break-glass 角色分配历史。"""

    __tablename__ = "user_roles"
    __table_args__ = (
        CheckConstraint(
            "assignment_source IN ('bootstrap', 'user', 'break_glass')",
            name="assignment_source_allowed",
        ),
        CheckConstraint(
            """
            (assignment_source = 'bootstrap'
                AND assigned_by IS NULL AND expires_at IS NULL
                AND break_glass_request_id IS NULL
                AND assignment_reason = 'system_bootstrap')
            OR (assignment_source = 'user'
                AND assigned_by IS NOT NULL AND expires_at IS NULL
                AND break_glass_request_id IS NULL)
            OR (assignment_source = 'break_glass'
                AND assigned_by IS NOT NULL AND expires_at IS NOT NULL
                AND break_glass_request_id IS NOT NULL)
            """,
            name="assignment_source_matrix",
        ),
        CheckConstraint(
            "length(btrim(assignment_reason)) > 0 "
            "AND (assignment_source <> 'user' "
            "OR assignment_reason = btrim(assignment_reason))",
            name="assignment_reason_nonempty",
        ),
        CheckConstraint(
            """
            (revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason IS NULL)
            OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL
                AND revoke_reason IS NOT NULL AND length(btrim(revoke_reason)) > 0
                AND (assignment_source = 'break_glass'
                    OR revoke_reason = btrim(revoke_reason)))
            """,
            name="revocation_matrix",
        ),
        CheckConstraint(
            "(expires_at IS NULL OR assigned_at < expires_at) "
            "AND (revoked_at IS NULL OR revoked_at >= assigned_at)",
            name="time_order",
        ),
        UniqueConstraint(
            "break_glass_request_id",
            name="uq_user_roles_break_glass_request_id",
        ),
        ExcludeConstraint(
            ("user_id", "="),
            ("role_id", "="),
            (
                text("tstzrange(assigned_at, COALESCE(expires_at, 'infinity'::timestamptz), '[)')"),
                "&&",
            ),
            where=text("revoked_at IS NULL"),
            using="gist",
            name="ex_user_roles_effective_range_no_overlap",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_user_roles_user_id_users"),
        nullable=False,
    )
    role_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("roles.id", name="fk_user_roles_role_id_roles"),
        nullable=False,
    )
    assigned_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_user_roles_assigned_by_users"),
    )
    assignment_source: Mapped[str] = mapped_column(String(20), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    break_glass_request_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "break_glass_requests.id",
            name="fk_user_roles_break_glass_request_id_break_glass_requests",
        ),
    )
    assignment_reason: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_user_roles_revoked_by_users"),
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text)


class TokenSession(Base):
    """只保存 Refresh Token 哈希的可撤销会话。"""

    __tablename__ = "token_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > issued_at", name="expires_after_issue"),
        UniqueConstraint("refresh_token_hash", name="uq_token_sessions_refresh_token_hash"),
        Index(
            "idx_token_sessions_user_active",
            "user_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_token_sessions_user_id_users"),
        nullable=False,
    )
    refresh_token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
