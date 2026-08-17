"""供应商来源候选解析、读取和人工处理用例。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.models.corrections import UserCorrection
from app.models.financial import Contract, Invoice, Supplier
from app.repositories.operation_log import OperationLogRepository
from app.repositories.supplier_write import SupplierWriteRepository
from app.repositories.user_write import IdempotencyClaim
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.suppliers import (
    SupplierCandidateUpdateRequest,
    SupplierData,
    SupplierListData,
    SupplierMutationData,
    SupplierResolveData,
    SupplierSourceResolveRequest,
    SupplierSourceType,
    SupplierStatus,
)
from app.services.auth import AuthenticatedActor
from app.services.supplier_runtime import public_tax_number, validate_supplier_state

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_IDEMPOTENCY_TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class SupplierResolveResult:
    data: SupplierResolveData
    replayed: bool


@dataclass(frozen=True, slots=True)
class SupplierMutationResult:
    data: SupplierMutationData
    replayed: bool


def _not_found() -> AppError:
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


def _invalid_cursor() -> AppError:
    return AppError(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合约束",
        details=[{"field": "query.cursor", "reason": "invalid"}],
    )


def _encode_cursor(supplier_id: UUID) -> str:
    payload = json.dumps(
        {"id": str(supplier_id), "v": 1},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor(value: str) -> UUID:
    if not value or len(value) > 256 or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise _invalid_cursor()
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
        if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
            raise ValueError("noncanonical base64url")
        payload = json.loads(decoded.decode("utf-8"))
        if type(payload) is not dict or set(payload) != {"id", "v"} or payload["v"] != 1:
            raise ValueError("invalid cursor object")
        raw_id = payload["id"]
        if type(raw_id) is not str:
            raise ValueError("invalid cursor id")
        supplier_id = UUID(raw_id)
        if str(supplier_id) != raw_id or _encode_cursor(supplier_id) != value:
            raise ValueError("noncanonical cursor id")
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError, ValueError, KeyError):
        raise _invalid_cursor() from None
    return supplier_id


def _project_supplier(supplier: Supplier) -> SupplierData:
    validate_supplier_state(
        supplier.confirmation_status,
        supplier.status,
        confirmed_by=supplier.confirmed_by,
        confirmed_at_present=supplier.confirmed_at is not None,
    )
    return SupplierData(
        id=supplier.id,
        standard_name=supplier.standard_name,
        tax_number=public_tax_number(
            supplier.unified_social_credit_code,
            supplier.tax_number,
        ),
        source_type=SupplierSourceType(supplier.source_type),
        source_contract_id=supplier.source_contract_id,
        source_invoice_id=supplier.source_invoice_id,
        confirmation_status=ConfirmationStatus(supplier.confirmation_status),
        status=SupplierStatus(supplier.status),
        confirmed_by=supplier.confirmed_by,
        confirmed_at=supplier.confirmed_at,
        row_version=str(supplier.row_version),
    )


def _actor_role(actor: AuthenticatedActor) -> str:
    if "finance_reviewer" in actor.roles:
        return "finance_reviewer"
    if "contract_admin" in actor.roles:
        return "contract_admin"
    raise RuntimeError("suppliers.correct actor lacks its source role")


def _source_name_tax(source: Contract | Invoice) -> tuple[str | None, str | None]:
    if isinstance(source, Contract):
        return source.party_b_name, source.party_b_tax_no
    return source.seller_name, source.seller_tax_no


def _source_is_confirmed(source: Contract | Invoice) -> bool:
    if source.confirmation_status != "confirmed":
        return False
    if source.confirmed_by is None or source.confirmed_at is None:
        return False
    if isinstance(source, Contract):
        return source.status in {"active", "expired", "terminated", "archived"}
    return source.status in {"confirmed", "archived"}


def _require_source_facts(source: Contract | Invoice) -> tuple[str, str]:
    name, tax_number = _source_name_tax(source)
    if (
        not _source_is_confirmed(source)
        or name is None
        or tax_number is None
        or not name
        or not tax_number
        or name != name.strip()
        or tax_number != tax_number.strip()
        or _CONTROL_CHARACTER_PATTERN.search(name) is not None
        or _CONTROL_CHARACTER_PATTERN.search(tax_number) is not None
    ):
        raise _conflict("SUPPLIER_STATE_CONFLICT", "来源尚未形成可用的已确认供应商事实")
    return name, tax_number


def _source_supplier_id(source: Contract | Invoice) -> UUID | None:
    return source.supplier_id


def _source_row_version(source: Contract | Invoice) -> str:
    return str(source.row_version)


def _integrity_error(error: IntegrityError) -> AppError:
    original = error.orig
    sqlstate = getattr(original, "sqlstate", None)
    diagnostic = getattr(original, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    if sqlstate == "23505" and constraint_name == "uq_suppliers_organization_tax_identity":
        return _conflict("SUPPLIER_TAX_NUMBER_CONFLICT", "供应商税务身份已被并发占用")
    if sqlstate == "23505" and constraint_name in {
        "uq_suppliers_organization_source_contract_candidate",
        "uq_suppliers_organization_source_invoice_candidate",
    }:
        return _conflict("SUPPLIER_STATE_CONFLICT", "来源供应商候选已发生并发变化")
    return AppError(status_code=500, code="INTERNAL_ERROR", message="服务暂时不可用")


class SupplierManagementService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_page(
        self,
        organization_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> SupplierListData:
        cursor_id = _decode_cursor(cursor) if cursor is not None else None
        with self._session_factory() as session:
            rows = SupplierWriteRepository(session).list_suppliers(
                organization_id,
                cursor_id,
                page_size + 1,
            )
        has_more = len(rows) > page_size
        page = rows[:page_size]
        return SupplierListData(
            items=tuple(_project_supplier(row) for row in page),
            page_size=page_size,
            next_cursor=_encode_cursor(page[-1].id) if has_more else None,
        )

    def get_detail(self, organization_id: UUID, supplier_id: UUID) -> SupplierData:
        with self._session_factory() as session:
            supplier = SupplierWriteRepository(session).get_supplier(
                organization_id,
                supplier_id,
            )
            if supplier is None:
                raise _not_found()
            return _project_supplier(supplier)

    def resolve_source(
        self,
        actor: AuthenticatedActor,
        payload: SupplierSourceResolveRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> SupplierResolveResult:
        _validate_idempotency_key(idempotency_key)
        path = "/api/v1/suppliers/source-candidates"
        digest = _request_hash("POST", path, payload.model_dump(mode="json"))
        try:
            with self._session_factory.begin() as session:
                repository, claim, now = self._claim(
                    session,
                    actor,
                    idempotency_key,
                    "POST",
                    path,
                    digest,
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._resolve_replay(claim)
                source = self._lock_source(
                    repository,
                    actor.organization_id,
                    payload.source_type,
                    payload.source_id,
                )
                if source is None:
                    raise _not_found()
                if source.row_version != int(payload.row_version):
                    raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
                standard_name, tax_number = _require_source_facts(source)

                candidate_id = repository.source_candidate_id(
                    actor.organization_id,
                    payload.source_type,
                    payload.source_id,
                )
                active_id = repository.active_supplier_id_by_tax(
                    actor.organization_id,
                    tax_number,
                )
                supplier_ids = {
                    supplier_id
                    for supplier_id in (
                        candidate_id,
                        active_id,
                        _source_supplier_id(source),
                    )
                    if supplier_id is not None
                }
                locked = repository.lock_suppliers(actor.organization_id, supplier_ids)
                created = False
                reused = False

                referenced_id = _source_supplier_id(source)
                if referenced_id is not None:
                    supplier = locked.get(referenced_id)
                    if supplier is None or (
                        supplier.confirmation_status,
                        supplier.status,
                    ) != ("confirmed", "active"):
                        raise _conflict(
                            "SUPPLIER_STATE_CONFLICT",
                            "来源已绑定不可用的供应商事实",
                        )
                    if (
                        public_tax_number(
                            supplier.unified_social_credit_code,
                            supplier.tax_number,
                        )
                        != tax_number
                    ):
                        raise _conflict(
                            "SUPPLIER_TAX_IDENTITY_CONFLICT",
                            "来源税务身份与已绑定供应商不一致",
                        )
                    reused = True
                elif candidate_id is not None:
                    supplier = locked.get(candidate_id)
                    if supplier is None or (
                        supplier.confirmation_status,
                        supplier.status,
                    ) != ("unconfirmed", "candidate"):
                        raise _conflict(
                            "SUPPLIER_STATE_CONFLICT",
                            "来源候选状态已发生变化",
                        )
                elif active_id is not None:
                    supplier = locked.get(active_id)
                    if supplier is None:
                        raise _conflict(
                            "SUPPLIER_STATE_CONFLICT",
                            "活动供应商状态已发生变化",
                        )
                    self._bind_source(repository, source, supplier.id, actor.user_id, now)
                    reused = True
                else:
                    supplier = Supplier(
                        organization_id=actor.organization_id,
                        standard_name=standard_name,
                        unified_social_credit_code=None,
                        tax_number=tax_number,
                        source_type=payload.source_type,
                        source_contract_id=(
                            payload.source_id if payload.source_type == "contract" else None
                        ),
                        source_invoice_id=(
                            payload.source_id if payload.source_type == "invoice" else None
                        ),
                        confirmation_status="unconfirmed",
                        status="candidate",
                        confirmed_by=None,
                        confirmed_at=None,
                        row_version=1,
                        created_at=now,
                        created_by=actor.user_id,
                        updated_at=now,
                        updated_by=actor.user_id,
                    )
                    repository.add(supplier)
                    repository.flush()
                    created = True

                data = SupplierResolveData(
                    supplier=_project_supplier(supplier),
                    source_row_version=_source_row_version(source),
                    created=created,
                    reused=reused,
                )
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="supplier.resolve",
                    outcome="succeeded",
                    resource_type="supplier",
                    resource_id=supplier.id,
                    trace_id=trace_id,
                    change_summary={
                        "created": created,
                        "reused": reused,
                        "source_type": payload.source_type,
                        "source_row_version": _source_row_version(source),
                        "supplier_status": supplier.status,
                    },
                )
                repository.complete_idempotency(
                    claim,
                    response_body=data.model_dump(mode="json"),
                    resource_id=supplier.id,
                )
                return SupplierResolveResult(data, False)
        except IntegrityError as error:
            raise _integrity_error(error) from None

    def update_candidate(
        self,
        actor: AuthenticatedActor,
        supplier_id: UUID,
        payload: SupplierCandidateUpdateRequest,
        idempotency_key: str,
        trace_id: UUID,
    ) -> SupplierMutationResult:
        _validate_idempotency_key(idempotency_key)
        path = f"/api/v1/suppliers/{supplier_id}"
        digest = _request_hash("PATCH", path, payload.model_dump(mode="json", exclude_unset=True))
        try:
            with self._session_factory.begin() as session:
                repository, claim, now = self._claim(
                    session,
                    actor,
                    idempotency_key,
                    "PATCH",
                    path,
                    digest,
                )
                if claim.conflict:
                    raise _conflict("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他请求")
                if claim.is_replay:
                    return self._mutation_replay(claim)

                located = repository.locate_supplier(actor.organization_id, supplier_id)
                if located is None:
                    raise _not_found()
                source = self._lock_candidate_source(
                    repository,
                    actor.organization_id,
                    located,
                )
                if source is None:
                    raise _not_found()
                source_name, source_tax = _require_source_facts(source)
                del source_name
                proposed_tax = (
                    payload.tax_number
                    if "tax_number" in payload.model_fields_set
                    else public_tax_number(
                        located.unified_social_credit_code,
                        located.tax_number,
                    )
                )
                assert proposed_tax is not None
                active_id = repository.active_supplier_id_by_tax(
                    actor.organization_id,
                    proposed_tax,
                    excluded_id=supplier_id,
                )
                supplier_ids = {
                    candidate_id
                    for candidate_id in (
                        supplier_id,
                        active_id,
                        _source_supplier_id(source),
                    )
                    if candidate_id is not None
                }
                locked = repository.lock_suppliers(actor.organization_id, supplier_ids)
                candidate = locked.get(supplier_id)
                if candidate is None:
                    raise _not_found()
                if candidate.row_version != int(payload.row_version):
                    raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
                if (candidate.confirmation_status, candidate.status) != (
                    "unconfirmed",
                    "candidate",
                ):
                    raise _conflict("SUPPLIER_STATE_CONFLICT", "当前供应商状态不可处理")
                if (
                    candidate.source_type == "contract"
                    and candidate.source_contract_id != source.id
                ) or (
                    candidate.source_type == "invoice" and candidate.source_invoice_id != source.id
                ):
                    raise _conflict("SUPPLIER_STATE_CONFLICT", "供应商来源事实不一致")
                if _source_supplier_id(source) is not None:
                    raise _conflict("SUPPLIER_STATE_CONFLICT", "来源已绑定活动供应商")

                current_tax = public_tax_number(
                    candidate.unified_social_credit_code,
                    candidate.tax_number,
                )
                if payload.tax_number is not None and (
                    candidate.unified_social_credit_code is not None
                    and candidate.unified_social_credit_code != payload.tax_number
                ):
                    raise _conflict(
                        "SUPPLIER_TAX_IDENTITY_CONFLICT",
                        "候选的税务身份来源相互冲突",
                    )
                final_name = payload.standard_name or candidate.standard_name
                final_tax = payload.tax_number or current_tax
                if not final_name or not final_tax:
                    raise _conflict(
                        "SUPPLIER_TAX_IDENTITY_CONFLICT",
                        "供应商名称或税务身份不完整",
                    )
                if payload.decision == "confirmed" and final_tax != source_tax:
                    raise _conflict(
                        "SUPPLIER_TAX_IDENTITY_CONFLICT",
                        "候选税务身份与当前来源确认事实不一致",
                    )

                active = locked.get(active_id) if active_id is not None else None
                reused = payload.decision == "confirmed" and active is not None
                before = {
                    "standard_name": candidate.standard_name,
                    "tax_number": current_tax,
                    "confirmation_status": candidate.confirmation_status,
                    "status": candidate.status,
                    "source_supplier_id": None,
                }
                values: dict[str, object] = {
                    "standard_name": final_name,
                    "tax_number": final_tax,
                    "updated_by": actor.user_id,
                    "updated_at": now,
                }
                final_supplier = candidate
                if payload.decision == "confirmed":
                    values.update(
                        confirmation_status="rejected" if reused else "confirmed",
                        status="inactive" if reused else "active",
                        confirmed_by=actor.user_id,
                        confirmed_at=now,
                    )
                    if reused:
                        assert active is not None
                        final_supplier = active
                elif payload.decision == "rejected":
                    values.update(
                        confirmation_status="rejected",
                        status="inactive",
                        confirmed_by=actor.user_id,
                        confirmed_at=now,
                    )

                if not repository.cas_supplier(
                    candidate,
                    int(payload.row_version),
                    values,
                ):
                    raise _conflict("RESOURCE_VERSION_CONFLICT", "资源版本已变化")
                if payload.decision == "confirmed":
                    self._bind_source(
                        repository,
                        source,
                        final_supplier.id,
                        actor.user_id,
                        now,
                    )

                after = {
                    "standard_name": candidate.standard_name,
                    "tax_number": public_tax_number(
                        candidate.unified_social_credit_code,
                        candidate.tax_number,
                    ),
                    "confirmation_status": candidate.confirmation_status,
                    "status": candidate.status,
                    "source_supplier_id": (
                        str(_source_supplier_id(source))
                        if _source_supplier_id(source) is not None
                        else None
                    ),
                }
                changed_fields = tuple(key for key in sorted(before) if before[key] != after[key])
                if not changed_fields:
                    raise _conflict("RESOURCE_STATE_UNCHANGED", "供应商事实未发生变化")
                correction = UserCorrection(
                    id=uuid4(),
                    organization_id=actor.organization_id,
                    correction_type="supplier_field",
                    object_type="supplier",
                    object_id=candidate.id,
                    field_path="supplier",
                    before_value_json={key: before[key] for key in changed_fields},
                    after_value_json={key: after[key] for key in changed_fields},
                    reason=payload.reason,
                    actor_id=actor.user_id,
                    actor_role_code=_actor_role(actor),
                    related_execution_id=None,
                    caused_outdated=False,
                    created_at=now,
                    trace_id=trace_id,
                )
                repository.add(correction)
                OperationLogRepository(session).append(
                    organization_id=actor.organization_id,
                    actor_kind="user",
                    actor_id=actor.user_id,
                    action_code="supplier.update",
                    outcome="succeeded",
                    resource_type="supplier",
                    resource_id=candidate.id,
                    trace_id=trace_id,
                    change_summary={
                        "changed_fields": list(changed_fields),
                        "reused": reused,
                        "row_version": str(candidate.row_version),
                        "status": candidate.status,
                    },
                )
                repository.flush()
                data = SupplierMutationData(
                    supplier=_project_supplier(final_supplier),
                    candidate_id=candidate.id,
                    candidate_row_version=str(candidate.row_version),
                    source_row_version=_source_row_version(source),
                    correction_id=correction.id,
                    reused=reused,
                )
                repository.complete_idempotency(
                    claim,
                    response_body=data.model_dump(mode="json"),
                    resource_id=candidate.id,
                )
                return SupplierMutationResult(data, False)
        except IntegrityError as error:
            raise _integrity_error(error) from None

    @staticmethod
    def _lock_source(
        repository: SupplierWriteRepository,
        organization_id: UUID,
        source_type: str,
        source_id: UUID,
    ) -> Contract | Invoice | None:
        if source_type == "contract":
            return repository.lock_contract(organization_id, source_id)
        return repository.lock_invoice(organization_id, source_id)

    @staticmethod
    def _lock_candidate_source(
        repository: SupplierWriteRepository,
        organization_id: UUID,
        candidate: Supplier,
    ) -> Contract | Invoice | None:
        if candidate.source_type == "contract" and candidate.source_contract_id is not None:
            return repository.lock_contract(organization_id, candidate.source_contract_id)
        if candidate.source_type == "invoice" and candidate.source_invoice_id is not None:
            return repository.lock_invoice(organization_id, candidate.source_invoice_id)
        return None

    @staticmethod
    def _bind_source(
        repository: SupplierWriteRepository,
        source: Contract | Invoice,
        supplier_id: UUID,
        actor_id: UUID,
        now: datetime,
    ) -> None:
        if _source_supplier_id(source) == supplier_id:
            return
        if _source_supplier_id(source) is not None:
            raise _conflict("SUPPLIER_STATE_CONFLICT", "来源已绑定其他供应商")
        if isinstance(source, Contract):
            updated = repository.cas_contract_supplier(source, supplier_id, actor_id, now)
        else:
            updated = repository.cas_invoice_supplier(source, supplier_id, actor_id, now)
        if not updated:
            raise _conflict("RESOURCE_VERSION_CONFLICT", "来源版本已变化")

    @staticmethod
    def _resolve_replay(claim: IdempotencyClaim) -> SupplierResolveResult:
        if claim.replay_status != 200 or claim.replay_body is None:
            raise RuntimeError("supplier resolve replay does not match the contract")
        encoded = json.dumps(
            claim.replay_body,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return SupplierResolveResult(
            SupplierResolveData.model_validate_json(encoded),
            True,
        )

    @staticmethod
    def _mutation_replay(claim: IdempotencyClaim) -> SupplierMutationResult:
        if claim.replay_status != 200 or claim.replay_body is None:
            raise RuntimeError("supplier mutation replay does not match the contract")
        encoded = json.dumps(
            claim.replay_body,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return SupplierMutationResult(
            SupplierMutationData.model_validate_json(encoded),
            True,
        )

    @staticmethod
    def _claim(
        session: Session,
        actor: AuthenticatedActor,
        idempotency_key: str,
        method: str,
        path: str,
        digest: str,
    ) -> tuple[SupplierWriteRepository, IdempotencyClaim, datetime]:
        repository = SupplierWriteRepository(session)
        repository.acquire_api_locks(
            actor.organization_id,
            actor.user_id,
            idempotency_key,
        )
        organization = repository.lock_active_organization(actor.organization_id)
        if organization is None:
            raise _not_found()
        now = repository.database_now()
        claim = repository.claim_idempotency(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            idempotency_key=idempotency_key,
            request_method=method,
            request_path=path,
            request_hash=digest,
            now=now,
            expires_at=now + _IDEMPOTENCY_TTL,
        )
        return repository, claim, now


__all__ = [
    "SupplierManagementService",
    "SupplierMutationResult",
    "SupplierResolveResult",
]
