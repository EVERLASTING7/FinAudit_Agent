from __future__ import annotations

import json
import os
import sys
from hashlib import sha256
from importlib import resources
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.ai.adapters.openai_compatible import (  # noqa: E402
    OPENAI_CHAT_COMPLETIONS_ADAPTER_ID,
    OpenAiChatCompletionsAdapter,
    OpenAiCompatibleProfile,
)
from app.ai.gateway import AiGateway  # noqa: E402
from app.ai.live_policy import (  # noqa: E402
    LIVE_LLM_POLICY,
    LIVE_POLICY_HASH,
    LIVE_POLICY_ID,
    LIVE_POLICY_RAW_SHA256,
)
from app.ai.network_policy import OutboundNetworkPolicy  # noqa: E402
from app.ai.output_validation import (  # noqa: E402
    FrozenRuleResult,
    RagCitation,
    RiskCitation,
)
from app.ai.policy_loader import ValidatedPolicySnapshot  # noqa: E402
from app.ai.rag_prompts import RagPromptCandidate  # noqa: E402
from app.ai.report_draft import (  # noqa: E402
    FrozenReportFacts,
    ReportDraftPromptInput,
)
from app.ai.risk_explanation_prompts import RiskExplanationPromptInput  # noqa: E402
from app.models.audit import AiCallLog  # noqa: E402
from app.models.documents import FilePrimaryBusinessObject  # noqa: E402
from app.models.financial import Contract, ContractField, Invoice, InvoiceItem  # noqa: E402
from app.models.reliability import AsyncJob  # noqa: E402
from app.repositories.ai_call_audit import AiCallProjectionStatus  # noqa: E402
from app.services.ai_call_audit import AiCallAuditService  # noqa: E402
from app.services.ai_extraction import AiExtractionService  # noqa: E402
from app.services.ai_rag_answer import AiRagAnswerService  # noqa: E402
from app.services.ai_report_draft import AiReportDraftService  # noqa: E402
from app.services.ai_risk_explanation import AiRiskExplanationService  # noqa: E402
from app.services.audited_llm import AuditedLlmInvoker  # noqa: E402
from app.services.contract_extraction_executor import (  # noqa: E402
    ContractExtractionExecutor,
)
from app.services.invoice_extraction_executor import InvoiceExtractionExecutor  # noqa: E402
from tests.integration.database.test_contract_extraction_management import (  # noqa: E402
    _clear_contract_subjects,
)
from tests.integration.database.test_file_intake_service import (  # noqa: E402
    ORGANIZATION_ID,
    _setup,
)
from tests.integration.database.test_file_job_executor import (  # noqa: E402
    _dispatch_pending,
)
from tests.integration.database.test_invoice_extraction_management import (  # noqa: E402
    _clear_invoice_subjects,
)
from tests.integration.database.test_invoice_extraction_management import (  # noqa: E402
    _upload_and_parse as _upload_and_parse_invoice,
)
from tests.integration.database.test_live_ai_extraction_runtime import (  # noqa: E402
    _clear_live_ai_subjects,
    _upload_and_parse_contract,
)

_CONFIRMATION = "ALLOW_ONE_BOUNDED_MINIMAX_CALL"
_REGISTRY_SHA256 = "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"


class LiveContractSmokeError(RuntimeError):
    pass


def _adapter() -> OpenAiChatCompletionsAdapter:
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key or api_key.upper().startswith("REPLACE_"):
        raise LiveContractSmokeError("LLM_API_KEY_REQUIRED")
    registry_bytes = (
        resources.files("app.ai.artifacts.cr011_v1").joinpath("ip-deny-cidrs-v1.json").read_bytes()
    )
    network_policy = OutboundNetworkPolicy(
        endpoint_id=LIVE_LLM_POLICY.endpoint_id,
        network_scope="external_public",
        base_url=LIVE_LLM_POLICY.base_url,
        approved_hostnames=LIVE_LLM_POLICY.approved_hostnames,
        allowed_cidrs=LIVE_LLM_POLICY.allowed_cidrs,
        billing_mode="external_usd",
        address_policy_version="ip-deny-cidrs-v1",
        registry_sha256=_REGISTRY_SHA256,
    )
    return OpenAiChatCompletionsAdapter(
        OpenAiCompatibleProfile(
            profile_type="chat",
            base_url=LIVE_LLM_POLICY.base_url,
            model_id=LIVE_LLM_POLICY.model_id,
            allowed_response_model_ids=LIVE_LLM_POLICY.allowed_response_model_ids,
            api_key=SecretStr(api_key),
            network_policy=network_policy,
            registry_bytes=registry_bytes,
            max_request_bytes=LIVE_LLM_POLICY.max_request_bytes,
            max_response_header_bytes=LIVE_LLM_POLICY.max_response_header_bytes,
            max_response_body_bytes=LIVE_LLM_POLICY.max_response_body_bytes,
            use_max_completion_tokens=True,
            thinking_mode="disabled",
            service_tier="standard",
        )
    )


