"""发票事实修正、人工确认和重复处置用例。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID, uuid4

from pydantic import BaseModel, JsonValue
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.models.corrections import UserCorrection
from app.models.financial import Invoice, InvoiceItem
from app.repositories.audit_runtime import AuditRuntimeRepository
from app.repositories.financial_read import FinancialReadRepository
from app.repositories.invoice_write import InvoiceWriteRepository
from app.repositories.operation_log import OperationLogRepository
from app.repositories.user_write import IdempotencyClaim
from app.schemas.invoices import (
    InvoiceCorrectionHistoryData,
    InvoiceCorrectionHistoryItemData,
    InvoiceDecisionRequest,
    InvoiceDuplicateCheckRequest,
    InvoiceDuplicateDecisionRequest,
    InvoiceEvidenceData,
    InvoiceEvidenceResponseData,
    InvoiceFactsReplaceRequest,
    InvoiceFactsWriteData,
    InvoiceItemWriteData,
    InvoiceMutationData,
)
from app.services.auth import AuthenticatedActor
from app.services.invoice_facts import (
    field_evidence_json,
    invoice_critical_fact_hash,
    invoice_snapshot,
    item_evidence_json,
    parse_field_evidence,
    parse_item_evidence,
)
from app.services.invoice_query import _project_invoice

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_IDEMPOTENCY_TTL = timedelta(hours=24)
_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_REQUIRED_CONFIRM_FIELDS = (
    "invoice_code",
    "invoice_number",
    "invoice_date",
    "buyer_tax_no",
    "seller_tax_no",
    "amount_excluding_tax",
    "tax_amount",
    "total_amount",
    "currency",
)


@dataclass(frozen=True, slots=True)
class InvoiceMutationResult:
    data: InvoiceMutationData
    replayed: bool


def _not_found() -> AppError:
    return AppError(status_code=404, code="RESOURCE_NOT_FOUND", message="目标资源不存在或不可见")


def _conflict(code: str, message: str) -> AppError:
    return AppError(status_code=409, code=code, message=message)


def _validate_idempotency_key(value: str) -> None:
    if type(value) is not str or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": "header.Idempotency-Key", "reason": "invalid"}],
        )


def _request_hash(method: str, path: str, body: dict[str, object]) -> str:
    encoded = json.dumps(
        {"method": method, "path": path, "body": body},
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _actor_role(actor: AuthenticatedActor) -> str:
    if "finance_reviewer" in actor.roles:
        return "finance_reviewer"
    raise RuntimeError("invoices.manage actor lacks finance_reviewer role")


def _bounded_decimal(
    value: str | None,
    *,
    scale: int,
    integer_digits: int,
    field: str,
) -> Decimal | None:
    if value is None:
        return None
    if _DECIMAL_PATTERN.fullmatch(value) is None:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": field, "reason": "invalid_decimal"}],
        )
    try:
        number = Decimal(value)
    except InvalidOperation:
        number = Decimal("NaN")
    exponent = cast(int, number.as_tuple().exponent) if number.is_finite() else 0
    digits_after = max(-exponent, 0) if number.is_finite() else scale + 1
    digits_before = max(number.adjusted() + 1, 1) if number.is_finite() and number else 1
    if not number.is_finite() or digits_after > scale or digits_before > integer_digits:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": field, "reason": "decimal_out_of_range"}],
        )
    return number


def _item_models(
    invoice_id: UUID,
    values: tuple[InvoiceItemWriteData, ...],
) -> tuple[InvoiceItem, ...]:
    models: list[InvoiceItem] = []
    for index, item in enumerate(values):
        prefix = f"body.items.{index}"
        tax_rate = _bounded_decimal(
            item.tax_rate,
            scale=6,
            integer_digits=1,
            field=f"{prefix}.tax_rate",
        )
        if tax_rate is not None and not Decimal(0) <= tax_rate <= Decimal(1):
            raise AppError(
                status_code=422,
                code="VALIDATION_ERROR",
                message="请求参数不符合约束",
                details=[{"field": f"{prefix}.tax_rate", "reason": "out_of_range"}],
            )
        models.append(
            InvoiceItem(
                id=uuid4(),
                invoice_id=invoice_id,
                line_no=item.line_no,
                item_name=item.item_name,
                specification=item.specification,
                unit=item.unit,
                quantity=_bounded_decimal(
                    item.quantity,
                    scale=6,
                    integer_digits=12,
                    field=f"{prefix}.quantity",
                ),
                unit_price=_bounded_decimal(
                    item.unit_price,
                    scale=6,
                    integer_digits=12,
                    field=f"{prefix}.unit_price",
                ),
                amount_excluding_tax=_bounded_decimal(
                    item.amount_excluding_tax,
                    scale=2,
                    integer_digits=16,
                    field=f"{prefix}.amount_excluding_tax",
                ),
                tax_rate=tax_rate,
                tax_amount=_bounded_decimal(
                    item.tax_amount,
                    scale=2,
                    integer_digits=16,
                    field=f"{prefix}.tax_amount",
                ),
                total_amount=_bounded_decimal(
                    item.total_amount,
                    scale=2,
                    integer_digits=16,
                    field=f"{prefix}.total_amount",
                ),
                evidence_json=item_evidence_json(item.evidence),
                row_version=1,
            )
        )
    return tuple(models)


def _all_evidence(payload: InvoiceFactsReplaceRequest) -> tuple[InvoiceEvidenceData, ...]:
    return tuple(item.evidence for item in payload.field_evidence) + tuple(
        evidence for item in payload.items for evidence in item.evidence
    )


class InvoiceManagementService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_evidence(
        self,
        organization_id: UUID,
        invoice_id: UUID,
    ) -> InvoiceEvidenceResponseData:
        with self._session_factory() as session:
            repository = InvoiceWriteRepository(session)
            invoice = repository.lock_invoice(organization_id, invoice_id)
            if invoice is None:
                raise _not_found()
            binding = repository.lock_binding(invoice.id)
            if binding is None:
                raise _conflict("INVOICE_SOURCE_NOT_BOUND", "发票没有可验证的来源文件")
            items = repository.lock_items(invoice.id)
            fields = parse_field_evidence(invoice.field_evidence_json)
            item_evidence = {
                str(item.line_no): parse_item_evidence(item.evidence_json) for item in items
            }
            evidence = tuple(item.evidence for item in fields) + tuple(
                value for values in item_evidence.values() for value in values
            )
            if not repository.validate_evidence(
                organization_id,
                binding.file_id,
                evidence,
                lock=False,
            ):
                raise _conflict("EVIDENCE_SCOPE_CONFLICT", "发票证据链不再有效")
            return InvoiceEvidenceResponseData(
                invoice_id=invoice.id,
                row_version=str(invoice.row_version),
                field_evidence=fields,
                item_evidence=item_evidence,
            )

    def get_history(
        self,
        organization_id: UUID,
        invoice_id: UUID,
    ) -> InvoiceCorrectionHistoryData:
        with self._session_factory() as session:
            rows = InvoiceWriteRepository(session).correction_history(
                organization_id,
                invoice_id,
            )
            if rows is None:
                raise _not_found()
            return InvoiceCorrectionHistoryData(
                invoice_id=invoice_id,
                items=tuple(
                    InvoiceCorrectionHistoryItemData(
                        id=row.id,
                        field_path=row.field_path,
                        before_value=cast(
                            dict[str, JsonValue] | None,
                            row.before_value_json,
                        ),
                        after_value=cast(
                            dict[str, JsonValue] | None,
                            row.after_value_json,
                        ),
                        reason=row.reason,
                        actor_id=row.actor_id,
                        actor_role_code=row.actor_role_code,
                        created_at=row.created_at,
                        trace_id=row.trace_id,
                    )
                    for row in rows
                ),
            )

    def replace_facts(
        self,
        actor: AuthenticatedActor,
        invoice_id: UUID,
        payload: InvoiceFactsReplaceRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> InvoiceMutationResult:
        path = f"/api/v1/invoices/{invoice_id}/facts"
        claim_args = self._claim_args("PUT", path, payload, idempotency_key)
        with self._session_factory.begin() as session:
            repository, claim, now = self._claim(session, actor, *claim_args)
            replay = self._replay(claim)
            if replay is not None:
                return replay
            invoice = self._lock_mutable(repository, actor, invoice_id, payload.row_version)
            if invoice.status != "draft" or invoice.confirmation_status not in {
                "unconfirmed",
                "rejected",
            }:
                raise _conflict("INVOICE_STATE_CONFLICT", "当前发票状态不可修正")
            binding = repository.lock_binding(invoice.id)
            if binding is None:
                raise _conflict("INVOICE_SOURCE_NOT_BOUND", "发票没有可验证的来源文件")
            evidence = _all_evidence(payload)
            if not repository.validate_evidence(actor.organization_id, binding.file_id, evidence):
                raise _conflict("EVIDENCE_SCOPE_CONFLICT", "提交的字段证据不可验证")
            old_items = repository.lock_items(invoice.id)
            before = invoice_snapshot(invoice, old_items)
            new_items = _item_models(invoice.id, payload.items)
            self._apply_facts(invoice, payload.facts)
            invoice.confirmation_status = "unconfirmed"
            invoice.status = "draft"
            invoice.confirmed_by = None
            invoice.confirmed_at = None
            invoice.field_evidence_json = field_evidence_json(payload.field_evidence)
            invoice.critical_fact_hash = invoice_critical_fact_hash(payload.facts, payload.items)
            invoice.updated_by = actor.user_id
            invoice.updated_at = now
            invoice.row_version += 1
            repository.replace_items(invoice.id, new_items)
            repository.flush()
            invoice.duplicate_status = self._derived_duplicate_status(repository, invoice)
            after = invoice_snapshot(invoice, new_items)
            if before == after:
                raise _conflict("RESOURCE_STATE_UNCHANGED", "发票事实未发生变化")
            repository.flush()
            outdated_ids = AuditRuntimeRepository(session).outdate_current_executions_for_invoice(
                actor.organization_id,
                invoice.id,
                actor_id=actor.user_id,
                now=now,
            )
            self._append_correction(
                repository,
                actor,
                invoice,
                field_path="facts",
                before=before,
                after=after,
                reason=payload.reason,
                now=now,
                trace_id=trace_id,
                caused_outdated=bool(outdated_ids),
            )
            repository.flush()
            data = self._project(session, actor.organization_id, invoice.id, None)
            self._append_log(
                session,
                actor,
                invoice,
                "invoices.facts_replaced",
                trace_id,
                {
                    "field_count": len(payload.field_evidence),
                    "item_count": len(new_items),
                    "duplicate_status": invoice.duplicate_status,
                    "row_version": str(invoice.row_version),
                },
            )
            repository.complete_idempotency(
                claim,
                response_body=data.model_dump(mode="json"),
                resource_id=invoice.id,
            )
            return InvoiceMutationResult(data, False)

    def decide(
        self,
        actor: AuthenticatedActor,
        invoice_id: UUID,
        payload: InvoiceDecisionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> InvoiceMutationResult:
        path = f"/api/v1/invoices/{invoice_id}/decision"
        claim_args = self._claim_args("POST", path, payload, idempotency_key)
        with self._session_factory.begin() as session:
            repository, claim, now = self._claim(session, actor, *claim_args)
            replay = self._replay(claim)
            if replay is not None:
                return replay
            invoice = self._lock_mutable(repository, actor, invoice_id, payload.row_version)
            if invoice.status != "draft" or invoice.confirmation_status != "unconfirmed":
                raise _conflict("INVOICE_STATE_CONFLICT", "当前发票状态不可决定")
            items = repository.lock_items(invoice.id)
            before = invoice_snapshot(invoice, items)
            if payload.decision == "confirmed":
                fields = parse_field_evidence(invoice.field_evidence_json)
                evidence_codes = {item.field_code for item in fields}
                missing = [
                    field
                    for field in _REQUIRED_CONFIRM_FIELDS
                    if getattr(invoice, field) is None or field not in evidence_codes
                ]
                if missing:
                    raise _conflict("INVOICE_CONFIRMATION_INCOMPLETE", "确认要求核心字段及证据完整")
                assert invoice.amount_excluding_tax is not None
                assert invoice.tax_amount is not None
                assert invoice.total_amount is not None
                if invoice.amount_excluding_tax + invoice.tax_amount != invoice.total_amount:
                    raise _conflict("INVOICE_AMOUNT_MISMATCH", "发票金额、税额与总额不一致")
                binding = repository.lock_binding(invoice.id)
                if binding is None or not repository.validate_evidence(
                    actor.organization_id,
                    binding.file_id,
                    tuple(item.evidence for item in fields),
                ):
                    raise _conflict("EVIDENCE_SCOPE_CONFLICT", "发票证据链不再有效")
            invoice.confirmation_status = payload.decision
            invoice.status = "confirmed" if payload.decision == "confirmed" else "draft"
            invoice.confirmed_by = actor.user_id
            invoice.confirmed_at = now
            invoice.updated_by = actor.user_id
            invoice.updated_at = now
            invoice.row_version += 1
            after = invoice_snapshot(invoice, items)
            repository.flush()
            outdated_ids = AuditRuntimeRepository(session).outdate_current_executions_for_invoice(
                actor.organization_id,
                invoice.id,
                actor_id=actor.user_id,
                now=now,
            )
            self._append_correction(
                repository,
                actor,
                invoice,
                field_path="decision",
                before=before,
                after=after,
                reason=payload.reason,
                now=now,
                trace_id=trace_id,
                caused_outdated=bool(outdated_ids),
            )
            repository.flush()
            data = self._project(session, actor.organization_id, invoice.id, None)
            self._append_log(
                session,
                actor,
                invoice,
                f"invoices.{payload.decision}",
                trace_id,
                {
                    "confirmation_status": payload.decision,
                    "row_version": str(invoice.row_version),
                },
            )
            repository.complete_idempotency(
                claim,
                response_body=data.model_dump(mode="json"),
                resource_id=invoice.id,
            )
            return InvoiceMutationResult(data, False)

    def check_duplicate(
        self,
        actor: AuthenticatedActor,
        invoice_id: UUID,
        payload: InvoiceDuplicateCheckRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> InvoiceMutationResult:
        path = f"/api/v1/invoices/{invoice_id}/duplicate-check"
        claim_args = self._claim_args("POST", path, payload, idempotency_key)
        with self._session_factory.begin() as session:
            repository, claim, now = self._claim(session, actor, *claim_args)
            replay = self._replay(claim)
            if replay is not None:
                return replay
            invoice = self._lock_mutable(repository, actor, invoice_id, payload.row_version)
            if invoice.duplicate_status in {"confirmed_duplicate", "exception_approved"}:
                raise _conflict("INVOICE_DUPLICATE_STATE_CONFLICT", "当前重复状态不可自动重检")
            old_status = invoice.duplicate_status
            candidate_ids = repository.exact_duplicate_ids(invoice, lock=True)
            new_status = (
                "not_checked"
                if not invoice.invoice_code
                or not invoice.invoice_number
                or not invoice.seller_tax_no
                else "suspected"
                if candidate_ids
                else "unique"
            )
            if new_status == old_status:
                raise _conflict("RESOURCE_STATE_UNCHANGED", "重复检测状态未发生变化")
            invoice.duplicate_status = new_status
            invoice.updated_by = actor.user_id
            invoice.updated_at = now
            invoice.row_version += 1
            repository.flush()
            outdated_ids = AuditRuntimeRepository(session).outdate_current_executions_for_invoice(
                actor.organization_id,
                invoice.id,
                actor_id=actor.user_id,
                now=now,
            )
            self._append_correction(
                repository,
                actor,
                invoice,
                field_path="duplicate_status",
                before={"duplicate_status": old_status},
                after={"duplicate_status": new_status},
                reason=payload.reason,
                now=now,
                trace_id=trace_id,
                caused_outdated=bool(outdated_ids),
            )
            repository.flush()
            candidate_id = candidate_ids[0] if candidate_ids else None
            data = self._project(session, actor.organization_id, invoice.id, candidate_id)
            self._append_log(
                session,
                actor,
                invoice,
                "invoices.duplicate_checked",
                trace_id,
                {"duplicate_status": new_status, "row_version": str(invoice.row_version)},
            )
            repository.complete_idempotency(
                claim,
                response_body=data.model_dump(mode="json"),
                resource_id=invoice.id,
            )
            return InvoiceMutationResult(data, False)

    def decide_duplicate(
        self,
        actor: AuthenticatedActor,
        invoice_id: UUID,
        payload: InvoiceDuplicateDecisionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> InvoiceMutationResult:
        path = f"/api/v1/invoices/{invoice_id}/duplicate-decision"
        claim_args = self._claim_args("POST", path, payload, idempotency_key)
        with self._session_factory.begin() as session:
            repository, claim, now = self._claim(session, actor, *claim_args)
            replay = self._replay(claim)
            if replay is not None:
                return replay
            invoice = self._lock_mutable(repository, actor, invoice_id, payload.row_version)
            candidate = repository.lock_exact_duplicate(invoice, payload.candidate_id)
            if candidate is None:
                raise _not_found()
            if invoice.duplicate_status == payload.decision:
                raise _conflict("RESOURCE_STATE_UNCHANGED", "重复处置状态未发生变化")
            old_status = invoice.duplicate_status
            invoice.duplicate_status = payload.decision
            invoice.updated_by = actor.user_id
            invoice.updated_at = now
            invoice.row_version += 1
            repository.flush()
            outdated_ids = AuditRuntimeRepository(session).outdate_current_executions_for_invoice(
                actor.organization_id,
                invoice.id,
                actor_id=actor.user_id,
                now=now,
            )
            self._append_correction(
                repository,
                actor,
                invoice,
                field_path="duplicate_status",
                before={"candidate_id": str(candidate.id), "duplicate_status": old_status},
                after={
                    "candidate_id": str(candidate.id),
                    "duplicate_status": payload.decision,
                },
                reason=payload.reason,
                now=now,
                trace_id=trace_id,
                caused_outdated=bool(outdated_ids),
            )
            repository.flush()
            data = self._project(session, actor.organization_id, invoice.id, candidate.id)
            action = (
                "invoices.duplicate_confirmed"
                if payload.decision == "confirmed_duplicate"
                else "invoices.duplicate_exception_approved"
            )
            self._append_log(
                session,
                actor,
                invoice,
                action,
                trace_id,
                {
                    "duplicate_status": payload.decision,
                    "row_version": str(invoice.row_version),
                },
            )
            repository.complete_idempotency(
                claim,
                response_body=data.model_dump(mode="json"),
                resource_id=invoice.id,
            )
            return InvoiceMutationResult(data, False)

    @staticmethod
    def _claim_args(
        method: str,
        path: str,
        payload: BaseModel,
        key: str,
    ) -> tuple[str, str, str, str]:
        _validate_idempotency_key(key)
        body = payload.model_dump(mode="json")
        return key, method, path, _request_hash(method, path, body)

    @staticmethod
    def _claim(
        session: Session,
        actor: AuthenticatedActor,
        key: str,
        method: str,
        path: str,
        digest: str,
    ) -> tuple[InvoiceWriteRepository, IdempotencyClaim, datetime]:
        repository = InvoiceWriteRepository(session)
        repository.acquire_api_locks(actor.organization_id, actor.user_id, key)
        if repository.lock_active_organization(actor.organization_id) is None:
            raise _not_found()
        now = repository.database_now()
        claim = repository.claim_idempotency(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            idempotency_key=key,
            request_method=method,
            request_path=path,
            request_hash=digest,
            now=now,
            expires_at=now + _IDEMPOTENCY_TTL,
        )
        if claim.conflict:
            raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
        return repository, claim, now

    @staticmethod
    def _replay(claim: IdempotencyClaim) -> InvoiceMutationResult | None:
        if not claim.is_replay:
            return None
        if claim.replay_status != 200 or claim.replay_body is None:
            raise RuntimeError("invoice replay does not match the contract")
        encoded = json.dumps(claim.replay_body, separators=(",", ":"), sort_keys=True)
        return InvoiceMutationResult(InvoiceMutationData.model_validate_json(encoded), True)

    @staticmethod
    def _lock_mutable(
        repository: InvoiceWriteRepository,
        actor: AuthenticatedActor,
        invoice_id: UUID,
        row_version: str,
    ) -> Invoice:
        invoice = repository.lock_invoice(actor.organization_id, invoice_id)
        if invoice is None:
            raise _not_found()
        if invoice.row_version != int(row_version):
            raise _conflict("ROW_VERSION_CONFLICT", "资源版本已变化")
        if invoice.status in {"voided", "archived"}:
            raise _conflict("INVOICE_STATE_CONFLICT", "当前发票状态不可写入")
        return invoice

    @staticmethod
    def _apply_facts(invoice: Invoice, facts: InvoiceFactsWriteData) -> None:
        invoice.invoice_code = facts.invoice_code
        invoice.invoice_number = facts.invoice_number
        invoice.invoice_type = facts.invoice_type
        invoice.is_red_invoice = facts.is_red_invoice
        invoice.invoice_date = facts.invoice_date
        invoice.buyer_name = facts.buyer_name
        invoice.buyer_tax_no = facts.buyer_tax_no
        invoice.seller_name = facts.seller_name
        invoice.seller_tax_no = facts.seller_tax_no
        invoice.amount_excluding_tax = _bounded_decimal(
            facts.amount_excluding_tax,
            scale=2,
            integer_digits=16,
            field="body.facts.amount_excluding_tax",
        )
        invoice.tax_amount = _bounded_decimal(
            facts.tax_amount,
            scale=2,
            integer_digits=16,
            field="body.facts.tax_amount",
        )
        invoice.total_amount = _bounded_decimal(
            facts.total_amount,
            scale=2,
            integer_digits=16,
            field="body.facts.total_amount",
        )
        invoice.currency = facts.currency

    @staticmethod
    def _derived_duplicate_status(
        repository: InvoiceWriteRepository,
        invoice: Invoice,
    ) -> str:
        if not invoice.invoice_code or not invoice.invoice_number or not invoice.seller_tax_no:
            return "not_checked"
        return "suspected" if repository.exact_duplicate_ids(invoice, lock=True) else "unique"

    @staticmethod
    def _append_correction(
        repository: InvoiceWriteRepository,
        actor: AuthenticatedActor,
        invoice: Invoice,
        *,
        field_path: str,
        before: dict[str, object],
        after: dict[str, object],
        reason: str,
        now: datetime,
        trace_id: UUID,
        caused_outdated: bool,
    ) -> None:
        repository.add(
            UserCorrection(
                id=uuid4(),
                organization_id=actor.organization_id,
                correction_type="invoice_field",
                object_type="invoice",
                object_id=invoice.id,
                field_path=field_path,
                before_value_json=before,
                after_value_json=after,
                reason=reason,
                actor_id=actor.user_id,
                actor_role_code=_actor_role(actor),
                related_execution_id=None,
                caused_outdated=caused_outdated,
                created_at=now,
                trace_id=trace_id,
            )
        )

    @staticmethod
    def _project(
        session: Session,
        organization_id: UUID,
        invoice_id: UUID,
        candidate_id: UUID | None,
    ) -> InvoiceMutationData:
        view = FinancialReadRepository(session).read_invoice(organization_id, invoice_id)
        if view is None:
            raise RuntimeError("persisted invoice is not readable")
        return InvoiceMutationData(
            invoice=_project_invoice(view),
            duplicate_candidate_id=candidate_id,
        )

    @staticmethod
    def _append_log(
        session: Session,
        actor: AuthenticatedActor,
        invoice: Invoice,
        action_code: str,
        trace_id: UUID,
        summary: dict[str, object],
    ) -> None:
        OperationLogRepository(session).append(
            organization_id=actor.organization_id,
            actor_kind="user",
            actor_id=actor.user_id,
            action_code=action_code,
            outcome="succeeded",
            resource_type="invoice",
            resource_id=invoice.id,
            trace_id=trace_id,
            change_summary=summary,
        )


__all__ = ["InvoiceManagementService", "InvoiceMutationResult"]
