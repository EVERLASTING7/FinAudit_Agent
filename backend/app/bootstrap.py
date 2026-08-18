from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

from app.ai.policy_loader import ValidatedPolicySnapshot, load_validated_policy
from app.core.config import AppEnvironment, Settings

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_app(settings: Settings | None = None) -> FastAPI:
    """验证 Settings 与本地 Policy 后构造唯一可启动的 FastAPI 应用。"""

    active_settings = settings or Settings()
    policy_snapshot = load_validated_policy(active_settings)

    # 应用图必须在 Policy 启动门禁之后导入，避免失败路径构造客户端或应用对象。
    from fastapi import FastAPI

    from app.api.exception_handlers import register_exception_handlers
    from app.api.metrics import router as metrics_router
    from app.api.v1.endpoints.health import router as health_router
    from app.api.v1.router import api_router
    from app.core.metrics import HttpMetricsMiddleware, MetricsRegistry
    from app.core.tracing import TraceIdMiddleware
    from app.schemas.common import ErrorResponse

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        adopted_snapshot = cast(
            ValidatedPolicySnapshot,
            application.state.ai_policy_snapshot,
        )
        _ = adopted_snapshot.policy_hash
        auth_engine = None
        rag_vector_store = None
        live_ai_runtime = None
        try:
            if active_settings.auth_jwt_active_kid is not None:
                from app.adapters.minio_original_storage import MinioOriginalStorageAdapter
                from app.adapters.minio_quarantine import MinioQuarantineAdapter
                from app.adapters.minio_report_storage import MinioReportStorageAdapter
                from app.adapters.qdrant_vector import QdrantVectorAdapter
                from app.ai.embedding_runtime import create_deterministic_embedding_runtime
                from app.ai.live_policy import LIVE_LLM_POLICY
                from app.ai.live_runtime import create_live_ai_runtime
                from app.api.dependencies.auth import load_auth_keyring
                from app.core.auth_security import hash_password
                from app.db.session import create_application_engine, create_session_factory
                from app.services.ai_call_audit_query import AiCallAuditQueryService
                from app.services.ai_rag_answer import AiRagAnswerService
                from app.services.audit_management import AuditManagementService
                from app.services.auth import AuthService
                from app.services.break_glass import BreakGlassService
                from app.services.contract_invoice_management import (
                    ContractInvoiceManagementService,
                )
                from app.services.contract_management import ContractManagementService
                from app.services.contract_primary_invoice_query import (
                    ContractPrimaryInvoiceQueryService,
                )
                from app.services.contract_query import ContractQueryService
                from app.services.dashboard import DashboardService
                from app.services.effective_contract_query import EffectiveContractQueryService
                from app.services.file_intake import FileIntakeService, FileQueryService
                from app.services.file_management import FileManagementService
                from app.services.invoice_management import InvoiceManagementService
                from app.services.invoice_primary_contract_query import (
                    InvoicePrimaryContractQueryService,
                )
                from app.services.invoice_query import InvoiceQueryService
                from app.services.knowledge_catalog import KnowledgeCatalogService
                from app.services.knowledge_index_management import (
                    KnowledgeIndexManagementService,
                )
                from app.services.operation_log_query import OperationLogQueryService
                from app.services.policy_management import PolicyManagementService
                from app.services.rag_query import RagQueryService
                from app.services.report_management import ReportManagementService
                from app.services.supplementary_agreement_management import (
                    SupplementaryAgreementManagementService,
                )
                from app.services.supplementary_agreement_query import (
                    SupplementaryAgreementQueryService,
                )
                from app.services.supplier_management import SupplierManagementService
                from app.services.user_management import UserManagementService
                from app.services.user_query import UserQueryService

                assert active_settings.auth_jwt_private_key_file is not None
                assert active_settings.auth_jwt_public_keyring_file is not None
                auth_keyring = load_auth_keyring(
                    active_settings.auth_jwt_active_kid,
                    active_settings.auth_jwt_private_key_file,
                    active_settings.auth_jwt_public_keyring_file,
                )
                auth_engine = create_application_engine(active_settings)
                session_factory = create_session_factory(auth_engine)
                if adopted_snapshot.provider_calls_enabled:
                    live_ai_runtime = create_live_ai_runtime(
                        settings=active_settings,
                        session_factory=session_factory,
                        policy_snapshot=adopted_snapshot,
                    )
                application.state.auth_service = AuthService(
                    session_factory,
                    auth_keyring,
                    hash_password("finaudit-dummy-password-value"),
                )
                application.state.audit_management_service = AuditManagementService(
                    session_factory, active_settings
                )
                application.state.ai_call_audit_query_service = AiCallAuditQueryService(
                    session_factory
                )
                application.state.break_glass_service = BreakGlassService(session_factory)
                application.state.contract_query_service = ContractQueryService(session_factory)
                application.state.dashboard_service = DashboardService(session_factory)
                application.state.contract_management_service = ContractManagementService(
                    session_factory
                )
                application.state.effective_contract_query_service = EffectiveContractQueryService(
                    session_factory
                )
                application.state.contract_primary_invoice_query_service = (
                    ContractPrimaryInvoiceQueryService(session_factory)
                )
                application.state.contract_invoice_management_service = (
                    ContractInvoiceManagementService(session_factory)
                )
                application.state.invoice_query_service = InvoiceQueryService(session_factory)
                application.state.invoice_management_service = InvoiceManagementService(
                    session_factory
                )
                file_storage = MinioQuarantineAdapter(active_settings)
                application.state.file_intake_service = FileIntakeService(
                    session_factory,
                    file_storage,
                    active_settings,
                )
                application.state.file_query_service = FileQueryService(session_factory)
                application.state.file_management_service = FileManagementService(
                    session_factory,
                    MinioOriginalStorageAdapter(active_settings),
                    active_settings,
                )
                application.state.operation_log_query_service = OperationLogQueryService(
                    session_factory
                )
                application.state.report_management_service = ReportManagementService(
                    session_factory,
                    MinioReportStorageAdapter(active_settings, credential_scope="api"),
                )
                application.state.policy_management_service = PolicyManagementService(
                    session_factory
                )
                application.state.knowledge_catalog_service = KnowledgeCatalogService(
                    session_factory
                )
                embedding_runtime = (
                    create_deterministic_embedding_runtime(
                        model_id=active_settings.embedding_model,
                        vector_size=active_settings.embedding_vector_size,
                        deadline_seconds=active_settings.ai_embedding_deadline_seconds,
                    )
                    if live_ai_runtime is None
                    else live_ai_runtime.embedding
                )
                application.state.knowledge_index_management_service = (
                    KnowledgeIndexManagementService(
                        session_factory,
                        active_settings,
                        embedding_target=embedding_runtime.target,
                    )
                )
                rag_vector_store = QdrantVectorAdapter(active_settings)
                application.state.rag_query_service = RagQueryService(
                    session_factory,
                    rag_vector_store,
                    embedding_runtime,
                    active_settings,
                    (
                        None
                        if live_ai_runtime is None
                        else AiRagAnswerService(live_ai_runtime.invoker, LIVE_LLM_POLICY)
                    ),
                )
                application.state.invoice_primary_contract_query_service = (
                    InvoicePrimaryContractQueryService(session_factory)
                )
                application.state.supplementary_agreement_query_service = (
                    SupplementaryAgreementQueryService(session_factory)
                )
                application.state.supplementary_agreement_management_service = (
                    SupplementaryAgreementManagementService(session_factory)
                )
                application.state.supplier_management_service = SupplierManagementService(
                    session_factory
                )
                application.state.user_query_service = UserQueryService(session_factory)
                application.state.user_management_service = UserManagementService(session_factory)
            yield
        finally:
            if live_ai_runtime is not None:
                live_ai_runtime.close()
            if rag_vector_store is not None:
                rag_vector_store.close()
            if auth_engine is not None:
                auth_engine.dispose()

    application = FastAPI(
        title=active_settings.app_name,
        version=active_settings.app_version,
        lifespan=lifespan,
        openapi_url=None if active_settings.app_env is AppEnvironment.PROD else "/openapi.json",
        docs_url=None if active_settings.app_env is AppEnvironment.PROD else "/docs",
        redoc_url=None if active_settings.app_env is AppEnvironment.PROD else "/redoc",
        responses={
            422: {
                "description": "请求参数不符合约束",
                "model": ErrorResponse,
            }
        },
    )
    application.state.settings = active_settings
    application.state.ai_policy_snapshot = policy_snapshot
    if active_settings.metrics_enabled:
        metrics_registry = MetricsRegistry()
        application.state.metrics_registry = metrics_registry
        application.add_middleware(HttpMetricsMiddleware, registry=metrics_registry)
    application.add_middleware(TraceIdMiddleware)
    register_exception_handlers(application)
    application.include_router(health_router)
    if active_settings.metrics_enabled:
        application.include_router(metrics_router)
    application.include_router(api_router, prefix="/api/v1")
    return application
