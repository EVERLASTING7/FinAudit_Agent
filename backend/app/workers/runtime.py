"""文件 Worker 与维护进程共享的惰性运行时构造。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from app.adapters.malware_scanner import create_malware_scanner
from app.adapters.minio_file_runtime import MinioFileRuntimeAdapter
from app.adapters.minio_report_storage import MinioReportStorageAdapter
from app.adapters.ocr import create_ocr_engine, create_pdf_renderer
from app.adapters.qdrant_vector import QdrantVectorAdapter
from app.ai.adapters.deterministic_hash import DeterministicHashEmbeddingAdapter
from app.ai.adapters.openai_compatible import OpenAiChatCompletionsAdapter
from app.ai.live_policy import LIVE_LLM_POLICY
from app.ai.live_runtime import create_live_llm_runtime
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
    llm_adapter: OpenAiChatCompletionsAdapter | None = None

    def close(self) -> None:
        if self.llm_adapter is not None:
            self.llm_adapter.close()
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
    llm_adapter: OpenAiChatCompletionsAdapter | None = None
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
            llm_runtime = create_live_llm_runtime(
                settings=settings,
                session_factory=session_factory,
                policy_snapshot=policy_snapshot,
            )
            llm_adapter = llm_runtime.adapter
            ai_extraction = AiExtractionService(
                llm_runtime.invoker,
                LIVE_LLM_POLICY,
            )
            ai_risk_explanation = AiRiskExplanationService(
                llm_runtime.invoker,
                LIVE_LLM_POLICY,
            )
            ai_report_draft = AiReportDraftService(
                llm_runtime.invoker,
                LIVE_LLM_POLICY,
            )
        invoice_executor = InvoiceExtractionExecutor(session_factory, ai_extraction)
        contract_executor = ContractExtractionExecutor(session_factory, ai_extraction)
        vector_store = QdrantVectorAdapter(settings)
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
                DeterministicHashEmbeddingAdapter(
                    model_id=settings.embedding_model,
                    vector_size=settings.embedding_vector_size,
                ),
                embedding_batch_size=min(settings.embedding_batch_size, 256),
            ),
            audit_executor=AuditJobExecutor(session_factory, ai_risk_explanation),
            report_executor=ReportJobExecutor(
                session_factory,
                MinioReportStorageAdapter(settings, credential_scope="worker"),
                ai_report_draft,
            ),
            vector_store=vector_store,
            llm_adapter=llm_adapter,
        )
    except Exception:
        if llm_adapter is not None:
            llm_adapter.close()
        if vector_store is not None:
            vector_store.close()
        engine.dispose()
        raise


__all__ = ["FileWorkerRuntime", "create_file_worker_runtime"]
