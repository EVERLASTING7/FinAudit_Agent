"""创建 Markdown、制度、分块与合同支持文件核心事实。

Revision ID: 20260814_018
Revises: 20260814_017
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260814_018"
down_revision: str | None = "20260814_017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATED_TABLES = (
    "contract_documents",
    "document_block_corrections",
    "document_chunk_sets",
    "document_chunk_sources",
    "document_chunks",
    "document_markdown_versions",
    "markdown_source_mappings",
    "markdown_validation_results",
    "chunking_configs",
    "policy_approval_records",
    "policy_documents",
)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM public.document_blocks
                     WHERE coordinate_unavailable_reason IS NOT NULL
                       AND coordinate_unavailable_reason NOT IN
                           ('source_not_paginated','extractor_not_available')
                ) OR EXISTS (
                    SELECT 1 FROM public.document_assets
                     WHERE coordinate_unavailable_reason IS NOT NULL
                       AND coordinate_unavailable_reason NOT IN
                           ('source_not_paginated','extractor_not_available')
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='legacy coordinate reason requires an explicit forward repair';
                END IF;
            END;
            $$;

            ALTER TABLE public.document_blocks
                ADD CONSTRAINT ck_document_blocks_coordinate_reason_allowed
                CHECK (
                    coordinate_unavailable_reason IS NULL
                    OR coordinate_unavailable_reason IN
                       ('source_not_paginated','extractor_not_available')
                );
            ALTER TABLE public.document_assets
                ADD CONSTRAINT ck_document_assets_coordinate_reason_allowed
                CHECK (
                    coordinate_unavailable_reason IS NULL
                    OR coordinate_unavailable_reason IN
                       ('source_not_paginated','extractor_not_available')
                );

            CREATE TABLE public.document_block_corrections (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                source_parse_version_id uuid NOT NULL
                    REFERENCES public.document_parse_versions(id),
                source_block_id uuid NOT NULL REFERENCES public.document_blocks(id),
                result_parse_version_id uuid NULL
                    REFERENCES public.document_parse_versions(id),
                field_name varchar(40) NOT NULL,
                before_value_json jsonb NOT NULL,
                after_value_json jsonb NOT NULL,
                reason text NOT NULL,
                corrected_by uuid NOT NULL REFERENCES public.users(id),
                corrected_at timestamptz NOT NULL DEFAULT now(),
                trace_id uuid NOT NULL,
                CONSTRAINT ck_document_block_corrections_field_name_allowed
                    CHECK (field_name IN ('text_content','block_type','reading_order','bbox')),
                CONSTRAINT ck_document_block_corrections_reason_nonempty
                    CHECK (btrim(reason) <> '')
            );

            CREATE TABLE public.document_markdown_versions (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id uuid NOT NULL REFERENCES public.organizations(id),
                file_id uuid NOT NULL REFERENCES public.files(id),
                parse_version_id uuid NOT NULL REFERENCES public.document_parse_versions(id),
                version_no integer NOT NULL,
                converter_name varchar(100) NOT NULL,
                converter_version varchar(100) NOT NULL,
                schema_version varchar(50) NOT NULL,
                code_version varchar(100) NOT NULL,
                status varchar(40) NOT NULL,
                markdown_text text NOT NULL,
                content_sha256 char(64) NOT NULL,
                char_count integer NOT NULL,
                token_count integer NULL,
                document_metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
                quality_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
                warning_count integer NOT NULL DEFAULT 0,
                blocking_issue_count integer NOT NULL DEFAULT 0,
                failure_reason text NULL,
                activated_at timestamptz NULL,
                superseded_at timestamptz NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                created_by uuid NULL REFERENCES public.users(id),
                trace_id uuid NOT NULL,
                CONSTRAINT ck_document_markdown_versions_version_no_positive
                    CHECK (version_no > 0),
                CONSTRAINT ck_document_markdown_versions_status_allowed CHECK (
                    status IN ('queued','converting','validating','review_required','ready',
                               'active','failed','superseded','archived')
                ),
                CONSTRAINT ck_document_markdown_versions_content_sha256_format
                    CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
                CONSTRAINT ck_document_markdown_versions_char_count_matches
                    CHECK (char_count = char_length(markdown_text)),
                CONSTRAINT ck_document_markdown_versions_token_count_nonnegative
                    CHECK (token_count IS NULL OR token_count >= 0),
                CONSTRAINT ck_document_markdown_versions_warning_count_nonnegative
                    CHECK (warning_count >= 0),
                CONSTRAINT ck_document_markdown_versions_blocking_issue_count_nonnegative
                    CHECK (blocking_issue_count >= 0),
                CONSTRAINT ck_document_markdown_versions_document_metadata_object
                    CHECK (jsonb_typeof(document_metadata_json) = 'object'),
                CONSTRAINT ck_document_markdown_versions_quality_object
                    CHECK (jsonb_typeof(quality_summary_json) = 'object'),
                CONSTRAINT ck_document_markdown_versions_lifecycle_matrix CHECK (
                    (status = 'active' AND activated_at IS NOT NULL
                     AND superseded_at IS NULL AND failure_reason IS NULL
                     AND blocking_issue_count = 0)
                    OR (status = 'superseded' AND activated_at IS NOT NULL
                        AND superseded_at IS NOT NULL AND superseded_at >= activated_at
                        AND failure_reason IS NULL)
                    OR (status = 'failed' AND activated_at IS NULL
                        AND superseded_at IS NULL AND failure_reason IS NOT NULL)
                    OR (status NOT IN ('active','superseded','failed')
                        AND activated_at IS NULL AND superseded_at IS NULL)
                ),
                CONSTRAINT uq_markdown_file_version UNIQUE (file_id, version_no),
                CONSTRAINT uq_markdown_deterministic_result UNIQUE
                    (parse_version_id, converter_version, schema_version, content_sha256)
            );
            CREATE UNIQUE INDEX uq_markdown_file_active
                ON public.document_markdown_versions(file_id) WHERE status = 'active';

            CREATE TABLE public.markdown_source_mappings (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                markdown_version_id uuid NOT NULL
                    REFERENCES public.document_markdown_versions(id),
                ast_node_id varchar(200) NOT NULL,
                mapping_type varchar(30) NOT NULL,
                md_char_start integer NOT NULL,
                md_char_end integer NOT NULL,
                md_line_start integer NOT NULL,
                md_line_end integer NOT NULL,
                page_id uuid NOT NULL REFERENCES public.document_pages(id),
                block_id uuid NOT NULL REFERENCES public.document_blocks(id),
                bbox_json jsonb NULL,
                coverage_status varchar(20) NOT NULL,
                coordinate_unavailable_reason text NULL,
                CONSTRAINT ck_markdown_source_mappings_mapping_type_allowed
                    CHECK (mapping_type = 'source'),
                CONSTRAINT ck_markdown_source_mappings_char_range
                    CHECK (md_char_start >= 0 AND md_char_end > md_char_start),
                CONSTRAINT ck_markdown_source_mappings_line_range
                    CHECK (md_line_start > 0 AND md_line_end >= md_line_start),
                CONSTRAINT ck_markdown_source_mappings_coverage_status_allowed
                    CHECK (coverage_status IN ('full','partial')),
                CONSTRAINT ck_markdown_source_mappings_coordinate_matrix CHECK (
                    (bbox_json IS NULL) = (coordinate_unavailable_reason IS NOT NULL)
                ),
                CONSTRAINT ck_markdown_source_mappings_coordinate_reason_allowed CHECK (
                    coordinate_unavailable_reason IS NULL
                    OR coordinate_unavailable_reason IN
                       ('source_not_paginated','extractor_not_available')
                ),
                CONSTRAINT uq_markdown_source_mapping_identity UNIQUE
                    (markdown_version_id, ast_node_id, md_char_start, md_char_end, block_id)
            );
            CREATE INDEX idx_markdown_source_mapping_version
                ON public.markdown_source_mappings(markdown_version_id, md_char_start);

            CREATE TABLE public.markdown_validation_results (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                markdown_version_id uuid NOT NULL
                    REFERENCES public.document_markdown_versions(id),
                validator_code varchar(80) NOT NULL,
                validator_version varchar(80) NOT NULL,
                severity varchar(20) NOT NULL,
                issue_code varchar(80) NOT NULL,
                message text NOT NULL,
                ast_node_id varchar(200) NULL,
                md_char_start integer NULL,
                md_char_end integer NULL,
                source_block_id uuid NULL REFERENCES public.document_blocks(id),
                is_blocking boolean NOT NULL,
                details_json jsonb NOT NULL DEFAULT '{}'::jsonb,
                created_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT ck_markdown_validation_results_severity_allowed
                    CHECK (severity IN ('info','warning','error')),
                CONSTRAINT ck_markdown_validation_results_validator_code_nonempty
                    CHECK (btrim(validator_code) <> ''),
                CONSTRAINT ck_markdown_validation_results_issue_code_nonempty
                    CHECK (btrim(issue_code) <> ''),
                CONSTRAINT ck_markdown_validation_results_char_range CHECK (
                    (md_char_start IS NULL AND md_char_end IS NULL)
                    OR (md_char_start >= 0 AND md_char_end > md_char_start)
                ),
                CONSTRAINT ck_markdown_validation_results_details_object
                    CHECK (jsonb_typeof(details_json) = 'object')
            );
            CREATE INDEX idx_markdown_validation_version
                ON public.markdown_validation_results(markdown_version_id, is_blocking, severity);

            CREATE TABLE public.policy_documents (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id uuid NOT NULL REFERENCES public.organizations(id),
                knowledge_base_id uuid NOT NULL REFERENCES public.knowledge_bases(id),
                source_file_id uuid NOT NULL REFERENCES public.files(id),
                policy_code varchar(100) NOT NULL,
                name varchar(300) NOT NULL,
                version varchar(50) NOT NULL,
                issuing_department varchar(200) NULL,
                effective_from date NOT NULL,
                effective_to date NULL,
                scope_json jsonb NOT NULL DEFAULT '{}'::jsonb,
                access_scope varchar(40) NOT NULL DEFAULT 'internal',
                allowed_role_codes text[] NOT NULL DEFAULT '{}'::text[],
                status varchar(40) NOT NULL,
                submitted_by uuid NULL REFERENCES public.users(id),
                submitted_at timestamptz NULL,
                business_approved_by uuid NULL REFERENCES public.users(id),
                business_approved_at timestamptz NULL,
                technical_published_by uuid NULL REFERENCES public.users(id),
                technical_published_at timestamptz NULL,
                superseded_by_policy_id uuid NULL REFERENCES public.policy_documents(id),
                revoked_at timestamptz NULL,
                revoked_by uuid NULL REFERENCES public.users(id),
                revoke_reason text NULL,
                row_version bigint NOT NULL DEFAULT 1,
                created_at timestamptz NOT NULL DEFAULT now(),
                created_by uuid NOT NULL REFERENCES public.users(id),
                updated_at timestamptz NOT NULL DEFAULT now(),
                updated_by uuid NULL REFERENCES public.users(id),
                deleted_at timestamptz NULL,
                deleted_by uuid NULL REFERENCES public.users(id),
                delete_reason text NULL,
                CONSTRAINT ck_policy_documents_status_allowed CHECK (
                    status IN ('draft','submitted','business_approved','published',
                               'superseded','revoked','archived')
                ),
                CONSTRAINT ck_policy_documents_effective_range
                    CHECK (effective_to IS NULL OR effective_to > effective_from),
                CONSTRAINT ck_policy_documents_scope_object
                    CHECK (jsonb_typeof(scope_json) = 'object'),
                CONSTRAINT ck_policy_documents_row_version_positive CHECK (row_version > 0),
                CONSTRAINT ck_policy_documents_publication_matrix CHECK (
                    (status IN ('published','superseded')
                     AND business_approved_by IS NOT NULL
                     AND business_approved_at IS NOT NULL
                     AND technical_published_by IS NOT NULL
                     AND technical_published_at IS NOT NULL)
                    OR status NOT IN ('published','superseded')
                ),
                CONSTRAINT uq_policy_code_version
                    UNIQUE (knowledge_base_id, policy_code, version),
                CONSTRAINT uq_policy_source_file UNIQUE (source_file_id)
            );
            CREATE INDEX idx_policy_effective_lookup
                ON public.policy_documents(knowledge_base_id, policy_code, status);
            ALTER TABLE public.policy_documents
                ADD CONSTRAINT ex_policy_effective_range_no_overlap
                EXCLUDE USING gist (
                    knowledge_base_id WITH =,
                    policy_code WITH =,
                    daterange(effective_from, effective_to, '[)') WITH &&
                ) WHERE (status IN ('published','superseded') AND deleted_at IS NULL);

            ALTER TABLE public.file_primary_business_objects
                ADD CONSTRAINT fk_file_primary_business_objects_policy_document
                FOREIGN KEY (policy_document_id) REFERENCES public.policy_documents(id);

            CREATE FUNCTION public.enforce_file_primary_business_object_v2()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                file_business_type text;
                file_organization_id uuid;
                business_organization_id uuid;
            BEGIN
                IF TG_OP IN ('UPDATE', 'DELETE') THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='file primary business object history is append-only';
                END IF;
                SELECT intended_business_type, organization_id
                  INTO file_business_type, file_organization_id
                  FROM public.files WHERE id = NEW.file_id FOR KEY SHARE;
                IF file_business_type IS DISTINCT FROM NEW.business_type THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='file primary business type mismatch';
                END IF;
                IF NEW.business_type = 'contract' THEN
                    SELECT organization_id INTO business_organization_id
                      FROM public.contracts WHERE id = NEW.contract_id FOR KEY SHARE;
                ELSIF NEW.business_type = 'invoice' THEN
                    SELECT organization_id INTO business_organization_id
                      FROM public.invoices WHERE id = NEW.invoice_id FOR KEY SHARE;
                ELSIF NEW.business_type = 'supplementary_agreement' THEN
                    SELECT organization_id INTO business_organization_id
                      FROM public.supplementary_agreements
                     WHERE id = NEW.supplementary_agreement_id FOR KEY SHARE;
                ELSIF NEW.business_type = 'policy' THEN
                    SELECT organization_id INTO business_organization_id
                      FROM public.policy_documents
                     WHERE id = NEW.policy_document_id FOR KEY SHARE;
                END IF;
                IF business_organization_id IS DISTINCT FROM file_organization_id THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='file primary business object organization mismatch';
                END IF;
                RETURN NEW;
            END;
            $$;
            REVOKE ALL ON FUNCTION public.enforce_file_primary_business_object_v2()
                FROM PUBLIC;
            DROP TRIGGER trg_file_primary_business_objects_state_v1
                ON public.file_primary_business_objects;
            CREATE TRIGGER trg_file_primary_business_objects_state_v1
                BEFORE INSERT OR UPDATE OR DELETE
                ON public.file_primary_business_objects FOR EACH ROW
                EXECUTE FUNCTION public.enforce_file_primary_business_object_v2();

            CREATE TABLE public.policy_approval_records (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                policy_document_id uuid NOT NULL REFERENCES public.policy_documents(id),
                action varchar(30) NOT NULL,
                from_status varchar(40) NULL,
                to_status varchar(40) NOT NULL,
                actor_id uuid NOT NULL REFERENCES public.users(id),
                actor_role_code varchar(40) NOT NULL,
                reason text NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                trace_id uuid NOT NULL,
                CONSTRAINT ck_policy_approval_records_action_nonempty
                    CHECK (btrim(action) <> '' AND btrim(to_status) <> ''),
                CONSTRAINT ck_policy_approval_records_role_nonempty
                    CHECK (btrim(actor_role_code) <> '')
            );
            CREATE INDEX idx_policy_approval_timeline
                ON public.policy_approval_records(policy_document_id, created_at);

            CREATE TABLE public.chunking_configs (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id uuid NOT NULL REFERENCES public.organizations(id),
                profile_version varchar(50) NOT NULL,
                profile_hash char(64) NOT NULL,
                parameters_json jsonb NOT NULL,
                published_at timestamptz NOT NULL DEFAULT now(),
                code_version varchar(100) NOT NULL,
                CONSTRAINT ck_chunking_configs_profile_version_allowed
                    CHECK (profile_version = 'chunk-profile-v1'),
                CONSTRAINT ck_chunking_configs_profile_hash_format
                    CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
                CONSTRAINT ck_chunking_configs_parameters_object
                    CHECK (jsonb_typeof(parameters_json) = 'object'),
                CONSTRAINT uq_chunk_profile_identity
                    UNIQUE (organization_id, profile_version, profile_hash)
            );

            CREATE TABLE public.document_chunk_sets (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id uuid NOT NULL REFERENCES public.organizations(id),
                policy_document_id uuid NOT NULL REFERENCES public.policy_documents(id),
                markdown_version_id uuid NOT NULL
                    REFERENCES public.document_markdown_versions(id),
                chunking_config_id uuid NOT NULL REFERENCES public.chunking_configs(id),
                version_no integer NOT NULL,
                status varchar(40) NOT NULL,
                profile_version varchar(50) NOT NULL,
                profile_hash char(64) NOT NULL,
                profile_json jsonb NOT NULL,
                chunk_count integer NOT NULL,
                content_manifest_hash char(64) NULL,
                quality_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
                blocking_issue_count integer NOT NULL DEFAULT 0,
                failure_reason text NULL,
                activated_at timestamptz NULL,
                superseded_at timestamptz NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                created_by uuid NULL REFERENCES public.users(id),
                trace_id uuid NOT NULL,
                CONSTRAINT ck_document_chunk_sets_version_no_positive CHECK (version_no > 0),
                CONSTRAINT ck_document_chunk_sets_status_allowed CHECK (
                    status IN ('building','ready','active','failed','superseded','archived')
                ),
                CONSTRAINT ck_document_chunk_sets_profile_version_allowed
                    CHECK (profile_version = 'chunk-profile-v1'),
                CONSTRAINT ck_document_chunk_sets_profile_hash_format
                    CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
                CONSTRAINT ck_document_chunk_sets_profile_object
                    CHECK (jsonb_typeof(profile_json) = 'object'),
                CONSTRAINT ck_document_chunk_sets_chunk_count_nonnegative
                    CHECK (chunk_count >= 0),
                CONSTRAINT ck_document_chunk_sets_manifest_hash_format CHECK (
                    content_manifest_hash IS NULL
                    OR content_manifest_hash ~ '^[0-9a-f]{64}$'
                ),
                CONSTRAINT ck_document_chunk_sets_quality_object
                    CHECK (jsonb_typeof(quality_summary_json) = 'object'),
                CONSTRAINT ck_document_chunk_sets_blocking_issue_count_nonnegative
                    CHECK (blocking_issue_count >= 0),
                CONSTRAINT uq_policy_chunk_set_version
                    UNIQUE (policy_document_id, version_no),
                CONSTRAINT uq_chunk_set_input
                    UNIQUE (policy_document_id, markdown_version_id, profile_hash)
            );
            CREATE UNIQUE INDEX uq_policy_active_chunk_set
                ON public.document_chunk_sets(policy_document_id) WHERE status = 'active';

            CREATE TABLE public.document_chunks (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                chunk_set_id uuid NOT NULL REFERENCES public.document_chunk_sets(id),
                chunk_index integer NOT NULL,
                title_path text[] NOT NULL DEFAULT '{}'::text[],
                content_text text NOT NULL,
                content_sha256 char(64) NOT NULL,
                ast_node_ids text[] NOT NULL,
                md_char_start integer NOT NULL,
                md_char_end integer NOT NULL,
                start_page_no integer NOT NULL,
                end_page_no integer NOT NULL,
                char_count integer NOT NULL,
                token_count integer NULL,
                quality_flags text[] NOT NULL DEFAULT '{}'::text[],
                CONSTRAINT ck_document_chunks_chunk_index_nonnegative CHECK (chunk_index >= 0),
                CONSTRAINT ck_document_chunks_content_nonempty CHECK (btrim(content_text) <> ''),
                CONSTRAINT ck_document_chunks_content_hash_format
                    CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
                CONSTRAINT ck_document_chunks_ast_nodes_nonempty
                    CHECK (cardinality(ast_node_ids) > 0),
                CONSTRAINT ck_document_chunks_char_range
                    CHECK (md_char_start >= 0 AND md_char_end > md_char_start),
                CONSTRAINT ck_document_chunks_page_range
                    CHECK (start_page_no > 0 AND end_page_no >= start_page_no),
                CONSTRAINT ck_document_chunks_char_count_matches
                    CHECK (char_count = char_length(content_text) AND char_count > 0),
                CONSTRAINT ck_document_chunks_token_count_nonnegative
                    CHECK (token_count IS NULL OR token_count >= 0),
                CONSTRAINT uq_chunk_set_index UNIQUE (chunk_set_id, chunk_index)
            );
            CREATE INDEX idx_document_chunks_content
                ON public.document_chunks(chunk_set_id, content_sha256);

            CREATE TABLE public.document_chunk_sources (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                chunk_id uuid NOT NULL REFERENCES public.document_chunks(id),
                source_seq integer NOT NULL,
                markdown_mapping_id uuid NOT NULL
                    REFERENCES public.markdown_source_mappings(id),
                parse_version_id uuid NOT NULL REFERENCES public.document_parse_versions(id),
                page_id uuid NOT NULL REFERENCES public.document_pages(id),
                block_id uuid NOT NULL REFERENCES public.document_blocks(id),
                page_no integer NOT NULL,
                bbox_json jsonb NULL,
                quoted_text_sha256 char(64) NOT NULL,
                coordinate_unavailable_reason text NULL,
                CONSTRAINT ck_document_chunk_sources_source_seq_positive CHECK (source_seq > 0),
                CONSTRAINT ck_document_chunk_sources_page_no_positive CHECK (page_no > 0),
                CONSTRAINT ck_document_chunk_sources_quoted_hash_format
                    CHECK (quoted_text_sha256 ~ '^[0-9a-f]{64}$'),
                CONSTRAINT ck_document_chunk_sources_coordinate_matrix CHECK (
                    (bbox_json IS NULL) = (coordinate_unavailable_reason IS NOT NULL)
                ),
                CONSTRAINT ck_document_chunk_sources_coordinate_reason_allowed CHECK (
                    coordinate_unavailable_reason IS NULL
                    OR coordinate_unavailable_reason IN
                       ('source_not_paginated','extractor_not_available')
                ),
                CONSTRAINT uq_chunk_source_sequence UNIQUE (chunk_id, source_seq),
                CONSTRAINT uq_chunk_source_identity
                    UNIQUE (chunk_id, markdown_mapping_id, block_id)
            );

            CREATE TABLE public.contract_documents (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id uuid NOT NULL REFERENCES public.organizations(id),
                contract_id uuid NOT NULL REFERENCES public.contracts(id),
                file_id uuid NOT NULL REFERENCES public.files(id),
                document_role varchar(40) NOT NULL,
                description text NULL,
                linked_by uuid NOT NULL REFERENCES public.users(id),
                linked_at timestamptz NOT NULL DEFAULT now(),
                unlinked_by uuid NULL REFERENCES public.users(id),
                unlinked_at timestamptz NULL,
                unlink_reason text NULL,
                CONSTRAINT ck_contract_documents_document_role_allowed
                    CHECK (document_role IN ('attachment','evidence','other')),
                CONSTRAINT ck_contract_documents_unlink_matrix CHECK (
                    (unlinked_at IS NULL AND unlink_reason IS NULL)
                    OR (unlinked_at IS NOT NULL AND unlink_reason IS NOT NULL
                        AND btrim(unlink_reason) <> '')
                )
            );
            CREATE UNIQUE INDEX uq_contract_document_active
                ON public.contract_documents(contract_id, file_id, document_role)
                WHERE unlinked_at IS NULL;
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_knowledge_append_only_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE='knowledge history is append-only';
            END;
            $$;

            CREATE FUNCTION public.enforce_markdown_lifecycle_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='markdown versions cannot be deleted';
                END IF;
                IF ROW(NEW.id, NEW.organization_id, NEW.file_id, NEW.parse_version_id,
                       NEW.version_no, NEW.converter_name, NEW.converter_version,
                       NEW.schema_version, NEW.code_version, NEW.markdown_text,
                       NEW.content_sha256, NEW.char_count, NEW.token_count,
                       NEW.document_metadata_json, NEW.quality_summary_json,
                       NEW.warning_count, NEW.blocking_issue_count, NEW.failure_reason,
                       NEW.activated_at, NEW.created_at, NEW.created_by, NEW.trace_id)
                   IS DISTINCT FROM
                   ROW(OLD.id, OLD.organization_id, OLD.file_id, OLD.parse_version_id,
                       OLD.version_no, OLD.converter_name, OLD.converter_version,
                       OLD.schema_version, OLD.code_version, OLD.markdown_text,
                       OLD.content_sha256, OLD.char_count, OLD.token_count,
                       OLD.document_metadata_json, OLD.quality_summary_json,
                       OLD.warning_count, OLD.blocking_issue_count, OLD.failure_reason,
                       OLD.activated_at, OLD.created_at, OLD.created_by, OLD.trace_id)
                   OR OLD.status <> 'active' OR NEW.status <> 'superseded'
                   OR OLD.superseded_at IS NOT NULL OR NEW.superseded_at IS NULL THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='markdown version is immutable';
                END IF;
                RETURN NEW;
            END;
            $$;

            CREATE FUNCTION public.enforce_chunk_set_lifecycle_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='chunk sets cannot be deleted';
                END IF;
                IF ROW(NEW.id, NEW.organization_id, NEW.policy_document_id,
                       NEW.markdown_version_id, NEW.chunking_config_id, NEW.version_no,
                       NEW.profile_version, NEW.profile_hash, NEW.profile_json,
                       NEW.chunk_count, NEW.content_manifest_hash,
                       NEW.quality_summary_json, NEW.blocking_issue_count,
                       NEW.failure_reason, NEW.activated_at, NEW.created_at,
                       NEW.created_by, NEW.trace_id)
                   IS DISTINCT FROM
                   ROW(OLD.id, OLD.organization_id, OLD.policy_document_id,
                       OLD.markdown_version_id, OLD.chunking_config_id, OLD.version_no,
                       OLD.profile_version, OLD.profile_hash, OLD.profile_json,
                       OLD.chunk_count, OLD.content_manifest_hash,
                       OLD.quality_summary_json, OLD.blocking_issue_count,
                       OLD.failure_reason, OLD.activated_at, OLD.created_at,
                       OLD.created_by, OLD.trace_id)
                   OR OLD.status <> 'active' OR NEW.status <> 'superseded'
                   OR OLD.superseded_at IS NOT NULL OR NEW.superseded_at IS NULL THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='chunk set is immutable';
                END IF;
                RETURN NEW;
            END;
            $$;

            CREATE FUNCTION public.enforce_contract_document_lifecycle_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='contract document history cannot be deleted';
                END IF;
                IF ROW(NEW.id, NEW.organization_id, NEW.contract_id, NEW.file_id,
                       NEW.document_role, NEW.description, NEW.linked_by, NEW.linked_at)
                   IS DISTINCT FROM
                   ROW(OLD.id, OLD.organization_id, OLD.contract_id, OLD.file_id,
                       OLD.document_role, OLD.description, OLD.linked_by, OLD.linked_at)
                   OR OLD.unlinked_at IS NOT NULL OR NEW.unlinked_at IS NULL
                   OR NEW.unlinked_by IS NULL THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='contract document transition is invalid';
                END IF;
                RETURN NEW;
            END;
            $$;

            CREATE TRIGGER trg_document_block_corrections_append_only_v1
                BEFORE UPDATE OR DELETE ON public.document_block_corrections
                FOR EACH ROW EXECUTE FUNCTION public.enforce_knowledge_append_only_v1();
            CREATE TRIGGER trg_markdown_source_mappings_append_only_v1
                BEFORE UPDATE OR DELETE ON public.markdown_source_mappings
                FOR EACH ROW EXECUTE FUNCTION public.enforce_knowledge_append_only_v1();
            CREATE TRIGGER trg_markdown_validation_results_append_only_v1
                BEFORE UPDATE OR DELETE ON public.markdown_validation_results
                FOR EACH ROW EXECUTE FUNCTION public.enforce_knowledge_append_only_v1();
            CREATE TRIGGER trg_policy_approval_records_append_only_v1
                BEFORE UPDATE OR DELETE ON public.policy_approval_records
                FOR EACH ROW EXECUTE FUNCTION public.enforce_knowledge_append_only_v1();
            CREATE TRIGGER trg_chunking_configs_append_only_v1
                BEFORE UPDATE OR DELETE ON public.chunking_configs
                FOR EACH ROW EXECUTE FUNCTION public.enforce_knowledge_append_only_v1();
            CREATE TRIGGER trg_document_chunks_append_only_v1
                BEFORE UPDATE OR DELETE ON public.document_chunks
                FOR EACH ROW EXECUTE FUNCTION public.enforce_knowledge_append_only_v1();
            CREATE TRIGGER trg_document_chunk_sources_append_only_v1
                BEFORE UPDATE OR DELETE ON public.document_chunk_sources
                FOR EACH ROW EXECUTE FUNCTION public.enforce_knowledge_append_only_v1();
            CREATE TRIGGER trg_document_markdown_versions_lifecycle_v1
                BEFORE UPDATE OR DELETE ON public.document_markdown_versions
                FOR EACH ROW EXECUTE FUNCTION public.enforce_markdown_lifecycle_v1();
            CREATE TRIGGER trg_document_chunk_sets_lifecycle_v1
                BEFORE UPDATE OR DELETE ON public.document_chunk_sets
                FOR EACH ROW EXECUTE FUNCTION public.enforce_chunk_set_lifecycle_v1();
            CREATE TRIGGER trg_contract_documents_lifecycle_v1
                BEFORE UPDATE OR DELETE ON public.contract_documents
                FOR EACH ROW EXECUTE FUNCTION public.enforce_contract_document_lifecycle_v1();

            REVOKE ALL ON FUNCTION public.enforce_knowledge_append_only_v1() FROM PUBLIC;
            REVOKE ALL ON FUNCTION public.enforce_markdown_lifecycle_v1() FROM PUBLIC;
            REVOKE ALL ON FUNCTION public.enforce_chunk_set_lifecycle_v1() FROM PUBLIC;
            REVOKE ALL ON FUNCTION public.enforce_contract_document_lifecycle_v1() FROM PUBLIC;
            """
        )
    )


