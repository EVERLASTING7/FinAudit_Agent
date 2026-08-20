"""落实 CR-010-R2 Scanner Registry 与 fixed_test 隔离消费者合同。

Revision ID: 20260818_027
Revises: 20260818_026
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_027"
down_revision: str | None = "20260818_026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _lock_tables() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout='5s'"))
    op.execute(
        sa.text(
            "LOCK TABLE public.document_parse_versions, public.document_assets, "
            "public.async_jobs, public.async_job_steps, public.outbox_events "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )


def _preflight() -> None:
    _lock_tables()
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                IF to_regclass('public.scanner_registry_profiles') IS NOT NULL
                   OR to_regprocedure(
                       'public.validate_scanner_registry_profile_current_v1(text,text,text)'
                   ) IS NOT NULL
                   OR EXISTS (
                       SELECT 1 FROM public.document_parse_versions
                        WHERE source_type='security_revalidation' LIMIT 1
                   )
                   OR EXISTS (
                       SELECT 1 FROM public.async_jobs
                        WHERE job_type='asset_security_revalidation' LIMIT 1
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='scanner registry objects require reviewed forward migration';
                END IF;
            END; $$;
            """
        )
    )


def _create_registry_table() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE public.scanner_registry_profiles (
                profile_class varchar(20) COLLATE "C" NOT NULL,
                registry_version varchar(100) COLLATE "C" NOT NULL,
                scanner_registry_hash char(64) COLLATE "C" NOT NULL,
                profile_jcs_bytes bytea NOT NULL,
                approval_artifact_sha256 char(64) COLLATE "C" NOT NULL,
                installed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
                activated_at timestamptz NULL,
                retired_at timestamptz NULL,
                CONSTRAINT pk_scanner_registry_profiles PRIMARY KEY
                    (profile_class,registry_version,scanner_registry_hash),
                CONSTRAINT uq_scanner_registry_profiles_version UNIQUE (registry_version),
                CONSTRAINT uq_scanner_registry_profiles_hash UNIQUE (scanner_registry_hash),
                CONSTRAINT ck_scanner_registry_profiles_class CHECK (
                    profile_class IN
                    ('contract','local_offline','fixed_test','staging','production')
                ),
                CONSTRAINT ck_scanner_registry_profiles_version CHECK (
                    registry_version ~ '^[a-z0-9][a-z0-9._-]{0,99}$'
                    AND registry_version NOT IN ('current','latest','default','unknown')
                ),
                CONSTRAINT ck_scanner_registry_profiles_hashes CHECK (
                    scanner_registry_hash ~ '^[0-9a-f]{64}$'
                    AND approval_artifact_sha256 ~ '^[0-9a-f]{64}$'
                ),
                CONSTRAINT ck_scanner_registry_profiles_bytes CHECK (
                    octet_length(profile_jcs_bytes)>0
                ),
                CONSTRAINT ck_scanner_registry_profiles_lifecycle CHECK (
                    ((activated_at IS NULL AND retired_at IS NULL)
                     OR (activated_at IS NOT NULL AND retired_at IS NULL)
                     OR (activated_at IS NOT NULL AND retired_at IS NOT NULL
                         AND retired_at>=activated_at))
                    AND (activated_at IS NULL OR activated_at>=installed_at)
                )
            );
            CREATE UNIQUE INDEX uq_scanner_registry_profiles_current
                ON public.scanner_registry_profiles((true))
                WHERE activated_at IS NOT NULL AND retired_at IS NULL;
            """
        )
    )


def _create_registry_state_guard() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_scanner_registry_profiles_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,public,pg_temp
            AS $$
            DECLARE
                payload jsonb;
                entry jsonb;
            BEGIN
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended('scanner_registry_profile_activation_v1',0)
                );
                IF TG_OP='INSERT' THEN
                    IF EXISTS (
                        SELECT 1 FROM public.scanner_registry_profiles
                         WHERE profile_class<>NEW.profile_class
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='SCANNER_REGISTRY_CLASS_CONFLICT';
                    END IF;
                    IF NEW.installed_at IS DISTINCT FROM transaction_timestamp()
                       OR NEW.activated_at IS NOT NULL OR NEW.retired_at IS NOT NULL THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='scanner registry insert lifecycle is invalid';
                    END IF;
                    IF encode(digest(NEW.profile_jcs_bytes,'sha256'),'hex')
                       IS DISTINCT FROM NEW.scanner_registry_hash THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='scanner registry profile hash is invalid';
                    END IF;
                    BEGIN
                        payload:=convert_from(NEW.profile_jcs_bytes,'UTF8')::jsonb;
                    EXCEPTION WHEN OTHERS THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='scanner registry profile bytes are invalid';
                    END;
                    IF jsonb_typeof(payload)<>'object'
                       OR (SELECT count(*) FROM jsonb_object_keys(payload))<>4
                       OR payload->>'schema_version'<>'scanner-registry-profile-v1'
                       OR payload->>'profile_class' IS DISTINCT FROM NEW.profile_class
                       OR payload->>'registry_version' IS DISTINCT FROM NEW.registry_version
                       OR jsonb_typeof(payload->'entries')<>'array' THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='scanner registry profile identity is invalid';
                    END IF;
                    FOR entry IN SELECT value FROM jsonb_array_elements(payload->'entries') LOOP
                        IF jsonb_typeof(entry)<>'object'
                           OR (SELECT count(*) FROM jsonb_object_keys(entry))<>5
                           OR entry->>'adapter_code' !~ '^[a-z][a-z0-9_.-]{0,63}$'
                           OR entry->>'scanner_version' IS NULL
                           OR btrim(entry->>'scanner_version')=''
                           OR entry->>'definition_version_mode'
                              NOT IN ('required_exact','null_only')
                           OR jsonb_typeof(entry->'allowed_definition_versions')<>'array'
                           OR jsonb_typeof(entry->'allowed_scan_outcomes')<>'array'
                           OR jsonb_array_length(entry->'allowed_scan_outcomes')=0
                           OR (
                               entry->>'definition_version_mode'='required_exact'
                               AND jsonb_array_length(
                                   entry->'allowed_definition_versions'
                               )=0
                           )
                           OR (
                               entry->>'definition_version_mode'='null_only'
                               AND jsonb_array_length(
                                   entry->'allowed_definition_versions'
                               )<>0
                           ) THEN
                            RAISE EXCEPTION USING ERRCODE='23514',
                                MESSAGE='scanner registry entry is invalid';
                        END IF;
                    END LOOP;
                    RETURN NEW;
                END IF;
                IF ROW(NEW.profile_class,NEW.registry_version,NEW.scanner_registry_hash,
                       NEW.profile_jcs_bytes,NEW.approval_artifact_sha256,NEW.installed_at)
                   IS DISTINCT FROM
                   ROW(OLD.profile_class,OLD.registry_version,OLD.scanner_registry_hash,
                       OLD.profile_jcs_bytes,OLD.approval_artifact_sha256,OLD.installed_at)
                   OR NOT (
                       (OLD.activated_at IS NULL AND OLD.retired_at IS NULL
                        AND NEW.activated_at IS NOT NULL
                        AND NEW.retired_at IS NULL
                        AND NEW.activated_at=transaction_timestamp())
                       OR (OLD.activated_at IS NOT NULL AND OLD.retired_at IS NULL
                           AND NEW.activated_at IS NOT DISTINCT FROM OLD.activated_at
                           AND NEW.retired_at=transaction_timestamp())
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='scanner registry lifecycle transition is invalid';
                END IF;
                RETURN NEW;
            END;
            $$;
            REVOKE ALL ON FUNCTION public.enforce_scanner_registry_profiles_v1() FROM PUBLIC;

            CREATE FUNCTION public.reject_scanner_registry_profiles_delete_truncate_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,public,pg_temp
            AS $$ BEGIN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE='scanner registry evidence is append-only';
            END; $$;
            REVOKE ALL ON FUNCTION
                public.reject_scanner_registry_profiles_delete_truncate_v1() FROM PUBLIC;

            CREATE TRIGGER trg_scanner_registry_profiles_state_v1
                BEFORE INSERT OR UPDATE ON public.scanner_registry_profiles
                FOR EACH ROW EXECUTE FUNCTION public.enforce_scanner_registry_profiles_v1();
            CREATE TRIGGER trg_scanner_registry_profiles_delete_v1
                BEFORE DELETE ON public.scanner_registry_profiles
                FOR EACH ROW EXECUTE FUNCTION
                    public.reject_scanner_registry_profiles_delete_truncate_v1();
            CREATE TRIGGER trg_scanner_registry_profiles_truncate_v1
                BEFORE TRUNCATE ON public.scanner_registry_profiles
                FOR EACH STATEMENT EXECUTE FUNCTION
                    public.reject_scanner_registry_profiles_delete_truncate_v1();
            """
        )
    )


