from fastapi import APIRouter

from app.api.v1.endpoints.ai_call_audit import router as ai_call_audit_router
from app.api.v1.endpoints.audits import router as audit_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.break_glass import router as break_glass_router
from app.api.v1.endpoints.contracts import router as contract_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.document_corrections import router as document_correction_router
from app.api.v1.endpoints.files import router as file_router
from app.api.v1.endpoints.invoices import router as invoice_router
from app.api.v1.endpoints.knowledge import feedback_router as qa_feedback_router
from app.api.v1.endpoints.knowledge import router as knowledge_router
from app.api.v1.endpoints.operation_logs import router as operation_log_router
from app.api.v1.endpoints.policies import router as policy_router
from app.api.v1.endpoints.reports import router as report_router
from app.api.v1.endpoints.suppliers import router as supplier_router
from app.api.v1.endpoints.users import router as user_router

api_router = APIRouter()
api_router.include_router(ai_call_audit_router)
api_router.include_router(audit_router)
api_router.include_router(auth_router)
api_router.include_router(break_glass_router)
api_router.include_router(contract_router)
api_router.include_router(dashboard_router)
api_router.include_router(document_correction_router)
api_router.include_router(file_router)
api_router.include_router(invoice_router)
api_router.include_router(knowledge_router)
api_router.include_router(qa_feedback_router)
api_router.include_router(operation_log_router)
api_router.include_router(policy_router)
api_router.include_router(report_router)
api_router.include_router(supplier_router)
api_router.include_router(user_router)
