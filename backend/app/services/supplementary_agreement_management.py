"""补充协议变更整组替换与原子决定用例。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.orm import Session, sessionmaker

from app.ai.policy import canonicalize_jcs
from app.core.errors import AppError
from app.models.corrections import UserCorrection
from app.models.financial import SupplementaryAgreement, SupplementaryAgreementChange
from app.repositories.audit_runtime import AuditRuntimeRepository
from app.repositories.financial_read import EffectiveContractReadView, FinancialReadRepository
from app.repositories.operation_log import OperationLogRepository
from app.repositories.supplementary_agreement_write import (
    SupplementaryAgreementWriteRepository,
)
from app.repositories.user_write import IdempotencyClaim
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import (
    ContractFieldValueType,
    SupplementaryAgreementChangeData,
    SupplementaryAgreementDecisionRequest,
    SupplementaryAgreementDetailData,
    SupplementaryAgreementStatus,
    SupplementaryChangesReplaceRequest,
)
from app.services.auth import AuthenticatedActor
from app.services.contract_effectivity import SupplementaryFieldChange, project_effective_fields
from app.services.effective_contract_query import original_contract_fields

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_IDEMPOTENCY_TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class SupplementaryAgreementMutationResult:
    data: SupplementaryAgreementDetailData
    replayed: bool


def _resource_not_found() -> AppError:
    return AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )


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


def _critical_fact_hash(agreement: SupplementaryAgreement) -> str:
    payload = [
        "supplementary-agreement-facts-v1",
        str(agreement.contract_id),
        agreement.agreement_no,
        agreement.name,
        agreement.signed_date.isoformat() if agreement.signed_date else None,
        agreement.effective_date.isoformat(),
        agreement.status,
        agreement.confirmation_status,
    ]
    return hashlib.sha256(canonicalize_jcs(payload)).hexdigest()


def _change_snapshot(changes: tuple[SupplementaryAgreementChange, ...]) -> dict[str, object]:
    return {
        "changes": [
            {
                "bbox": change.bbox_json,
                "confirmation_status": change.confirmation_status,
                "evidence_block_id": (
                    str(change.evidence_block_id) if change.evidence_block_id else None
                ),
                "field_code": change.field_code,
                "new_value": change.new_value_json,
                "old_value": change.old_value_json,
                "page_no": change.page_no,
                "quote_text": change.quote_text,
                "value_type": change.value_type,
            }
            for change in changes
        ]
    }


def _project_change(change: SupplementaryAgreementChange) -> SupplementaryAgreementChangeData:
    return SupplementaryAgreementChangeData(
        id=change.id,
        field_code=change.field_code,
        value_type=cast(ContractFieldValueType, change.value_type),
        old_value=cast(JsonValue, change.old_value_json),
        new_value=cast(JsonValue, change.new_value_json),
        evidence_block_id=change.evidence_block_id,
        page_no=change.page_no,
        quote_text=change.quote_text,
        bbox=cast(dict[str, JsonValue] | None, change.bbox_json),
        confirmation_status=ConfirmationStatus(change.confirmation_status),
    )


def _project_detail(
    agreement: SupplementaryAgreement,
    changes: tuple[SupplementaryAgreementChange, ...],
) -> SupplementaryAgreementDetailData:
    return SupplementaryAgreementDetailData(
        id=agreement.id,
        contract_id=agreement.contract_id,
        agreement_no=agreement.agreement_no,
        name=agreement.name,
        signed_date=agreement.signed_date,
        effective_date=agreement.effective_date,
        status=SupplementaryAgreementStatus(agreement.status),
        confirmation_status=ConfirmationStatus(agreement.confirmation_status),
        changes=tuple(_project_change(change) for change in changes),
        row_version=str(agreement.row_version),
    )


def _replay(claim: IdempotencyClaim) -> SupplementaryAgreementMutationResult:
    if claim.replay_status != 200 or claim.replay_body is None:
        raise RuntimeError("supplementary agreement replay does not match the contract")
    encoded = json.dumps(
        claim.replay_body,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return SupplementaryAgreementMutationResult(
        data=SupplementaryAgreementDetailData.model_validate_json(encoded),
        replayed=True,
    )


def _actor_role(actor: AuthenticatedActor) -> str:
    if "contract_admin" in actor.roles:
        return "contract_admin"
    raise RuntimeError("contracts.manage actor lacks its source role")


class SupplementaryAgreementManagementService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_detail(
        self,
        actor: AuthenticatedActor,
        contract_id: UUID,
        agreement_id: UUID,
    ) -> SupplementaryAgreementDetailData:
        with self._session_factory() as session:
            repository = SupplementaryAgreementWriteRepository(session)
            agreement = repository.lock_agreement(
                actor.organization_id,
                contract_id,
                agreement_id,
            )
            if agreement is None:
                raise _resource_not_found()
            changes = repository.lock_changes(agreement.id)
            return _project_detail(agreement, changes)

    def replace_changes(
        self,
        actor: AuthenticatedActor,
        contract_id: UUID,
        agreement_id: UUID,
        payload: SupplementaryChangesReplaceRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> SupplementaryAgreementMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/contracts/{contract_id}/supplementary-agreements/{agreement_id}/changes"
        digest = _request_hash("PUT", path, payload.model_dump(mode="json"))
        with self._session_factory.begin() as session:
            repository = SupplementaryAgreementWriteRepository(session)
            claim, now = self._claim(
                repository,
                actor,
                idempotency_key,
                "PUT",
                path,
                digest,
            )
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return _replay(claim)
            agreement = repository.lock_agreement(
                actor.organization_id,
                contract_id,
                agreement_id,
            )
            contract = repository.lock_contract(actor.organization_id, contract_id)
            if agreement is None or contract is None:
                raise _resource_not_found()
            if agreement.row_version != int(payload.row_version):
                raise _conflict("ROW_VERSION_CONFLICT", "资源版本已变化")
            if agreement.status not in {"draft", "pending_confirmation"}:
                raise _conflict("SUPPLEMENTARY_AGREEMENT_STATE_CONFLICT", "当前协议状态不可修改")
            existing = repository.lock_changes(agreement.id)
            contract_fields = repository.lock_contract_fields(contract_id)
            prior_changes = repository.lock_prior_changes(
                contract_id,
                agreement.id,
                agreement.effective_date,
            )
            effective_view = FinancialReadRepository(session).read_effective_contract(
                actor.organization_id,
                contract_id,
            )
            if effective_view is None:
                raise _resource_not_found()
            allowed_types = self._field_types(effective_view)
            for change in payload.changes:
                if allowed_types.get(change.field_code) != change.value_type:
                    raise _conflict(
                        "SUPPLEMENTARY_FIELD_UNAVAILABLE",
                        "补充协议字段不存在或类型不兼容",
                    )
            evidence = tuple(
                (change.evidence_block_id, change.page_no)
                for change in payload.changes
                if change.evidence_block_id is not None and change.page_no is not None
            )
            if not repository.validate_evidence_blocks(actor.organization_id, evidence):
                raise _conflict("EVIDENCE_SCOPE_CONFLICT", "字段证据不可见或页码不一致")
            old_values = self._old_values(
                effective_view,
                agreement,
                prior_changes,
                tuple(field.field_code for field in contract_fields),
            )
            new_models = tuple(
                SupplementaryAgreementChange(
                    id=uuid4(),
                    supplementary_agreement_id=agreement.id,
                    field_code=change.field_code,
                    value_type=change.value_type,
                    old_value_json=old_values[change.field_code],
                    new_value_json=change.new_value,
                    evidence_block_id=change.evidence_block_id,
                    page_no=change.page_no,
                    quote_text=change.quote_text,
                    bbox_json=cast(dict[str, object] | None, change.bbox),
                    confirmation_status="unconfirmed",
                    confirmed_by=None,
                    confirmed_at=None,
                )
                for change in sorted(payload.changes, key=lambda item: item.field_code)
            )
            before = _change_snapshot(existing)
            after = _change_snapshot(new_models)
            if before == after:
                raise _conflict("RESOURCE_STATE_UNCHANGED", "补充协议变更未发生变化")
            repository.replace_changes(agreement.id, new_models)
            agreement.status = "pending_confirmation"
            agreement.confirmation_status = "unconfirmed"
            agreement.confirmed_by = None
            agreement.confirmed_at = None
            agreement.confirmation_reason = None
            agreement.updated_by = actor.user_id
            agreement.updated_at = now
            agreement.row_version += 1
            agreement.critical_fact_hash = _critical_fact_hash(agreement)
            repository.flush()
            outdated_ids = AuditRuntimeRepository(session).outdate_current_executions_for_contract(
                actor.organization_id,
                contract_id,
                actor_id=actor.user_id,
                now=now,
                effective_from=agreement.effective_date,
            )
            correction = UserCorrection(
                id=uuid4(),
                organization_id=actor.organization_id,
                correction_type="supplementary_agreement_changes",
                object_type="supplementary_agreement",
                object_id=agreement.id,
                field_path="changes",
                before_value_json=before,
                after_value_json=after,
                reason=payload.reason,
                actor_id=actor.user_id,
                actor_role_code=_actor_role(actor),
                related_execution_id=None,
                caused_outdated=bool(outdated_ids),
                created_at=now,
                trace_id=trace_id,
            )
            repository.add(correction)
            repository.flush()
            data = _project_detail(agreement, new_models)
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code="supplementary_agreements.changes_replaced",
                outcome="succeeded",
                resource_type="supplementary_agreement",
                resource_id=agreement.id,
                trace_id=trace_id,
                change_summary={
                    "change_count": len(new_models),
                    "row_version": data.row_version,
                },
            )
            repository.complete_idempotency(
                claim,
                response_body=data.model_dump(mode="json"),
                resource_id=agreement.id,
            )
            return SupplementaryAgreementMutationResult(data=data, replayed=False)

    def decide(
        self,
        actor: AuthenticatedActor,
        contract_id: UUID,
        agreement_id: UUID,
        payload: SupplementaryAgreementDecisionRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> SupplementaryAgreementMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/contracts/{contract_id}/supplementary-agreements/{agreement_id}/decision"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        with self._session_factory.begin() as session:
            repository = SupplementaryAgreementWriteRepository(session)
            claim, now = self._claim(
                repository,
                actor,
                idempotency_key,
                "POST",
                path,
                digest,
            )
            if claim.conflict:
                raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
            if claim.is_replay:
                return _replay(claim)
            agreement = repository.lock_agreement(
                actor.organization_id,
                contract_id,
                agreement_id,
            )
            if agreement is None:
                raise _resource_not_found()
            if agreement.row_version != int(payload.row_version):
                raise _conflict("ROW_VERSION_CONFLICT", "资源版本已变化")
            if agreement.status != "pending_confirmation":
                raise _conflict("SUPPLEMENTARY_AGREEMENT_STATE_CONFLICT", "当前协议状态不可决定")
            changes = repository.lock_changes(agreement.id)
            if not changes:
                raise _conflict("SUPPLEMENTARY_CHANGES_REQUIRED", "补充协议没有可决定的字段变更")
            if payload.decision == "confirmed" and any(
                change.evidence_block_id is None for change in changes
            ):
                raise _conflict("SUPPLEMENTARY_EVIDENCE_REQUIRED", "确认要求每项变更都有原文证据")
            for change in changes:
                change.confirmation_status = payload.decision
                change.confirmed_by = actor.user_id
                change.confirmed_at = now
            # 子变更必须在父协议进入终态前落库；数据库随后会冻结终态协议的变更行。
            repository.flush()
            agreement.status = payload.decision
            agreement.confirmation_status = payload.decision
            agreement.confirmed_by = actor.user_id
            agreement.confirmed_at = now
            agreement.confirmation_reason = payload.reason
            agreement.updated_by = actor.user_id
            agreement.updated_at = now
            agreement.row_version += 1
            agreement.critical_fact_hash = _critical_fact_hash(agreement)
            repository.flush()
            AuditRuntimeRepository(session).outdate_current_executions_for_contract(
                actor.organization_id,
                contract_id,
                actor_id=actor.user_id,
                now=now,
                effective_from=agreement.effective_date,
            )
            data = _project_detail(agreement, changes)
            OperationLogRepository(session).append(
                organization_id=actor.organization_id,
                actor_kind="user",
                actor_id=actor.user_id,
                action_code=f"supplementary_agreements.{payload.decision}",
                outcome="succeeded",
                resource_type="supplementary_agreement",
                resource_id=agreement.id,
                trace_id=trace_id,
                change_summary={
                    "change_count": len(changes),
                    "row_version": data.row_version,
                },
            )
            repository.complete_idempotency(
                claim,
                response_body=data.model_dump(mode="json"),
                resource_id=agreement.id,
            )
            return SupplementaryAgreementMutationResult(data=data, replayed=False)

    @staticmethod
    def _claim(
        repository: SupplementaryAgreementWriteRepository,
        actor: AuthenticatedActor,
        key: str,
        method: str,
        path: str,
        digest: str,
    ) -> tuple[IdempotencyClaim, datetime]:
        repository.acquire_locks(actor.organization_id, actor.user_id, key)
        if repository.lock_active_organization(actor.organization_id) is None:
            raise _resource_not_found()
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
    def _field_types(view: EffectiveContractReadView) -> dict[str, str]:
        _, field_types = original_contract_fields(view)
        return field_types

    @staticmethod
    def _old_values(
        view: EffectiveContractReadView,
        agreement: SupplementaryAgreement,
        prior_rows: tuple[tuple[SupplementaryAgreementChange, SupplementaryAgreement], ...],
        contract_field_codes: tuple[str, ...],
    ) -> dict[str, object]:
        original, _ = original_contract_fields(view)
        prior = tuple(
            SupplementaryFieldChange(
                agreement_id=parent.id,
                field_code=change.field_code,
                new_value=change.new_value_json,
                agreement_status=SupplementaryAgreementStatus(parent.status),
                agreement_confirmation_status=ConfirmationStatus(parent.confirmation_status),
                change_confirmation_status=ConfirmationStatus(change.confirmation_status),
                effective_date=parent.effective_date,
            )
            for change, parent in prior_rows
        )
        try:
            projection = project_effective_fields(original, prior, agreement.effective_date)
        except ValueError as error:
            if str(error) == "conflicting supplementary agreement field changes":
                raise _conflict(
                    "EFFECTIVE_FIELD_CONFLICT",
                    "同一字段存在冲突的生效协议",
                ) from None
            raise
        values = projection.materialize_field_values()
        # Defensive invariant: loaded contract_fields must be represented in the projection.
        if not set(contract_field_codes).issubset(values):
            raise RuntimeError("contract field projection is incomplete")
        return values


__all__ = [
    "SupplementaryAgreementManagementService",
    "SupplementaryAgreementMutationResult",
]
