"""闭合 quarantine 与 clean originals 双定位。

Revision ID: 20260813_012
Revises: 20260813_011
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_012"
down_revision: str | None = "20260813_011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("original_minio_bucket", sa.String(length=100), nullable=True),
        schema="public",
    )
    op.add_column(
        "files",
        sa.Column("original_minio_object_key", sa.String(length=1000), nullable=True),
        schema="public",
    )
    op.create_check_constraint(
        "ck_files_original_locator_null_matrix",
        "files",
        "(original_minio_bucket IS NULL) = (original_minio_object_key IS NULL)",
        schema="public",
    )
    op.create_index(
        "uq_files_original_minio_object_key",
        "files",
        ["original_minio_object_key"],
        unique=True,
        postgresql_where=sa.text("original_minio_object_key IS NOT NULL"),
        schema="public",
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_file_original_locator_v1()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    IF NEW.original_minio_bucket IS NOT NULL
                       OR NEW.original_minio_object_key IS NOT NULL THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='new file cannot have an originals locator';
                    END IF;
                    RETURN NEW;
                END IF;

                IF OLD.original_minio_bucket IS NOT NULL AND (
                    NEW.original_minio_bucket IS DISTINCT FROM OLD.original_minio_bucket
                    OR NEW.original_minio_object_key IS DISTINCT FROM
                        OLD.original_minio_object_key
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='file originals locator is immutable';
                END IF;
                IF OLD.original_minio_bucket IS NULL AND NEW.original_minio_bucket IS NOT NULL
                   AND NOT (
                       OLD.status = 'validating'
                       AND OLD.security_scan_status = 'pending'
                       AND NEW.status = 'stored'
                       AND NEW.security_scan_status = 'clean'
                       AND btrim(NEW.original_minio_bucket) <> ''
                       AND btrim(NEW.original_minio_object_key) <> ''
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='file originals locator requires the clean transition';
                END IF;
                IF (
                    NEW.status IN ('uploaded','validating','rejected')
                    AND NEW.original_minio_bucket IS NOT NULL
                ) OR (
                    NEW.status IN ('stored','archived')
                    AND NEW.original_minio_bucket IS NULL
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='file status and originals locator are inconsistent';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text("REVOKE ALL ON FUNCTION public.enforce_file_original_locator_v1() FROM PUBLIC")
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_files_original_locator_v1 "
            "BEFORE INSERT OR UPDATE ON public.files FOR EACH ROW "
            "EXECUTE FUNCTION public.enforce_file_original_locator_v1()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.execute(sa.text("LOCK TABLE public.files IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM public.files LIMIT 1) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='refusing to drop file originals locator from non-empty files';
                END IF;
            END;
            $$
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER trg_files_original_locator_v1 ON public.files"))
    op.execute(sa.text("DROP FUNCTION public.enforce_file_original_locator_v1()"))
    op.drop_index("uq_files_original_minio_object_key", table_name="files", schema="public")
    op.drop_constraint(
        "ck_files_original_locator_null_matrix",
        "files",
        type_="check",
        schema="public",
    )
    op.drop_column("files", "original_minio_object_key", schema="public")
    op.drop_column("files", "original_minio_bucket", schema="public")
