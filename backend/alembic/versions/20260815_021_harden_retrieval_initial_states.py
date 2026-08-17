"""封锁检索索引、评测集和评测运行的非初始状态直写旁路。

Revision ID: 20260815_021
Revises: 20260814_020
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260815_021"
down_revision: str | None = "20260814_020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INITIAL_STATE_TRIGGERS = (
    (
        "document_index_versions",
        "trg_document_index_versions_initial_state_v1",
    ),
    (
        "retrieval_eval_datasets",
        "trg_retrieval_eval_datasets_initial_state_v1",
    ),
    (
        "retrieval_eval_runs",
        "trg_retrieval_eval_runs_initial_state_v1",
    ),
)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                      FROM public.document_index_versions AS index_version
                     WHERE index_version.status = 'active'
                       AND NOT EXISTS (
                           SELECT 1
                             FROM public.retrieval_eval_runs AS evaluation_run
                            WHERE evaluation_run.index_version_id = index_version.id
                              AND evaluation_run.tier = 'formal_release'
                              AND evaluation_run.status = 'passed'
                       )
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='existing active retrieval index lacks formal evaluation';
                END IF;

                IF EXISTS (
                    SELECT 1
                      FROM public.retrieval_eval_datasets AS dataset
                     WHERE dataset.status IN ('approved', 'superseded')
                       AND (
                           dataset.case_count <> (
                               SELECT count(*)
                                 FROM public.retrieval_eval_cases AS evaluation_case
                                WHERE evaluation_case.dataset_id = dataset.id
                           )
                           OR dataset.case_count < CASE dataset.tier
                               WHEN 'smoke' THEN 5
                               WHEN 'mvp_uat' THEN 50
                               ELSE 100
                           END
                       )
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='existing retrieval evaluation dataset fails case gate';
                END IF;

                IF EXISTS (
                    SELECT 1
                      FROM public.retrieval_eval_runs AS evaluation_run
                     WHERE evaluation_run.status IN ('passed', 'failed')
                       AND (
                           evaluation_run.completed_case_count <> (
                               SELECT count(*)
                                 FROM public.retrieval_eval_results AS evaluation_result
                                WHERE evaluation_result.run_id = evaluation_run.id
                           )
                           OR (
                               evaluation_run.status = 'passed'
                               AND EXISTS (
                                   SELECT 1
                                     FROM public.retrieval_eval_results AS evaluation_result
                                    WHERE evaluation_result.run_id = evaluation_run.id
                                      AND (
                                          NOT evaluation_result.passed
                                          OR evaluation_result.authorization_leak
                                      )
                               )
                           )
                       )
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='existing retrieval evaluation run fails result gate';
                END IF;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_retrieval_initial_state_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                IF TG_TABLE_NAME = 'document_index_versions' AND NEW.status <> 'building' THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='document index must start in building status';
                ELSIF TG_TABLE_NAME = 'retrieval_eval_datasets' AND NEW.status <> 'draft' THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='retrieval evaluation dataset must start in draft status';
                ELSIF TG_TABLE_NAME = 'retrieval_eval_runs' AND NEW.status <> 'running' THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='retrieval evaluation run must start in running status';
                END IF;
                RETURN NEW;
            END;
            $$;
            REVOKE ALL ON FUNCTION public.enforce_retrieval_initial_state_v1() FROM PUBLIC;
            """
        )
    )
    for table_name, trigger_name in _INITIAL_STATE_TRIGGERS:
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {trigger_name}
                BEFORE INSERT ON public.{table_name}
                FOR EACH ROW EXECUTE FUNCTION public.enforce_retrieval_initial_state_v1();
                """
            )
        )


def downgrade() -> None:
    for table_name, trigger_name in reversed(_INITIAL_STATE_TRIGGERS):
        op.execute(sa.text(f"DROP TRIGGER {trigger_name} ON public.{table_name}"))
    op.execute(sa.text("DROP FUNCTION public.enforce_retrieval_initial_state_v1()"))