def _invoker(
    factory: sessionmaker[Session],
    adapter: OpenAiChatCompletionsAdapter,
) -> AuditedLlmInvoker:
    gateway = AiGateway(
        llm_adapters={OPENAI_CHAT_COMPLETIONS_ADAPTER_ID: adapter},
        embedding_adapters={},
    )
    return AuditedLlmInvoker(
        session_factory=factory,
        gateway=gateway,
        adapter=adapter,
        policy_snapshot=ValidatedPolicySnapshot(
            policy_version=1,
            policy_hash=LIVE_POLICY_HASH,
            raw_sha256=LIVE_POLICY_RAW_SHA256,
            provider_calls_enabled=True,
            runtime_profile_id=LIVE_POLICY_ID,
        ),
        llm_policy=LIVE_LLM_POLICY,
    )


def _exercise_generation_services(
    factory: sessionmaker[Session],
    invoker: AuditedLlmInvoker,
    *,
    job_id: UUID,
) -> tuple[UUID, UUID, UUID]:
    rag_operation_id = uuid4()
    rag_content = "差旅住宿费应取得合规发票，并由授权审批人完成事前或事后审批。"
    rag_citation = RagCitation(
        candidate_id=str(uuid4()),
        policy_document_id=str(uuid4()),
        policy_version="v1",
        markdown_version_id=str(uuid4()),
        chunk_id=str(uuid4()),
        block_ids=(str(uuid4()),),
        index_version_id=str(uuid4()),
        page_range="1",
        title_path=("差旅费制度", "住宿费"),
        quote=rag_content,
        content_sha256=sha256(rag_content.encode("utf-8")).hexdigest(),
    )
    rag_result = AiRagAnswerService(invoker, LIVE_LLM_POLICY).answer(
        organization_id=ORGANIZATION_ID,
        query_id=rag_operation_id,
        trace_id=uuid4(),
        question="差旅住宿费报销需要哪些凭证和审批？",
        candidates=(
            RagPromptCandidate(
                citation=rag_citation,
                policy_name="差旅费制度",
                content=rag_content,
            ),
        ),
    )
    if rag_result.output.answer_status != "answered" or not rag_result.output.citations:
        raise LiveContractSmokeError("LIVE_RAG_ANSWER_INVALID")
    with factory.begin() as session:
        rag_result.adoption.adopt_in_transaction(session)

    risk_operation_id = uuid4()
    risk_citation = RiskCitation(
        candidate_id=str(uuid4()),
        policy_document_id=str(uuid4()),
        chunk_id=str(uuid4()),
        quote="单笔采购金额超过审批阈值时，必须完成授权审批。",
    )
    risk_result = AiRiskExplanationService(invoker, LIVE_LLM_POLICY).explain(
        organization_id=ORGANIZATION_ID,
        job_id=job_id,
        risk_id=risk_operation_id,
        trace_id=uuid4(),
        prompt_input=RiskExplanationPromptInput(
            frozen_rule=FrozenRuleResult(
                rule_code="RULE-LIVE-001",
                rule_version="v1",
                rule_status="hit",
                original_risk_level="high",
            ),
            title="采购金额超过审批阈值",
            actual_value="120000 CNY",
            expected_value="不超过 100000 CNY，或具备授权审批记录",
            explanation_template="采购金额超过阈值且缺少已确认的授权审批事实。",
            requires_policy_citation=True,
            candidates=(risk_citation,),
        ),
    )
    if risk_result.output.rule_code != "RULE-LIVE-001":
        raise LiveContractSmokeError("LIVE_RISK_EXPLANATION_INVALID")
    with factory.begin() as session:
        risk_result.adoption.adopt_in_transaction(session)

    report_operation_id = uuid4()
    execution_id = uuid4()
    frozen_report = FrozenReportFacts(
        report_id=str(report_operation_id),
        execution_id=str(execution_id),
        overall_level="high",
        active_risk_count=1,
        dismissed_risk_count=0,
        has_effective_high=True,
        has_unreviewed_high=False,
    )
    report_result = AiReportDraftService(invoker, LIVE_LLM_POLICY).draft(
        organization_id=ORGANIZATION_ID,
        job_id=job_id,
        report_id=report_operation_id,
        trace_id=uuid4(),
        prompt_input=ReportDraftPromptInput(
            frozen=frozen_report,
            facts={
                "scope": {"contract_count": 1, "invoice_count": 1},
                "rules": [
                    {
                        "rule_code": "RULE-LIVE-001",
                        "rule_status": "hit",
                        "original_risk_level": "high",
                    }
                ],
                "risks": [
                    {
                        "review_status": "confirmed",
                        "title": "采购金额超过审批阈值",
                    }
                ],
            },
        ),
    )
    if report_result.output.report_id != str(report_operation_id):
        raise LiveContractSmokeError("LIVE_REPORT_DRAFT_INVALID")
    with factory.begin() as session:
        report_result.adoption.adopt_in_transaction(session)
    return rag_operation_id, risk_operation_id, report_operation_id


