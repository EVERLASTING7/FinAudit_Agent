from __future__ import annotations

import io
import json
from collections.abc import Iterator
from importlib import resources
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.ai.adapters.openai_compatible import (
    OPENAI_CHAT_COMPLETIONS_ADAPTER_ID,
    OpenAiChatCompletionsAdapter,
    OpenAiCompatibleProfile,
)
from app.ai.gateway import AiGateway
from app.ai.live_policy import (
    LIVE_LLM_POLICY,
    LIVE_POLICY_HASH,
    LIVE_POLICY_ID,
    LIVE_POLICY_RAW_SHA256,
)
from app.ai.network_policy import OutboundNetworkPolicy
from app.ai.policy import canonicalize_jcs
from app.ai.policy_loader import ValidatedPolicySnapshot
from app.models.audit import AiCallLog
from app.models.documents import FilePrimaryBusinessObject
from app.models.financial import Contract, Invoice
from app.models.reliability import AsyncJob
from app.repositories.job_runtime import JobRuntimeRepository
from app.schemas.files import FileUploadIntent, IntendedBusinessType
from app.services.ai_call_audit import AiCallAuditService
from app.services.ai_extraction import AiExtractionService
from app.services.audited_llm import AuditedLlmInvoker
from app.services.contract_extraction_executor import ContractExtractionExecutor
from app.services.file_intake import FileIntakeService
from app.services.invoice_extraction_executor import InvoiceExtractionExecutor
from tests.integration.database.test_contract_extraction_management import (
    _clear_contract_subjects,
    _contract_actor,
    _contract_docx,
)
from tests.integration.database.test_contract_extraction_management import (
    _file_executor as _contract_file_executor,
)
from tests.integration.database.test_file_intake_service import (
    ORGANIZATION_ID,
    MemoryQuarantineStorage,
    _clear_subjects,
    _setup,
)
from tests.integration.database.test_file_job_executor import (
    _clear_document_subjects,
    _dispatch_pending,
    _RuntimeStorage,
)
from tests.integration.database.test_invoice_extraction_management import (
    _clear_invoice_subjects,
)
from tests.integration.database.test_invoice_extraction_management import (
    _upload_and_parse as _upload_and_parse_invoice,
)

pytestmark = pytest.mark.integration

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_CONTRACT_FIELDS = (
    "contract_no",
    "name",
    "party_a_name",
    "party_a_tax_no",
    "party_b_name",
    "party_b_tax_no",
    "amount",
    "currency",
    "signed_date",
    "effective_date",
    "expiry_date",
    "payment_method",
    "payment_terms",
)
_INVOICE_FIELDS = (
    "invoice_code",
    "invoice_number",
    "invoice_type",
    "is_red_invoice",
    "invoice_date",
    "buyer_name",
    "buyer_tax_no",
    "seller_name",
    "seller_tax_no",
    "amount_excluding_tax",
    "tax_amount",
    "total_amount",
    "currency",
)


class _StaticByteStream(httpx.SyncByteStream):
    def __init__(self, content: bytes) -> None:
        self._content = content

    def __iter__(self) -> Iterator[bytes]:
        yield self._content


