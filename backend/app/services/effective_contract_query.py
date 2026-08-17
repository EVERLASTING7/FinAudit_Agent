"""基准日期有效合同字段的数据库投影服务。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from math import isfinite
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.financial_read import EffectiveContractReadView, FinancialReadRepository
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import (
    ContractFieldValueType,
    EffectiveContractData,
    EffectiveContractFieldData,
    SupplementaryAgreementStatus,
)
from app.services.contract_effectivity import SupplementaryFieldChange, project_effective_fields

_CORE_FIELD_TYPES: dict[str, ContractFieldValueType] = {
    "contract_no": "string",
    "name": "string",
    "party_a_name": "string",
    "party_a_tax_no": "string",
    "party_b_name": "string",
    "party_b_tax_no": "string",
    "amount": "number",
    "currency": "string",
    "signed_date": "date",
    "effective_date": "date",
    "expiry_date": "date",
    "payment_method": "string",
    "payment_terms": "string",
}


def _json_value(value: object) -> object:
    if type(value) is Decimal:
        return format(value, "f")
    if type(value) is date:
        return value.isoformat()
    return value


def _public_field_value(value: object, value_type: str) -> JsonValue:
    if value is None:
        return None
    if value_type == "number":
        if type(value) is Decimal:
            numeric = value
        elif type(value) is int:
            numeric = Decimal(value)
        elif type(value) is float and isfinite(value):
            numeric = Decimal(str(value))
        elif type(value) is str:
            numeric = Decimal(value)
        else:
            raise RuntimeError("number field cannot be projected safely")
        if not numeric.is_finite():
            raise RuntimeError("number field cannot be projected safely")
        return format(numeric, "f")
    if value_type == "date" and type(value) is date:
        return value.isoformat()
    return cast(JsonValue, value)


def original_contract_fields(
    view: EffectiveContractReadView,
) -> tuple[dict[str, object], dict[str, str]]:
    contract = view.contract
    values = {
        "contract_no": contract.contract_no,
        "name": contract.name,
        "party_a_name": contract.party_a_name,
        "party_a_tax_no": contract.party_a_tax_no,
        "party_b_name": contract.party_b_name,
        "party_b_tax_no": contract.party_b_tax_no,
        "amount": _json_value(contract.amount),
        "currency": contract.currency,
        "signed_date": _json_value(contract.signed_date),
        "effective_date": _json_value(contract.effective_date),
        "expiry_date": _json_value(contract.expiry_date),
        "payment_method": contract.payment_method,
        "payment_terms": contract.payment_terms,
    }
    field_types: dict[str, str] = dict(_CORE_FIELD_TYPES)
    for item in view.extended_fields:
        if item.field_code in values:
            if field_types[item.field_code] != item.value_type or values[
                item.field_code
            ] != _json_value(item.value):
                raise RuntimeError("contract core field mirror is inconsistent")
            # 合同提取把字段证据保存在 contract_fields，当前权威值仍在 contracts。
            # 相同镜像属于证据元数据，不应作为覆盖核心字段的扩展字段处理。
            continue
        values[item.field_code] = item.value
        field_types[item.field_code] = item.value_type
    return values, field_types


def project_effective_contract(
    view: EffectiveContractReadView,
    baseline_date: date,
) -> EffectiveContractData:
    original, field_types = original_contract_fields(view)
    changes: list[SupplementaryFieldChange] = []
    for item in view.changes:
        if item.field_code not in field_types or field_types[item.field_code] != item.value_type:
            raise RuntimeError("supplementary change targets an unknown or incompatible field")
        changes.append(
            SupplementaryFieldChange(
                agreement_id=item.agreement_id,
                field_code=item.field_code,
                new_value=item.new_value,
                agreement_status=SupplementaryAgreementStatus(item.agreement_status),
                agreement_confirmation_status=ConfirmationStatus(
                    item.agreement_confirmation_status
                ),
                change_confirmation_status=ConfirmationStatus(item.change_confirmation_status),
                effective_date=item.effective_date,
            )
        )
    try:
        projection = project_effective_fields(original, tuple(changes), baseline_date)
    except ValueError as error:
        if str(error) == "conflicting supplementary agreement field changes":
            raise AppError(
                status_code=409,
                code="EFFECTIVE_FIELD_CONFLICT",
                message="同一字段存在冲突的生效协议",
            ) from None
        raise
    materialized = projection.materialize_field_values()
    fields = tuple(
        EffectiveContractFieldData(
            field_code=field_code,
            value_type=cast(ContractFieldValueType, field_types[field_code]),
            original_value=_public_field_value(original[field_code], field_types[field_code]),
            effective_value=_public_field_value(materialized[field_code], field_types[field_code]),
            source_agreement_id=projection.field_sources[field_code].agreement_id,
            source_effective_date=projection.field_sources[field_code].effective_date,
        )
        for field_code in sorted(original)
    )
    return EffectiveContractData(
        id=view.contract.id,
        baseline_date=baseline_date,
        confirmation_status=ConfirmationStatus(view.contract.confirmation_status),
        fields=fields,
        applied_agreement_ids=projection.applied_agreement_ids,
        row_version=str(view.contract.row_version),
    )


class EffectiveContractQueryService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_effective_contract(
        self,
        organization_id: UUID,
        contract_id: UUID,
        baseline_date: date,
    ) -> EffectiveContractData:
        with self._session_factory() as session:
            view = FinancialReadRepository(session).read_effective_contract(
                organization_id,
                contract_id,
            )
        if view is None:
            raise AppError(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                message="目标资源不存在或不可见",
            )
        return project_effective_contract(view, baseline_date)


__all__ = [
    "EffectiveContractQueryService",
    "original_contract_fields",
    "project_effective_contract",
]
