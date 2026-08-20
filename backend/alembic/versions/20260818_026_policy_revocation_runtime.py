"""落实 CR-028-R1 制度撤销、检索失效与历史保留合同。

Revision ID: 20260818_026
Revises: 20260818_025
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_026"
down_revision: str | None = "20260818_025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _lock_tables() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout='5s'"))
    op.execute(
        sa.text(
            "LOCK TABLE public.policy_documents, public.policy_approval_records "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )


def _preflight_upgrade() -> None:
    _lock_tables()
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM public.policy_documents
                     WHERE status IN ('revoked','archived') LIMIT 1
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='existing terminal policies require reviewed forward migration';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM public.policy_approval_records
                     WHERE action NOT IN ('submit','approve','publish')
                        OR reason IS NULL OR btrim(reason)='' LIMIT 1
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='existing policy approvals require reviewed forward migration';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM public.policy_documents
                     WHERE row_version<=0
                        OR revoked_at IS NOT NULL OR revoked_by IS NOT NULL
                        OR revoke_reason IS NOT NULL
                        OR (status='draft' AND (
                            submitted_by IS NOT NULL OR submitted_at IS NOT NULL
                            OR business_approved_by IS NOT NULL OR business_approved_at IS NOT NULL
                            OR technical_published_by IS NOT NULL
                            OR technical_published_at IS NOT NULL))
                        OR (status='submitted' AND (
                            submitted_by IS NULL OR submitted_at IS NULL
                            OR business_approved_by IS NOT NULL OR business_approved_at IS NOT NULL
                            OR technical_published_by IS NOT NULL
                            OR technical_published_at IS NOT NULL))
                        OR (status='business_approved' AND (
                            submitted_by IS NULL OR submitted_at IS NULL
                            OR business_approved_by IS NULL OR business_approved_at IS NULL
                            OR technical_published_by IS NOT NULL
                            OR technical_published_at IS NOT NULL))
                        OR (status IN ('published','superseded') AND (
                            submitted_by IS NULL OR submitted_at IS NULL
                            OR business_approved_by IS NULL OR business_approved_at IS NULL
                            OR technical_published_by IS NULL
                            OR technical_published_at IS NULL))
                        OR status NOT IN (
                            'draft','submitted','business_approved','published','superseded'
                        )
                     LIMIT 1
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='existing policy lifecycle requires reviewed forward migration';
                END IF;
            END; $$;
            """
        )
    )


def _add_revocation_contract() -> None:
    op.execute(
        sa.text(
            """
            ALTER TABLE public.policy_approval_records
                ADD COLUMN related_record_id uuid NULL;
            ALTER TABLE public.policy_approval_records
                ADD CONSTRAINT fk_policy_approval_related_record
                FOREIGN KEY (related_record_id)
                REFERENCES public.policy_approval_records(id);
            CREATE UNIQUE INDEX uq_policy_revocation_execution
                ON public.policy_approval_records(related_record_id)
                WHERE related_record_id IS NOT NULL;
            CREATE UNIQUE INDEX uq_policy_revocation_request
                ON public.policy_approval_records(policy_document_id)
                WHERE action='revoke_request';

            ALTER TABLE public.policy_approval_records
                DROP CONSTRAINT ck_policy_approval_records_action_nonempty;
            ALTER TABLE public.policy_approval_records
                ADD CONSTRAINT ck_policy_approval_records_action_matrix CHECK (
                    reason IS NOT NULL AND btrim(reason)<>'' AND (
                        (action='submit' AND from_status='draft'
                         AND to_status='submitted' AND actor_role_code='audit_reviewer'
                         AND related_record_id IS NULL)
                        OR (action='approve' AND from_status='submitted'
                            AND to_status='business_approved'
                            AND actor_role_code='audit_reviewer'
                            AND related_record_id IS NULL)
                        OR (action='publish' AND from_status='business_approved'
                            AND to_status='published' AND actor_role_code='system_admin'
                            AND related_record_id IS NULL)
                        OR (action='revoke_request' AND from_status='published'
                            AND to_status='revoked' AND actor_role_code='audit_reviewer'
                            AND related_record_id IS NULL)
                        OR (action='revoke' AND from_status='published'
                            AND to_status='revoked' AND actor_role_code='system_admin'
                            AND related_record_id IS NOT NULL)
                    )
                );

            ALTER TABLE public.policy_documents
                DROP CONSTRAINT ck_policy_documents_publication_matrix;
            ALTER TABLE public.policy_documents
                ADD CONSTRAINT ck_policy_documents_publication_matrix CHECK (
                    (status IN ('published','superseded','revoked')
                     AND business_approved_by IS NOT NULL
                     AND business_approved_at IS NOT NULL
                     AND technical_published_by IS NOT NULL
                     AND technical_published_at IS NOT NULL)
                    OR status NOT IN ('published','superseded','revoked')
                );
            ALTER TABLE public.policy_documents
                ADD CONSTRAINT ck_policy_documents_revocation_matrix CHECK (
                    (status='revoked' AND revoked_at IS NOT NULL
                     AND revoked_by IS NOT NULL AND btrim(revoke_reason)<>'')
                    OR (status<>'revoked' AND revoked_at IS NULL
                        AND revoked_by IS NULL AND revoke_reason IS NULL)
                );
            """
        )
    )