def _model_output(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    messages = body["messages"]
    source = json.loads(messages[1]["content"])
    purpose = source["purpose"]
    blocks = source["blocks"]
    if purpose == "contract_field_extraction":
        field_code = "contract_no"
        value = "SYNTH-CONTRACT-001"
        marker = "合同编号"
        facts: dict[str, object] = {field: None for field in _CONTRACT_FIELDS}
    else:
        assert purpose == "invoice_field_extraction"
        field_code = "invoice_number"
        value = "000001"
        marker = "发票号码"
        facts = {field: None for field in _INVOICE_FIELDS}
    facts[field_code] = value
    block = next(item for item in blocks if marker in item["text"])
    evidence = {
        "block_id": block["block_id"],
        "parse_version_id": source["parse_version_id"],
        "page_no": block["page_no"],
        "quote_text": block["text"],
        "bbox": block["bbox"],
        "confidence": block["confidence"],
    }
    output: dict[str, object] = {
        "facts": facts,
        "field_evidence": [{"field_code": field_code, "evidence": evidence}],
    }
    if purpose == "invoice_field_extraction":
        output["items"] = []
    content = canonicalize_jcs(output).decode("utf-8")
    response_body = json.dumps(
        {
            "model": "MiniMax-M3",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {
                "prompt_tokens": 800,
                "completion_tokens": 100,
                "total_tokens": 900,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        stream=_StaticByteStream(response_body),
    )


def _ai_extraction(
    factory: sessionmaker[Session],
) -> tuple[AiExtractionService, OpenAiChatCompletionsAdapter]:
    registry_bytes = (
        resources.files("app.ai.artifacts.cr011_v1").joinpath("ip-deny-cidrs-v1.json").read_bytes()
    )
    network_policy = OutboundNetworkPolicy(
        endpoint_id=LIVE_LLM_POLICY.endpoint_id,
        network_scope="external_public",
        base_url=LIVE_LLM_POLICY.base_url,
        approved_hostnames=LIVE_LLM_POLICY.approved_hostnames,
        allowed_cidrs=(),
        billing_mode="external_usd",
        address_policy_version="ip-deny-cidrs-v1",
        registry_sha256=("628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"),
    )
    adapter = OpenAiChatCompletionsAdapter(
        OpenAiCompatibleProfile(
            profile_type="chat",
            base_url=LIVE_LLM_POLICY.base_url,
            model_id=LIVE_LLM_POLICY.model_id,
            allowed_response_model_ids=LIVE_LLM_POLICY.allowed_response_model_ids,
            api_key=SecretStr("synthetic-test-key"),
            network_policy=network_policy,
            registry_bytes=registry_bytes,
            use_max_completion_tokens=True,
            thinking_mode="disabled",
            service_tier="standard",
        ),
        transport=httpx.MockTransport(_model_output),
        resolver=lambda _hostname, _port: ("8.8.8.8",),
        peer_address_reader=lambda _response: "8.8.8.8",
    )
    gateway = AiGateway(
        llm_adapters={OPENAI_CHAT_COMPLETIONS_ADAPTER_ID: adapter},
        embedding_adapters={},
    )
    invoker = AuditedLlmInvoker(
        session_factory=factory,
        gateway=gateway,
        adapter=adapter,
        policy_snapshot=ValidatedPolicySnapshot(
            policy_version=2,
            policy_hash=LIVE_POLICY_HASH,
            raw_sha256=LIVE_POLICY_RAW_SHA256,
            provider_calls_enabled=True,
            runtime_profile_id=LIVE_POLICY_ID,
        ),
        llm_policy=LIVE_LLM_POLICY,
    )
    return AiExtractionService(invoker, LIVE_LLM_POLICY), adapter


def _upload_and_parse_contract(
    factory: sessionmaker[Session],
    intake: FileIntakeService,
    quarantine: MemoryQuarantineStorage,
) -> tuple[UUID, UUID]:
    uploaded = intake.upload(
        _contract_actor(),
        FileUploadIntent(intended_business_type=IntendedBusinessType.CONTRACT),
        file_name="live-ai-contract.docx",
        declared_mime=_DOCX_MIME,
        stream=io.BytesIO(_contract_docx()),
        idempotency_key="live-ai-contract-upload-001",
        trace_id=uuid4(),
    )
    file_event = _dispatch_pending(factory, uploaded.data.job_id)
    parsed = _contract_file_executor(
        factory,
        _RuntimeStorage(quarantine),
    ).execute(
        job_id=uploaded.data.job_id,
        event_id=file_event.event_id,
        event_schema_version=file_event.event_version,
        worker_id="live-ai-contract-file-worker",
    )
    assert parsed.outcome == "succeeded"
    with factory() as session:
        extraction_job_id = session.scalars(
            select(AsyncJob.id).where(
                AsyncJob.resource_id == uploaded.data.file_id,
                AsyncJob.job_type == "contract_extract",
            )
        ).one()
    return uploaded.data.file_id, extraction_job_id


def _clear_live_ai_subjects(engine: Engine, file_ids: tuple[UUID, ...]) -> None:
    with engine.begin() as connection:
        for table_name in ("outbox_events", "ai_call_logs"):
            connection.execute(text(f"ALTER TABLE {table_name} DISABLE TRIGGER USER"))
        try:
            connection.execute(
                text("DELETE FROM outbox_events"),
            )
            connection.execute(
                text("DELETE FROM ai_call_logs WHERE organization_id=:organization_id"),
                {"organization_id": ORGANIZATION_ID},
            )
        finally:
            for table_name in ("ai_call_logs", "outbox_events"):
                connection.execute(text(f"ALTER TABLE {table_name} ENABLE TRIGGER USER"))
    for file_id in file_ids:
        _clear_document_subjects(engine, file_id)
    _clear_subjects(engine)


def test_mock_provider_audit_and_contract_invoice_facts_commit_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    adapter: OpenAiChatCompletionsAdapter | None = None
    file_ids: list[UUID] = []
    try:
        ai_extraction, adapter = _ai_extraction(factory)
        contract_file_id, contract_job_id = _upload_and_parse_contract(
            factory,
            intake,
            quarantine,
        )
        file_ids.append(contract_file_id)
        contract_event = _dispatch_pending(factory, contract_job_id)
        contract_result = ContractExtractionExecutor(factory, ai_extraction).execute(
            job_id=contract_job_id,
            event_id=contract_event.event_id,
            event_schema_version=contract_event.event_version,
            worker_id="live-ai-contract-extraction-worker",
        )
        assert contract_result.outcome == "succeeded"

        invoice_file_id, invoice_job_id, _ = _upload_and_parse_invoice(
            factory,
            intake,
            quarantine,
        )
        file_ids.append(invoice_file_id)
        invoice_event = _dispatch_pending(factory, invoice_job_id)
        invoice_result = InvoiceExtractionExecutor(factory, ai_extraction).execute(
            job_id=invoice_job_id,
            event_id=invoice_event.event_id,
            event_schema_version=invoice_event.event_version,
            worker_id="live-ai-invoice-extraction-worker",
        )
        assert invoice_result.outcome == "succeeded"

        audit_service = AiCallAuditService(factory)
        for _ in range(4):
            audit_service.project_once()

        with factory() as session:
            logs = tuple(
                session.scalars(
                    select(AiCallLog)
                    .where(AiCallLog.job_id.in_((contract_job_id, invoice_job_id)))
                    .order_by(AiCallLog.call_type)
                ).all()
            )
            assert [(log.call_type, log.status, log.event_sequence) for log in logs] == [
                ("contract_field_extraction", "succeeded", 2),
                ("invoice_field_extraction", "succeeded", 2),
            ]
            assert all(log.output_hash is not None for log in logs)
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
            assert contract is not None
            assert contract.contract_no == "SYNTH-CONTRACT-001"
            assert invoice is not None
            assert invoice.invoice_number == "000001"
            assert invoice.currency is None
    finally:
        if adapter is not None:
            adapter.close()
        if file_ids:
            if len(file_ids) > 1:
                _clear_invoice_subjects(engine, file_ids[1])
            _clear_contract_subjects(engine, file_ids[0])
            _clear_live_ai_subjects(engine, tuple(file_ids))
        engine.dispose()


def test_business_transaction_rollback_keeps_successful_model_output_unadopted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory, intake, quarantine = _setup(monkeypatch)
    adapter: OpenAiChatCompletionsAdapter | None = None
    file_id: UUID | None = None
    try:
        ai_extraction, adapter = _ai_extraction(factory)
        file_id, job_id = _upload_and_parse_contract(factory, intake, quarantine)
        event = _dispatch_pending(factory, job_id)

        def fail_after_adoption(*_args: object, **_kwargs: object) -> bool:
            raise RuntimeError("synthetic business transaction failure")

        monkeypatch.setattr(JobRuntimeRepository, "finish_job", fail_after_adoption)
        with pytest.raises(RuntimeError, match="synthetic business transaction failure"):
            ContractExtractionExecutor(factory, ai_extraction).execute(
                job_id=job_id,
                event_id=event.event_id,
                event_schema_version=event.event_version,
                worker_id="live-ai-rollback-worker",
            )

        AiCallAuditService(factory).project_once()
        with factory() as session:
            log = session.scalars(select(AiCallLog).where(AiCallLog.job_id == job_id)).one()
            assert (log.status, log.event_sequence, log.completed_at) == (
                "pending",
                1,
                None,
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(FilePrimaryBusinessObject)
                    .where(FilePrimaryBusinessObject.file_id == file_id)
                )
                == 0
            )
            assert session.scalar(select(func.count()).select_from(Contract)) == 0
    finally:
        if adapter is not None:
            adapter.close()
        if file_id is not None:
            _clear_contract_subjects(engine, file_id)
            _clear_live_ai_subjects(engine, (file_id,))
        engine.dispose()
