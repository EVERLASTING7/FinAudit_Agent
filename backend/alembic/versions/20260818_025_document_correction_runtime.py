"""落实 CR-005-R2 文档纠错与资源安全存储合同。

Revision ID: 20260818_025
Revises: 20260817_024
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_025"
down_revision: str | None = "20260817_024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ASSET_POLICY_HASH = "b074e9cb6af5e20b57cb14f042977417bcf6f9d9eb35c47abf6a13de3823efe0"


def _lock_tables() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout='5s'"))
    op.execute(
        sa.text(
            "LOCK TABLE public.document_parse_versions, "
            "public.document_block_corrections, public.document_assets, "
            "public.markdown_source_mappings, public.async_jobs, "
            "public.async_job_steps, public.outbox_events IN ACCESS EXCLUSIVE MODE"
        )
    )


def _preflight_upgrade() -> None:
    _lock_tables()
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM public.document_assets LIMIT 1) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='existing document assets require reviewed forward migration';
                END IF;
                IF EXISTS (SELECT 1 FROM public.document_block_corrections LIMIT 1) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='existing document corrections require reviewed forward migration';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM public.document_parse_versions
                     WHERE source_type IN ('manual_correction','security_revalidation') LIMIT 1
                ) OR EXISTS (
                    SELECT 1 FROM public.async_jobs
                     WHERE job_type IN
                           ('manual_correction_snapshot','asset_security_revalidation') LIMIT 1
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='existing document rebuild runtime requires reviewed migration';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM public.markdown_source_mappings
                     WHERE block_id IS NULL LIMIT 1
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='existing nullable mappings require reviewed forward migration';
                END IF;
            END; $$;
            """
        )
    )


