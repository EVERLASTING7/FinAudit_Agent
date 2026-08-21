"""从已持久化文档块生成未确认的发票事实候选。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
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
_ENGLISH_AMOUNT_PATTERN = re.compile(
    r"^\s*(?:(?P<prefix>[A-Za-z]{3})\s*)?[\$€£¥]?\s*"
    r"(?P<amount>-?[0-9][0-9,]*(?:\.[0-9]+)?)"
    r"(?:\s*(?P<suffix>[A-Za-z]{3}))?\s*$"
)
_ENGLISH_VALUE_END = (
    r"(?=\s{2,}(?:invoice|date|due|terms|purchase|order|subtotal|sales\s+tax|"
    r"total|amount|ship\s+to|bill\s+to|customer|currency)\b|$)"
)
_ENGLISH_FIELD_PATTERNS: tuple[tuple[InvoiceFieldCode, re.Pattern[str]], ...] = (
    (
        "invoice_number",
        re.compile(
            r"\binvoice\s*(?:number|no\.?|#|id)\s*[:#-]?\s*"
            r"(?P<value>(?=[A-Z0-9./-]*\d)[A-Z0-9][A-Z0-9./-]{0,49})",
            re.IGNORECASE,
        ),
    ),
    (
        "invoice_date",
        re.compile(
            r"\binvoice\s+date\s*[:#-]?\s*"
            r"(?P<value>\d{1,4}[/-]\d{1,2}[/-]\d{1,4})",
            re.IGNORECASE,
        ),
    ),
    (
        "buyer_name",
        re.compile(
            r"\b(?:bill|invoice)\s+to\s*[:#-]?\s*"
            r"(?P<value>[A-Z][A-Z0-9&.,'() -]{1,299}?)" + _ENGLISH_VALUE_END,
            re.IGNORECASE,
        ),
    ),
    (
        "seller_name",
        re.compile(
            r"\b(?:vendor|supplier|seller)\s*(?:name)?\s*[:#-]?\s*"
            r"(?P<value>[A-Z][A-Z0-9&.,'() -]{1,299}?)" + _ENGLISH_VALUE_END,
            re.IGNORECASE,
        ),
    ),
    (
        "seller_tax_no",
        re.compile(
            r"\b(?:federal\s+id|vendor\s+tax\s+id|seller\s+tax\s+id|fein|ein)"
            r"\s*[:#-]?\s*(?P<value>(?=[A-Z0-9-]*\d)[A-Z0-9-]{2,32})",
            re.IGNORECASE,
        ),
    ),
    (
        "amount_excluding_tax",
        re.compile(
            r"\bsub\s*total\s*[:#-]?\s*"
            r"(?P<value>(?:[A-Z]{3}\s*)?[\$€£¥]?\s*-?[0-9][0-9,]*(?:\.[0-9]+)?"
            r"(?:\s*[A-Z]{3})?)",
            re.IGNORECASE,
        ),
    ),
    (
        "tax_amount",
        re.compile(
            r"\b(?:sales\s+tax|tax\s+total|total\s+tax)\s*[:#-]?\s*"
            r"(?P<value>(?:[A-Z]{3}\s*)?[\$€£¥]?\s*-?[0-9][0-9,]*(?:\.[0-9]+)?"
            r"(?:\s*[A-Z]{3})?)",
            re.IGNORECASE,
        ),
    ),
    (
        "total_amount",
        re.compile(
            r"(?:\b(?:invoice\s+total|amount\s+due|total\s+due|balance\s+due|"
            r"grand\s+total)|(?:^|\s{2,})total)\s*[:#-]?\s*"
            r"(?P<value>(?:[A-Z]{3}\s*)?[\$€£¥]?\s*-?[0-9][0-9,]*(?:\.[0-9]+)?"
            r"(?:\s*[A-Z]{3})?)",
            re.IGNORECASE,
        ),
    ),
    (
        "currency",
        re.compile(r"\bcurrency\s*[:#-]?\s*(?P<value>[A-Z]{3})\b", re.IGNORECASE),
    ),
)
_STANDARD_INVOICE_PATTERN = re.compile(
    r"(?:^\s*(?:tax\s+)?invoice\s*$|\s{2,}(?:tax\s+)?invoice\s*$)",
    re.IGNORECASE,
)
_CREDIT_INVOICE_PATTERN = re.compile(r"\bcredit\s+(?:memo|note)\b", re.IGNORECASE)
_SELLER_BEFORE_INVOICE_PATTERN = re.compile(
    r"^\s*(?P<value>[A-Z][A-Z0-9&.,'() -]{1,299}?)\s{2,}"
    r"(?:tax\s+)?invoice(?:\s+(?:id|number|no\.?|#))?\b",
    re.IGNORECASE,
)
_ENGLISH_HEADER_PATTERNS: tuple[tuple[InvoiceFieldCode, re.Pattern[str]], ...] = (
    (
        "invoice_number",
        re.compile(r"\binvoice\s*(?:number|no\.?|#|id)\b", re.IGNORECASE),
    ),
    ("invoice_date", re.compile(r"\binvoice\s+date\b", re.IGNORECASE)),
    ("buyer_name", re.compile(r"\b(?:bill|invoice)\s+to\b", re.IGNORECASE)),
    ("seller_tax_no", re.compile(r"\b(?:federal\s+id|fein|ein)\b", re.IGNORECASE)),
    ("amount_excluding_tax", re.compile(r"\bsub\s*total\b", re.IGNORECASE)),
    (
        "tax_amount",
        re.compile(r"\b(?:sales\s+tax|tax\s+total|total\s+tax)\b", re.IGNORECASE),
    ),
    (
        "total_amount",
        re.compile(
            r"\b(?:invoice\s+total|amount\s+due|total\s+due|balance\s+due|"
            r"grand\s+total)\b",
            re.IGNORECASE,
        ),
    ),
    ("currency", re.compile(r"\bcurrency\b", re.IGNORECASE)),
)
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


def _tax_identifier(value: str) -> str | None:
    normalized = re.sub(r"[\s-]", "", value).upper()
    return (
        normalized
        if normalized
        and len(normalized) <= 32
        and re.fullmatch(r"[A-Z0-9]+", normalized) is not None
        else None
    )


def _date_value(value: str) -> str | None:
    normalized = "".join(value.split())
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            if pattern == "%Y-%m-%d":
                return date.fromisoformat(normalized).isoformat()
            return datetime.strptime(normalized, pattern).date().isoformat()
        except ValueError:
            pass
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


def _amount_value(value: str) -> tuple[str | None, str | None]:
    match = _ENGLISH_AMOUNT_PATTERN.fullmatch(value)
    if match is None:
        return _decimal_value(value), None
    amount = _decimal_value(match.group("amount"))
    currency = _currency(match.group("prefix") or match.group("suffix") or "")
    return amount, currency


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
    "buyer_tax_no": _tax_identifier,
    "seller_name": lambda value: _text_value(value, limit=300),
    "seller_tax_no": _tax_identifier,
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


def _english_labeled_values(text: str) -> tuple[tuple[InvoiceFieldCode, str], ...]:
    values = [
        (field_code, match.group("value"))
        for field_code, pattern in _ENGLISH_FIELD_PATTERNS
        if (match := pattern.search(text)) is not None
    ]
    if match := _CREDIT_INVOICE_PATTERN.search(text):
        del match
        values.extend((("invoice_type", "credit"), ("is_red_invoice", "true")))
    elif _STANDARD_INVOICE_PATTERN.search(text) is not None:
        values.extend((("invoice_type", "standard"), ("is_red_invoice", "false")))
    if match := _SELLER_BEFORE_INVOICE_PATTERN.search(text):
        values.append(("seller_name", match.group("value")))
    return tuple(values)


def _english_following_values(
    block: InvoiceSourceBlock,
    following: InvoiceSourceBlock | None,
) -> tuple[tuple[InvoiceFieldCode, str, InvoiceSourceBlock], ...]:
    if (
        following is None
        or following.page_no != block.page_no
        or following.block_index != block.block_index + 1
        or any(character.isdigit() for character in block.text)
    ):
        return ()
    headers = sorted(
        (
            (match.start(), match.end(), field_code)
            for field_code, pattern in _ENGLISH_HEADER_PATTERNS
            if (match := pattern.search(block.text)) is not None
        ),
        key=lambda item: item[0],
    )
    values: list[tuple[InvoiceFieldCode, str, InvoiceSourceBlock]] = []
    for index, (start, _, field_code) in enumerate(headers):
        end = headers[index + 1][0] if index + 1 < len(headers) else len(following.text)
        if start >= len(following.text):
            continue
        value = following.text[start:end].strip()
        if field_code == "invoice_number" and not any(character.isdigit() for character in value):
            continue
        if value:
            values.append((field_code, value, following))
    return tuple(values)


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


def _select(
    selected: dict[InvoiceFieldCode, tuple[str, InvoiceSourceBlock]],
    ambiguous: set[InvoiceFieldCode],
    field_code: InvoiceFieldCode,
    value: str,
    block: InvoiceSourceBlock,
) -> None:
    previous = selected.get(field_code)
    if previous is None and field_code not in ambiguous:
        selected[field_code] = (value, block)
    elif previous is not None and previous[0] != value:
        selected.pop(field_code, None)
        ambiguous.add(field_code)


def extract_invoice_candidate(
    blocks: tuple[InvoiceSourceBlock, ...],
) -> InvoiceExtractionCandidate:
    """确定性提取候选；冲突字段留空，且永不产生确认事实。"""

    ordered = tuple(sorted(blocks, key=lambda item: (item.page_no, item.block_index, item.id.int)))
    selected: dict[InvoiceFieldCode, tuple[str, InvoiceSourceBlock]] = {}
    ambiguous: set[InvoiceFieldCode] = set()
    item_candidates: list[InvoiceItemWriteData] = []
    for index, block in enumerate(ordered):
        if not block.text or len(block.text) > 4000 or block.page_no < 1:
            continue
        english_values = _english_labeled_values(block.text)
        labeled_values = [
            (field_code, raw_value, block) for field_code, raw_value in english_values
        ]
        direct_english_fields = {field_code for field_code, _ in english_values}
        labeled_values.extend(
            value
            for value in _english_following_values(
                block, ordered[index + 1] if index + 1 < len(ordered) else None
            )
            if value[0] not in direct_english_fields
        )
        labeled = _labeled_value(block.text)
        if labeled is not None:
            labeled_values.append((labeled[0], labeled[1], block))
        if labeled_values:
            for field_code, raw_value, source_block in labeled_values:
                if field_code in {"amount_excluding_tax", "tax_amount", "total_amount"}:
                    parsed, parsed_currency = _amount_value(raw_value)
                    if parsed_currency is not None:
                        _select(
                            selected,
                            ambiguous,
                            "currency",
                            parsed_currency,
                            source_block,
                        )
                else:
                    parsed = _PARSERS[field_code](raw_value)
                if parsed is None or len(parsed) > _FIELD_LIMITS[field_code]:
                    continue
                _select(selected, ambiguous, field_code, parsed, source_block)
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