def _project_operation(factory: sessionmaker[Session]) -> None:
    service = AiCallAuditService(factory)
    for _ in range(16):
        if service.project_once().status is AiCallProjectionStatus.IDLE:
            return
    raise LiveContractSmokeError("AI_AUDIT_PROJECTION_LIMIT_EXCEEDED")


def _estimated_cost_micro_usd(input_tokens: int, output_tokens: int) -> int:
    numerator = (
        input_tokens * LIVE_LLM_POLICY.input_price_micro_usd_per_million
        + output_tokens * LIVE_LLM_POLICY.output_price_micro_usd_per_million
    )
    return (numerator + 999_999) // 1_000_000


def _safe_failure_code(
    factory: sessionmaker[Session],
    *,
    prefix: str,
    operation_id: UUID,
) -> str:
    summary = AiCallAuditService(factory).get_operation_summary(
        ORGANIZATION_ID,
        operation_id,
    )
    with factory() as session:
        job = session.get(AsyncJob, operation_id)
    job_code = "JOB_UNKNOWN" if job is None or job.error_code is None else job.error_code
    if summary is None:
        return f"{prefix}_{job_code}_AUDIT_MISSING"
    attempts = "_".join(
        f"{attempt.status}-{attempt.safe_error_code or 'NONE'}" for attempt in summary.attempts
    )
    return f"{prefix}_{job_code}_{attempts or 'ATTEMPTS_MISSING'}"


