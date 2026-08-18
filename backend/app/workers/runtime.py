"""文件 Worker 与维护进程共享的惰性运行时构造。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from app.adapters.malware_scanner import create_malware_scanner
from app.adapters.minio_file_runtime import MinioFileRuntimeAdapter
from app.adapters.minio_report_storage import MinioReportStorageAdapter
from app.adapters.ocr import create_ocr_engine, create_pdf_renderer
from app.adapters.qdrant_vector import QdrantVectorAdapter
from app.ai.embedding_runtime import create_deterministic_embedding_runtime
from app.ai.live_policy import LIVE_LLM_POLICY
from app.ai.live_runtime import LiveAiRuntime, create_live_ai_runtime
from app.ai.policy_loader import ValidatedPolicySnapshot, load_validated_policy
from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.services.ai_extraction import AiExtractionService
from app.services.ai_report_draft import AiReportDraftService
from app.services.ai_risk_explanation import AiRiskExplanationService
from app.services.audit_job_executor import AuditJobExecutor
from app.services.contract_extraction_executor import ContractExtractionExecutor
from app.services.document_parser import DocumentParser
from app.services.extraction_job_executor import ExtractionJobExecutor
from app.services.file_job_executor import FileJobExecutor
from app.services.invoice_extraction_executor import InvoiceExtractionExecutor
from app.services.knowledge_job_executor import KnowledgeJobExecutor
from app.services.report_job_executor import ReportJobExecutor


@dataclass(slots=True)
class FileWorkerRuntime:
    executor: FileJobExecutor
    engine: Engine
    invoice_executor: InvoiceExtractionExecutor | None = None
    contract_executor: ContractExtractionExecutor | None = None
    extraction_executor: ExtractionJobExecutor | None = None
    knowledge_executor: KnowledgeJobExecutor | None = None
    audit_executor: AuditJobExecutor | None = None
    report_executor: ReportJobExecutor | None = None
    vector_store: QdrantVectorAdapter | None = None
    live_ai_runtime: LiveAiRuntime | None = None

    def close(self) -> None:
        if self.live_ai_runtime is not None:
            self.live_ai_runtime.close()
        if self.vector_store is not None:
            self.vector_store.close()
        self.engine.dispose()


def create_file_worker_runtime(settings: Settings) -> FileWorkerRuntime:
    policy_snapshot = (
        load_validated_policy(settings)
        if isinstance(settings, Settings)
        else ValidatedPolicySnapshot(1, "0" * 64, "0" * 64)
    )
    engine = create_application_engine(settings)
    vector_store: QdrantVectorAdapter | None = None
    live_ai_runtime: LiveAiRuntime | None = None
    try:
        session_factory = create_session_factory(engine)
        parser = DocumentParser(
            ocr_engine=create_ocr_engine(settings),
            pdf_renderer=create_pdf_renderer(settings),
        )
        executor = FileJobExecutor(
            session_factory,
            MinioFileRuntimeAdapter(settings),
            create_malware_scanner(settings),
            parser,
            max_file_bytes=settings.max_upload_size_mb * 1024 * 1024,
        )
        ai_extraction: AiExtractionService | None = None
        ai_risk_explanation: AiRiskExplanationService | None = None
        ai_report_draft: AiReportDraftService | None = None
        if policy_snapshot.provider_calls_enabled:
            live_ai_runtime = create_live_ai_runtime(
                settings=settings,
                session_factory=session_factory,
                policy_snapshot=policy_snapshot,
            )
            ai_extraction = AiExtractionService(
                live_ai_runtime.invoker,
                LIVE_LLM_POLICY,
            )
            ai_risk_explanation = AiRiskExplanationService(
                live_ai_runtime.invoker,
                LIVE_LLM_POLICY,
            )
            ai_report_draft = AiReportDraftService(
                live_ai_runtime.invoker,
                LIVE_LLM_POLICY,
            )
        invoice_executor = InvoiceExtractionExecutor(session_factory, ai_extraction)
        contract_executor = ContractExtractionExecutor(session_factory, ai_extraction)
        vector_store = QdrantVectorAdapter(settings)
        embedding_runtime = (
            create_deterministic_embedding_runtime(
                model_id=settings.embedding_model,
                vector_size=settings.embedding_vector_size,
                deadline_seconds=settings.ai_embedding_deadline_seconds,
            )
            if live_ai_runtime is None
            else live_ai_runtime.embedding
        )
        return FileWorkerRuntime(
            executor=executor,
            engine=engine,
            invoice_executor=invoice_executor,
            contract_executor=contract_executor,
            extraction_executor=ExtractionJobExecutor(
                session_factory,
                invoice_executor,
                contract_executor,
            ),
            knowledge_executor=KnowledgeJobExecutor(
                session_factory,
                vector_store,
                embedding_runtime,
                embedding_batch_size=min(settings.embedding_batch_size, 256),
            ),
            audit_executor=AuditJobExecutor(session_factory, ai_risk_explanation),
            report_executor=ReportJobExecutor(
                session_factory,
                MinioReportStorageAdapter(settings, credential_scope="worker"),
                ai_report_draft,
            ),
            vector_store=vector_store,
            live_ai_runtime=live_ai_runtime,
        )
    except Exception:
        if live_ai_runtime is not None:
            live_ai_runtime.close()
        if vector_store is not None:
            vector_store.close()
        engine.dispose()
        raise


__all__ = ["FileWorkerRuntime", "create_file_worker_runtime"]
