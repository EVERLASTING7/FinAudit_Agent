"""从已持久化文档块确定性生成未确认合同候选。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID

from app.schemas.contracts import (
    CONTRACT_CORE_FIELD_CODES,
    ContractEvidenceData,
    ContractFactsWriteData,
    ContractFieldCode,
    ContractFieldEvidenceData,
)

_DECIMAL_PATTERN = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d+)?$")
_AMOUNT_WITH_CURRENCY = re.compile(
    r"^\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:元)?\s*([A-Za-z]{3})?\s*$"
)
_LABELS: dict[str, ContractFieldCode] = {
    "合同编号": "contract_no",
    "合同名称": "name",
    "甲方": "party_a_name",
    "甲方名称": "party_a_name",
    "甲方税号": "party_a_tax_no",
    "乙方": "party_b_name",
    "乙方名称": "party_b_name",
    "乙方税号": "party_b_tax_no",
    "合同金额": "amount",
    "金额": "amount",
    "币种": "currency",
    "签订日期": "signed_date",
    "签署日期": "signed_date",
    "生效日期": "effective_date",
    "到期日期": "expiry_date",
    "终止日期": "expiry_date",
    "付款方式": "payment_method",
    "付款条件": "payment_terms",
}
_FIELD_LIMITS: dict[ContractFieldCode, int] = {
    "contract_no": 100,
    "name": 300,
    "party_a_name": 300,
    "party_a_tax_no": 32,
    "party_b_name": 300,
    "party_b_tax_no": 32,
    "amount": 21,
    "currency": 3,
    "signed_date": 10,
    "effective_date": 10,
    "expiry_date": 10,
    "payment_method": 100,
    "payment_terms": 4000,
}


@dataclass(frozen=True, slots=True)
class ContractSourceBlock:
    id: UUID
    parse_version_id: UUID
    page_no: int
    block_index: int
    text: str
    bbox: dict[str, object] | None
    confidence: Decimal | None


@dataclass(frozen=True, slots=True)
class ContractExtractionCandidate:
    facts: ContractFactsWriteData
    field_evidence: tuple[ContractFieldEvidenceData, ...]


def _text_value(value: str, *, limit: int) -> str | None:
    normalized = " ".join(value.strip().split())
    return normalized if normalized and len(normalized) <= limit else None


def _identifier(value: str, *, limit: int) -> str | None:
    normalized = "".join(value.split()).upper()
    return normalized if normalized and len(normalized) <= limit else None


def _date_value(value: str) -> str | None:
    normalized = "".join(value.split())
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError:
        return None


def _decimal_value(value: str) -> str | None:
    normalized = "".join(value.split()).replace(",", "")
    if _DECIMAL_PATTERN.fullmatch(normalized) is None:
        return None
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0:
        return None
    exponent = cast(int, number.as_tuple().exponent)
    if exponent < -2:
        return None
    integer_digits = max(number.adjusted() + 1, 1) if number else 1
    return format(number, "f") if integer_digits <= 16 else None


def _currency(value: str) -> str | None:
    normalized = "".join(value.split()).upper()
    return normalized if re.fullmatch(r"[A-Z]{3}", normalized) is not None else None


_PARSERS: dict[ContractFieldCode, Callable[[str], str | None]] = {
    "contract_no": lambda value: _identifier(value, limit=100),
    "name": lambda value: _text_value(value, limit=300),
    "party_a_name": lambda value: _text_value(value, limit=300),
    "party_a_tax_no": lambda value: _identifier(value, limit=32),
    "party_b_name": lambda value: _text_value(value, limit=300),
    "party_b_tax_no": lambda value: _identifier(value, limit=32),
    "amount": _decimal_value,
    "currency": _currency,
    "signed_date": _date_value,
    "effective_date": _date_value,
    "expiry_date": _date_value,
    "payment_method": lambda value: _text_value(value, limit=100),
    "payment_terms": lambda value: _text_value(value, limit=4000),
}


def _labeled_value(text: str) -> tuple[ContractFieldCode, str] | None:
    normalized = text.replace("：", ":").strip()
    if ":" in normalized:
        raw_label, value = normalized.split(":", maxsplit=1)
        field_code = _LABELS.get("".join(raw_label.split()))
        return None if field_code is None else (field_code, value)
    compact = "".join(normalized.split())
    for label in sorted(_LABELS, key=len, reverse=True):
        if compact.startswith(label) and len(compact) > len(label):
            return _LABELS[label], compact[len(label) :]
    return None


def _evidence(block: ContractSourceBlock) -> ContractEvidenceData:
    return ContractEvidenceData(
        block_id=block.id,
        parse_version_id=block.parse_version_id,
        page_no=block.page_no,
        quote_text=block.text,
        bbox=None if block.bbox is None else dict(block.bbox),  # type: ignore[arg-type]
        confidence=None if block.confidence is None else format(block.confidence, "f"),
    )


def _select(
    selected: dict[ContractFieldCode, tuple[str, ContractSourceBlock]],
    ambiguous: set[ContractFieldCode],
    field_code: ContractFieldCode,
    value: str,
    block: ContractSourceBlock,
) -> None:
    previous = selected.get(field_code)
    if previous is None and field_code not in ambiguous:
        selected[field_code] = (value, block)
    elif previous is not None and previous[0] != value:
        selected.pop(field_code, None)
        ambiguous.add(field_code)


def extract_contract_candidate(
    blocks: tuple[ContractSourceBlock, ...],
) -> ContractExtractionCandidate:
    """只接受带标签且无冲突的值；缺失字段保持空值。"""

    ordered = tuple(sorted(blocks, key=lambda item: (item.page_no, item.block_index, item.id.int)))
    selected: dict[ContractFieldCode, tuple[str, ContractSourceBlock]] = {}
    ambiguous: set[ContractFieldCode] = set()
    for block in ordered:
        if not block.text or len(block.text) > 4000 or block.page_no < 1:
            continue
        labeled = _labeled_value(block.text)
        if labeled is None:
            continue
        field_code, raw_value = labeled
        parsed = _PARSERS[field_code](raw_value)
        if field_code == "amount":
            combined = _AMOUNT_WITH_CURRENCY.fullmatch(raw_value)
            if combined is not None:
                parsed = _decimal_value(combined.group(1))
                parsed_currency = _currency(combined.group(2) or "")
                if parsed_currency is not None:
                    _select(selected, ambiguous, "currency", parsed_currency, block)
        if parsed is None or len(parsed) > _FIELD_LIMITS[field_code]:
            continue
        _select(selected, ambiguous, field_code, parsed, block)

    fact_values: dict[str, object] = {field_code: None for field_code in CONTRACT_CORE_FIELD_CODES}
    evidence: list[ContractFieldEvidenceData] = []
    for field_code, (value, block) in selected.items():
        fact_values[field_code] = (
            date.fromisoformat(value)
            if field_code in {"signed_date", "effective_date", "expiry_date"}
            else value
        )
        evidence.append(ContractFieldEvidenceData(field_code=field_code, evidence=_evidence(block)))
    evidence.sort(key=lambda item: CONTRACT_CORE_FIELD_CODES.index(item.field_code))
    return ContractExtractionCandidate(
        facts=ContractFactsWriteData.model_validate(fact_values),
        field_evidence=tuple(evidence),
    )


__all__ = [
    "ContractExtractionCandidate",
    "ContractSourceBlock",
    "extract_contract_candidate",
]