def _create_asset_guard() -> None:
    op.execute(sa.text("DROP TRIGGER trg_document_assets_state_v1 ON public.document_assets"))
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_document_assets_state_v2()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,pg_temp
            AS $$
            DECLARE
                parse_file_id uuid;
                parse_status text;
                parse_source_type text;
                parse_parent_id uuid;
                source_parse_id uuid;
                source_file_id uuid;
                source_page_no integer;
                source_asset_type text;
            BEGIN
                IF TG_OP='DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='document assets cannot be deleted';
                END IF;
                IF TG_OP='INSERT' THEN
                    SELECT file_id,status,source_type,parent_version_id
                      INTO parse_file_id,parse_status,parse_source_type,parse_parent_id
                      FROM public.document_parse_versions WHERE id=NEW.parse_version_id;
                    IF parse_file_id IS DISTINCT FROM NEW.file_id OR parse_status<>'running' THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='document asset parse boundary is invalid';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM public.document_pages
                         WHERE parse_version_id=NEW.parse_version_id AND page_no=NEW.page_no
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='document asset page does not exist';
                    END IF;
                    IF NEW.source_asset_id IS NULL THEN
                        IF parse_source_type='security_revalidation' THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='security revalidation asset requires source lineage';
                        END IF;
                    ELSE
                        SELECT parse_version_id,file_id,page_no,asset_type
                          INTO source_parse_id,source_file_id,source_page_no,source_asset_type
                          FROM public.document_assets WHERE id=NEW.source_asset_id;
                        IF parse_source_type<>'security_revalidation'
                           OR source_parse_id IS DISTINCT FROM parse_parent_id
                           OR source_file_id IS DISTINCT FROM NEW.file_id
                           OR source_page_no IS DISTINCT FROM NEW.page_no
                           OR source_asset_type IS DISTINCT FROM NEW.asset_type
                           OR NEW.source_asset_id=NEW.id THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='document asset lineage is invalid';
                        END IF;
                    END IF;
                    RETURN NEW;
                END IF;
                IF OLD.security_status<>'pending'
                   OR NEW.security_status NOT IN
                      ('clean','infected','scan_failed','unsupported','not_configured')
                   OR ROW(NEW.id,NEW.file_id,NEW.parse_version_id,NEW.page_no,NEW.asset_type,
                          NEW.bbox_json,NEW.coordinate_unavailable_reason,NEW.mime_type,
                          NEW.minio_object_key,NEW.content_sha256,NEW.security_policy_version,
                          NEW.security_policy_hash,NEW.source_asset_id,NEW.metadata_json,
                          NEW.created_at,NEW.created_by,NEW.trace_id,NEW.archived_at)
                      IS DISTINCT FROM
                      ROW(OLD.id,OLD.file_id,OLD.parse_version_id,OLD.page_no,OLD.asset_type,
                          OLD.bbox_json,OLD.coordinate_unavailable_reason,OLD.mime_type,
                          OLD.minio_object_key,OLD.content_sha256,OLD.security_policy_version,
                          OLD.security_policy_hash,OLD.source_asset_id,OLD.metadata_json,
                          OLD.created_at,OLD.created_by,OLD.trace_id,OLD.archived_at)
                THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='document asset transition is invalid';
                END IF;
                RETURN NEW;
            END;
            $$;
            REVOKE ALL ON FUNCTION public.enforce_document_assets_state_v2() FROM PUBLIC;
            CREATE TRIGGER trg_document_assets_state_v2
                BEFORE INSERT OR UPDATE OR DELETE ON public.document_assets
                FOR EACH ROW EXECUTE FUNCTION public.enforce_document_assets_state_v2();
            """
        )
    )


def _create_correction_guard() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.validate_document_correction_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,pg_temp
            AS $$
            DECLARE
                source_file_id uuid;
                source_block_parse_id uuid;
                result_file_id uuid;
                result_parent_id uuid;
                result_source_type text;
                correction_job_id uuid;
                correction_job_count integer;
                dispatch_count integer;
            BEGIN
                SELECT file_id INTO source_file_id
                  FROM public.document_parse_versions WHERE id=NEW.source_parse_version_id;
                SELECT parse_version_id INTO source_block_parse_id
                  FROM public.document_blocks WHERE id=NEW.source_block_id;
                SELECT file_id,parent_version_id,source_type
                  INTO result_file_id,result_parent_id,result_source_type
                  FROM public.document_parse_versions WHERE id=NEW.result_parse_version_id;
                IF source_file_id IS NULL
                   OR source_block_parse_id IS DISTINCT FROM NEW.source_parse_version_id
                   OR result_file_id IS DISTINCT FROM source_file_id
                   OR result_parent_id IS DISTINCT FROM NEW.source_parse_version_id
                   OR result_source_type<>'manual_correction'
                   OR NEW.result_parse_version_id=NEW.source_parse_version_id THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='document correction lineage is invalid';
                END IF;
                SELECT count(*) INTO correction_job_count
                  FROM public.async_jobs
                 WHERE job_type='manual_correction_snapshot'
                   AND resource_type='document_parse_version'
                   AND resource_id=NEW.result_parse_version_id
                   AND input_schema_version=1
                   AND input_json->>'file_id'=source_file_id::text
                   AND input_json->>'source_parse_version_id'=NEW.source_parse_version_id::text
                   AND input_json->>'result_parse_version_id'=NEW.result_parse_version_id::text
                   AND input_json->>'correction_id'=NEW.id::text
                   AND input_json->>'handler_code_version'='manual-correction-snapshot-v1'
                   AND input_json->>'handler_registry_version'=handler_registry_version
                   AND input_json->>'handler_registry_hash'=handler_registry_hash
                   AND (SELECT count(*) FROM jsonb_object_keys(input_json))=7;
                IF correction_job_count<>1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='document correction job identity is invalid';
                END IF;
                SELECT id INTO correction_job_id FROM public.async_jobs
                 WHERE job_type='manual_correction_snapshot'
                   AND resource_type='document_parse_version'
                   AND resource_id=NEW.result_parse_version_id;
                SELECT count(*) INTO dispatch_count FROM public.outbox_events
                 WHERE aggregate_type='async_job' AND aggregate_id=correction_job_id
                   AND event_type='job.dispatch.requested' AND event_version=1
                   AND event_sequence=1
                   AND payload_json=jsonb_build_object('job_id',correction_job_id::text);
                IF dispatch_count<>1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='document correction dispatch identity is invalid';
                END IF;
                RETURN NEW;
            END;
            $$;
            REVOKE ALL ON FUNCTION public.validate_document_correction_v1() FROM PUBLIC;
            CREATE CONSTRAINT TRIGGER trg_document_correction_consistency_v1
                AFTER INSERT ON public.document_block_corrections
                DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW EXECUTE FUNCTION public.validate_document_correction_v1();
            """
        )
    )


