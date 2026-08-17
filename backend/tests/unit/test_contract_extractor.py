from decimal import Decimal
from uuid import UUID

from app.services.contract_extractor import ContractSourceBlock, extract_contract_candidate

PARSE_VERSION_ID = UUID("96000000-0000-4000-8000-000000000101")


def _block(index: int, text: str) -> ContractSourceBlock:
    return ContractSourceBlock(
        id=UUID(f"96000000-0000-4000-8000-{index + 110:012d}"),
        parse_version_id=PARSE_VERSION_ID,
        page_no=1,
        block_index=index,
        text=text,
        bbox={"left": 10, "top": index * 20, "width": 300, "height": 18},
        confidence=Decimal("0.95000"),
    )


def test_extracts_contract_fields_with_exact_evidence() -> None:
    blocks = tuple(
        _block(index, text)
        for index, text in enumerate(
            (
                "合同编号：CONTRACT-001",
                "合同名称：年度咨询服务合同",
                "甲方名称：测试采购方",
                "甲方税号：91310000BUYER0001X",
                "乙方名称：测试供应商",
                "乙方税号：91310000SELLER001X",
                "合同金额：100,000.00 CNY",
                "签订日期：2026-01-01",
                "生效日期：2026-01-01",
                "到期日期：2026-12-31",
                "付款方式：银行转账",
                "付款条件：验收后十个工作日内付款",
            )
        )
    )

    candidate = extract_contract_candidate(tuple(reversed(blocks)))

    assert candidate.facts.model_dump(mode="json") == {
        "contract_no": "CONTRACT-001",
        "name": "年度咨询服务合同",
        "party_a_name": "测试采购方",
        "party_a_tax_no": "91310000BUYER0001X",
        "party_b_name": "测试供应商",
        "party_b_tax_no": "91310000SELLER001X",
        "amount": "100000.00",
        "currency": "CNY",
        "signed_date": "2026-01-01",
        "effective_date": "2026-01-01",
        "expiry_date": "2026-12-31",
        "payment_method": "银行转账",
        "payment_terms": "验收后十个工作日内付款",
    }
    amount = next(item for item in candidate.field_evidence if item.field_code == "amount")
    currency = next(item for item in candidate.field_evidence if item.field_code == "currency")
    assert amount.evidence.block_id == blocks[6].id
    assert currency.evidence.block_id == blocks[6].id
    assert amount.evidence.quote_text == "合同金额：100,000.00 CNY"
    assert amount.evidence.confidence == "0.95000"


def test_conflicting_or_invalid_contract_values_remain_empty() -> None:
    candidate = extract_contract_candidate(
        (
            _block(0, "合同编号：CONTRACT-001"),
            _block(1, "合同编号：CONTRACT-002"),
            _block(2, "合同金额：-1.00"),
            _block(3, "生效日期：2026-02-30"),
            _block(4, "币种：人民币"),
            _block(5, "这是一段没有标签的标题"),
        )
    )

    assert candidate.facts.contract_no is None
    assert candidate.facts.amount is None
    assert candidate.facts.effective_date is None
    assert candidate.facts.currency is None
    assert candidate.facts.name is None
    assert candidate.field_evidence == ()
