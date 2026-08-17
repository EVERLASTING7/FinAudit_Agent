"""创建文件主对象、合同字段、补充协议变更和人工纠错事实。

Revision ID: 20260813_014
Revises: 20260813_013
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_014"
down_revision: str | None = "20260813_013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "file_primary_business_objects",
        sa.Column("id", _uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("file_id", _uuid(), nullable=False),
        sa.Column("business_type", sa.String(length=40), nullable=False),
        sa.Column("contract_id", _uuid(), nullable=True),
        sa.Column("invoice_id", _uuid(), nullable=True),
        sa.Column("supplementary_agreement_id", _uuid(), nullable=True),
        sa.Column("policy_document_id", _uuid(), nullable=True),
        sa.Column(
            "bound_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("bound_by", _uuid(), nullable=False),
        sa.CheckConstraint(
            "business_type IN ('contract', 'supplementary_agreement', 'invoice', 'policy')",
            name="business_type_allowed",
        ),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name="fk_file_primary_business_objects_file_id_files"
        ),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["contracts.id"],
            name="fk_file_primary_business_objects_contract_id_contracts",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name="fk_file_primary_business_objects_invoice_id_invoices",
        ),
        sa.ForeignKeyConstraint(
            ["supplementary_agreement_id"],
            ["supplementary_agreements.id"],
            name="fk_file_primary_business_objects_agreement",
        ),
        sa.ForeignKeyConstraint(
            ["bound_by"], ["users.id"], name="fk_file_primary_business_objects_bound_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_file_primary_business_objects"),
        sa.UniqueConstraint("file_id", name="uq_file_primary_business_objects_file_id"),
        sa.UniqueConstraint("contract_id", name="uq_file_primary_business_objects_contract_id"),
        sa.UniqueConstraint("invoice_id", name="uq_file_primary_business_objects_invoice_id"),
        sa.UniqueConstraint(
            "supplementary_agreement_id",
            name="uq_file_primary_business_objects_supplementary_agreement_id",
        ),
        sa.UniqueConstraint(
            "policy_document_id",
            name="uq_file_primary_business_objects_policy_document_id",
        ),
        schema="public",
    )

    op.create_table(
        "contract_fields",
        sa.Column("id", _uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("contract_id", _uuid(), nullable=False),
        sa.Column("field_code", sa.String(length=80), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False),
        sa.Column("extracted_value_json", _jsonb(), nullable=True),
        sa.Column("confirmed_value_json", _jsonb(), nullable=True),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=True),
        sa.Column("confirmation_status", sa.String(length=20), nullable=False),
        sa.Column("evidence_file_id", _uuid(), nullable=True),
        sa.Column("evidence_parse_version_id", _uuid(), nullable=True),
        sa.Column("evidence_block_id", _uuid(), nullable=True),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("quote_text", sa.Text(), nullable=True),
        sa.Column("bbox_json", _jsonb(), nullable=True),
        sa.Column("confirmed_by", _uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "(field_code COLLATE \"C\") ~ '^[a-z][a-z0-9_.]{0,79}$'",
            name="field_code_format",
        ),
        sa.CheckConstraint(
            "value_type IN ('string', 'number', 'date', 'json')",
            name="value_type_allowed",
        ),
        sa.CheckConstraint(
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        sa.CheckConstraint("page_no IS NULL OR page_no > 0", name="page_no_positive"),
        sa.CheckConstraint(
            "(evidence_file_id IS NULL AND evidence_parse_version_id IS NULL "
            "AND evidence_block_id IS NULL AND page_no IS NULL AND quote_text IS NULL "
            "AND bbox_json IS NULL) OR "
            "(evidence_file_id IS NOT NULL AND evidence_parse_version_id IS NOT NULL "
            "AND evidence_block_id IS NOT NULL AND page_no IS NOT NULL "
            "AND quote_text IS NOT NULL AND btrim(quote_text) <> '')",
            name="evidence_matrix",
        ),
        sa.CheckConstraint(
            "bbox_json IS NULL OR jsonb_typeof(bbox_json) = 'object'", name="bbox_object"
        ),
        sa.CheckConstraint(
            "extracted_value_json IS NOT NULL OR confirmed_value_json IS NOT NULL",
            name="value_present",
        ),
        sa.CheckConstraint(
            "(confirmation_status = 'unconfirmed' AND confirmed_value_json IS NULL "
            "AND confirmed_by IS NULL AND confirmed_at IS NULL) OR "
            "(confirmation_status = 'confirmed' AND confirmed_value_json IS NOT NULL "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL "
            "AND evidence_block_id IS NOT NULL) OR "
            "(confirmation_status = 'rejected' AND confirmed_value_json IS NULL "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="confirmation_matrix",
        ),
        sa.CheckConstraint(
            "(extracted_value_json IS NULL OR CASE value_type "
            "WHEN 'string' THEN jsonb_typeof(extracted_value_json) = 'string' "
            "WHEN 'number' THEN jsonb_typeof(extracted_value_json) = 'string' "
            "AND (extracted_value_json #>> '{}') ~ '^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$' "
            "WHEN 'date' THEN jsonb_typeof(extracted_value_json) = 'string' "
            "AND (extracted_value_json #>> '{}') ~ '^\\d{4}-\\d{2}-\\d{2}$' "
            "WHEN 'json' THEN jsonb_typeof(extracted_value_json) IN "
            "('object', 'array', 'boolean') ELSE false END) AND "
            "(confirmed_value_json IS NULL OR CASE value_type "
            "WHEN 'string' THEN jsonb_typeof(confirmed_value_json) = 'string' "
            "WHEN 'number' THEN jsonb_typeof(confirmed_value_json) = 'string' "
            "AND (confirmed_value_json #>> '{}') ~ '^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$' "
            "WHEN 'date' THEN jsonb_typeof(confirmed_value_json) = 'string' "
            "AND (confirmed_value_json #>> '{}') ~ '^\\d{4}-\\d{2}-\\d{2}$' "
            "WHEN 'json' THEN jsonb_typeof(confirmed_value_json) IN "
            "('object', 'array', 'boolean') ELSE false END)",
            name="value_shape",
        ),
        sa.CheckConstraint("row_version > 0", name="row_version_positive"),
        sa.ForeignKeyConstraint(
            ["contract_id"], ["contracts.id"], name="fk_contract_fields_contract_id_contracts"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_file_id"],
            ["files.id"],
            name="fk_contract_fields_evidence_file_id_files",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_parse_version_id"],
            ["document_parse_versions.id"],
            name="fk_contract_fields_evidence_parse",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_block_id"],
            ["document_blocks.id"],
            name="fk_contract_fields_evidence_block",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name="fk_contract_fields_confirmed_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_contract_fields"),
        sa.UniqueConstraint("contract_id", "field_code", name="uq_contract_fields_contract_field"),
        schema="public",
    )

    op.create_table(
        "supplementary_agreement_changes",
        sa.Column("id", _uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("supplementary_agreement_id", _uuid(), nullable=False),
        sa.Column("field_code", sa.String(length=80), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False),
        sa.Column("old_value_json", _jsonb(), nullable=True),
        sa.Column("new_value_json", _jsonb(), nullable=False),
        sa.Column("evidence_block_id", _uuid(), nullable=True),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("quote_text", sa.Text(), nullable=True),
        sa.Column("bbox_json", _jsonb(), nullable=True),
        sa.Column("confirmation_status", sa.String(length=20), nullable=False),
        sa.Column("confirmed_by", _uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(field_code COLLATE \"C\") ~ '^[a-z][a-z0-9_.]{0,79}$'",
            name="field_code_format",
        ),
        sa.CheckConstraint(
            "value_type IN ('string', 'number', 'date', 'json')",
            name="value_type_allowed",
        ),
        sa.CheckConstraint(
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        sa.CheckConstraint("page_no IS NULL OR page_no > 0", name="page_no_positive"),
        sa.CheckConstraint(
            "(evidence_block_id IS NULL AND page_no IS NULL AND quote_text IS NULL "
            "AND bbox_json IS NULL) OR (evidence_block_id IS NOT NULL "
            "AND page_no IS NOT NULL AND quote_text IS NOT NULL AND btrim(quote_text) <> '')",
            name="evidence_matrix",
        ),
        sa.CheckConstraint(
            "bbox_json IS NULL OR jsonb_typeof(bbox_json) = 'object'", name="bbox_object"
        ),
        sa.CheckConstraint(
            "(confirmation_status = 'unconfirmed' AND confirmed_by IS NULL "
            "AND confirmed_at IS NULL) OR (confirmation_status = 'confirmed' "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL "
            "AND evidence_block_id IS NOT NULL) OR (confirmation_status = 'rejected' "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="confirmation_matrix",
        ),
        sa.CheckConstraint(
            "(old_value_json IS NULL OR jsonb_typeof(old_value_json) = 'null' OR "
            "CASE value_type "
            "WHEN 'string' THEN jsonb_typeof(old_value_json) = 'string' "
            "WHEN 'number' THEN jsonb_typeof(old_value_json) = 'string' "
            "AND (old_value_json #>> '{}') ~ '^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$' "
            "WHEN 'date' THEN jsonb_typeof(old_value_json) = 'string' "
            "AND (old_value_json #>> '{}') ~ '^\\d{4}-\\d{2}-\\d{2}$' "
            "WHEN 'json' THEN jsonb_typeof(old_value_json) IN "
            "('object', 'array', 'boolean') ELSE false END) AND "
            "(jsonb_typeof(new_value_json) = 'null' OR CASE value_type "
            "WHEN 'string' THEN jsonb_typeof(new_value_json) = 'string' "
            "WHEN 'number' THEN jsonb_typeof(new_value_json) = 'string' "
            "AND (new_value_json #>> '{}') ~ '^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$' "
            "WHEN 'date' THEN jsonb_typeof(new_value_json) = 'string' "
            "AND (new_value_json #>> '{}') ~ '^\\d{4}-\\d{2}-\\d{2}$' "
            "WHEN 'json' THEN jsonb_typeof(new_value_json) IN "
            "('object', 'array', 'boolean') ELSE false END)",
            name="value_shape",
        ),
        sa.ForeignKeyConstraint(
            ["supplementary_agreement_id"],
            ["supplementary_agreements.id"],
            name="fk_sagr_changes_agreement",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_block_id"],
            ["document_blocks.id"],
            name="fk_sagr_changes_evidence_block",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name="fk_sagr_changes_confirmed_by"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supplementary_agreement_changes"),
        sa.UniqueConstraint(
            "supplementary_agreement_id",
            "field_code",
            name="uq_supplementary_agreement_changes_agreement_field",
        ),
        schema="public",
    )

    op.create_table(
        "user_corrections",
        sa.Column("id", _uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("correction_type", sa.String(length=40), nullable=False),
        sa.Column("object_type", sa.String(length=60), nullable=False),
        sa.Column("object_id", _uuid(), nullable=False),
        sa.Column("field_path", sa.String(length=300), nullable=False),
        sa.Column("before_value_json", _jsonb(), nullable=True),
        sa.Column("after_value_json", _jsonb(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", _uuid(), nullable=False),
        sa.Column("actor_role_code", sa.String(length=40), nullable=False),
        sa.Column("related_execution_id", _uuid(), nullable=True),
        sa.Column("caused_outdated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("trace_id", _uuid(), nullable=False),
        sa.CheckConstraint(
            "correction_type IN ('contract_field', 'supplementary_agreement_changes', "
            "'invoice_field', 'contract_invoice')",
            name="correction_type_allowed",
        ),
        sa.CheckConstraint(
            "(object_type COLLATE \"C\") ~ '^[a-z][a-z0-9_]{0,59}$'",
            name="object_type_format",
        ),
        sa.CheckConstraint(
            "(field_path COLLATE \"C\") ~ '^[a-z][a-z0-9_.]*$'",
            name="field_path_format",
        ),
        sa.CheckConstraint(
            "before_value_json IS NOT NULL OR after_value_json IS NOT NULL",
            name="value_present",
        ),
        sa.CheckConstraint(
            "(before_value_json IS NULL OR jsonb_typeof(before_value_json) = 'object') "
            "AND (after_value_json IS NULL OR jsonb_typeof(after_value_json) = 'object')",
            name="value_objects",
        ),
        sa.CheckConstraint("btrim(reason) <> ''", name="reason_nonempty"),
        sa.CheckConstraint(
            "actor_role_code IN ('system_admin', 'finance_reviewer', 'audit_reviewer', "
            "'contract_admin', 'read_only')",
            name="actor_role_code_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_user_corrections_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_user_corrections_actor_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_corrections"),
        schema="public",
    )
    op.create_index(
        "idx_user_corrections_object_created",
        "user_corrections",
        ["organization_id", "object_type", "object_id", sa.text("created_at DESC")],
        schema="public",
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_financial_fact_details_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                file_business_type text;
                parent_file_id uuid;
                parent_parse_id uuid;
                parent_page_no integer;
                agreement_state text;
                parent_organization_id uuid;
                file_organization_id uuid;
                business_organization_id uuid;
            BEGIN
                IF TG_OP = 'TRUNCATE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='financial detail facts cannot be truncated';
                END IF;
                IF TG_TABLE_NAME IN ('file_primary_business_objects', 'user_corrections')
                   AND TG_OP IN ('UPDATE', 'DELETE') THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='financial detail history is append-only';
                END IF;
                IF TG_TABLE_NAME = 'contract_fields' AND TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='contract fields cannot be deleted';
                END IF;
                IF TG_TABLE_NAME = 'file_primary_business_objects' THEN
                    SELECT intended_business_type, organization_id
                      INTO file_business_type, file_organization_id
                      FROM public.files WHERE id = NEW.file_id FOR KEY SHARE;
                    IF file_business_type IS DISTINCT FROM NEW.business_type THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='file primary business type mismatch';
                    END IF;
                    IF NEW.business_type = 'policy' THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='policy primary binding is not configured';
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
                    END IF;
                    IF business_organization_id IS DISTINCT FROM file_organization_id THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='file primary business object organization mismatch';
                    END IF;
                ELSIF TG_TABLE_NAME = 'contract_fields' THEN
                    IF TG_OP = 'UPDATE' AND (
                        NEW.contract_id IS DISTINCT FROM OLD.contract_id
                        OR NEW.field_code IS DISTINCT FROM OLD.field_code
                        OR NEW.row_version <> OLD.row_version + 1
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='contract field identity or row version is invalid';
                    END IF;
                    IF NEW.evidence_block_id IS NOT NULL THEN
                        SELECT parse_version.file_id, block.parse_version_id, page.page_no,
                               file_record.organization_id, contract.organization_id
                          INTO parent_file_id, parent_parse_id, parent_page_no,
                               file_organization_id, parent_organization_id
                          FROM public.document_blocks AS block
                          JOIN public.document_parse_versions AS parse_version
                            ON parse_version.id = block.parse_version_id
                          JOIN public.document_pages AS page ON page.id = block.page_id
                          JOIN public.files AS file_record ON file_record.id = parse_version.file_id
                          JOIN public.contracts AS contract ON contract.id = NEW.contract_id
                         WHERE block.id = NEW.evidence_block_id;
                        IF parent_file_id IS DISTINCT FROM NEW.evidence_file_id
                           OR parent_parse_id IS DISTINCT FROM NEW.evidence_parse_version_id
                           OR parent_page_no IS DISTINCT FROM NEW.page_no
                           OR file_organization_id IS DISTINCT FROM parent_organization_id THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='contract field evidence chain mismatch';
                        END IF;
                    END IF;
                ELSIF TG_TABLE_NAME = 'supplementary_agreement_changes' THEN
                    SELECT status INTO agreement_state
                      FROM public.supplementary_agreements
                     WHERE id = COALESCE(NEW.supplementary_agreement_id,
                                         OLD.supplementary_agreement_id)
                     FOR KEY SHARE;
                    IF agreement_state IN ('confirmed', 'rejected', 'archived') THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='terminal supplementary agreement changes are immutable';
                    END IF;
                    IF TG_OP <> 'DELETE' AND NEW.evidence_block_id IS NOT NULL THEN
                        SELECT page.page_no, file_record.organization_id,
                               agreement.organization_id
                          INTO parent_page_no, file_organization_id, parent_organization_id
                          FROM public.document_blocks AS block
                          JOIN public.document_pages AS page ON page.id = block.page_id
                          JOIN public.document_parse_versions AS parse_version
                            ON parse_version.id = block.parse_version_id
                          JOIN public.files AS file_record ON file_record.id = parse_version.file_id
                          JOIN public.supplementary_agreements AS agreement
                            ON agreement.id = NEW.supplementary_agreement_id
                         WHERE block.id = NEW.evidence_block_id;
                        IF parent_page_no IS DISTINCT FROM NEW.page_no
                           OR file_organization_id IS DISTINCT FROM parent_organization_id THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='supplementary change evidence page mismatch';
                        END IF;
                    END IF;
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text("REVOKE ALL ON FUNCTION public.enforce_financial_fact_details_v1() FROM PUBLIC")
    )
    for table_name in (
        "file_primary_business_objects",
        "contract_fields",
        "supplementary_agreement_changes",
        "user_corrections",
    ):
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table_name}_state_v1 "
                f"BEFORE INSERT OR UPDATE OR DELETE ON public.{table_name} FOR EACH ROW "
                "EXECUTE FUNCTION public.enforce_financial_fact_details_v1()"
            )
        )
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table_name}_no_truncate_v1 "
                f"BEFORE TRUNCATE ON public.{table_name} FOR EACH STATEMENT "
                "EXECUTE FUNCTION public.enforce_financial_fact_details_v1()"
            )
        )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    table_names = (
        "user_corrections",
        "supplementary_agreement_changes",
        "contract_fields",
        "file_primary_business_objects",
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
            "MESSAGE='refusing to drop non-empty financial fact details'; "
            "END IF; END; $$"
        )
    )
    for table_name in table_names:
        op.execute(sa.text(f"DROP TRIGGER trg_{table_name}_no_truncate_v1 ON public.{table_name}"))
        op.execute(sa.text(f"DROP TRIGGER trg_{table_name}_state_v1 ON public.{table_name}"))
    op.execute(sa.text("DROP FUNCTION public.enforce_financial_fact_details_v1()"))
    for table_name in table_names:
        op.drop_table(table_name, schema="public")
