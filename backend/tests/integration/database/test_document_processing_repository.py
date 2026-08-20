from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.db.migration import create_migration_engine
from app.db.session import create_session_factory
from app.models.document_processing import DocumentBlock, DocumentPage, DocumentParseVersion
from app.repositories.document_processing import (
    DocumentProcessingRepository,
    ParseBlockWrite,
    ParsePageWrite,
    ParseVersionWrite,
)
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
)

pytestmark = pytest.mark.integration


def _seed_stored_file(engine: Engine) -> tuple[UUID, UUID]:
    organization_id = uuid4()
    user_id = uuid4()
    file_id = uuid4()
    identity = uuid4().hex[:20]
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organizations "
                "(id, name, unified_social_credit_code, tax_number, status) "
                "VALUES (:id, :name, :tax, :tax, 'active')"
            ),
            {"id": organization_id, "name": f"parse-{identity}", "tax": f"PARSE-{identity}"},
        )
        connection.execute(
            text(
                "INSERT INTO users (id, organization_id, username, display_name, "
                "password_hash, status, password_changed_at) VALUES "
                "(:id, :organization_id, :username, 'Parse User', 'synthetic', 'active', now())"
            ),
            {
                "id": user_id,
                "organization_id": organization_id,
                "username": f"parse-{identity}",
            },
        )
        object_key = f"{organization_id}/{file_id}"
        connection.execute(
            text(
                "INSERT INTO files (id, organization_id, original_name, extension, "
                "mime_type, detected_mime_type, size_bytes, sha256, minio_bucket, "
                "minio_object_key, status, intended_business_type, auto_process_requested, "
                "security_scan_status, uploaded_by, created_by) VALUES "
                "(:id, :organization_id, 'contract.pdf', '.pdf', 'application/pdf', "
                "'application/pdf', 10, :sha, 'quarantine', :key, 'uploaded', 'contract', "
                "true, 'pending', :user_id, :user_id)"
            ),
            {
                "id": file_id,
                "organization_id": organization_id,
                "sha": "a" * 64,
                "key": object_key,
                "user_id": user_id,
            },
        )
        connection.execute(
            text(
                "UPDATE files SET status='validating', row_version=row_version+1, "
                "updated_at=clock_timestamp() WHERE id=:id"
            ),
            {"id": file_id},
        )
        connection.execute(
            text(
                "UPDATE files SET status='stored', security_scan_status='clean', "
                "original_minio_bucket='originals', original_minio_object_key=:key, "
                "stored_at=clock_timestamp(), row_version=row_version+1, "
                "updated_at=clock_timestamp() WHERE id=:id"
            ),
            {"id": file_id, "key": object_key},
        )
    return organization_id, file_id


def _clear_subjects(engine: Engine, organization_id: UUID, file_id: UUID) -> None:
    document_tables = (
        "document_content_exclusions",
        "document_blocks",
        "document_assets",
        "document_pages",
        "document_parse_versions",
    )
    with engine.begin() as connection:
        for table in (*document_tables, "files"):
            connection.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
        try:
            connection.execute(
                text(
                    "DELETE FROM document_content_exclusions WHERE parse_version_id IN "
                    "(SELECT id FROM document_parse_versions WHERE file_id=:file_id)"
                ),
                {"file_id": file_id},
            )
            connection.execute(
                text(
                    "DELETE FROM document_blocks WHERE parse_version_id IN "
                    "(SELECT id FROM document_parse_versions WHERE file_id=:file_id)"
                ),
                {"file_id": file_id},
            )
            connection.execute(
                text(
                    "DELETE FROM document_assets WHERE parse_version_id IN "
                    "(SELECT id FROM document_parse_versions WHERE file_id=:file_id)"
                ),
                {"file_id": file_id},
            )
            connection.execute(
                text(
                    "DELETE FROM document_pages WHERE parse_version_id IN "
                    "(SELECT id FROM document_parse_versions WHERE file_id=:file_id)"
                ),
                {"file_id": file_id},
            )
            connection.execute(
                text("DELETE FROM document_parse_versions WHERE file_id=:file_id"),
                {"file_id": file_id},
            )
            connection.execute(text("DELETE FROM files WHERE id=:id"), {"id": file_id})
            connection.execute(
                text("DELETE FROM users WHERE organization_id=:id"),
                {"id": organization_id},
            )
            connection.execute(
                text("DELETE FROM organizations WHERE id=:id"),
                {"id": organization_id},
            )
        finally:
            for table in reversed((*document_tables, "files")):
                connection.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))


def _setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Engine, sessionmaker[Session], UUID, UUID]:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    engine = create_migration_engine(database_url)
    organization_id, file_id = _seed_stored_file(engine)
    return engine, create_session_factory(engine), organization_id, file_id