def _create_policy_lifecycle_guard() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_policy_lifecycle_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,pg_temp
            AS $$
            BEGIN
                IF TG_OP='DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='policy documents cannot be deleted';
                END IF;
                IF NEW.row_version<>OLD.row_version+1
                   OR NEW.updated_by IS NULL OR NEW.updated_at<OLD.updated_at
                   OR ROW(
                        NEW.id,NEW.organization_id,NEW.knowledge_base_id,NEW.source_file_id,
                        NEW.policy_code,NEW.name,NEW.version,NEW.issuing_department,
                        NEW.effective_from,NEW.effective_to,NEW.scope_json,NEW.access_scope,
                        NEW.allowed_role_codes,NEW.superseded_by_policy_id,
                        NEW.created_at,NEW.created_by,NEW.deleted_at,NEW.deleted_by,
                        NEW.delete_reason
                   ) IS DISTINCT FROM ROW(
                        OLD.id,OLD.organization_id,OLD.knowledge_base_id,OLD.source_file_id,
                        OLD.policy_code,OLD.name,OLD.version,OLD.issuing_department,
                        OLD.effective_from,OLD.effective_to,OLD.scope_json,OLD.access_scope,
                        OLD.allowed_role_codes,OLD.superseded_by_policy_id,
                        OLD.created_at,OLD.created_by,OLD.deleted_at,OLD.deleted_by,
                        OLD.delete_reason
                   )
                THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='policy immutable fields or row version changed';
                END IF;

                IF OLD.status='draft' AND NEW.status='submitted' THEN
                    IF NEW.submitted_by IS NULL OR NEW.submitted_at IS NULL
                       OR NEW.updated_by IS DISTINCT FROM NEW.submitted_by
                       OR NEW.updated_at IS DISTINCT FROM NEW.submitted_at
                       OR ROW(NEW.business_approved_by,NEW.business_approved_at,
                              NEW.technical_published_by,NEW.technical_published_at,
                              NEW.revoked_at,NEW.revoked_by,NEW.revoke_reason)
                          IS DISTINCT FROM
                          ROW(OLD.business_approved_by,OLD.business_approved_at,
                              OLD.technical_published_by,OLD.technical_published_at,
                              OLD.revoked_at,OLD.revoked_by,OLD.revoke_reason) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='policy submit transition is invalid';
                    END IF;
                ELSIF OLD.status='submitted' AND NEW.status='business_approved' THEN
                    IF ROW(NEW.submitted_by,NEW.submitted_at)
                          IS DISTINCT FROM ROW(OLD.submitted_by,OLD.submitted_at)
                       OR NEW.business_approved_by IS NULL OR NEW.business_approved_at IS NULL
                       OR NEW.updated_by IS DISTINCT FROM NEW.business_approved_by
                       OR NEW.updated_at IS DISTINCT FROM NEW.business_approved_at
                       OR ROW(NEW.technical_published_by,NEW.technical_published_at,
                              NEW.revoked_at,NEW.revoked_by,NEW.revoke_reason)
                          IS DISTINCT FROM
                          ROW(OLD.technical_published_by,OLD.technical_published_at,
                              OLD.revoked_at,OLD.revoked_by,OLD.revoke_reason) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='policy approval transition is invalid';
                    END IF;
                ELSIF OLD.status='business_approved' AND NEW.status='published' THEN
                    IF ROW(NEW.submitted_by,NEW.submitted_at,NEW.business_approved_by,
                           NEW.business_approved_at)
                          IS DISTINCT FROM
                          ROW(OLD.submitted_by,OLD.submitted_at,OLD.business_approved_by,
                              OLD.business_approved_at)
                       OR NEW.technical_published_by IS NULL
                       OR NEW.technical_published_at IS NULL
                       OR NEW.updated_by IS DISTINCT FROM NEW.technical_published_by
                       OR NEW.updated_at IS DISTINCT FROM NEW.technical_published_at
                       OR ROW(NEW.revoked_at,NEW.revoked_by,NEW.revoke_reason)
                          IS DISTINCT FROM
                          ROW(OLD.revoked_at,OLD.revoked_by,OLD.revoke_reason) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='policy publish transition is invalid';
                    END IF;
                ELSIF OLD.status='published' AND NEW.status='revoked' THEN
                    IF ROW(NEW.submitted_by,NEW.submitted_at,NEW.business_approved_by,
                           NEW.business_approved_at,NEW.technical_published_by,
                           NEW.technical_published_at)
                          IS DISTINCT FROM
                          ROW(OLD.submitted_by,OLD.submitted_at,OLD.business_approved_by,
                              OLD.business_approved_at,OLD.technical_published_by,
                              OLD.technical_published_at)
                       OR NEW.revoked_at IS NULL OR NEW.revoked_by IS NULL
                       OR NEW.revoke_reason IS NULL OR btrim(NEW.revoke_reason)=''
                       OR NEW.updated_by IS DISTINCT FROM NEW.revoked_by
                       OR NEW.updated_at IS DISTINCT FROM NEW.revoked_at THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='policy revoke transition is invalid';
                    END IF;
                ELSE
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='policy state transition is not allowed';
                END IF;
                RETURN NEW;
            END;
            $$;
            REVOKE ALL ON FUNCTION public.enforce_policy_lifecycle_v1() FROM PUBLIC;
            CREATE TRIGGER trg_policy_documents_lifecycle_v1
                BEFORE UPDATE OR DELETE ON public.policy_documents
                FOR EACH ROW EXECUTE FUNCTION public.enforce_policy_lifecycle_v1();
            """
        )
    )


def _create_revocation_evidence_guard() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.validate_policy_revocation_evidence_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,pg_temp
            AS $$
            DECLARE
                target_policy_id uuid;
                policy_status text;
                policy_revoked_at timestamptz;
                policy_revoked_by uuid;
                policy_revoke_reason text;
                request_count integer;
                execution_count integer;
                request_id uuid;
                request_actor uuid;
                execution_actor uuid;
                execution_related_id uuid;
                execution_created_at timestamptz;
                execution_reason text;
            BEGIN
                IF TG_TABLE_NAME='policy_documents' THEN
                    target_policy_id:=CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END;
                ELSE
                    target_policy_id:=CASE WHEN TG_OP='DELETE'
                        THEN OLD.policy_document_id ELSE NEW.policy_document_id END;
                END IF;
                SELECT status,revoked_at,revoked_by,revoke_reason
                  INTO policy_status,policy_revoked_at,policy_revoked_by,policy_revoke_reason
                  FROM public.policy_documents WHERE id=target_policy_id;
                IF policy_status IS NULL THEN
                    RETURN NULL;
                END IF;
                SELECT count(*) INTO request_count
                  FROM public.policy_approval_records
                 WHERE policy_document_id=target_policy_id AND action='revoke_request';
                IF request_count>0 THEN
                    SELECT id,actor_id INTO request_id,request_actor
                      FROM public.policy_approval_records
                     WHERE policy_document_id=target_policy_id AND action='revoke_request';
                END IF;
                SELECT count(*) INTO execution_count
                  FROM public.policy_approval_records
                 WHERE policy_document_id=target_policy_id AND action='revoke';
                IF execution_count>0 THEN
                    SELECT actor_id,related_record_id,created_at,reason
                      INTO execution_actor,execution_related_id,
                           execution_created_at,execution_reason
                      FROM public.policy_approval_records
                     WHERE policy_document_id=target_policy_id AND action='revoke';
                END IF;

                IF request_count>0 AND policy_status NOT IN ('published','revoked') THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='revocation request policy state is invalid';
                END IF;
                IF policy_status='revoked' THEN
                    IF request_count<>1 OR execution_count<>1
                       OR request_actor IS NULL OR execution_actor IS NULL
                       OR request_actor=execution_actor
                       OR execution_related_id IS DISTINCT FROM request_id
                       OR policy_revoked_by IS DISTINCT FROM execution_actor
                       OR policy_revoked_at IS DISTINCT FROM execution_created_at
                       OR policy_revoke_reason IS DISTINCT FROM execution_reason THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='policy revocation evidence is incomplete';
                    END IF;
                ELSIF execution_count<>0 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='revocation execution requires revoked policy';
                END IF;
                RETURN NULL;
            END;
            $$;
            REVOKE ALL ON FUNCTION public.validate_policy_revocation_evidence_v1() FROM PUBLIC;
            CREATE CONSTRAINT TRIGGER trg_policy_revocation_approval_evidence_v1
                AFTER INSERT OR UPDATE OR DELETE ON public.policy_approval_records
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                EXECUTE FUNCTION public.validate_policy_revocation_evidence_v1();
            CREATE CONSTRAINT TRIGGER trg_policy_revocation_document_evidence_v1
                AFTER INSERT OR UPDATE OR DELETE ON public.policy_documents
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                EXECUTE FUNCTION public.validate_policy_revocation_evidence_v1();
            """
        )
    )


