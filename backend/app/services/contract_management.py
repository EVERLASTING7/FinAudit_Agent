"""合同候选事实读取、人工修正与确认用例。"""

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
from app.models.financial import Contract, ContractField
from app.repositories.audit_runtime import AuditRuntimeRepository
from app.repositories.contract_write import ContractWriteRepository
from app.repositories.financial_read import FinancialReadRepository
from app.repositories.operation_log import OperationLogRepository
from app.repositories.user_write import IdempotencyClaim
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import (
    CONTRACT_CORE_FIELD_CODES,
    ContractCorrectionHistoryData,
    ContractCorrectionHistoryItemData,
    ContractDecisionRequest,
    ContractEvidenceData,
    ContractEvidenceResponseData,
    ContractFactsReplaceRequest,
    ContractFactsWriteData,
    ContractFieldCandidateData,
    ContractFieldCode,
    ContractMutationData,
)
from app.services.auth import AuthenticatedActor
from app.services.contract_facts import (
    CONTRACT_FIELD_VALUE_TYPES,
    contract_critical_fact_hash,
    contract_facts_from_model,
    contract_snapshot,
    fact_json_value,
)
from app.services.contract_query import _project_detail

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_IDEMPOTENCY_TTL = timedelta(hours=24)
_DECIMAL_PATTERN = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d+)?$")
_REQUIRED_CONFIRM_FIELDS = (
    "contract_no",
    "name",
    "party_a_name",
    "party_a_tax_no",
    "party_b_name",
    "party_b_tax_no",
    "amount",
    "currency",
    "effective_date",
)


@dataclass(frozen=True, slots=True)
class ContractMutationResult:
    data: ContractMutationData
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
    if "contract_admin" in actor.roles:
        return "contract_admin"
    raise RuntimeError("contracts.manage actor lacks contract_admin role")


def _bounded_amount(value: str | None) -> Decimal | None:
    if value is None:
        return None
    if _DECIMAL_PATTERN.fullmatch(value) is None:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": "body.facts.amount", "reason": "invalid_decimal"}],
        )
    try:
        number = Decimal(value)
    except InvalidOperation:
        number = Decimal("NaN")
    exponent = cast(int, number.as_tuple().exponent) if number.is_finite() else 0
    digits_after = max(-exponent, 0) if number.is_finite() else 3
    digits_before = max(number.adjusted() + 1, 1) if number.is_finite() and number else 1
    if not number.is_finite() or number < 0 or digits_after > 2 or digits_before > 16:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数不符合约束",
            details=[{"field": "body.facts.amount", "reason": "decimal_out_of_range"}],
        )
    return number


def _field_evidence(field: ContractField) -> ContractEvidenceData | None:
    if field.evidence_block_id is None:
        return None
    if field.evidence_parse_version_id is None or field.page_no is None or field.quote_text is None:
        raise RuntimeError("stored contract evidence is incomplete")
    return ContractEvidenceData(
        block_id=field.evidence_block_id,
        parse_version_id=field.evidence_parse_version_id,
        page_no=field.page_no,
        quote_text=field.quote_text,
        bbox=cast(dict[str, JsonValue] | None, field.bbox_json),
        confidence=None if field.confidence is None else format(field.confidence, "f"),
    )


