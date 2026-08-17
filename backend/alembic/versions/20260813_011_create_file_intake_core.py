"""创建文件上传与知识库生命周期存储。

Revision ID: 20260813_011
Revises: 20260813_010
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_011"
down_revision: str | None = "20260813_010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("default_top_k", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("default_score_threshold", sa.Numeric(8, 6), nullable=True),
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
        sa.CheckConstraint("status IN ('active', 'archived')", name="status_allowed"),
        sa.CheckConstraint("default_top_k = 5", name="default_top_k_fixed"),
        sa.CheckConstraint("default_score_threshold IS NULL", name="default_score_threshold_unset"),
        sa.CheckConstraint(
            "deleted_at IS NULL AND deleted_by IS NULL AND delete_reason IS NULL",
            name="soft_delete_disabled",
        ),
        sa.CheckConstraint("row_version > 0", name="row_version_positive"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_knowledge_bases_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_knowledge_bases_created_by_users"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name="fk_knowledge_bases_updated_by_users"
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by"], ["users.id"], name="fk_knowledge_bases_deleted_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_bases"),
        schema="public",
    )
    op.create_index(
        "uq_knowledge_bases_active_code",
        "knowledge_bases",
        ["organization_id", "code"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND deleted_at IS NULL"),
        schema="public",
    )
    op.create_index(
        "idx_knowledge_bases_org_status",
        "knowledge_bases",
        ["organization_id", "status"],
        schema="public",
    )

    op.create_table(
        "files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_name", sa.String(length=500), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("detected_mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("minio_bucket", sa.String(length=100), nullable=False),
        sa.Column("minio_object_key", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("intended_business_type", sa.String(length=30), nullable=False),
        sa.Column("target_knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "auto_process_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("security_scan_status", sa.String(length=20), nullable=False),
        sa.Column("rejection_code", sa.String(length=80), nullable=True),
        sa.Column("rejection_message", sa.Text(), nullable=True),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_lower_hex"),
        sa.CheckConstraint(
            "status IN ('uploaded', 'validating', 'stored', 'rejected', 'archived')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "security_scan_status IN ('pending', 'clean', 'infected', 'scan_failed', "
            "'unsupported', 'not_configured')",
            name="security_scan_status_allowed",
        ),
        sa.CheckConstraint(
            "intended_business_type IN "
            "('contract', 'supplementary_agreement', 'invoice', 'policy')",
            name="business_type_allowed",
        ),
        sa.CheckConstraint(
            "(intended_business_type = 'policy') = (target_knowledge_base_id IS NOT NULL)",
            name="knowledge_base_target_matrix",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "rejection_code IS NULL OR rejection_code ~ '^[A-Z][A-Z0-9_]{0,79}$'",
            name="rejection_code_safe",
        ),
        sa.CheckConstraint(
            "deleted_at IS NULL AND deleted_by IS NULL AND delete_reason IS NULL",
            name="soft_delete_disabled",
        ),
        sa.CheckConstraint("row_version > 0", name="row_version_positive"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_files_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["target_knowledge_base_id"],
            ["knowledge_bases.id"],
            name="fk_files_target_knowledge_base_id_knowledge_bases",
        ),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], name="fk_files_uploaded_by_users"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_files_created_by_users"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name="fk_files_updated_by_users"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], name="fk_files_deleted_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_files"),
        sa.UniqueConstraint("minio_object_key", name="uq_files_minio_object_key"),
        schema="public",
    )
    op.create_index(
        "uq_files_content_active",
        "files",
        ["organization_id", "sha256", "size_bytes"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        schema="public",
    )
    op.create_index(
        "idx_files_org_created",
        "files",
        ["organization_id", sa.text("created_at DESC"), sa.text("id DESC")],
        schema="public",
    )
    op.create_index(
        "idx_files_org_status",
        "files",
        ["organization_id", "status"],
        schema="public",
    )
    op.create_index(
        "uq_async_jobs_file_job_type_lifetime",
        "async_jobs",
        ["resource_type", "resource_id", "job_type"],
        unique=True,
        postgresql_where=sa.text(
            "resource_type = 'file' AND job_type IN ('file_scan', 'file_process')"
        ),
        schema="public",
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_file_intake_state_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                target_organization uuid;
                target_status text;
                target_deleted_at timestamptz;
            BEGIN
                IF TG_TABLE_NAME = 'knowledge_bases' THEN
                    IF TG_OP = 'DELETE' OR TG_OP = 'TRUNCATE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='knowledge bases cannot be deleted';
                    END IF;
                    IF TG_OP = 'UPDATE' THEN
                        IF OLD.code IS DISTINCT FROM NEW.code
                            OR OLD.organization_id IS DISTINCT FROM NEW.organization_id
                            OR OLD.created_at IS DISTINCT FROM NEW.created_at
                            OR OLD.created_by IS DISTINCT FROM NEW.created_by THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='knowledge base identity is immutable';
                        END IF;
                        IF OLD.status = 'archived' AND NEW.status IS DISTINCT FROM OLD.status THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='knowledge base archive is irreversible';
                        END IF;
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_OP = 'DELETE' OR TG_OP = 'TRUNCATE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000', MESSAGE='files cannot be deleted';
                END IF;
                IF TG_OP = 'UPDATE' THEN
                    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
                        OR OLD.original_name IS DISTINCT FROM NEW.original_name
                        OR OLD.extension IS DISTINCT FROM NEW.extension
                        OR OLD.mime_type IS DISTINCT FROM NEW.mime_type
                        OR OLD.detected_mime_type IS DISTINCT FROM NEW.detected_mime_type
                        OR OLD.size_bytes IS DISTINCT FROM NEW.size_bytes
                        OR OLD.sha256 IS DISTINCT FROM NEW.sha256
                        OR OLD.minio_bucket IS DISTINCT FROM NEW.minio_bucket
                        OR OLD.minio_object_key IS DISTINCT FROM NEW.minio_object_key
                        OR OLD.intended_business_type IS DISTINCT FROM NEW.intended_business_type
                        OR OLD.target_knowledge_base_id IS DISTINCT FROM
                            NEW.target_knowledge_base_id
                        OR OLD.uploaded_by IS DISTINCT FROM NEW.uploaded_by
                        OR OLD.created_at IS DISTINCT FROM NEW.created_at
                        OR OLD.created_by IS DISTINCT FROM NEW.created_by THEN
                        RAISE EXCEPTION USING ERRCODE='55000', MESSAGE='file identity is immutable';
                    END IF;
                    IF OLD.auto_process_requested AND NOT NEW.auto_process_requested THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='file processing intent cannot be reduced';
                    END IF;
                END IF;
                IF NEW.target_knowledge_base_id IS NOT NULL
                   AND (
                       TG_OP = 'INSERT'
                       OR OLD.target_knowledge_base_id IS DISTINCT FROM
                           NEW.target_knowledge_base_id
                       OR OLD.organization_id IS DISTINCT FROM NEW.organization_id
                   ) THEN
                    SELECT organization_id, status, deleted_at
                      INTO target_organization, target_status, target_deleted_at
                      FROM public.knowledge_bases
                     WHERE id = NEW.target_knowledge_base_id
                     FOR KEY SHARE;
                    IF NOT FOUND
                        OR target_organization IS DISTINCT FROM NEW.organization_id
                        OR target_status <> 'active'
                        OR target_deleted_at IS NOT NULL THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='file target knowledge base is not active in organization';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(sa.text("REVOKE ALL ON FUNCTION public.enforce_file_intake_state_v1() FROM PUBLIC"))
    for statement in (
        "CREATE TRIGGER trg_knowledge_bases_state_v1 BEFORE INSERT OR UPDATE OR DELETE "
        "ON public.knowledge_bases FOR EACH ROW EXECUTE FUNCTION "
        "public.enforce_file_intake_state_v1()",
        "CREATE TRIGGER trg_knowledge_bases_no_truncate_v1 BEFORE TRUNCATE "
        "ON public.knowledge_bases FOR EACH STATEMENT EXECUTE FUNCTION "
        "public.enforce_file_intake_state_v1()",
        "CREATE TRIGGER trg_files_state_v1 BEFORE INSERT OR UPDATE OR DELETE "
        "ON public.files FOR EACH ROW EXECUTE FUNCTION public.enforce_file_intake_state_v1()",
        "CREATE TRIGGER trg_files_no_truncate_v1 BEFORE TRUNCATE ON public.files "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.enforce_file_intake_state_v1()",
    ):
        op.execute(sa.text(statement))


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE public.knowledge_bases IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE public.files IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE public.async_jobs IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM public.files LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.knowledge_bases LIMIT 1)
                   OR EXISTS (
                       SELECT 1 FROM public.async_jobs
                        WHERE resource_type='file'
                          AND job_type IN ('file_scan','file_process')
                       LIMIT 1
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='refusing to drop non-empty file intake core';
                END IF;
            END;
            $$
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER trg_files_no_truncate_v1 ON public.files"))
    op.execute(sa.text("DROP TRIGGER trg_files_state_v1 ON public.files"))
    op.execute(sa.text("DROP TRIGGER trg_knowledge_bases_no_truncate_v1 ON public.knowledge_bases"))
    op.execute(sa.text("DROP TRIGGER trg_knowledge_bases_state_v1 ON public.knowledge_bases"))
    op.drop_index("uq_async_jobs_file_job_type_lifetime", table_name="async_jobs", schema="public")
    op.drop_table("files", schema="public")
    op.drop_table("knowledge_bases", schema="public")
    op.execute(sa.text("DROP FUNCTION public.enforce_file_intake_state_v1()"))
