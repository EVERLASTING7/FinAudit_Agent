"""创建 BASE-005 身份核心表并写入固定五角色。

Revision ID: 20260807_002
Revises: 20260806_001
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260807_002"
down_revision: str | None = "20260806_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("singleton_key", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("unified_social_credit_code", sa.String(length=32), nullable=False),
        sa.Column("tax_number", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("delete_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("singleton_key = 1", name="singleton_key_is_one"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="status_allowed"),
        sa.CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("singleton_key", name="uq_organizations_singleton"),
        sa.UniqueConstraint(
            "unified_social_credit_code",
            name="uq_organizations_unified_social_credit_code",
        ),
        sa.UniqueConstraint("tax_number", name="uq_organizations_tax_number"),
    )

    op.create_table(
        "roles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system_role", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "code IN ('system_admin', 'finance_reviewer', 'audit_reviewer', "
            "'contract_admin', 'read_only')",
            name="code_allowed",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )

    op.execute(
        """
        INSERT INTO roles (id, code, name, description, is_system_role, is_enabled)
        VALUES
          ('00000000-0000-0000-0000-000000000101', 'system_admin',
           '系统管理员', '系统配置、用户和技术发布管理', TRUE, TRUE),
          ('00000000-0000-0000-0000-000000000102', 'finance_reviewer',
           '财务复核人员', '财务事实确认与审核任务执行', TRUE, TRUE),
          ('00000000-0000-0000-0000-000000000103', 'audit_reviewer',
           '审计复核人员', '高风险复核与业务审批', TRUE, TRUE),
          ('00000000-0000-0000-0000-000000000104', 'contract_admin',
           '合同管理员', '合同与补充协议维护', TRUE, TRUE),
          ('00000000-0000-0000-0000-000000000105', 'read_only',
           '只读用户', '授权范围内只读访问', TRUE, TRUE)
        ON CONFLICT (code) DO UPDATE
        SET name = EXCLUDED.name,
            description = EXCLUDED.description,
            is_system_role = TRUE,
            is_enabled = TRUE
        """
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", postgresql.CITEXT(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "force_change_on_login", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "token_invalid_before",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("delete_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('active', 'disabled', 'locked')", name="status_allowed"),
        sa.CheckConstraint("failed_login_count >= 0", name="failed_login_count_nonnegative"),
        sa.CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_users_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_users_created_by_users"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name="fk_users_updated_by_users"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], name="fk_users_deleted_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index(
        "uq_users_username_active",
        "users",
        ["organization_id", "username"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_users_email_active",
        "users",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL AND deleted_at IS NULL"),
    )

    op.create_foreign_key(
        "fk_organizations_created_by_users", "organizations", "users", ["created_by"], ["id"]
    )
    op.create_foreign_key(
        "fk_organizations_updated_by_users", "organizations", "users", ["updated_by"], ["id"]
    )
    op.create_foreign_key(
        "fk_organizations_deleted_by_users", "organizations", "users", ["deleted_by"], ["id"]
    )

    op.create_table(
        "token_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("refresh_token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=100), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("expires_at > issued_at", name="expires_after_issue"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_token_sessions_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_token_sessions"),
        sa.UniqueConstraint("refresh_token_hash", name="uq_token_sessions_refresh_token_hash"),
    )
    op.create_index(
        "idx_token_sessions_user_active",
        "token_sessions",
        ["user_id", "expires_at"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_token_sessions_user_active", table_name="token_sessions")
    op.drop_table("token_sessions")
    op.drop_constraint("fk_organizations_deleted_by_users", "organizations", type_="foreignkey")
    op.drop_constraint("fk_organizations_updated_by_users", "organizations", type_="foreignkey")
    op.drop_constraint("fk_organizations_created_by_users", "organizations", type_="foreignkey")
    op.drop_index("uq_users_email_active", table_name="users")
    op.drop_index("uq_users_username_active", table_name="users")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("organizations")