def test_repository_publishes_complete_parse_then_database_blocks_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, organization_id, file_id = _setup(monkeypatch)
    try:
        with factory.begin() as session:
            parse_id = DocumentProcessingRepository(session).append_result(
                organization_id=organization_id,
                file_id=file_id,
                trace_id=uuid4(),
                result=ParseVersionWrite(
                    source_type="parser",
                    parser_name="synthetic-parser",
                    parser_version="1",
                    ocr_name=None,
                    ocr_version=None,
                    average_confidence=None,
                    pages=(
                        ParsePageWrite(
                            page_no=1,
                            width=Decimal("100"),
                            height=Decimal("200"),
                            unit="point",
                            text="Contract body",
                            confidence=None,
                            blocks=(
                                ParseBlockWrite(
                                    block_index=0,
                                    block_type="paragraph",
                                    text="Contract body",
                                    bbox=None,
                                    confidence=None,
                                ),
                            ),
                        ),
                    ),
                ),
            )

        with factory() as session:
            version = session.get(DocumentParseVersion, parse_id)
            assert version is not None
            assert version.status == "succeeded"
            assert version.page_count == 1
            assert (
                session.scalar(
                    select(DocumentPage).where(DocumentPage.parse_version_id == parse_id)
                )
                is not None
            )
            assert (
                session.scalar(
                    select(DocumentBlock).where(DocumentBlock.parse_version_id == parse_id)
                )
                is not None
            )

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO document_pages "
                        "(parse_version_id, page_no, unit, page_text, text_sha256) "
                        "VALUES (:parse_id, 2, 'unknown', 'late', :sha)"
                    ),
                    {"parse_id": parse_id, "sha": "b" * 64},
                )
    finally:
        _clear_subjects(engine, organization_id, file_id)
        engine.dispose()


def test_cr005_r2_storage_constraints_fail_closed_without_job_and_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, organization_id, file_id = _setup(monkeypatch)
    try:
        with factory.begin() as session:
            source_parse_id = DocumentProcessingRepository(session).append_result(
                organization_id=organization_id,
                file_id=file_id,
                trace_id=uuid4(),
                result=ParseVersionWrite(
                    source_type="parser",
                    parser_name="synthetic-parser",
                    parser_version="1",
                    ocr_name=None,
                    ocr_version=None,
                    average_confidence=None,
                    pages=(
                        ParsePageWrite(
                            page_no=1,
                            width=Decimal("100"),
                            height=Decimal("200"),
                            unit="point",
                            text="Contract body",
                            confidence=None,
                            blocks=(
                                ParseBlockWrite(
                                    block_index=0,
                                    block_type="paragraph",
                                    text="Contract body",
                                    bbox=None,
                                    confidence=None,
                                ),
                            ),
                        ),
                    ),
                ),
            )
        with engine.connect() as connection:
            source_block_id = connection.scalar(
                text("SELECT id FROM document_blocks WHERE parse_version_id=:parse_version_id"),
                {"parse_version_id": source_parse_id},
            )
            actor_id = connection.scalar(
                text("SELECT uploaded_by FROM files WHERE id=:file_id"),
                {"file_id": file_id},
            )
            assert source_block_id is not None and actor_id is not None
            result_nullable = connection.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='document_block_corrections' "
                    "AND column_name='result_parse_version_id'"
                )
            )
            mapping_definition = connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname='uq_markdown_source_mapping_identity'"
                )
            )
            asset_columns = set(
                connection.scalars(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name='document_assets' "
                        "AND column_name LIKE 'security_%'"
                    )
                )
            )
        assert result_nullable == "NO"
        assert mapping_definition is not None and "NULLS NOT DISTINCT" in mapping_definition
        assert {
            "security_policy_version",
            "security_policy_hash",
            "security_checked_at",
            "security_error_code",
            "security_scanner_profile_class",
            "security_scanner_registry_version",
            "security_scanner_registry_hash",
            "security_scanner_adapter_code",
            "security_scanner_version",
            "security_scanner_definition_version",
            "security_scanner_invoked",
        } <= asset_columns

        result_parse_id = uuid4()
        correction_id = uuid4()
        with pytest.raises(DBAPIError) as exc_info:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO document_parse_versions "
                        "(id,file_id,version_no,parent_version_id,source_type,parser_name,"
                        "parser_version,code_version,status,page_count,created_by,trace_id) "
                        "VALUES (:id,:file_id,2,:parent,'manual_correction','synthetic-parser',"
                        "'1','manual-correction-snapshot-v1','queued',0,:actor,:trace_id)"
                    ),
                    {
                        "id": result_parse_id,
                        "file_id": file_id,
                        "parent": source_parse_id,
                        "actor": actor_id,
                        "trace_id": uuid4(),
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO document_block_corrections "
                        "(id,source_parse_version_id,source_block_id,result_parse_version_id,"
                        "field_name,before_value_json,after_value_json,reason,"
                        "corrected_by,trace_id) "
                        "VALUES (:id,:source_parse,:source_block,:result_parse,'text_content',"
                        "CAST(:before AS jsonb),CAST(:after AS jsonb),'fix OCR',:actor,:trace_id)"
                    ),
                    {
                        "id": correction_id,
                        "source_parse": source_parse_id,
                        "source_block": source_block_id,
                        "result_parse": result_parse_id,
                        "before": json.dumps("Contract body"),
                        "after": json.dumps("Corrected contract body"),
                        "actor": actor_id,
                        "trace_id": uuid4(),
                    },
                )
        assert getattr(exc_info.value.orig, "sqlstate", None) == "23514"
    finally:
        _clear_subjects(engine, organization_id, file_id)
        engine.dispose()