def downgrade() -> None:
    lock_targets = ", ".join(f"public.{name}" for name in sorted(_CREATED_TABLES))
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text(f"LOCK TABLE {lock_targets} IN ACCESS EXCLUSIVE MODE"))
    unions = " UNION ALL ".join(f"SELECT 1 FROM public.{name}" for name in sorted(_CREATED_TABLES))
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS ({unions}) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='markdown and knowledge facts block downgrade';
                END IF;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            DROP TRIGGER trg_contract_documents_lifecycle_v1 ON public.contract_documents;
            DROP TRIGGER trg_document_chunk_sets_lifecycle_v1 ON public.document_chunk_sets;
            DROP TRIGGER trg_document_markdown_versions_lifecycle_v1
                ON public.document_markdown_versions;
            DROP TRIGGER trg_document_chunk_sources_append_only_v1
                ON public.document_chunk_sources;
            DROP TRIGGER trg_document_chunks_append_only_v1 ON public.document_chunks;
            DROP TRIGGER trg_chunking_configs_append_only_v1 ON public.chunking_configs;
            DROP TRIGGER trg_policy_approval_records_append_only_v1
                ON public.policy_approval_records;
            DROP TRIGGER trg_markdown_validation_results_append_only_v1
                ON public.markdown_validation_results;
            DROP TRIGGER trg_markdown_source_mappings_append_only_v1
                ON public.markdown_source_mappings;
            DROP TRIGGER trg_document_block_corrections_append_only_v1
                ON public.document_block_corrections;

            DROP TRIGGER trg_file_primary_business_objects_state_v1
                ON public.file_primary_business_objects;
            CREATE TRIGGER trg_file_primary_business_objects_state_v1
                BEFORE INSERT OR UPDATE OR DELETE
                ON public.file_primary_business_objects FOR EACH ROW
                EXECUTE FUNCTION public.enforce_financial_fact_details_v1();
            DROP FUNCTION public.enforce_file_primary_business_object_v2();

            ALTER TABLE public.file_primary_business_objects
                DROP CONSTRAINT fk_file_primary_business_objects_policy_document;

            DROP TABLE public.contract_documents;
            DROP TABLE public.document_chunk_sources;
            DROP TABLE public.document_chunks;
            DROP TABLE public.document_chunk_sets;
            DROP TABLE public.chunking_configs;
            DROP TABLE public.policy_approval_records;
            DROP TABLE public.policy_documents;
            DROP TABLE public.markdown_validation_results;
            DROP TABLE public.markdown_source_mappings;
            DROP TABLE public.document_markdown_versions;
            DROP TABLE public.document_block_corrections;

            DROP FUNCTION public.enforce_contract_document_lifecycle_v1();
            DROP FUNCTION public.enforce_chunk_set_lifecycle_v1();
            DROP FUNCTION public.enforce_markdown_lifecycle_v1();
            DROP FUNCTION public.enforce_knowledge_append_only_v1();

            ALTER TABLE public.document_assets
                DROP CONSTRAINT ck_document_assets_coordinate_reason_allowed;
            ALTER TABLE public.document_blocks
                DROP CONSTRAINT ck_document_blocks_coordinate_reason_allowed;
            """
        )
    )