def _create_registry_validators() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.validate_scanner_registry_profile_current_v1(
                requested_class text,requested_version text,requested_hash text
            ) RETURNS boolean
            LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE
            SET search_path=pg_catalog,public,pg_temp
            AS $$ DECLARE matched integer; BEGIN
                IF requested_class IS NULL OR requested_version IS NULL
                   OR requested_hash IS NULL THEN RETURN false; END IF;
                SELECT 1 INTO matched FROM public.scanner_registry_profiles
                 WHERE profile_class=requested_class
                   AND registry_version=requested_version
                   AND scanner_registry_hash=requested_hash
                   AND activated_at IS NOT NULL AND retired_at IS NULL
                 FOR SHARE;
                RETURN matched=1;
            END; $$;

            CREATE FUNCTION public.validate_scanner_registry_profile_history_v1(
                requested_class text,requested_version text,requested_hash text
            ) RETURNS boolean
            LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
            SET search_path=pg_catalog,public,pg_temp
            AS $$
                SELECT requested_class IS NOT NULL
                   AND requested_version IS NOT NULL AND requested_hash IS NOT NULL
                   AND EXISTS (
                       SELECT 1 FROM public.scanner_registry_profiles
                        WHERE profile_class=requested_class
                          AND registry_version=requested_version
                          AND scanner_registry_hash=requested_hash
                          AND activated_at IS NOT NULL
                   )
            $$;

            CREATE FUNCTION public.validate_scanner_registry_current_v1(
                requested_class text,requested_version text,requested_hash text,
                requested_adapter text,requested_scanner text,
                requested_definition text,requested_outcome text
            ) RETURNS boolean
            LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE
            SET search_path=pg_catalog,public,pg_temp
            AS $$ DECLARE payload jsonb; entry jsonb; BEGIN
                IF NOT public.validate_scanner_registry_profile_current_v1(
                    requested_class,requested_version,requested_hash
                ) THEN RETURN false; END IF;
                SELECT convert_from(profile_jcs_bytes,'UTF8')::jsonb INTO payload
                  FROM public.scanner_registry_profiles
                 WHERE profile_class=requested_class
                   AND registry_version=requested_version
                   AND scanner_registry_hash=requested_hash;
                FOR entry IN SELECT value FROM jsonb_array_elements(payload->'entries') LOOP
                    IF entry->>'adapter_code'=requested_adapter
                       AND entry->>'scanner_version'=requested_scanner
                       AND entry->'allowed_scan_outcomes' ? requested_outcome
                       AND (
                           (entry->>'definition_version_mode'='null_only'
                            AND requested_definition IS NULL)
                           OR (entry->>'definition_version_mode'='required_exact'
                               AND requested_definition IS NOT NULL
                               AND entry->'allowed_definition_versions'
                                   ? requested_definition)
                       ) THEN RETURN true; END IF;
                END LOOP;
                RETURN false;
            END; $$;

            CREATE FUNCTION public.validate_scanner_registry_history_v1(
                requested_class text,requested_version text,requested_hash text,
                requested_adapter text,requested_scanner text,
                requested_definition text,requested_outcome text
            ) RETURNS boolean
            LANGUAGE plpgsql STABLE SECURITY DEFINER PARALLEL SAFE
            SET search_path=pg_catalog,public,pg_temp
            AS $$ DECLARE payload jsonb; entry jsonb; BEGIN
                IF NOT public.validate_scanner_registry_profile_history_v1(
                    requested_class,requested_version,requested_hash
                ) THEN RETURN false; END IF;
                SELECT convert_from(profile_jcs_bytes,'UTF8')::jsonb INTO payload
                  FROM public.scanner_registry_profiles
                 WHERE profile_class=requested_class
                   AND registry_version=requested_version
                   AND scanner_registry_hash=requested_hash;
                FOR entry IN SELECT value FROM jsonb_array_elements(payload->'entries') LOOP
                    IF entry->>'adapter_code'=requested_adapter
                       AND entry->>'scanner_version'=requested_scanner
                       AND entry->'allowed_scan_outcomes' ? requested_outcome
                       AND (
                           (entry->>'definition_version_mode'='null_only'
                            AND requested_definition IS NULL)
                           OR (entry->>'definition_version_mode'='required_exact'
                               AND requested_definition IS NOT NULL
                               AND entry->'allowed_definition_versions'
                                   ? requested_definition)
                       ) THEN RETURN true; END IF;
                END LOOP;
                RETURN false;
            END; $$;

            CREATE FUNCTION public.validate_scanner_registry_v1(
                requested_class text,requested_version text,requested_hash text,
                requested_adapter text,requested_scanner text,
                requested_definition text,requested_outcome text
            ) RETURNS boolean
            LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
            SET search_path=pg_catalog,public,pg_temp
            AS $$ SELECT public.validate_scanner_registry_history_v1(
                requested_class,requested_version,requested_hash,requested_adapter,
                requested_scanner,requested_definition,requested_outcome
            ) $$;

            CREATE FUNCTION public.validate_asset_security_revalidation_target_current_v1(
                requested_class text,requested_version text,requested_hash text,
                requested_adapter text,requested_scanner text,requested_definition text
            ) RETURNS boolean
            LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE
            SET search_path=pg_catalog,public,pg_temp
            AS $$ DECLARE payload jsonb; entry jsonb; matched integer:=0; BEGIN
                IF requested_definition IS NULL
                   OR requested_class NOT IN ('fixed_test','production')
                   OR NOT public.validate_scanner_registry_profile_current_v1(
                       requested_class,requested_version,requested_hash
                   ) THEN RETURN false; END IF;
                SELECT convert_from(profile_jcs_bytes,'UTF8')::jsonb INTO payload
                  FROM public.scanner_registry_profiles
                 WHERE profile_class=requested_class
                   AND registry_version=requested_version
                   AND scanner_registry_hash=requested_hash;
                FOR entry IN SELECT value FROM jsonb_array_elements(payload->'entries') LOOP
                    IF entry->>'definition_version_mode'='required_exact'
                       AND jsonb_array_length(entry->'allowed_definition_versions')=1
                       AND entry->'allowed_scan_outcomes' ? 'clean'
                       AND entry->'allowed_scan_outcomes' ? 'infected'
                       AND entry->'allowed_scan_outcomes' ? 'scan_failed' THEN
                        matched:=matched+1;
                        IF entry->>'adapter_code'<>requested_adapter
                           OR entry->>'scanner_version'<>requested_scanner
                           OR entry->'allowed_definition_versions'->>0
                              <>requested_definition THEN RETURN false; END IF;
                    END IF;
                END LOOP;
                RETURN matched=1;
            END; $$;

            CREATE FUNCTION public.activate_scanner_registry_profile_v1(
                target_class text,target_version text,target_hash text,
                expected_current_hash text
            ) RETURNS void
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,public,pg_temp
            AS $$ DECLARE current_row public.scanner_registry_profiles%ROWTYPE;
                         target_row public.scanner_registry_profiles%ROWTYPE;
            BEGIN
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended('scanner_registry_profile_activation_v1',0)
                );
                SELECT * INTO current_row FROM public.scanner_registry_profiles
                 WHERE activated_at IS NOT NULL AND retired_at IS NULL FOR UPDATE;
                SELECT * INTO target_row FROM public.scanner_registry_profiles
                 WHERE profile_class=target_class AND registry_version=target_version
                   AND scanner_registry_hash=target_hash FOR UPDATE;
                IF target_row.registry_version IS NULL OR target_row.activated_at IS NOT NULL
                   OR target_row.retired_at IS NOT NULL THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='SCANNER_REGISTRY_CURRENT_CONFLICT';
                END IF;
                IF current_row.registry_version IS NULL THEN
                    IF expected_current_hash IS NOT NULL OR EXISTS (
                        SELECT 1 FROM public.scanner_registry_profiles
                         WHERE activated_at IS NOT NULL
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='SCANNER_REGISTRY_CURRENT_CONFLICT';
                    END IF;
                ELSIF expected_current_hash IS DISTINCT FROM
                      current_row.scanner_registry_hash THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='SCANNER_REGISTRY_CURRENT_CONFLICT';
                ELSE
                    UPDATE public.scanner_registry_profiles
                       SET retired_at=transaction_timestamp()
                     WHERE profile_class=current_row.profile_class
                       AND registry_version=current_row.registry_version
                       AND scanner_registry_hash=current_row.scanner_registry_hash;
                END IF;
                UPDATE public.scanner_registry_profiles
                   SET activated_at=transaction_timestamp()
                 WHERE profile_class=target_class AND registry_version=target_version
                   AND scanner_registry_hash=target_hash;
            END; $$;

            REVOKE ALL ON FUNCTION
                public.validate_scanner_registry_profile_current_v1(text,text,text),
                public.validate_scanner_registry_profile_history_v1(text,text,text),
                public.validate_scanner_registry_current_v1(
                    text,text,text,text,text,text,text
                ),
                public.validate_scanner_registry_history_v1(
                    text,text,text,text,text,text,text
                ),
                public.validate_scanner_registry_v1(text,text,text,text,text,text,text),
                public.validate_asset_security_revalidation_target_current_v1(
                    text,text,text,text,text,text
                ),
                public.activate_scanner_registry_profile_v1(text,text,text,text)
                FROM PUBLIC;
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='finaudit_app_rw') THEN
                    EXECUTE 'GRANT EXECUTE ON FUNCTION '
                        'public.validate_scanner_registry_profile_current_v1(text,text,text),'
                        'public.validate_scanner_registry_profile_history_v1(text,text,text),'
                        'public.validate_scanner_registry_current_v1('
                            'text,text,text,text,text,text,text),'
                        'public.validate_scanner_registry_history_v1('
                            'text,text,text,text,text,text,text),'
                        'public.validate_scanner_registry_v1('
                            'text,text,text,text,text,text,text),'
                        'public.validate_asset_security_revalidation_target_current_v1('
                            'text,text,text,text,text,text) TO finaudit_app_rw';
                END IF;
            END; $$;
            """
        )
    )


def _create_asset_consumer_guards() -> None:
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_parse_security_revalidation_in_progress
                ON public.document_parse_versions(file_id,parent_version_id)
                WHERE source_type='security_revalidation'
                  AND status IN ('queued','running');

            CREATE FUNCTION public.validate_document_asset_scanner_evidence_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,public,pg_temp
            AS $$ BEGIN
                IF NEW.security_status='pending' THEN
                    IF ROW(NEW.security_scanner_profile_class,
                           NEW.security_scanner_registry_version,
                           NEW.security_scanner_registry_hash,
                           NEW.security_scanner_adapter_code,
                           NEW.security_scanner_version,
                           NEW.security_scanner_definition_version,
                           NEW.security_scanner_invoked)
                       IS DISTINCT FROM ROW(NULL,NULL,NULL,NULL,NULL,NULL,NULL) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='pending asset scanner evidence is invalid';
                    END IF;
                ELSIF NEW.security_status IN ('clean','infected')
                   OR (NEW.security_status='scan_failed'
                       AND NEW.security_error_code IN
                           ('SCANNER_TIMEOUT','SCANNER_UNAVAILABLE')) THEN
                    IF NEW.security_scanner_profile_class NOT IN ('fixed_test','production')
                       OR NEW.security_scanner_invoked IS NOT TRUE
                       OR NOT public.validate_scanner_registry_v1(
                           NEW.security_scanner_profile_class,
                           NEW.security_scanner_registry_version,
                           NEW.security_scanner_registry_hash,
                           NEW.security_scanner_adapter_code,
                           NEW.security_scanner_version,
                           NEW.security_scanner_definition_version,
                           NEW.security_status
                       ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='asset scanner evidence is not approved';
                    END IF;
                ELSIF NEW.security_status='not_configured' THEN
                    IF NEW.security_scanner_profile_class
                          NOT IN ('local_offline','fixed_test')
                       OR NEW.security_scanner_invoked IS NOT FALSE
                       OR ROW(NEW.security_scanner_adapter_code,
                              NEW.security_scanner_version,
                              NEW.security_scanner_definition_version)
                          IS DISTINCT FROM ROW(NULL,NULL,NULL)
                       OR NOT public.validate_scanner_registry_profile_history_v1(
                           NEW.security_scanner_profile_class,
                           NEW.security_scanner_registry_version,
                           NEW.security_scanner_registry_hash
                       ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='asset not-configured evidence is invalid';
                    END IF;
                ELSE
                    IF ROW(NEW.security_scanner_profile_class,
                           NEW.security_scanner_registry_version,
                           NEW.security_scanner_registry_hash,
                           NEW.security_scanner_adapter_code,
                           NEW.security_scanner_version,
                           NEW.security_scanner_definition_version)
                       IS DISTINCT FROM ROW(NULL,NULL,NULL,NULL,NULL,NULL)
                       OR NEW.security_scanner_invoked IS NOT FALSE THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='pre-scanner asset evidence is invalid';
                    END IF;
                END IF;
                RETURN NULL;
            END; $$;
            REVOKE ALL ON FUNCTION
                public.validate_document_asset_scanner_evidence_v1() FROM PUBLIC;
            CREATE CONSTRAINT TRIGGER trg_document_asset_scanner_evidence_v1
                AFTER INSERT OR UPDATE ON public.document_assets
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                EXECUTE FUNCTION public.validate_document_asset_scanner_evidence_v1();

            CREATE FUNCTION public.validate_asset_revalidation_runtime_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,public,pg_temp
            AS $$
            DECLARE
                target_parse_id uuid;
                parse_status text;
                source_parse_id uuid;
                job_status text;
                job_count integer;
                job_id uuid;
                job_input jsonb;
                source_asset_count integer;
                result_asset_count integer;
                result_clean_count integer;
                dispatch_count integer;
            BEGIN
                IF TG_TABLE_NAME='async_jobs' THEN
                    IF NEW.job_type<>'asset_security_revalidation' THEN RETURN NULL; END IF;
                    target_parse_id:=NEW.resource_id;
                ELSE
                    IF NEW.source_type<>'security_revalidation' THEN RETURN NULL; END IF;
                    target_parse_id:=NEW.id;
                END IF;
                SELECT status,parent_version_id INTO parse_status,source_parse_id
                  FROM public.document_parse_versions WHERE id=target_parse_id;
                SELECT count(*) INTO job_count FROM public.async_jobs
                 WHERE job_type='asset_security_revalidation'
                   AND resource_type='document_parse_version'
                   AND resource_id=target_parse_id AND max_attempts=1;
                IF job_count=1 THEN
                    SELECT id,status,input_json INTO job_id,job_status,job_input
                      FROM public.async_jobs
                     WHERE job_type='asset_security_revalidation'
                       AND resource_type='document_parse_version'
                       AND resource_id=target_parse_id AND max_attempts=1;
                END IF;
                IF parse_status IS NULL OR source_parse_id IS NULL OR job_count<>1
                   OR (SELECT count(*) FROM jsonb_object_keys(job_input))<>14
                   OR job_input->>'result_parse_version_id'<>target_parse_id::text
                   OR job_input->>'source_parse_version_id'<>source_parse_id::text
                   OR job_input->>'handler_code_version'
                      <>'asset-security-revalidation-v1'
                   OR NOT public.validate_scanner_registry_history_v1(
                       job_input->>'scanner_profile_class',
                       job_input->>'scanner_registry_version',
                       job_input->>'scanner_registry_hash',
                       job_input->>'scanner_adapter_code',
                       job_input->>'scanner_version',
                       job_input->>'scanner_definition_version','clean'
                   )
                   OR NOT (
                       (parse_status='queued' AND job_status='queued')
                       OR (parse_status='running' AND job_status='running')
                       OR (parse_status IN ('succeeded','manual_review_required','active',
                                           'superseded') AND job_status='succeeded')
                       OR (parse_status='failed' AND job_status='failed')
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='asset revalidation job and parse are inconsistent';
                END IF;
                SELECT count(*) INTO dispatch_count FROM public.outbox_events
                 WHERE aggregate_type='async_job' AND aggregate_id=job_id
                   AND event_type='job.dispatch.requested' AND event_version=1
                   AND event_sequence=1
                   AND payload_json=jsonb_build_object('job_id',job_id::text);
                IF dispatch_count<>1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='asset revalidation dispatch is inconsistent';
                END IF;
                IF parse_status IN ('succeeded','manual_review_required','active','superseded')
                THEN
                    SELECT count(*) INTO source_asset_count FROM public.document_assets
                     WHERE parse_version_id=source_parse_id;
                    SELECT count(*),count(*) FILTER (WHERE security_status='clean')
                      INTO result_asset_count,result_clean_count
                      FROM public.document_assets WHERE parse_version_id=target_parse_id;
                    IF source_asset_count=0 OR result_asset_count<>source_asset_count
                       OR EXISTS (
                           SELECT 1 FROM public.document_assets
                            WHERE parse_version_id=target_parse_id
                              AND source_asset_id IS NULL
                       ) OR (
                           parse_status IN ('succeeded','active','superseded')
                           AND result_clean_count<>result_asset_count
                       ) OR (
                           parse_status='manual_review_required'
                           AND result_clean_count=result_asset_count
                       ) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='asset revalidation snapshot is incomplete';
                    END IF;
                END IF;
                RETURN NULL;
            END; $$;
            REVOKE ALL ON FUNCTION public.validate_asset_revalidation_runtime_v1() FROM PUBLIC;
            CREATE CONSTRAINT TRIGGER trg_asset_revalidation_parse_runtime_v1
                AFTER INSERT OR UPDATE ON public.document_parse_versions
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                WHEN (NEW.source_type='security_revalidation')
                EXECUTE FUNCTION public.validate_asset_revalidation_runtime_v1();
            CREATE CONSTRAINT TRIGGER trg_asset_revalidation_job_runtime_v1
                AFTER INSERT OR UPDATE ON public.async_jobs
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                WHEN (NEW.job_type='asset_security_revalidation')
                EXECUTE FUNCTION public.validate_asset_revalidation_runtime_v1();
            """
        )
    )