def _run() -> dict[str, object]:
    if os.environ.get("FINAUDIT_LIVE_AI_SMOKE") != _CONFIRMATION:
        raise LiveContractSmokeError("LIVE_AI_SMOKE_CONFIRMATION_REQUIRED")
    patcher = pytest.MonkeyPatch()
    engine: Engine | None = None
    adapter: OpenAiChatCompletionsAdapter | None = None
    contract_file_id: UUID | None = None
    invoice_file_id: UUID | None = None
    try:
        engine, factory, intake, quarantine = _setup(patcher)
        adapter = _adapter()
        invoker = _invoker(factory, adapter)
        ai_extraction = AiExtractionService(invoker, LIVE_LLM_POLICY)
        contract_file_id, contract_job_id = _upload_and_parse_contract(
            factory,
            intake,
            quarantine,
        )
        contract_event = _dispatch_pending(factory, contract_job_id)
        contract_result = ContractExtractionExecutor(factory, ai_extraction).execute(
            job_id=contract_job_id,
            event_id=contract_event.event_id,
            event_schema_version=contract_event.event_version,
            worker_id="live-minimax-contract-smoke",
        )
        if contract_result.outcome != "succeeded":
            raise LiveContractSmokeError(
                _safe_failure_code(
                    factory,
                    prefix="LIVE_CONTRACT_EXTRACTION_FAILED",
                    operation_id=contract_job_id,
                )
            )

        invoice_file_id, invoice_job_id, _ = _upload_and_parse_invoice(
            factory,
            intake,
            quarantine,
        )
        invoice_event = _dispatch_pending(factory, invoice_job_id)
        invoice_result = InvoiceExtractionExecutor(factory, ai_extraction).execute(
            job_id=invoice_job_id,
            event_id=invoice_event.event_id,
            event_schema_version=invoice_event.event_version,
            worker_id="live-minimax-invoice-smoke",
        )
        if invoice_result.outcome != "succeeded":
            raise LiveContractSmokeError(
                _safe_failure_code(
                    factory,
                    prefix="LIVE_INVOICE_EXTRACTION_FAILED",
                    operation_id=invoice_job_id,
                )
            )

        generated_operation_ids = _exercise_generation_services(
            factory,
            invoker,
            job_id=contract_job_id,
        )

        _project_operation(factory)
        audit_service = AiCallAuditService(factory)
        contract_summary = audit_service.get_operation_summary(
            ORGANIZATION_ID,
            contract_job_id,
        )
        invoice_summary = audit_service.get_operation_summary(
            ORGANIZATION_ID,
            invoice_job_id,
        )
        generated_summaries = tuple(
            audit_service.get_operation_summary(ORGANIZATION_ID, operation_id)
            for operation_id in generated_operation_ids
        )
        if contract_summary is None or not contract_summary.attempts:
            raise LiveContractSmokeError("LIVE_CONTRACT_AUDIT_MISSING")
        if invoice_summary is None or not invoice_summary.attempts:
            raise LiveContractSmokeError("LIVE_INVOICE_AUDIT_MISSING")
        if any(summary is None or not summary.attempts for summary in generated_summaries):
            raise LiveContractSmokeError("LIVE_GENERATION_AUDIT_MISSING")
        with factory() as session:
            contract_binding = session.scalars(
                select(FilePrimaryBusinessObject).where(
                    FilePrimaryBusinessObject.file_id == contract_file_id
                )
            ).one()
            invoice_binding = session.scalars(
                select(FilePrimaryBusinessObject).where(
                    FilePrimaryBusinessObject.file_id == invoice_file_id
                )
            ).one()
            contract = session.get(Contract, contract_binding.contract_id)
            invoice = session.get(Invoice, invoice_binding.invoice_id)
            contract_field_count = session.scalar(
                select(func.count())
                .select_from(ContractField)
                .where(ContractField.contract_id == contract_binding.contract_id)
            )
            invoice_item_count = session.scalar(
                select(func.count())
                .select_from(InvoiceItem)
                .where(InvoiceItem.invoice_id == invoice_binding.invoice_id)
            )
            log_count = session.scalar(
                select(func.count())
                .select_from(AiCallLog)
                .where(
                    AiCallLog.business_operation_id.in_(
                        (contract_job_id, invoice_job_id, *generated_operation_ids)
                    )
                )
            )
        if (
            contract is None
            or invoice is None
            or contract_field_count is None
            or invoice_item_count is None
            or log_count is None
        ):
            raise LiveContractSmokeError("LIVE_EXTRACTION_FACTS_MISSING")
        invoice_fields = invoice.field_evidence_json.get("fields")
        if type(invoice_fields) is not list:
            raise LiveContractSmokeError("LIVE_INVOICE_EVIDENCE_MISSING")
        operation_summaries = (
            contract_summary,
            invoice_summary,
            *(summary for summary in generated_summaries if summary is not None),
        )
        for operation_summary in operation_summaries:
            statuses = tuple(attempt.status for attempt in operation_summary.attempts)
            if statuses[-1] != "succeeded" or any(
                status not in {"rejected", "succeeded"} for status in statuses
            ):
                raise LiveContractSmokeError("LIVE_EXTRACTION_AUDIT_STATUS_INVALID")
        input_tokens = sum(summary.actual_input_tokens for summary in operation_summaries)
        output_tokens = sum(summary.actual_output_tokens for summary in operation_summaries)
        return {
            "attempt_count": sum(summary.attempt_count for summary in operation_summaries),
            "audit_log_count": log_count,
            "estimated_cost_micro_usd": _estimated_cost_micro_usd(
                input_tokens,
                output_tokens,
            ),
            "contract_field_count": contract_field_count,
            "input_tokens": input_tokens,
            "invoice_field_count": len(invoice_fields),
            "invoice_item_count": invoice_item_count,
            "model_id": contract_summary.attempts[-1].model_id,
            "output_tokens": output_tokens,
            "policy_hash": LIVE_POLICY_HASH,
            "validated_generation_flows": [
                "rag_answer",
                "risk_explanation",
                "report_draft",
            ],
            "status": "passed",
        }
    finally:
        if adapter is not None:
            adapter.close()
        if engine is not None:
            file_ids = tuple(
                file_id for file_id in (contract_file_id, invoice_file_id) if file_id is not None
            )
            if invoice_file_id is not None:
                _clear_invoice_subjects(engine, invoice_file_id)
            if contract_file_id is not None:
                _clear_contract_subjects(engine, contract_file_id)
            if file_ids:
                _clear_live_ai_subjects(engine, file_ids)
            engine.dispose()
        patcher.undo()


def main() -> int:
    try:
        summary = _run()
    except LiveContractSmokeError as error:
        print(json.dumps({"code": str(error), "status": "failed"}, separators=(",", ":")))
        return 1
    except Exception:
        print(
            json.dumps(
                {"code": "LIVE_CONTRACT_SMOKE_UNEXPECTED", "status": "failed"},
                separators=(",", ":"),
            )
        )
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
