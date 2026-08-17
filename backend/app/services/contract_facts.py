"""合同核心事实的规范投影、证据快照与关键哈希。"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import cast

from pydantic import JsonValue

from app.ai.policy import canonicalize_jcs
from app.models.financial import Contract, ContractField
from app.schemas.contracts import (
    CONTRACT_CORE_FIELD_CODES,
    ContractFactsWriteData,
    ContractFieldCode,
    ContractFieldValueType,
)

CONTRACT_FIELD_VALUE_TYPES: dict[ContractFieldCode, ContractFieldValueType] = {
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


def decimal_or_none(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def fact_json_value(facts: ContractFactsWriteData, field_code: ContractFieldCode) -> JsonValue:
    value = getattr(facts, field_code)
    if value is None:
        return None
    if field_code in {"signed_date", "effective_date", "expiry_date"}:
        return cast(JsonValue, value.isoformat())
    return cast(JsonValue, value)


def contract_critical_fact_hash(facts: ContractFactsWriteData) -> str:
    payload: JsonValue = [
        "contract-facts-v1",
        cast(JsonValue, facts.model_dump(mode="json")),
    ]
    return hashlib.sha256(canonicalize_jcs(payload)).hexdigest()


def contract_facts_from_model(contract: Contract) -> ContractFactsWriteData:
    return ContractFactsWriteData(
        contract_no=contract.contract_no,
        name=contract.name or None,
        party_a_name=contract.party_a_name,
        party_a_tax_no=contract.party_a_tax_no,
        party_b_name=contract.party_b_name,
        party_b_tax_no=contract.party_b_tax_no,
        amount=format(contract.amount, "f") if contract.amount is not None else None,
        currency=contract.currency,
        signed_date=contract.signed_date,
        effective_date=contract.effective_date,
        expiry_date=contract.expiry_date,
        payment_method=contract.payment_method,
        payment_terms=contract.payment_terms,
    )


def contract_snapshot(
    contract: Contract,
    fields: tuple[ContractField, ...],
) -> dict[str, object]:
    facts = contract_facts_from_model(contract)
    ordered = tuple(sorted(fields, key=lambda item: item.field_code))
    return {
        "facts": facts.model_dump(mode="json"),
        "fields": [
            {
                "field_code": field.field_code,
                "value_type": field.value_type,
                "candidate_value": field.extracted_value_json,
                "confirmed_value": field.confirmed_value_json,
                "confirmation_status": field.confirmation_status,
                "evidence": (
                    None
                    if field.evidence_block_id is None
                    else {
                        "block_id": str(field.evidence_block_id),
                        "parse_version_id": str(field.evidence_parse_version_id),
                        "page_no": field.page_no,
                        "quote_text": field.quote_text,
                        "bbox": field.bbox_json,
                        "confidence": (
                            format(field.confidence, "f") if field.confidence is not None else None
                        ),
                    }
                ),
            }
            for field in ordered
            if field.field_code in CONTRACT_CORE_FIELD_CODES
        ],
        "confirmation_status": contract.confirmation_status,
        "status": contract.status,
    }


__all__ = [
    "CONTRACT_FIELD_VALUE_TYPES",
    "contract_critical_fact_hash",
    "contract_facts_from_model",
    "contract_snapshot",
    "decimal_or_none",
    "fact_json_value",
]
