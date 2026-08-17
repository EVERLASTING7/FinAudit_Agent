"""创建不可覆盖的文档解析、页面、资源、块和排除事实。

Revision ID: 20260813_013
Revises: 20260813_012
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_013"
down_revision: str | None = "20260813_012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_parse_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("parser_name", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=False),
        sa.Column("ocr_name", sa.String(length=100), nullable=True),
        sa.Column("ocr_version", sa.String(length=100), nullable=True),
        sa.Column("code_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_text_object_key", sa.String(length=1000), nullable=True),
        sa.Column("raw_text_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("average_confidence", sa.Numeric(6, 5), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version_no > 0", name="version_no_positive"),
        sa.CheckConstraint(
            "source_type IN ('parser','ocr','manual_correction','security_revalidation')",
            name="source_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','manual_review_required',"
            "'active','failed','superseded')",
            name="status_allowed",
        ),
        sa.CheckConstraint("page_count >= 0", name="page_count_nonnegative"),
        sa.CheckConstraint(
            "average_confidence IS NULL OR (average_confidence >= 0 AND average_confidence <= 1)",
            name="average_confidence_range",
        ),
        sa.CheckConstraint(
            "raw_text_sha256 IS NULL OR raw_text_sha256 ~ '^[0-9a-f]{64}$'",
            name="raw_text_sha256_format",
        ),
        sa.CheckConstraint(
            "(raw_text_object_key IS NULL) = (raw_text_sha256 IS NULL)",
            name="raw_text_locator_matrix",
        ),
        sa.CheckConstraint(
            "btrim(parser_name) <> '' AND btrim(parser_version) <> '' "
            "AND btrim(code_version) <> ''",
            name="versions_nonempty",
        ),
        sa.CheckConstraint(
            "source_type <> 'ocr' OR (ocr_name IS NOT NULL AND ocr_version IS NOT NULL "
            "AND btrim(ocr_name) <> '' AND btrim(ocr_version) <> '')",
            name="ocr_identity_matrix",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,79}$'",
            name="error_code_safe",
        ),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name="fk_doc_parse_file",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["document_parse_versions.id"],
            name="fk_doc_parse_parent",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_doc_parse_created_by",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_parse_versions"),
        sa.UniqueConstraint(
            "file_id",
            "version_no",
            name="uq_parse_versions_file_version",
        ),
        schema="public",
    )
    op.create_index(
        "uq_parse_versions_file_active",
        "document_parse_versions",
        ["file_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND archived_at IS NULL"),
        schema="public",
    )
    op.create_index(
        "idx_parse_versions_file_created",
        "document_parse_versions",
        ["file_id", sa.text("created_at DESC")],
        schema="public",
    )

    op.create_table(
        "document_pages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("parse_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("width", sa.Numeric(12, 4), nullable=True),
        sa.Column("height", sa.Numeric(12, 4), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("page_text", sa.Text(), nullable=True),
        sa.Column("text_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("preview_object_key", sa.String(length=1000), nullable=True),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint("page_no > 0", name="page_no_positive"),
        sa.CheckConstraint("width IS NULL OR width > 0", name="width_positive"),
        sa.CheckConstraint("height IS NULL OR height > 0", name="height_positive"),
        sa.CheckConstraint("unit IN ('pixel','point','unknown')", name="unit_allowed"),
        sa.CheckConstraint(
            "text_sha256 IS NULL OR text_sha256 ~ '^[0-9a-f]{64}$'",
            name="text_sha256_format",
        ),
        sa.CheckConstraint(
            "(page_text IS NULL) = (text_sha256 IS NULL)",
            name="text_hash_matrix",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        sa.CheckConstraint("jsonb_typeof(metadata_json) = 'object'", name="metadata_object"),
        sa.ForeignKeyConstraint(
            ["parse_version_id"],
            ["document_parse_versions.id"],
            name="fk_doc_page_parse",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_pages"),
        sa.UniqueConstraint(
            "parse_version_id",
            "page_no",
            name="uq_document_pages_parse_page",
        ),
        schema="public",
    )

    op.create_table(
        "document_assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parse_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("asset_type", sa.String(length=40), nullable=False),
        sa.Column("bbox_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("coordinate_unavailable_reason", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("minio_object_key", sa.String(length=1000), nullable=False),
        sa.Column("content_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("security_status", sa.String(length=20), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("page_no > 0", name="page_no_positive"),
        sa.CheckConstraint(
            "asset_type IN ('image','signature','seal','complex_table','attachment_fragment')",
            name="asset_type_allowed",
        ),
        sa.CheckConstraint(
            "(bbox_json IS NULL) = (coordinate_unavailable_reason IS NOT NULL)",
            name="coordinate_reason_matrix",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_sha256_format",
        ),
        sa.CheckConstraint(
            "security_status IN ('pending','clean','infected','scan_failed',"
            "'unsupported','not_configured')",
            name="security_status_allowed",
        ),
        sa.CheckConstraint("jsonb_typeof(metadata_json) = 'object'", name="metadata_object"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], name="fk_doc_asset_file"),
        sa.ForeignKeyConstraint(
            ["parse_version_id"],
            ["document_parse_versions.id"],
            name="fk_doc_asset_parse",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_doc_asset_created_by"),
        sa.PrimaryKeyConstraint("id", name="pk_document_assets"),
        sa.UniqueConstraint("minio_object_key", name="uq_document_assets_minio_object_key"),
        schema="public",
    )
    op.create_index(
        "idx_document_assets_parse_page",
        "document_assets",
        ["parse_version_id", "page_no"],
        schema="public",
    )

    op.create_table(
        "document_blocks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("parse_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=30), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("text_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("bbox_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("coordinate_unavailable_reason", sa.Text(), nullable=True),
        sa.Column("reading_order", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "is_effective_content",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint("block_index >= 0", name="block_index_nonnegative"),
        sa.CheckConstraint("reading_order >= 0", name="reading_order_nonnegative"),
        sa.CheckConstraint(
            "block_type IN ('title','paragraph','list','table','quote','asset','other')",
            name="block_type_allowed",
        ),
        sa.CheckConstraint(
            "text_sha256 IS NULL OR text_sha256 ~ '^[0-9a-f]{64}$'",
            name="text_sha256_format",
        ),
        sa.CheckConstraint(
            "(text_content IS NULL) = (text_sha256 IS NULL)",
            name="text_hash_matrix",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        sa.CheckConstraint(
            "(bbox_json IS NULL) = (coordinate_unavailable_reason IS NOT NULL)",
            name="coordinate_reason_matrix",
        ),
        sa.CheckConstraint(
            "(block_type = 'asset') = (asset_id IS NOT NULL)",
            name="asset_reference_matrix",
        ),
        sa.CheckConstraint("jsonb_typeof(metadata_json) = 'object'", name="metadata_object"),
        sa.ForeignKeyConstraint(
            ["parse_version_id"],
            ["document_parse_versions.id"],
            name="fk_doc_block_parse",
        ),
        sa.ForeignKeyConstraint(["page_id"], ["document_pages.id"], name="fk_doc_block_page"),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["document_assets.id"],
            name="fk_doc_block_asset",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_blocks"),
        sa.UniqueConstraint(
            "parse_version_id",
            "block_index",
            name="uq_document_blocks_parse_block",
        ),
        schema="public",
    )
    op.create_index(
        "idx_document_blocks_parse_page_order",
        "document_blocks",
        ["parse_version_id", "page_id", "reading_order"],
        schema="public",
    )

    op.create_table(
        "document_content_exclusions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("parse_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exclusion_type", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.String(length=100), nullable=True),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "exclusion_type IN ('header','footer','page_number','watermark',"
            "'duplicate_region','ocr_noise','other')",
            name="exclusion_type_allowed",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending','approved','rejected')",
            name="review_status_allowed",
        ),
        sa.CheckConstraint(
            "(review_status = 'approved') = (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="approval_matrix",
        ),
        sa.CheckConstraint("btrim(reason) <> ''", name="reason_nonempty"),
        sa.ForeignKeyConstraint(
            ["parse_version_id"],
            ["document_parse_versions.id"],
            name="fk_doc_exclusion_parse",
        ),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["document_blocks.id"],
            name="fk_doc_exclusion_block",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["users.id"],
            name="fk_doc_exclusion_submitted_by",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name="fk_doc_exclusion_approved_by",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_doc_exclusion_created_by",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_content_exclusions"),
        sa.UniqueConstraint(
            "parse_version_id",
            "block_id",
            "exclusion_type",
            name="uq_content_exclusions_target",
        ),
        schema="public",
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_document_processing_state_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                parent_file_id uuid;
                parse_file_id uuid;
                related_parse_id uuid;
                file_status text;
                file_scan_status text;
                file_original_bucket text;
                file_original_key text;
            BEGIN
                IF TG_OP = 'TRUNCATE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='document processing facts cannot be truncated';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='document processing facts cannot be deleted';
                END IF;

                IF TG_TABLE_NAME = 'document_parse_versions' THEN
                    IF TG_OP = 'INSERT' THEN
                        SELECT status, security_scan_status,
                               original_minio_bucket, original_minio_object_key
                          INTO file_status, file_scan_status,
                               file_original_bucket, file_original_key
                          FROM public.files WHERE id = NEW.file_id FOR KEY SHARE;
                        IF NOT FOUND
                           OR file_status <> 'stored'
                           OR file_scan_status <> 'clean'
                           OR file_original_bucket IS NULL
                           OR file_original_key IS NULL THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='parse version requires a stored clean file';
                        END IF;
                    END IF;
                    IF NEW.parent_version_id = NEW.id THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='parse version cannot parent itself';
                    END IF;
                    IF NEW.parent_version_id IS NOT NULL THEN
                        SELECT file_id INTO parent_file_id
                          FROM public.document_parse_versions
                         WHERE id = NEW.parent_version_id;
                        IF parent_file_id IS DISTINCT FROM NEW.file_id THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='parse parent must belong to the same file';
                        END IF;
                    END IF;
                    IF TG_OP = 'UPDATE' THEN
                        IF ROW(NEW.id, NEW.file_id, NEW.version_no, NEW.parent_version_id,
                               NEW.source_type, NEW.parser_name, NEW.parser_version,
                               NEW.ocr_name, NEW.ocr_version, NEW.code_version,
                               NEW.created_at, NEW.created_by, NEW.trace_id)
                           IS DISTINCT FROM
                           ROW(OLD.id, OLD.file_id, OLD.version_no, OLD.parent_version_id,
                               OLD.source_type, OLD.parser_name, OLD.parser_version,
                               OLD.ocr_name, OLD.ocr_version, OLD.code_version,
                               OLD.created_at, OLD.created_by, OLD.trace_id) THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='parse version identity is immutable';
                        END IF;
                        IF NOT (
                            (OLD.status = 'queued' AND NEW.status = 'running')
                            OR (OLD.status = 'running' AND NEW.status IN
                                ('succeeded','manual_review_required','failed'))
                            OR (OLD.status IN ('succeeded','manual_review_required')
                                AND NEW.status = 'active')
                            OR (OLD.status = 'active' AND NEW.status = 'superseded')
                        ) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='invalid parse version lifecycle transition';
                        END IF;
                        IF OLD.status IN ('succeeded','manual_review_required','active')
                           AND ROW(NEW.page_count, NEW.raw_text_object_key,
                                   NEW.raw_text_sha256, NEW.average_confidence,
                                   NEW.error_code, NEW.error_message, NEW.archived_at)
                               IS DISTINCT FROM
                               ROW(OLD.page_count, OLD.raw_text_object_key,
                                   OLD.raw_text_sha256, OLD.average_confidence,
                                   OLD.error_code, OLD.error_message, OLD.archived_at) THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='published parse result is immutable';
                        END IF;
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME = 'document_pages' THEN
                    IF TG_OP = 'UPDATE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='document pages are append-only';
                    END IF;
                    SELECT status INTO file_status
                      FROM public.document_parse_versions
                     WHERE id = NEW.parse_version_id;
                    IF file_status <> 'running' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='document pages require a running parse version';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME = 'document_assets' THEN
                    IF TG_OP = 'UPDATE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='document assets are append-only';
                    END IF;
                    SELECT file_id INTO parse_file_id
                      FROM public.document_parse_versions
                     WHERE id = NEW.parse_version_id;
                    IF parse_file_id IS DISTINCT FROM NEW.file_id THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='document asset must belong to the parse file';
                    END IF;
                    SELECT status INTO file_status
                      FROM public.document_parse_versions
                     WHERE id = NEW.parse_version_id;
                    IF file_status <> 'running' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='document assets require a running parse version';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM public.document_pages
                         WHERE parse_version_id = NEW.parse_version_id
                           AND page_no = NEW.page_no
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='document asset page does not exist';
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME = 'document_blocks' THEN
                    IF TG_OP = 'UPDATE' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='document blocks are append-only';
                    END IF;
                    SELECT parse_version_id INTO related_parse_id
                      FROM public.document_pages WHERE id = NEW.page_id;
                    IF related_parse_id IS DISTINCT FROM NEW.parse_version_id THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='document block page belongs to another parse version';
                    END IF;
                    SELECT status INTO file_status
                      FROM public.document_parse_versions
                     WHERE id = NEW.parse_version_id;
                    IF file_status <> 'running' THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='document blocks require a running parse version';
                    END IF;
                    IF NEW.asset_id IS NOT NULL THEN
                        SELECT parse_version_id INTO related_parse_id
                          FROM public.document_assets WHERE id = NEW.asset_id;
                        IF related_parse_id IS DISTINCT FROM NEW.parse_version_id THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='document block asset belongs to another parse version';
                        END IF;
                    END IF;
                    RETURN NEW;
                END IF;

                IF TG_TABLE_NAME = 'document_content_exclusions' THEN
                    SELECT parse_version_id INTO related_parse_id
                      FROM public.document_blocks WHERE id = NEW.block_id;
                    IF related_parse_id IS DISTINCT FROM NEW.parse_version_id THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='content exclusion block belongs to another parse version';
                    END IF;
                    IF TG_OP = 'UPDATE' THEN
                        IF ROW(NEW.id, NEW.parse_version_id, NEW.block_id,
                               NEW.exclusion_type, NEW.reason, NEW.rule_version,
                               NEW.submitted_by, NEW.created_at, NEW.created_by,
                               NEW.trace_id)
                           IS DISTINCT FROM
                           ROW(OLD.id, OLD.parse_version_id, OLD.block_id,
                               OLD.exclusion_type, OLD.reason, OLD.rule_version,
                               OLD.submitted_by, OLD.created_at, OLD.created_by,
                               OLD.trace_id)
                           OR OLD.review_status <> 'pending'
                           OR NEW.review_status NOT IN ('approved','rejected') THEN
                            RAISE EXCEPTION USING ERRCODE='55000',
                                MESSAGE='content exclusion review is append-protected';
                        END IF;
                    END IF;
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION USING ERRCODE='55000', MESSAGE='unsupported document table';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_document_parse_consistency_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                target_parse_id uuid;
                parse_record record;
                actual_page_count integer;
                minimum_page_no integer;
                maximum_page_no integer;
                actual_block_count integer;
                minimum_block_index integer;
                maximum_block_index integer;
            BEGIN
                IF TG_TABLE_NAME = 'document_parse_versions' THEN
                    target_parse_id := NEW.id;
                ELSIF TG_TABLE_NAME = 'document_pages' THEN
                    target_parse_id := NEW.parse_version_id;
                ELSE
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='unsupported parse consistency table';
                END IF;
                SELECT id, status, page_count INTO parse_record
                  FROM public.document_parse_versions WHERE id = target_parse_id;
                IF NOT FOUND THEN
                    RETURN NULL;
                END IF;
                SELECT count(*), min(page_no), max(page_no)
                  INTO actual_page_count, minimum_page_no, maximum_page_no
                  FROM public.document_pages
                 WHERE parse_version_id = target_parse_id;
                IF parse_record.status IN
                    ('succeeded','manual_review_required','active','superseded')
                   AND (
                       actual_page_count <> parse_record.page_count
                       OR minimum_page_no <> 1
                       OR maximum_page_no <> actual_page_count
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='published parse version pages are incomplete';
                END IF;
                SELECT count(*), min(block_index), max(block_index)
                  INTO actual_block_count, minimum_block_index, maximum_block_index
                  FROM public.document_blocks
                 WHERE parse_version_id = target_parse_id;
                IF parse_record.status IN
                    ('succeeded','manual_review_required','active','superseded')
                   AND (
                       actual_block_count = 0
                       OR minimum_block_index <> 0
                       OR maximum_block_index <> actual_block_count - 1
                       OR EXISTS (
                           SELECT 1 FROM public.document_pages AS page
                            WHERE page.parse_version_id = target_parse_id
                              AND NOT EXISTS (
                                  SELECT 1 FROM public.document_blocks AS block
                                   WHERE block.parse_version_id = target_parse_id
                                     AND block.page_id = page.id
                              )
                       )
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='published parse version blocks are incomplete';
                END IF;
                IF parse_record.status IN ('queued','running','failed')
                   AND (actual_page_count <> 0 OR actual_block_count <> 0) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='non-published parse version cannot retain pages';
                END IF;
                RETURN NULL;
            END;
            $$
            """
        )
    )
    for function_name in (
        "enforce_document_processing_state_v1()",
        "enforce_document_parse_consistency_v1()",
    ):
        op.execute(sa.text(f"REVOKE ALL ON FUNCTION public.{function_name} FROM PUBLIC"))

    for table_name in (
        "document_parse_versions",
        "document_pages",
        "document_assets",
        "document_blocks",
        "document_content_exclusions",
    ):
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table_name}_state_v1 "
                f"BEFORE INSERT OR UPDATE OR DELETE ON public.{table_name} FOR EACH ROW "
                "EXECUTE FUNCTION public.enforce_document_processing_state_v1()"
            )
        )
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table_name}_no_truncate_v1 "
                f"BEFORE TRUNCATE ON public.{table_name} FOR EACH STATEMENT "
                "EXECUTE FUNCTION public.enforce_document_processing_state_v1()"
            )
        )
    for table_name in ("document_parse_versions", "document_pages"):
        op.execute(
            sa.text(
                f"CREATE CONSTRAINT TRIGGER trg_{table_name}_consistency_v1 "
                f"AFTER INSERT OR UPDATE ON public.{table_name} "
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                "EXECUTE FUNCTION public.enforce_document_parse_consistency_v1()"
            )
        )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    table_names = (
        "document_content_exclusions",
        "document_blocks",
        "document_assets",
        "document_pages",
        "document_parse_versions",
    )
    op.execute(
        sa.text(
            "LOCK TABLE "
            + ", ".join(f"public.{name}" for name in table_names)
            + " IN ACCESS EXCLUSIVE MODE"
        )
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN IF "
            + " OR ".join(f"EXISTS (SELECT 1 FROM public.{name} LIMIT 1)" for name in table_names)
            + " THEN RAISE EXCEPTION USING ERRCODE='55000', "
            "MESSAGE='refusing to drop non-empty document processing core'; "
            "END IF; END; $$"
        )
    )
    for table_name in ("document_pages", "document_parse_versions"):
        op.execute(sa.text(f"DROP TRIGGER trg_{table_name}_consistency_v1 ON public.{table_name}"))
    for table_name in table_names:
        op.execute(sa.text(f"DROP TRIGGER trg_{table_name}_no_truncate_v1 ON public.{table_name}"))
        op.execute(sa.text(f"DROP TRIGGER trg_{table_name}_state_v1 ON public.{table_name}"))
    op.execute(sa.text("DROP FUNCTION public.enforce_document_parse_consistency_v1()"))
    op.execute(sa.text("DROP FUNCTION public.enforce_document_processing_state_v1()"))
    for table_name in table_names:
        op.drop_table(table_name, schema="public")
