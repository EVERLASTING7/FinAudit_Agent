"""从已持久化文档块生成未确认的发票事实候选。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID

from app.schemas.invoices import (
    InvoiceEvidenceData,
    InvoiceFactsWriteData,
    InvoiceFieldCode,
    InvoiceFieldEvidenceData,
    InvoiceItemWriteData,
)

_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_LABELS: dict[str, InvoiceFieldCode] = {
    "发票代码": "invoice_code",
    "发票号码": "invoice_number",
    "发票类型": "invoice_type",
    "是否红字": "is_red_invoice",
    "开票日期": "invoice_date",
    "购买方名称": "buyer_name",
    "购买方税号": "buyer_tax_no",
    "销售方名称": "seller_name",
    "销售方税号": "seller_tax_no",
    "不含税金额": "amount_excluding_tax",
    "税额": "tax_amount",
    "价税合计": "total_amount",
    "币种": "currency",
}
_FIELD_LIMITS: dict[InvoiceFieldCode, int] = {
    "invoice_code": 50,
    "invoice_number": 50,
    "invoice_type": 40,
    "is_red_invoice": 5,
    "buyer_name": 300,
    "buyer_tax_no": 32,
    "seller_name": 300,
    "seller_tax_no": 32,
    "currency": 3,
    "invoice_date": 10,
    "amount_excluding_tax": 21,
    "tax_amount": 21,
    "total_amount": 21,
}


@dataclass(frozen=True, slots=True)
class InvoiceSourceBlock:
    id: UUID
    parse_version_id: UUID
    page_no: int
    block_index: int
    text: str
    bbox: dict[str, object] | None
    confidence: Decimal | None


@dataclass(frozen=True, slots=True)
class InvoiceExtractionCandidate:
    facts: InvoiceFactsWriteData
    field_evidence: tuple[InvoiceFieldEvidenceData, ...]
    items: tuple[InvoiceItemWriteData, ...]


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
    if not number.is_finite():
        return None
    exponent = cast(int, number.as_tuple().exponent)
    if exponent < -2:
        return None
    integer_digits = max(number.adjusted() + 1, 1) if number else 1
    if integer_digits > 16:
        return None
    return format(number, "f")


def _currency(value: str) -> str | None:
    normalized = "".join(value.split()).upper()
    return normalized if re.fullmatch(r"[A-Z]{3}", normalized) is not None else None


def _red_invoice_flag(value: str) -> str | None:
    normalized = "".join(value.split()).casefold()
    if normalized in {"是", "true", "1", "红字"}:
        return "true"
    if normalized in {"否", "false", "0", "正常"}:
        return "false"
    return None


_PARSERS: dict[InvoiceFieldCode, Callable[[str], str | None]] = {
    "invoice_code": lambda value: _identifier(value, limit=50),
    "invoice_number": lambda value: _identifier(value, limit=50),
    "invoice_type": lambda value: _text_value(value, limit=40),
    "is_red_invoice": _red_invoice_flag,
    "invoice_date": _date_value,
    "buyer_name": lambda value: _text_value(value, limit=300),
    "buyer_tax_no": lambda value: _identifier(value, limit=32),
    "seller_name": lambda value: _text_value(value, limit=300),
    "seller_tax_no": lambda value: _identifier(value, limit=32),
    "amount_excluding_tax": _decimal_value,
    "tax_amount": _decimal_value,
    "total_amount": _decimal_value,
    "currency": _currency,
}


def _labeled_value(text: str) -> tuple[InvoiceFieldCode, str] | None:
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


def _evidence(block: InvoiceSourceBlock) -> InvoiceEvidenceData:
    bbox = None if block.bbox is None else dict(block.bbox)
    return InvoiceEvidenceData(
        block_id=block.id,
        parse_version_id=block.parse_version_id,
        page_no=block.page_no,
        quote_text=block.text,
        bbox=bbox,  # type: ignore[arg-type]
        confidence=None if block.confidence is None else format(block.confidence, "f"),
    )


def extract_invoice_candidate(
    blocks: tuple[InvoiceSourceBlock, ...],
) -> InvoiceExtractionCandidate:
    """确定性提取候选；冲突字段留空，且永不产生确认事实。"""

    ordered = tuple(sorted(blocks, key=lambda item: (item.page_no, item.block_index, item.id.int)))
    selected: dict[InvoiceFieldCode, tuple[str, InvoiceSourceBlock]] = {}
    ambiguous: set[InvoiceFieldCode] = set()
    item_candidates: list[InvoiceItemWriteData] = []
    for block in ordered:
        if not block.text or len(block.text) > 4000 or block.page_no < 1:
            continue
        labeled = _labeled_value(block.text)
        if labeled is not None:
            field_code, raw_value = labeled
            parsed = _PARSERS[field_code](raw_value)
            if parsed is None or len(parsed) > _FIELD_LIMITS[field_code]:
                continue
            previous = selected.get(field_code)
            if previous is None and field_code not in ambiguous:
                selected[field_code] = (parsed, block)
            elif previous is not None and previous[0] != parsed:
                selected.pop(field_code, None)
                ambiguous.add(field_code)
            continue

        normalized = block.text.replace("：", ":").strip()
        if normalized.startswith("明细:"):
            name = _text_value(normalized.split(":", maxsplit=1)[1], limit=500)
            if name is not None and len(item_candidates) < 1000:
                item_candidates.append(
                    InvoiceItemWriteData(
                        line_no=len(item_candidates) + 1,
                        item_name=name,
                        evidence=(_evidence(block),),
                    )
                )

    facts_values: dict[str, object] = {
        "invoice_code": None,
        "invoice_number": None,
        "invoice_type": None,
        "is_red_invoice": None,
        "invoice_date": None,
        "buyer_name": None,
        "buyer_tax_no": None,
        "seller_name": None,
        "seller_tax_no": None,
        "amount_excluding_tax": None,
        "tax_amount": None,
        "total_amount": None,
        "currency": None,
    }
    field_evidence: list[InvoiceFieldEvidenceData] = []
    for field_code, (value, block) in selected.items():
        facts_values[field_code] = (
            date.fromisoformat(value)
            if field_code == "invoice_date"
            else value == "true"
            if field_code == "is_red_invoice"
            else value
        )
        field_evidence.append(
            InvoiceFieldEvidenceData(field_code=field_code, evidence=_evidence(block))
        )
    field_evidence.sort(key=lambda item: item.field_code)
    return InvoiceExtractionCandidate(
        facts=InvoiceFactsWriteData.model_validate(facts_values),
        field_evidence=tuple(field_evidence),
        items=tuple(item_candidates),
    )


__all__ = [
    "InvoiceExtractionCandidate",
    "InvoiceSourceBlock",
    "extract_invoice_candidate",
]
