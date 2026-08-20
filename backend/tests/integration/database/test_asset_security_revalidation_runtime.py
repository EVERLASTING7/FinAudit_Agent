from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine

from app.adapters.malware_scanner import NotConfiguredScanner
from app.adapters.minio_file_runtime import MemoryFileRuntimeAdapter
from app.adapters.ocr import NotConfiguredOcrEngine
from app.models.document_processing import DocumentAsset, DocumentParseVersion
from app.models.documents import FileRecord
from app.models.reliability import AsyncJob
from app.schemas.document_corrections import (
    DocumentParseActivationRequest,
    SecurityRevalidationRequest,
)
from app.security.asset_runtime_storage import MemoryAssetRuntimeStorage
from app.security.fixed_test_asset_scanner import FixedTestAssetScanner
from app.security.scanner_registry import FIXED_TEST_REGISTRY_HASH
from app.services.auth import AuthenticatedActor
from app.services.document_correction import DocumentCorrectionService
from app.services.document_parser import DocumentParser
from app.services.file_job_executor import FileJobExecutor
from tests.integration.database.test_document_processing_repository import (
    _clear_subjects,
    _setup,
)
from tests.integration.database.test_file_job_executor import _dispatch_pending

pytestmark = pytest.mark.integration

PROFILE_PATH = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "security"
    / "artifacts"
    / "fixed-test-scanner-profile-v1.json"
)


def _cleanup_runtime(engine: Engine, organization_id: UUID) -> None:
    tables = (
        "markdown_source_mappings",
        "markdown_validation_results",
        "document_markdown_versions",
        "outbox_events",
        "async_job_steps",
        "async_jobs",
        "operation_logs",
        "idempotency_records",
        "scanner_registry_profiles",
    )
    with engine.begin() as connection:
        for table_name in tables:
            connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
        try:
            connection.execute(
                text(
                    "DELETE FROM markdown_source_mappings WHERE markdown_version_id IN "
                    "(SELECT id FROM document_markdown_versions WHERE file_id IN "
                    "(SELECT id FROM files WHERE organization_id=:organization_id))"
                ),
                {"organization_id": organization_id},
            )
            connection.execute(
                text(
                    "DELETE FROM markdown_validation_results WHERE markdown_version_id IN "
                    "(SELECT id FROM document_markdown_versions WHERE file_id IN "
                    "(SELECT id FROM files WHERE organization_id=:organization_id))"
                ),
                {"organization_id": organization_id},
            )
            connection.execute(
                text(
                    "DELETE FROM document_markdown_versions WHERE file_id IN "
                    "(SELECT id FROM files WHERE organization_id=:organization_id)"
                ),
                {"organization_id": organization_id},
            )
            connection.execute(
                text(
                    "DELETE FROM outbox_events WHERE aggregate_id IN "
                    "(SELECT id FROM async_jobs WHERE organization_id=:organization_id)"
                ),
                {"organization_id": organization_id},
            )
            connection.execute(
                text(
                    "DELETE FROM async_job_steps WHERE job_id IN "
                    "(SELECT id FROM async_jobs WHERE organization_id=:organization_id)"
                ),
                {"organization_id": organization_id},
            )
            for table_name in ("async_jobs", "operation_logs", "idempotency_records"):
                connection.execute(
                    text(f"DELETE FROM {table_name} WHERE organization_id=:organization_id"),
                    {"organization_id": organization_id},
                )
            connection.execute(text("DELETE FROM scanner_registry_profiles"))
        finally:
            for table_name in reversed(tables):
                connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))


