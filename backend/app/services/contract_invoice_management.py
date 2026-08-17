"""可解释合同候选、建议、主合同替换/取消和历史读取用例。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.models.corrections import UserCorrection
from app.models.financial import ContractInvoice, Invoice
from app.repositories.audit_runtime import AuditRuntimeRepository
from app.repositories.contract_invoice_write import ContractInvoiceWriteRepository
from app.repositories.financial_read import ContractReadView, FinancialReadRepository
from app.repositories.operation_log import OperationLogRepository
from app.repositories.user_write import IdempotencyClaim
from app.rules.contract_invoice_matching import (
    ContractInvoiceCandidate,
    ContractInvoiceMatchReason,
    ContractMatchFacts,
    InvoiceMatchFacts,
    derive_contract_invoice_candidates,
)
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import ContractListItemData, ContractStatus
from app.schemas.invoices import (
    ContractInvoiceCandidateData,
    ContractInvoiceCandidateListData,
    ContractInvoiceHistoryData,
    ContractInvoiceLinkData,
    ContractInvoiceLinkStatus,
    ContractInvoiceMatchReasonData,
    ContractInvoiceMatchReasonsData,
    ContractInvoiceMutationData,
    ContractLinkSuggestionRequest,
    PrimaryContractCancelRequest,
    PrimaryContractSetRequest,
)
from app.services.auth import AuthenticatedActor
from app.services.contract_query import project_contract_list_item
from app.services.effective_contract_query import project_effective_contract

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_IDEMPOTENCY_TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class ContractInvoiceMutationResult:
    data: ContractInvoiceMutationData
    replayed: bool


@dataclass(frozen=True, slots=True)
class _ProjectedCandidate:
    candidate: ContractInvoiceCandidate
    contract: ContractListItemData


def _not_found() -> AppError:
    return AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )


def _conflict(code: str, message: str) -> AppError:
    return AppError(status_code=409, code=code, message=message)


def _validate_key(value: str) -> None:
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
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _reason_data(reason: ContractInvoiceMatchReason) -> ContractInvoiceMatchReasonData:
    return ContractInvoiceMatchReasonData(
        status=reason.status.value,
        code=reason.code.value,
    )


def _match_reasons(candidate: ContractInvoiceCandidate) -> ContractInvoiceMatchReasonsData:
    return ContractInvoiceMatchReasonsData(
        tax_no=_reason_data(candidate.tax_no_reason),
        name=_reason_data(candidate.name_reason),
        date=_reason_data(candidate.date_reason),
    )


def _match_json(candidate: ContractInvoiceCandidate) -> dict[str, object]:
    return _match_reasons(candidate).model_dump(mode="json")


def _link_data(relation: ContractInvoice) -> ContractInvoiceLinkData:
    return ContractInvoiceLinkData(
        id=relation.id,
        contract_id=relation.contract_id,
        status=cast(ContractInvoiceLinkStatus, relation.status),
        match_reasons=ContractInvoiceMatchReasonsData.model_validate(relation.match_reasons_json),
        suggested_at=relation.created_at,
        confirmed_at=relation.confirmed_at,
        cancelled_at=relation.cancelled_at,
        cancel_reason=relation.cancel_reason,
        row_version=str(relation.row_version),
    )


def _relation_snapshot(relation: ContractInvoice | None) -> dict[str, object]:
    if relation is None:
        return {"relation": None}
    return {"relation": _link_data(relation).model_dump(mode="json")}


def _actor_role(actor: AuthenticatedActor) -> str:
    if "finance_reviewer" in actor.roles:
        return "finance_reviewer"
    raise RuntimeError("primary-contract mutation actor lacks finance_reviewer role")


def _candidate_for_contract(
    session: Session,
    organization_id: UUID,
    invoice: Invoice,
    contract_id: UUID,
) -> _ProjectedCandidate | None:
    repository = FinancialReadRepository(session)
    view = repository.read_effective_contract(organization_id, contract_id)
    if (
        view is None
        or view.contract.confirmation_status != "confirmed"
        or view.contract.status == "draft"
    ):
        return None
    if invoice.invoice_date is None:
        contract = view.contract
        contract_facts = ContractMatchFacts(
            contract.id,
            contract.party_b_tax_no,
            contract.party_b_name,
            contract.effective_date,
            contract.expiry_date,
        )
        contract_projection = project_contract_list_item(contract)
    else:
        projected = project_effective_contract(view, invoice.invoice_date)
        values = {field.field_code: field.effective_value for field in projected.fields}
        contract_no = cast(str | None, values["contract_no"])
        name = values["name"]
        party_b_name = cast(str | None, values["party_b_name"])
        amount = cast(str | None, values["amount"])
        currency = cast(str | None, values["currency"])
        effective_date = _optional_date(values["effective_date"], "effective_date")
        expiry_date = _optional_date(values["expiry_date"], "expiry_date")
        if type(name) is not str:
            raise RuntimeError("effective contract name is invalid")
        contract_facts = ContractMatchFacts(
            projected.id,
            cast(str | None, values["party_b_tax_no"]),
            party_b_name,
            effective_date,
            expiry_date,
        )
        contract_projection = ContractListItemData(
            id=projected.id,
            contract_no=contract_no,
            name=name,
            party_b_name=party_b_name,
            amount=amount,
            currency=currency,
            effective_date=effective_date,
            expiry_date=expiry_date,
            confirmation_status=ConfirmationStatus(view.contract.confirmation_status),
            status=ContractStatus(view.contract.status),
        )
    candidate = derive_contract_invoice_candidates(
        InvoiceMatchFacts(
            invoice.id,
            invoice.seller_tax_no,
            invoice.seller_name,
            invoice.invoice_date,
        ),
        (contract_facts,),
    )[0]
    return _ProjectedCandidate(candidate=candidate, contract=contract_projection)


def _optional_date(value: object, field_name: str) -> date | None:
    if value is None:
        return None
    if type(value) is not str:
        raise RuntimeError(f"effective contract {field_name} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise RuntimeError(f"effective contract {field_name} is invalid") from None
    if parsed.isoformat() != value:
        raise RuntimeError(f"effective contract {field_name} is invalid")
    return parsed


def _all_visible_contracts(
    repository: FinancialReadRepository,
    organization_id: UUID,
) -> tuple[ContractReadView, ...]:
    collected: list[ContractReadView] = []
    cursor_date: date | None = None
    cursor_id: UUID | None = None
    while True:
        page, has_more = repository.read_contract_page(
            organization_id,
            100,
            cursor_date,
            cursor_id,
        )
        collected.extend(page)
        if not has_more:
            return tuple(collected)
        if not page:
            raise RuntimeError("contract candidate pagination did not advance")
        cursor_date = page[-1].effective_date
        cursor_id = page[-1].id


class ContractInvoiceManagementService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_candidates(
        self,
        organization_id: UUID,
        invoice_id: UUID,
    ) -> ContractInvoiceCandidateListData:
        with self._session_factory() as session:
            invoice = session.get(Invoice, invoice_id)
            if (
                invoice is None
                or invoice.organization_id != organization_id
                or invoice.deleted_at is not None
            ):
                raise _not_found()
            financial_repository = FinancialReadRepository(session)
            contracts = _all_visible_contracts(financial_repository, organization_id)
            candidates: list[_ProjectedCandidate] = []
            for contract in contracts:
                candidate = _candidate_for_contract(
                    session,
                    organization_id,
                    invoice,
                    contract.id,
                )
                if candidate is None:
                    continue
                candidates.append(candidate)
            candidates.sort(
                key=lambda item: (
                    {"matched": 0, "mismatched": 1, "unavailable": 2}[
                        item.candidate.tax_no_reason.status.value
                    ],
                    {"matched": 0, "mismatched": 1, "unavailable": 2}[
                        item.candidate.name_reason.status.value
                    ],
                    {"matched": 0, "mismatched": 1, "unavailable": 2}[
                        item.candidate.date_reason.status.value
                    ],
                    item.candidate.contract_id.bytes,
                )
            )
            return ContractInvoiceCandidateListData(
                invoice_id=invoice.id,
                invoice_row_version=str(invoice.row_version),
                items=tuple(
                    ContractInvoiceCandidateData(
                        contract=item.contract,
                        match_reasons=_match_reasons(item.candidate),
                    )
                    for item in candidates
                ),
            )

    def get_history(
        self,
        organization_id: UUID,
        invoice_id: UUID,
    ) -> ContractInvoiceHistoryData:
        with self._session_factory() as session:
            invoice = session.get(Invoice, invoice_id)
            if (
                invoice is None
                or invoice.organization_id != organization_id
                or invoice.deleted_at is not None
            ):
                raise _not_found()
            relations = (
                session.query(ContractInvoice)
                .filter(
                    ContractInvoice.invoice_id == invoice_id,
                    ContractInvoice.deleted_at.is_(None),
                )
                .order_by(ContractInvoice.created_at, ContractInvoice.id)
            )
            return ContractInvoiceHistoryData(
                invoice_id=invoice_id,
                items=tuple(_link_data(item) for item in relations),
            )

    def suggest(
        self,
        actor: AuthenticatedActor,
        invoice_id: UUID,
        payload: ContractLinkSuggestionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> ContractInvoiceMutationResult:
        return self._mutate(
            actor,
            invoice_id,
            payload,
            idempotency_key,
            trace_id,
            "POST",
            f"/api/v1/invoices/{invoice_id}/contract-link-suggestions",
            "suggest",
        )

    def set_primary(
        self,
        actor: AuthenticatedActor,
        invoice_id: UUID,
        payload: PrimaryContractSetRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> ContractInvoiceMutationResult:
        return self._mutate(
            actor,
            invoice_id,
            payload,
            idempotency_key,
            trace_id,
            "PUT",
            f"/api/v1/invoices/{invoice_id}/primary-contract",
            "set_primary",
        )

    def cancel_primary(
        self,
        actor: AuthenticatedActor,
        invoice_id: UUID,
        payload: PrimaryContractCancelRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> ContractInvoiceMutationResult:
        return self._mutate(
            actor,
            invoice_id,
            payload,
            idempotency_key,
            trace_id,
            "POST",
            f"/api/v1/invoices/{invoice_id}/primary-contract/cancel",
            "cancel_primary",
        )

    def _mutate(
        self,
        actor: AuthenticatedActor,
        invoice_id: UUID,
        payload: ContractLinkSuggestionRequest
        | PrimaryContractSetRequest
        | PrimaryContractCancelRequest,
        idempotency_key: str,
        trace_id: UUID,
        method: str,
        path: str,
        action: str,
    ) -> ContractInvoiceMutationResult:
        _validate_key(idempotency_key)
        digest = _request_hash(method, path, payload.model_dump(mode="json"))
        with self._session_factory.begin() as session:
            repository = ContractInvoiceWriteRepository(session)
            claim, now = self._claim(repository, actor, idempotency_key, method, path, digest)
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return self._replay(claim)
            invoice = repository.lock_invoice(actor.organization_id, invoice_id)
            if invoice is None:
                raise _not_found()
            expected_invoice_version = int(payload.invoice_row_version)
            if invoice.row_version != expected_invoice_version:
                raise _conflict("ROW_VERSION_CONFLICT", "发票版本已变化")
            relations = repository.lock_relations(invoice_id)
            previous_primary = next(
                (item for item in relations if item.status == "confirmed_primary"),
                None,
            )
            correction_before_snapshot: dict[str, object]
            if action == "suggest":
                assert isinstance(payload, ContractLinkSuggestionRequest)
                relation = self._suggest(
                    repository,
                    session,
                    actor,
                    invoice,
                    relations,
                    payload,
                    now,
                )
                log_action = "contract_invoices.suggested"
                correction_before_snapshot = _relation_snapshot(None)
            elif action == "set_primary":
                assert isinstance(payload, PrimaryContractSetRequest)
                correction_before_snapshot = _relation_snapshot(previous_primary)
                relation = self._set_primary(
                    repository,
                    actor,
                    invoice,
                    relations,
                    previous_primary,
                    payload,
                    now,
                )
                log_action = (
                    "contract_invoices.primary_replaced"
                    if previous_primary is not None
                    else "contract_invoices.primary_confirmed"
                )
            else:
                assert isinstance(payload, PrimaryContractCancelRequest)
                if previous_primary is None:
                    raise _conflict("PRIMARY_CONTRACT_NOT_SET", "当前发票没有已确认主合同")
                if previous_primary.row_version != int(payload.relation_row_version):
                    raise _conflict("ROW_VERSION_CONFLICT", "关系版本已变化")
                correction_before_snapshot = _relation_snapshot(previous_primary)
                relation = previous_primary
                relation.status = "cancelled"
                relation.cancelled_by = actor.user_id
                relation.cancelled_at = now
                relation.cancel_reason = payload.reason
                relation.row_version += 1
                log_action = "contract_invoices.primary_cancelled"
            invoice.row_version += 1
            invoice.updated_by = actor.user_id
            invoice.updated_at = now
            repository.flush()
            outdated_ids: tuple[UUID, ...] = ()
            if action != "suggest":
                outdated_ids = AuditRuntimeRepository(
                    session
                ).outdate_current_executions_for_invoice(
                    actor.organization_id,
                    invoice.id,
                    actor_id=actor.user_id,
                    now=now,
                )
            if action != "suggest":
                session.add(
                    UserCorrection(
                        id=uuid4(),
                        organization_id=actor.organization_id,
                        correction_type="contract_invoice",
                        object_type="invoice",
                        object_id=invoice.id,
                        field_path="primary_contract",
                        before_value_json=correction_before_snapshot,
                        after_value_json=_relation_snapshot(
                            relation if relation.status != "cancelled" else None
                        ),
                        reason=payload.reason,
                        actor_id=actor.user_id,
                        actor_role_code=_actor_role(actor),
                        related_execution_id=None,
                        caused_outdated=bool(outdated_ids),
                        created_at=now,
                        trace_id=trace_id,
                    )
                )
            data = ContractInvoiceMutationData(
                invoice_id=invoice.id,
                invoice_row_version=str(invoice.row_version),
                relation=_link_data(relation),
                previous_primary_relation_id=(
                    previous_primary.id
                    if previous_primary is not None and previous_primary.id != relation.id
                    else None
                ),
            )
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code=log_action,
                outcome="succeeded",
                resource_type="contract_invoice",
                resource_id=relation.id,
                trace_id=trace_id,
                change_summary={
                    "invoice_row_version": data.invoice_row_version,
                    "relation_row_version": data.relation.row_version,
                    "relation_status": data.relation.status,
                },
            )
            repository.complete_idempotency(
                claim,
                response_body=data.model_dump(mode="json"),
                resource_id=relation.id,
            )
            return ContractInvoiceMutationResult(data, False)

    @staticmethod
    def _suggest(
        repository: ContractInvoiceWriteRepository,
        session: Session,
        actor: AuthenticatedActor,
        invoice: Invoice,
        relations: tuple[ContractInvoice, ...],
        payload: ContractLinkSuggestionRequest,
        now: datetime,
    ) -> ContractInvoice:
        if any(
            item.contract_id == payload.contract_id and item.status != "cancelled"
            for item in relations
        ):
            raise _conflict(
                "CONTRACT_INVOICE_RELATION_EXISTS",
                "该合同发票关系已存在",
            )
        if repository.lock_linkable_contract(actor.organization_id, payload.contract_id) is None:
            raise _not_found()
        candidate = _candidate_for_contract(
            session,
            actor.organization_id,
            invoice,
            payload.contract_id,
        )
        if candidate is None:
            raise _not_found()
        relation = ContractInvoice(
            id=uuid4(),
            contract_id=payload.contract_id,
            invoice_id=invoice.id,
            status="suggested",
            match_reasons_json=_match_json(candidate.candidate),
            suggested_by="user",
            confirmed_by=None,
            confirmed_at=None,
            cancelled_by=None,
            cancelled_at=None,
            cancel_reason=None,
            row_version=1,
            created_at=now,
            created_by=actor.user_id,
            deleted_at=None,
        )
        repository.add(relation)
        repository.flush()
        return relation

    @staticmethod
    def _set_primary(
        repository: ContractInvoiceWriteRepository,
        actor: AuthenticatedActor,
        invoice: Invoice,
        relations: tuple[ContractInvoice, ...],
        previous_primary: ContractInvoice | None,
        payload: PrimaryContractSetRequest,
        now: datetime,
    ) -> ContractInvoice:
        relation = next((item for item in relations if item.id == payload.suggestion_id), None)
        if relation is None or relation.invoice_id != invoice.id:
            raise _not_found()
        if relation.row_version != int(payload.relation_row_version):
            raise _conflict("ROW_VERSION_CONFLICT", "关系版本已变化")
        if relation.status != "suggested":
            raise _conflict("CONTRACT_INVOICE_STATE_CONFLICT", "当前关系不可确认")
        if repository.lock_linkable_contract(actor.organization_id, relation.contract_id) is None:
            raise _not_found()
        if previous_primary is not None:
            previous_primary.status = "cancelled"
            previous_primary.cancelled_by = actor.user_id
            previous_primary.cancelled_at = now
            previous_primary.cancel_reason = payload.reason
            previous_primary.row_version += 1
            # 先释放条件唯一索引中的旧主关系，再确认新关系；事务仍保持原子。
            repository.flush()
        relation.status = "confirmed_primary"
        relation.confirmed_by = actor.user_id
        relation.confirmed_at = now
        relation.row_version += 1
        return relation

    @staticmethod
    def _claim(
        repository: ContractInvoiceWriteRepository,
        actor: AuthenticatedActor,
        key: str,
        method: str,
        path: str,
        digest: str,
    ) -> tuple[IdempotencyClaim, datetime]:
        repository.acquire_locks(actor.organization_id, actor.user_id, key)
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
        return claim, now

    @staticmethod
    def _replay(claim: IdempotencyClaim) -> ContractInvoiceMutationResult:
        if claim.replay_status != 200 or claim.replay_body is None:
            raise RuntimeError("contract invoice replay does not match the contract")
        encoded = json.dumps(claim.replay_body, separators=(",", ":"), sort_keys=True)
        return ContractInvoiceMutationResult(
            ContractInvoiceMutationData.model_validate_json(encoded),
            True,
        )


__all__ = ["ContractInvoiceManagementService", "ContractInvoiceMutationResult"]