def _create_manual_runtime_guard() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.validate_manual_correction_runtime_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,pg_temp
            AS $$
            DECLARE
                target_parse_id uuid;
                parse_status text;
                job_status text;
                matching_job_count integer;
            BEGIN
                IF TG_TABLE_NAME='async_jobs' THEN
                    IF NEW.job_type<>'manual_correction_snapshot' THEN
                        RETURN NULL;
                    END IF;
                    IF NEW.resource_type<>'document_parse_version' OR NEW.max_attempts<>1 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='manual correction job identity is invalid';
                    END IF;
                    target_parse_id := NEW.resource_id;
                ELSIF TG_TABLE_NAME='document_parse_versions' THEN
                    IF NEW.source_type<>'manual_correction' THEN
                        RETURN NULL;
                    END IF;
                    target_parse_id := NEW.id;
                ELSE
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='unsupported manual correction runtime table';
                END IF;

                SELECT status INTO parse_status
                  FROM public.document_parse_versions
                 WHERE id=target_parse_id AND source_type='manual_correction';
                SELECT count(*),min(status) INTO matching_job_count,job_status
                  FROM public.async_jobs
                 WHERE job_type='manual_correction_snapshot'
                   AND resource_type='document_parse_version'
                   AND resource_id=target_parse_id;
                IF parse_status IS NULL OR matching_job_count<>1 OR NOT (
                    (parse_status='queued' AND job_status='queued') OR
                    (parse_status='running' AND job_status='running') OR
                    (parse_status IN ('succeeded','active','superseded')
                        AND job_status='succeeded') OR
                    (parse_status='failed' AND job_status='failed')
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='manual correction job and parse states are inconsistent';
                END IF;
                RETURN NULL;
            END;
            $$;
            REVOKE ALL ON FUNCTION public.validate_manual_correction_runtime_v1() FROM PUBLIC;
            CREATE CONSTRAINT TRIGGER trg_manual_correction_parse_runtime_v1
                AFTER INSERT OR UPDATE ON public.document_parse_versions
                DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW WHEN (NEW.source_type='manual_correction')
                EXECUTE FUNCTION public.validate_manual_correction_runtime_v1();
            CREATE CONSTRAINT TRIGGER trg_manual_correction_job_runtime_v1
                AFTER INSERT OR UPDATE ON public.async_jobs
                DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW WHEN (NEW.job_type='manual_correction_snapshot')
                EXECUTE FUNCTION public.validate_manual_correction_runtime_v1();
            """
        )
    )


def upgrade() -> None:
    _preflight_upgrade()
    op.alter_column(
        "document_block_corrections",
        "result_parse_version_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_document_block_corrections_result_parse",
        "document_block_corrections",
        ["result_parse_version_id"],
    )

    op.drop_constraint(
        "uq_markdown_source_mapping_identity", "markdown_source_mappings", type_="unique"
    )
    op.alter_column("markdown_source_mappings", "block_id", existing_type=sa.Uuid(), nullable=True)
    op.execute(
        sa.text(
            "ALTER TABLE public.markdown_source_mappings ADD CONSTRAINT "
            "uq_markdown_source_mapping_identity UNIQUE NULLS NOT DISTINCT "
            "(markdown_version_id,ast_node_id,md_char_start,md_char_end,block_id)"
        )
    )

    op.add_column(
        "document_assets", sa.Column("security_policy_version", sa.String(50), nullable=False)
    )
    op.add_column("document_assets", sa.Column("security_policy_hash", sa.CHAR(64), nullable=False))
    op.add_column("document_assets", sa.Column("security_checked_at", sa.DateTime(timezone=True)))
    op.add_column("document_assets", sa.Column("security_error_code", sa.String(80)))
    op.add_column("document_assets", sa.Column("security_scanner_profile_class", sa.String(20)))
    op.add_column("document_assets", sa.Column("security_scanner_registry_version", sa.String(100)))
    op.add_column("document_assets", sa.Column("security_scanner_registry_hash", sa.CHAR(64)))
    op.add_column("document_assets", sa.Column("security_scanner_adapter_code", sa.String(64)))
    op.add_column("document_assets", sa.Column("security_scanner_version", sa.String(100)))
    op.add_column("document_assets", sa.Column("security_scanner_definition_version", sa.Text()))
    op.add_column("document_assets", sa.Column("security_scanner_invoked", sa.Boolean()))
    op.add_column(
        "document_assets",
        sa.Column(
            "source_asset_id",
            sa.Uuid(),
            sa.ForeignKey("document_assets.id", name="fk_document_assets_source_asset"),
        ),
    )
    op.create_index(
        "uq_document_assets_parse_source",
        "document_assets",
        ["parse_version_id", "source_asset_id"],
        unique=True,
        postgresql_where=sa.text("source_asset_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_document_assets_security_policy_identity",
        "document_assets",
        "security_policy_version='asset-security-v1' AND "
        f"security_policy_hash='{_ASSET_POLICY_HASH}'",
    )
    op.create_check_constraint(
        "ck_document_assets_security_error_matrix",
        "document_assets",
        "(security_status='pending' AND security_checked_at IS NULL "
        "AND security_error_code IS NULL AND security_scanner_invoked IS NULL) OR "
        "(security_status='clean' AND security_checked_at IS NOT NULL "
        "AND security_error_code IS NULL AND security_scanner_invoked IS TRUE) OR "
        "(security_status='infected' AND security_checked_at IS NOT NULL "
        "AND security_error_code IN ('ACTIVE_CONTENT_DETECTED','MALWARE_DETECTED') "
        "AND security_scanner_invoked IS TRUE) OR "
        "(security_status='scan_failed' AND security_checked_at IS NOT NULL "
        "AND security_error_code IN "
        "('OBJECT_READ_TRANSIENT','SCANNER_TIMEOUT','SCANNER_UNAVAILABLE') "
        "AND security_scanner_invoked IS NOT NULL) OR "
        "(security_status='unsupported' AND security_checked_at IS NOT NULL "
        "AND security_error_code IN ('IMAGE_DECODE_INVALID','IMAGE_LIMIT_EXCEEDED',"
        "'MAGIC_BYTES_MISMATCH','MEDIA_TYPE_UNSUPPORTED') "
        "AND security_scanner_invoked IS FALSE) OR "
        "(security_status='not_configured' AND security_checked_at IS NOT NULL "
        "AND security_error_code='SCANNER_NOT_CONFIGURED' AND security_scanner_invoked IS FALSE)",
    )
    _create_asset_guard()
    _create_correction_guard()
    _create_manual_runtime_guard()


def downgrade() -> None:
    _lock_tables()
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM public.document_block_corrections LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.document_assets LIMIT 1)
                   OR EXISTS (SELECT 1 FROM public.markdown_source_mappings WHERE block_id IS NULL)
                   OR EXISTS (SELECT 1 FROM public.document_parse_versions
                               WHERE source_type IN ('manual_correction','security_revalidation'))
                   OR EXISTS (SELECT 1 FROM public.async_jobs
                               WHERE job_type IN
                                  ('manual_correction_snapshot','asset_security_revalidation'))
                THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='document correction evidence blocks downgrade';
                END IF;
            END; $$;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER trg_manual_correction_job_runtime_v1 ON public.async_jobs"))
    op.execute(
        sa.text(
            "DROP TRIGGER trg_manual_correction_parse_runtime_v1 ON public.document_parse_versions"
        )
    )
    op.execute(sa.text("DROP FUNCTION public.validate_manual_correction_runtime_v1()"))
    op.execute(
        sa.text(
            "DROP TRIGGER trg_document_correction_consistency_v1 "
            "ON public.document_block_corrections"
        )
    )
    op.execute(sa.text("DROP FUNCTION public.validate_document_correction_v1()"))
    op.execute(sa.text("DROP TRIGGER trg_document_assets_state_v2 ON public.document_assets"))
    op.execute(sa.text("DROP FUNCTION public.enforce_document_assets_state_v2()"))
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_document_assets_state_v1 "
            "BEFORE INSERT OR UPDATE OR DELETE ON public.document_assets "
            "FOR EACH ROW EXECUTE FUNCTION public.enforce_document_processing_state_v1()"
        )
    )

    op.drop_constraint("ck_document_assets_security_error_matrix", "document_assets", type_="check")
    op.drop_constraint(
        "ck_document_assets_security_policy_identity", "document_assets", type_="check"
    )
    op.drop_index("uq_document_assets_parse_source", table_name="document_assets")
    op.drop_constraint("fk_document_assets_source_asset", "document_assets", type_="foreignkey")
    for column in (
        "source_asset_id",
        "security_scanner_invoked",
        "security_scanner_definition_version",
        "security_scanner_version",
        "security_scanner_adapter_code",
        "security_scanner_registry_hash",
        "security_scanner_registry_version",
        "security_scanner_profile_class",
        "security_error_code",
        "security_checked_at",
        "security_policy_hash",
        "security_policy_version",
    ):
        op.drop_column("document_assets", column)

    op.drop_constraint(
        "uq_markdown_source_mapping_identity", "markdown_source_mappings", type_="unique"
    )
    op.alter_column("markdown_source_mappings", "block_id", existing_type=sa.Uuid(), nullable=False)
    op.create_unique_constraint(
        "uq_markdown_source_mapping_identity",
        "markdown_source_mappings",
        ["markdown_version_id", "ast_node_id", "md_char_start", "md_char_end", "block_id"],
    )
    op.drop_constraint(
        "uq_document_block_corrections_result_parse",
        "document_block_corrections",
        type_="unique",
    )
    op.alter_column(
        "document_block_corrections",
        "result_parse_version_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