def test_fixed_test_profile_runs_isolated_asset_revalidation_and_preserves_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, organization_id, file_id = _setup(monkeypatch)
    source_parse_id = uuid4()
    source_asset_id = uuid4()
    page_id = uuid4()
    payload = b"\x89PNG\r\n\x1a\nsynthetic-clean-asset"
    source_key = "synthetic/source-asset.png"
    try:
        with engine.begin() as connection:
            actor_id = connection.execute(
                text("SELECT uploaded_by FROM files WHERE id=:file_id"),
                {"file_id": file_id},
            ).scalar_one()
            profile_bytes = PROFILE_PATH.read_bytes().removesuffix(b"\n")
            connection.execute(
                text(
                    "INSERT INTO scanner_registry_profiles ("
                    "profile_class,registry_version,scanner_registry_hash,"
                    "profile_jcs_bytes,approval_artifact_sha256) VALUES ("
                    "'fixed_test','fixed-test-registry-v1',:profile_hash,:profile,'a' || "
                    "repeat('a',63))"
                ),
                {"profile_hash": FIXED_TEST_REGISTRY_HASH, "profile": profile_bytes},
            )
            connection.execute(
                text(
                    "SELECT activate_scanner_registry_profile_v1("
                    "'fixed_test','fixed-test-registry-v1',:profile_hash,NULL)"
                ),
                {"profile_hash": FIXED_TEST_REGISTRY_HASH},
            )
            for table_name in (
                "document_parse_versions",
                "document_pages",
                "document_assets",
                "document_blocks",
            ):
                connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
            try:
                connection.execute(
                    text(
                        "INSERT INTO document_parse_versions ("
                        "id,file_id,version_no,parent_version_id,source_type,parser_name,"
                        "parser_version,code_version,status,page_count,average_confidence,"
                        "activated_at,created_by,trace_id) VALUES ("
                        ":id,:file_id,1,NULL,'parser','synthetic-parser','1',"
                        "'synthetic-parser-v1','active',1,1,clock_timestamp(),:actor_id,:trace_id)"
                    ),
                    {
                        "id": source_parse_id,
                        "file_id": file_id,
                        "actor_id": actor_id,
                        "trace_id": uuid4(),
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO document_pages ("
                        "id,parse_version_id,page_no,width,height,unit,page_text,text_sha256,"
                        "confidence,metadata_json) VALUES ("
                        ":id,:parse_id,1,100,100,'point','合成文本',:text_hash,1,'{}'::jsonb)"
                    ),
                    {
                        "id": page_id,
                        "parse_id": source_parse_id,
                        "text_hash": hashlib.sha256("合成文本".encode()).hexdigest(),
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO document_assets ("
                        "id,file_id,parse_version_id,page_no,asset_type,bbox_json,mime_type,"
                        "minio_object_key,content_sha256,security_status,"
                        "security_policy_version,security_policy_hash,security_checked_at,"
                        "security_error_code,security_scanner_invoked,metadata_json,"
                        "created_by,trace_id) VALUES ("
                        ":id,:file_id,:parse_id,1,'image',CAST(:bbox AS jsonb),'image/png',"
                        ":object_key,:content_hash,'scan_failed','asset-security-v1',"
                        ":policy_hash,clock_timestamp(),'OBJECT_READ_TRANSIENT',false,'{}'::jsonb,"
                        ":actor_id,:trace_id)"
                    ),
                    {
                        "id": source_asset_id,
                        "file_id": file_id,
                        "parse_id": source_parse_id,
                        "bbox": json.dumps({"left": 0, "top": 0, "width": 10, "height": 10}),
                        "object_key": source_key,
                        "content_hash": hashlib.sha256(payload).hexdigest(),
                        "policy_hash": (
                            "b074e9cb6af5e20b57cb14f042977417bcf6f9d9eb35c47abf6a13de3823efe0"
                        ),
                        "actor_id": actor_id,
                        "trace_id": uuid4(),
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO document_blocks ("
                        "id,parse_version_id,page_id,block_index,block_type,text_content,"
                        "text_sha256,bbox_json,reading_order,confidence,asset_id,"
                        "is_effective_content,metadata_json) VALUES "
                        "(:text_id,:parse_id,:page_id,0,'paragraph','合成文本',:text_hash,"
                        "CAST(:text_bbox AS jsonb),0,1,NULL,true,'{}'::jsonb),"
                        "(:asset_block_id,:parse_id,:page_id,1,'asset',NULL,NULL,"
                        "CAST(:asset_bbox AS jsonb),1,1,:asset_id,true,'{}'::jsonb)"
                    ),
                    {
                        "text_id": uuid4(),
                        "asset_block_id": uuid4(),
                        "parse_id": source_parse_id,
                        "page_id": page_id,
                        "text_hash": hashlib.sha256("合成文本".encode()).hexdigest(),
                        "text_bbox": json.dumps({"left": 0, "top": 0, "width": 50, "height": 10}),
                        "asset_bbox": json.dumps({"left": 0, "top": 20, "width": 10, "height": 10}),
                        "asset_id": source_asset_id,
                    },
                )
            finally:
                for table_name in reversed(
                    (
                        "document_parse_versions",
                        "document_pages",
                        "document_assets",
                        "document_blocks",
                    )
                ):
                    connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))

        actor = AuthenticatedActor(
            actor_id,
            organization_id,
            uuid4(),
            ("system_admin",),
            ("system.configure",),
        )
        service = DocumentCorrectionService(factory)
        request = SecurityRevalidationRequest(
            reason="隔离合成安全重评",
            security_policy_version="asset-security-v1",
            force_recheck=True,
        )
        accepted = service.request_security_revalidation(
            actor,
            source_parse_id,
            request,
            "asset-revalidation-001",
            uuid4(),
        )
        dispatch = _dispatch_pending(factory, accepted.data.job_id)
        asset_storage = MemoryAssetRuntimeStorage({source_key: payload})
        executor = FileJobExecutor(
            factory,
            MemoryFileRuntimeAdapter(b"unused"),
            NotConfiguredScanner(),
            DocumentParser(ocr_engine=NotConfiguredOcrEngine(), pdf_renderer=None),
            max_file_bytes=1024,
            heartbeat_interval_seconds=0.05,
            asset_storage=asset_storage,
            asset_scanner=FixedTestAssetScanner(),
        )
        completed = executor.execute(
            job_id=accepted.data.job_id,
            event_id=dispatch.event_id,
            event_schema_version=dispatch.event_version,
            worker_id="fixed-test-asset-worker",
        )
        assert completed.outcome == "succeeded"

        replay = service.request_security_revalidation(
            actor,
            source_parse_id,
            request,
            "asset-revalidation-001",
            uuid4(),
        )
        assert replay.replayed is True
        assert replay.data == accepted.data
        with factory() as session:
            result_parse = session.get(DocumentParseVersion, accepted.data.resource_id)
            assert result_parse is not None and result_parse.status == "succeeded"
            result_asset = session.scalar(
                select(DocumentAsset).where(DocumentAsset.parse_version_id == result_parse.id)
            )
            assert result_asset is not None
            assert result_asset.source_asset_id == source_asset_id
            assert result_asset.security_status == "clean"
            assert result_asset.security_scanner_profile_class == "fixed_test"
            assert result_asset.security_scanner_registry_hash == FIXED_TEST_REGISTRY_HASH
            assert result_asset.minio_object_key != source_key
            assert session.get(DocumentAsset, source_asset_id).security_status == "scan_failed"  # type: ignore[union-attr]
            job = session.get(AsyncJob, accepted.data.job_id)
            assert job is not None and job.status == "succeeded"

        activated = service.activate_parse(
            actor,
            accepted.data.resource_id,
            DocumentParseActivationRequest(reason="合成安全重评通过"),
            "asset-activation-001",
            uuid4(),
        )
        assert activated.data.status == "active"
        with factory() as session:
            assert session.get(DocumentParseVersion, source_parse_id).status == "superseded"  # type: ignore[union-attr]
            assert session.get(DocumentParseVersion, accepted.data.resource_id).status == "active"  # type: ignore[union-attr]
            file_record = session.get(FileRecord, file_id)
            assert file_record is not None and file_record.status == "stored"
    finally:
        _cleanup_runtime(engine, organization_id)
        _clear_subjects(engine, organization_id, file_id)
        engine.dispose()