def upgrade() -> None:
    _preflight()
    _create_registry_table()
    _create_registry_state_guard()
    _create_registry_validators()
    _create_asset_consumer_guards()


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout='5s'"))
    op.execute(sa.text("LOCK TABLE public.scanner_registry_profiles IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM public.scanner_registry_profiles LIMIT 1)
                   OR EXISTS (
                       SELECT 1 FROM public.document_parse_versions
                        WHERE source_type='security_revalidation' LIMIT 1
                   ) OR EXISTS (
                       SELECT 1 FROM public.async_jobs
                        WHERE job_type='asset_security_revalidation' LIMIT 1
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='scanner registry or asset evidence blocks downgrade';
                END IF;
            END; $$;
            DROP TRIGGER trg_asset_revalidation_job_runtime_v1 ON public.async_jobs;
            DROP TRIGGER trg_asset_revalidation_parse_runtime_v1
                ON public.document_parse_versions;
            DROP FUNCTION public.validate_asset_revalidation_runtime_v1();
            DROP TRIGGER trg_document_asset_scanner_evidence_v1 ON public.document_assets;
            DROP FUNCTION public.validate_document_asset_scanner_evidence_v1();
            DROP INDEX public.uq_parse_security_revalidation_in_progress;

            DROP FUNCTION public.validate_asset_security_revalidation_target_current_v1(
                text,text,text,text,text,text
            );
            DROP FUNCTION public.validate_scanner_registry_v1(
                text,text,text,text,text,text,text
            );
            DROP FUNCTION public.validate_scanner_registry_history_v1(
                text,text,text,text,text,text,text
            );
            DROP FUNCTION public.validate_scanner_registry_current_v1(
                text,text,text,text,text,text,text
            );
            DROP FUNCTION public.validate_scanner_registry_profile_history_v1(text,text,text);
            DROP FUNCTION public.validate_scanner_registry_profile_current_v1(text,text,text);
            DROP FUNCTION public.activate_scanner_registry_profile_v1(text,text,text,text);
            DROP TRIGGER trg_scanner_registry_profiles_truncate_v1
                ON public.scanner_registry_profiles;
            DROP TRIGGER trg_scanner_registry_profiles_delete_v1
                ON public.scanner_registry_profiles;
            DROP TRIGGER trg_scanner_registry_profiles_state_v1
                ON public.scanner_registry_profiles;
            DROP FUNCTION public.reject_scanner_registry_profiles_delete_truncate_v1();
            DROP FUNCTION public.enforce_scanner_registry_profiles_v1();
            DROP TABLE public.scanner_registry_profiles;
            """
        )
    )


__all__ = ["downgrade", "upgrade"]
