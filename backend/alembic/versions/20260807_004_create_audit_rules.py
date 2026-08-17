"""创建 BASE-005 不可变审核规则版本表。

Revision ID: 20260807_004
Revises: 20260807_003
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260807_004"
down_revision: str | None = "20260807_003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_FUNCTION = "finaudit_reject_audit_rules_mutation"
_IMMUTABLE_TRIGGER = "trg_audit_rules_immutable"
_NO_TRUNCATE_TRIGGER = "trg_audit_rules_no_truncate"


def upgrade() -> None:
    op.create_table(
        "audit_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("rule_code", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column(
            "input_schema_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("implementation_key", sa.String(length=200), nullable=False),
        sa.Column("implementation_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("default_risk_level", sa.String(length=20), nullable=False),
        sa.Column("explanation_template", sa.Text(), nullable=False),
        sa.Column(
            "requires_policy_citation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("version > 0", name="version_positive"),
        sa.CheckConstraint(
            "default_risk_level IN ('none', 'notice', 'low', 'medium', 'high')",
            name="default_risk_level_allowed",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_rules"),
        sa.UniqueConstraint(
            "rule_code",
            "version",
            name="uq_audit_rules_code_version",
        ),
    )
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_IMMUTABLE_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION USING
                    ERRCODE = '55000',
                    MESSAGE = 'audit_rules rows are immutable';
                RETURN NULL;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_IMMUTABLE_TRIGGER}
            BEFORE UPDATE OR DELETE ON audit_rules
            FOR EACH ROW EXECUTE FUNCTION {_IMMUTABLE_FUNCTION}()
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_NO_TRUNCATE_TRIGGER}
            BEFORE TRUNCATE ON audit_rules
            FOR EACH STATEMENT EXECUTE FUNCTION {_IMMUTABLE_FUNCTION}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("LOCK TABLE audit_rules IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM audit_rules LIMIT 1) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '55000',
                        MESSAGE = 'refusing to drop non-empty audit_rules';
                END IF;
            END;
            $$
            """
        )
    )
    op.execute(sa.text(f"DROP TRIGGER {_NO_TRUNCATE_TRIGGER} ON audit_rules"))
    op.execute(sa.text(f"DROP TRIGGER {_IMMUTABLE_TRIGGER} ON audit_rules"))
    op.execute(sa.text(f"DROP FUNCTION {_IMMUTABLE_FUNCTION}()"))
    op.drop_table("audit_rules")