def upgrade() -> None:
    _preflight_upgrade()
    _add_revocation_contract()
    _create_policy_lifecycle_guard()
    _create_revocation_evidence_guard()


def downgrade() -> None:
    _lock_tables()
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM public.policy_documents WHERE status='revoked' LIMIT 1
                ) OR EXISTS (
                    SELECT 1 FROM public.policy_approval_records
                     WHERE action IN ('revoke_request','revoke')
                        OR related_record_id IS NOT NULL LIMIT 1
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='policy revocation evidence blocks downgrade';
                END IF;
            END; $$;

            DROP TRIGGER trg_policy_revocation_document_evidence_v1
                ON public.policy_documents;
            DROP TRIGGER trg_policy_revocation_approval_evidence_v1
                ON public.policy_approval_records;
            DROP FUNCTION public.validate_policy_revocation_evidence_v1();
            DROP TRIGGER trg_policy_documents_lifecycle_v1 ON public.policy_documents;
            DROP FUNCTION public.enforce_policy_lifecycle_v1();

            ALTER TABLE public.policy_documents
                DROP CONSTRAINT ck_policy_documents_revocation_matrix;
            ALTER TABLE public.policy_documents
                DROP CONSTRAINT ck_policy_documents_publication_matrix;
            ALTER TABLE public.policy_documents
                ADD CONSTRAINT ck_policy_documents_publication_matrix CHECK (
                    (status IN ('published','superseded')
                     AND business_approved_by IS NOT NULL
                     AND business_approved_at IS NOT NULL
                     AND technical_published_by IS NOT NULL
                     AND technical_published_at IS NOT NULL)
                    OR status NOT IN ('published','superseded')
                );

            ALTER TABLE public.policy_approval_records
                DROP CONSTRAINT ck_policy_approval_records_action_matrix;
            ALTER TABLE public.policy_approval_records
                ADD CONSTRAINT ck_policy_approval_records_action_nonempty
                CHECK (btrim(action)<>'' AND btrim(to_status)<>'');
            DROP INDEX public.uq_policy_revocation_request;
            DROP INDEX public.uq_policy_revocation_execution;
            ALTER TABLE public.policy_approval_records
                DROP CONSTRAINT fk_policy_approval_related_record;
            ALTER TABLE public.policy_approval_records DROP COLUMN related_record_id;
            """
        )
    )


__all__ = ["downgrade", "upgrade"]