class ContractManagementService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_evidence(
        self,
        organization_id: UUID,
        contract_id: UUID,
    ) -> ContractEvidenceResponseData:
        with self._session_factory() as session:
            repository = ContractWriteRepository(session)
            contract = repository.lock_contract(organization_id, contract_id)
            if contract is None:
                raise _not_found()
            binding = repository.lock_binding(contract.id)
            if binding is None:
                raise _conflict("CONTRACT_SOURCE_NOT_BOUND", "合同没有可验证的来源文件")
            rows = repository.lock_fields(contract.id)
            evidence = tuple(
                item for item in (_field_evidence(field) for field in rows) if item is not None
            )
            if not repository.validate_evidence(
                organization_id,
                binding.file_id,
                evidence,
                lock=False,
            ):
                raise _conflict("EVIDENCE_SCOPE_CONFLICT", "合同证据链不再有效")
            by_code = {field.field_code: field for field in rows}
            fields: list[ContractFieldCandidateData] = []
            for field_code in CONTRACT_CORE_FIELD_CODES:
                field = by_code.get(field_code)
                fields.append(
                    ContractFieldCandidateData(
                        field_code=field_code,
                        value_type=CONTRACT_FIELD_VALUE_TYPES[field_code],
                        candidate_value=(
                            None if field is None else cast(JsonValue, field.extracted_value_json)
                        ),
                        confirmed_value=(
                            None if field is None else cast(JsonValue, field.confirmed_value_json)
                        ),
                        confirmation_status=(
                            ConfirmationStatus.UNCONFIRMED
                            if field is None
                            else ConfirmationStatus(field.confirmation_status)
                        ),
                        evidence=None if field is None else _field_evidence(field),
                    )
                )
            return ContractEvidenceResponseData(
                contract_id=contract.id,
                file_id=binding.file_id,
                row_version=str(contract.row_version),
                fields=tuple(fields),
            )

    def get_history(
        self,
        organization_id: UUID,
        contract_id: UUID,
    ) -> ContractCorrectionHistoryData:
        with self._session_factory() as session:
            rows = ContractWriteRepository(session).correction_history(
                organization_id,
                contract_id,
            )
            if rows is None:
                raise _not_found()
            return ContractCorrectionHistoryData(
                contract_id=contract_id,
                items=tuple(
                    ContractCorrectionHistoryItemData(
                        id=row.id,
                        field_path=row.field_path,
                        before_value=cast(dict[str, JsonValue] | None, row.before_value_json),
                        after_value=cast(dict[str, JsonValue] | None, row.after_value_json),
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
        contract_id: UUID,
        payload: ContractFactsReplaceRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> ContractMutationResult:
        path = f"/api/v1/contracts/{contract_id}/facts"
        claim_args = self._claim_args("PUT", path, payload, idempotency_key)
        with self._session_factory.begin() as session:
            repository, claim, now = self._claim(session, actor, *claim_args)
            replay = self._replay(claim)
            if replay is not None:
                return replay
            contract = self._lock_mutable(repository, actor, contract_id, payload.row_version)
            if contract.status != "draft" or contract.confirmation_status not in {
                "unconfirmed",
                "rejected",
            }:
                raise _conflict("CONTRACT_STATE_CONFLICT", "当前合同状态不可修正")
            binding = repository.lock_binding(contract.id)
            if binding is None:
                raise _conflict("CONTRACT_SOURCE_NOT_BOUND", "合同没有可验证的来源文件")
            evidence = tuple(item.evidence for item in payload.field_evidence)
            if not repository.validate_evidence(actor.organization_id, binding.file_id, evidence):
                raise _conflict("EVIDENCE_SCOPE_CONFLICT", "提交的字段证据不可验证")
            if repository.contract_no_exists(
                actor.organization_id,
                contract.id,
                payload.facts.contract_no,
            ):
                raise _conflict("CONTRACT_NUMBER_CONFLICT", "合同编号已存在")
            existing = repository.lock_fields(contract.id)
            before = contract_snapshot(contract, existing)
            replacement_rows = self._field_models(contract.id, binding.file_id, payload)
            self._apply_facts(contract, payload.facts)
            contract.confirmation_status = "unconfirmed"
            contract.status = "draft"
            contract.confirmed_by = None
            contract.confirmed_at = None
            contract.critical_fact_hash = contract_critical_fact_hash(payload.facts)
            contract.updated_by = actor.user_id
            contract.updated_at = now
            contract.row_version += 1
            current_rows = repository.replace_fields(
                existing,
                replacement_rows,
                actor_id=actor.user_id,
                decided_at=now,
            )
            repository.flush()
            after = contract_snapshot(contract, current_rows)
            if before == after:
                raise _conflict("RESOURCE_STATE_UNCHANGED", "合同事实未发生变化")
            outdated_ids = AuditRuntimeRepository(session).outdate_current_executions_for_contract(
                actor.organization_id,
                contract.id,
                actor_id=actor.user_id,
                now=now,
            )
            self._append_correction(
                repository,
                actor,
                contract,
                field_path="facts",
                before=before,
                after=after,
                reason=payload.reason,
                now=now,
                trace_id=trace_id,
                caused_outdated=bool(outdated_ids),
            )
            repository.flush()
            data = self._project(session, actor.organization_id, contract.id)
            self._append_log(
                session,
                actor,
                contract,
                "contracts.facts_replaced",
                trace_id,
                {
                    "field_count": len(replacement_rows),
                    "row_version": str(contract.row_version),
                },
            )
            repository.complete_idempotency(
                claim,
                response_body=data.model_dump(mode="json"),
                resource_id=contract.id,
            )
            return ContractMutationResult(data, False)

    def decide(
        self,
        actor: AuthenticatedActor,
        contract_id: UUID,
        payload: ContractDecisionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> ContractMutationResult:
        path = f"/api/v1/contracts/{contract_id}/decision"
        claim_args = self._claim_args("POST", path, payload, idempotency_key)
        with self._session_factory.begin() as session:
            repository, claim, now = self._claim(session, actor, *claim_args)
            replay = self._replay(claim)
            if replay is not None:
                return replay
            contract = self._lock_mutable(repository, actor, contract_id, payload.row_version)
            if contract.status != "draft" or contract.confirmation_status != "unconfirmed":
                raise _conflict("CONTRACT_STATE_CONFLICT", "当前合同状态不可决定")
            fields = repository.lock_fields(contract.id)
            before = contract_snapshot(contract, fields)
            current_facts = contract_facts_from_model(contract)
            by_code = {field.field_code: field for field in fields}
            if payload.decision == "confirmed":
                missing = [
                    field_code
                    for field_code in _REQUIRED_CONFIRM_FIELDS
                    if getattr(current_facts, field_code) is None
                    or (
                        type(getattr(current_facts, field_code)) is str
                        and not getattr(current_facts, field_code)
                    )
                    or field_code not in by_code
                    or by_code[field_code].confirmation_status != "unconfirmed"
                    or by_code[field_code].evidence_block_id is None
                ]
                if missing:
                    raise _conflict(
                        "CONTRACT_CONFIRMATION_INCOMPLETE",
                        "确认要求核心字段及证据完整",
                    )
                current_evidence: list[ContractEvidenceData] = []
                for field_code in CONTRACT_CORE_FIELD_CODES:
                    value = fact_json_value(current_facts, field_code)
                    if value is None:
                        continue
                    field = by_code.get(field_code)
                    if (
                        field is None
                        or field.confirmation_status != "unconfirmed"
                        or field.extracted_value_json != value
                    ):
                        raise _conflict(
                            "CONTRACT_CONFIRMATION_INCOMPLETE",
                            "合同候选与当前事实不一致",
                        )
                    evidence = _field_evidence(field)
                    if evidence is None:
                        raise _conflict(
                            "CONTRACT_CONFIRMATION_INCOMPLETE",
                            "确认要求每个非空字段都有原文证据",
                        )
                    current_evidence.append(evidence)
                binding = repository.lock_binding(contract.id)
                if binding is None or not repository.validate_evidence(
                    actor.organization_id,
                    binding.file_id,
                    tuple(current_evidence),
                ):
                    raise _conflict("EVIDENCE_SCOPE_CONFLICT", "合同证据链不再有效")
            for field in fields:
                if field.confirmation_status != "unconfirmed":
                    continue
                current_value = fact_json_value(
                    current_facts,
                    cast(ContractFieldCode, field.field_code),
                )
                field.confirmation_status = payload.decision
                field.confirmed_value_json = (
                    current_value if payload.decision == "confirmed" else None
                )
                field.confirmed_by = actor.user_id
                field.confirmed_at = now
                field.row_version += 1
            repository.flush()
            contract.confirmation_status = payload.decision
            contract.status = "active" if payload.decision == "confirmed" else "draft"
            contract.confirmed_by = actor.user_id
            contract.confirmed_at = now
            contract.updated_by = actor.user_id
            contract.updated_at = now
            contract.row_version += 1
            after = contract_snapshot(contract, fields)
            repository.flush()
            outdated_ids = AuditRuntimeRepository(session).outdate_current_executions_for_contract(
                actor.organization_id,
                contract.id,
                actor_id=actor.user_id,
                now=now,
            )
            self._append_correction(
                repository,
                actor,
                contract,
                field_path="decision",
                before=before,
                after=after,
                reason=payload.reason,
                now=now,
                trace_id=trace_id,
                caused_outdated=bool(outdated_ids),
            )
            repository.flush()
            data = self._project(session, actor.organization_id, contract.id)
            self._append_log(
                session,
                actor,
                contract,
                f"contracts.{payload.decision}",
                trace_id,
                {
                    "confirmation_status": payload.decision,
                    "row_version": str(contract.row_version),
                },
            )
            repository.complete_idempotency(
                claim,
                response_body=data.model_dump(mode="json"),
                resource_id=contract.id,
            )
            return ContractMutationResult(data, False)

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
    ) -> tuple[ContractWriteRepository, IdempotencyClaim, datetime]:
        repository = ContractWriteRepository(session)
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
    def _replay(claim: IdempotencyClaim) -> ContractMutationResult | None:
        if not claim.is_replay:
            return None
        if claim.replay_status != 200 or claim.replay_body is None:
            raise RuntimeError("contract replay does not match the contract")
        encoded = json.dumps(claim.replay_body, separators=(",", ":"), sort_keys=True)
        return ContractMutationResult(ContractMutationData.model_validate_json(encoded), True)

    @staticmethod
    def _lock_mutable(
        repository: ContractWriteRepository,
        actor: AuthenticatedActor,
        contract_id: UUID,
        row_version: str,
    ) -> Contract:
        contract = repository.lock_contract(actor.organization_id, contract_id)
        if contract is None:
            raise _not_found()
        if contract.row_version != int(row_version):
            raise _conflict("ROW_VERSION_CONFLICT", "资源版本已变化")
        if contract.status in {"active", "expired", "terminated", "archived"}:
            raise _conflict("CONTRACT_STATE_CONFLICT", "当前合同状态不可写入")
        return contract

    @staticmethod
    def _apply_facts(contract: Contract, facts: ContractFactsWriteData) -> None:
        contract.contract_no = facts.contract_no
        contract.name = facts.name or ""
        contract.party_a_name = facts.party_a_name
        contract.party_a_tax_no = facts.party_a_tax_no
        contract.party_b_name = facts.party_b_name
        contract.party_b_tax_no = facts.party_b_tax_no
        contract.amount = _bounded_amount(facts.amount)
        contract.currency = facts.currency
        contract.signed_date = facts.signed_date
        contract.effective_date = facts.effective_date
        contract.expiry_date = facts.expiry_date
        contract.payment_method = facts.payment_method
        contract.payment_terms = facts.payment_terms

    @staticmethod
    def _field_models(
        contract_id: UUID,
        file_id: UUID,
        payload: ContractFactsReplaceRequest,
    ) -> tuple[ContractField, ...]:
        return tuple(
            ContractField(
                id=uuid4(),
                contract_id=contract_id,
                field_code=item.field_code,
                value_type=CONTRACT_FIELD_VALUE_TYPES[item.field_code],
                extracted_value_json=fact_json_value(payload.facts, item.field_code),
                confirmed_value_json=None,
                confidence=(
                    None if item.evidence.confidence is None else Decimal(item.evidence.confidence)
                ),
                confirmation_status="unconfirmed",
                evidence_file_id=file_id,
                evidence_parse_version_id=item.evidence.parse_version_id,
                evidence_block_id=item.evidence.block_id,
                page_no=item.evidence.page_no,
                quote_text=item.evidence.quote_text,
                bbox_json=item.evidence.bbox,
                confirmed_by=None,
                confirmed_at=None,
                row_version=1,
            )
            for item in payload.field_evidence
        )

    @staticmethod
    def _append_correction(
        repository: ContractWriteRepository,
        actor: AuthenticatedActor,
        contract: Contract,
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
                correction_type="contract_field",
                object_type="contract",
                object_id=contract.id,
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
        contract_id: UUID,
    ) -> ContractMutationData:
        view = FinancialReadRepository(session).read_contract(organization_id, contract_id)
        if view is None:
            raise RuntimeError("persisted contract is not readable")
        return ContractMutationData(contract=_project_detail(view))

    @staticmethod
    def _append_log(
        session: Session,
        actor: AuthenticatedActor,
        contract: Contract,
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
            resource_type="contract",
            resource_id=contract.id,
            trace_id=trace_id,
            change_summary=summary,
        )


__all__ = ["ContractManagementService", "ContractMutationResult"]
