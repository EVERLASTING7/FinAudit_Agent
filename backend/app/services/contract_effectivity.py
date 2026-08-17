"""CON-003 补充协议变更的纯生效资格判定。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from math import isfinite
from types import MappingProxyType
from typing import cast
from uuid import UUID

from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import SupplementaryAgreementStatus


def _validate_field_code(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("field_code must be a non-empty exact str")
    return value


def _freeze_field_value(value: object) -> object:
    value_type = type(value)
    if value is None or value_type in (bool, int, str, date, UUID):
        return value
    if value_type is Decimal:
        if not cast(Decimal, value).is_finite():
            raise ValueError("contract field values must be finite")
        return value
    if value_type is float:
        if not isfinite(cast(float, value)):
            raise ValueError("contract field values must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, child in value.items():
            if type(key) is not str:
                raise ValueError("contract field object keys must be exact str values")
            frozen[key] = _freeze_field_value(child)
        return MappingProxyType(frozen)
    if value_type in (list, tuple):
        sequence = cast(list[object] | tuple[object, ...], value)
        return tuple(_freeze_field_value(child) for child in sequence)
    raise ValueError("contract field value type is not supported")


def _materialize_field_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _materialize_field_value(child) for key, child in value.items()}
    if type(value) is tuple:
        return [_materialize_field_value(child) for child in cast(tuple[object, ...], value)]
    return value


def _validate_effectivity_inputs(
    *,
    agreement_status: SupplementaryAgreementStatus,
    agreement_confirmation_status: ConfirmationStatus,
    change_confirmation_status: ConfirmationStatus,
    effective_date: date,
    baseline_date: date,
) -> None:
    if type(agreement_status) is not SupplementaryAgreementStatus:
        raise ValueError("agreement_status must be a SupplementaryAgreementStatus")
    if type(agreement_confirmation_status) is not ConfirmationStatus:
        raise ValueError("agreement_confirmation_status must be a ConfirmationStatus")
    if type(change_confirmation_status) is not ConfirmationStatus:
        raise ValueError("change_confirmation_status must be a ConfirmationStatus")
    if type(effective_date) is not date:
        raise ValueError("effective_date must be an exact datetime.date")
    if type(baseline_date) is not date:
        raise ValueError("baseline_date must be an exact datetime.date")


def is_supplementary_change_effective(
    *,
    agreement_status: SupplementaryAgreementStatus,
    agreement_confirmation_status: ConfirmationStatus,
    change_confirmation_status: ConfirmationStatus,
    effective_date: date,
    baseline_date: date,
) -> bool:
    """判断单个已确认补充协议变更是否已在基准日期生效。"""

    _validate_effectivity_inputs(
        agreement_status=agreement_status,
        agreement_confirmation_status=agreement_confirmation_status,
        change_confirmation_status=change_confirmation_status,
        effective_date=effective_date,
        baseline_date=baseline_date,
    )

    return bool(
        agreement_status is SupplementaryAgreementStatus.CONFIRMED
        and agreement_confirmation_status is ConfirmationStatus.CONFIRMED
        and change_confirmation_status is ConfirmationStatus.CONFIRMED
        and effective_date <= baseline_date
    )


@dataclass(frozen=True, slots=True)
class SupplementaryFieldChange:
    """可参与基准日期投影的单个补充协议字段变更。"""

    agreement_id: UUID
    field_code: str
    new_value: object = field(repr=False)
    agreement_status: SupplementaryAgreementStatus
    agreement_confirmation_status: ConfirmationStatus
    change_confirmation_status: ConfirmationStatus
    effective_date: date

    def __post_init__(self) -> None:
        if type(self.agreement_id) is not UUID:
            raise ValueError("agreement_id must be an exact uuid.UUID")
        _validate_field_code(self.field_code)
        _validate_effectivity_inputs(
            agreement_status=self.agreement_status,
            agreement_confirmation_status=self.agreement_confirmation_status,
            change_confirmation_status=self.change_confirmation_status,
            effective_date=self.effective_date,
            baseline_date=self.effective_date,
        )
        object.__setattr__(self, "new_value", _freeze_field_value(self.new_value))


@dataclass(frozen=True, slots=True)
class EffectiveFieldSource:
    """有效字段来源；两个空值表示仍来自原合同。"""

    agreement_id: UUID | None = None
    effective_date: date | None = None

    def __post_init__(self) -> None:
        if (self.agreement_id is None) != (self.effective_date is None):
            raise ValueError(
                "source agreement_id and effective_date must both be set or both be null"
            )
        if self.agreement_id is not None and type(self.agreement_id) is not UUID:
            raise ValueError("source agreement_id must be an exact uuid.UUID or None")
        if self.effective_date is not None and type(self.effective_date) is not date:
            raise ValueError("source effective_date must be an exact datetime.date or None")


def _copy_field_mapping(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    copied: dict[str, object] = {}
    for field_code, field_value in value.items():
        copied[_validate_field_code(field_code)] = _freeze_field_value(field_value)
    return copied


@dataclass(frozen=True, slots=True)
class EffectiveFieldsProjection:
    """基准日期字段值、逐字段来源和实际采用的补充协议。"""

    field_values: Mapping[str, object] = field(repr=False)
    field_sources: Mapping[str, EffectiveFieldSource]
    applied_agreement_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        values = _copy_field_mapping(self.field_values, name="field_values")
        if not isinstance(self.field_sources, Mapping):
            raise ValueError("field_sources must be a mapping")
        sources: dict[str, EffectiveFieldSource] = {}
        for field_code, source in self.field_sources.items():
            validated_code = _validate_field_code(field_code)
            if type(source) is not EffectiveFieldSource:
                raise ValueError("field_sources values must be EffectiveFieldSource")
            sources[validated_code] = source
        if values.keys() != sources.keys():
            raise ValueError("field_values and field_sources must contain the same fields")
        if type(self.applied_agreement_ids) is not tuple or any(
            type(agreement_id) is not UUID for agreement_id in self.applied_agreement_ids
        ):
            raise ValueError("applied_agreement_ids must be a tuple of uuid.UUID values")
        if len(set(self.applied_agreement_ids)) != len(self.applied_agreement_ids):
            raise ValueError("applied_agreement_ids must be unique")
        object.__setattr__(self, "field_values", MappingProxyType(values))
        object.__setattr__(self, "field_sources", MappingProxyType(sources))

    def materialize_field_values(self) -> dict[str, object]:
        """为 Pydantic/API 输出边界生成与内部冻结事实隔离的新容器。"""

        return {
            field_code: _materialize_field_value(value)
            for field_code, value in self.field_values.items()
        }


def project_effective_fields(
    original_fields: Mapping[str, object],
    changes: tuple[SupplementaryFieldChange, ...],
    baseline_date: date,
) -> EffectiveFieldsProjection:
    """按基准日期重放无歧义的已确认变更，不修改原字段映射。"""

    projected_values = _copy_field_mapping(original_fields, name="original_fields")
    if type(changes) is not tuple or any(
        type(change) is not SupplementaryFieldChange for change in changes
    ):
        raise ValueError("changes must be a tuple of SupplementaryFieldChange values")
    if type(baseline_date) is not date:
        raise ValueError("baseline_date must be an exact datetime.date")

    seen_agreement_fields: set[tuple[UUID, str]] = set()
    agreement_facts: dict[
        UUID,
        tuple[SupplementaryAgreementStatus, ConfirmationStatus, date],
    ] = {}
    change_statuses: dict[UUID, list[ConfirmationStatus]] = {}
    for change in changes:
        agreement_field_key = change.agreement_id, change.field_code
        if agreement_field_key in seen_agreement_fields:
            raise ValueError("duplicate supplementary agreement field change")
        seen_agreement_fields.add(agreement_field_key)

        facts = (
            change.agreement_status,
            change.agreement_confirmation_status,
            change.effective_date,
        )
        existing_facts = agreement_facts.setdefault(change.agreement_id, facts)
        if existing_facts != facts:
            raise ValueError("supplementary agreement facts must be consistent")
        change_statuses.setdefault(change.agreement_id, []).append(
            change.change_confirmation_status
        )

    fully_confirmed_agreement_ids = {
        agreement_id
        for agreement_id, statuses in change_statuses.items()
        if all(status is ConfirmationStatus.CONFIRMED for status in statuses)
    }

    applicable = sorted(
        (
            change
            for change in changes
            if change.agreement_id in fully_confirmed_agreement_ids
            and is_supplementary_change_effective(
                agreement_status=change.agreement_status,
                agreement_confirmation_status=change.agreement_confirmation_status,
                change_confirmation_status=change.change_confirmation_status,
                effective_date=change.effective_date,
                baseline_date=baseline_date,
            )
        ),
        key=lambda change: (change.field_code, change.effective_date, change.agreement_id.bytes),
    )

    seen_field_dates: set[tuple[str, date]] = set()
    for change in applicable:
        field_date_key = change.field_code, change.effective_date
        if field_date_key in seen_field_dates:
            raise ValueError("conflicting supplementary agreement field changes")
        seen_field_dates.add(field_date_key)

    sources = {field_code: EffectiveFieldSource() for field_code in projected_values}
    applied_agreement_ids: list[UUID] = []
    for change in sorted(
        applicable,
        key=lambda item: (item.effective_date, item.agreement_id.bytes, item.field_code),
    ):
        projected_values[change.field_code] = change.new_value
        sources[change.field_code] = EffectiveFieldSource(
            agreement_id=change.agreement_id,
            effective_date=change.effective_date,
        )
        if change.agreement_id not in applied_agreement_ids:
            applied_agreement_ids.append(change.agreement_id)

    return EffectiveFieldsProjection(
        field_values=projected_values,
        field_sources=sources,
        applied_agreement_ids=tuple(applied_agreement_ids),
    )
