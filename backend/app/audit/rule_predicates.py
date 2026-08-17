"""P0 审核规则的纯离线判定谓词。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from fractions import Fraction


class RuleExecutionStatus(str, Enum):
    """规则执行状态；`failed` 表示规则命中。"""

    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class RulePredicateResult:
    """规则谓词返回的最小不可变结果。"""

    status: RuleExecutionStatus

    def __post_init__(self) -> None:
        if type(self.status) is not RuleExecutionStatus:
            raise ValueError("status must be a RuleExecutionStatus")


def _validate_exact_bool(value: object, *, name: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be an exact bool")


def _validate_optional_exact_bool(value: object, *, name: str) -> None:
    if value is not None and type(value) is not bool:
        raise ValueError(f"{name} must be an exact bool or None")


def _validate_optional_non_blank_str(value: object, *, name: str) -> None:
    if value is not None and (type(value) is not str or not value.strip()):
        raise ValueError(f"{name} must be a non-blank exact str or None")


def evaluate_rule_001(
    has_confirmed_primary_contract: bool,
    contract_party_b_tax_no: str | None,
    invoice_seller_tax_no: str | None,
) -> RulePredicateResult:
    """判断已确认主合同乙方税号与发票销售方税号是否精确一致。"""

    _validate_exact_bool(
        has_confirmed_primary_contract,
        name="has_confirmed_primary_contract",
    )
    _validate_optional_non_blank_str(
        contract_party_b_tax_no,
        name="contract_party_b_tax_no",
    )
    _validate_optional_non_blank_str(
        invoice_seller_tax_no,
        name="invoice_seller_tax_no",
    )
    if (
        not has_confirmed_primary_contract
        or contract_party_b_tax_no is None
        or invoice_seller_tax_no is None
    ):
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    status = (
        RuleExecutionStatus.PASSED
        if contract_party_b_tax_no == invoice_seller_tax_no
        else RuleExecutionStatus.FAILED
    )
    return RulePredicateResult(status)


def evaluate_rule_002(
    organization_tax_number: str,
    invoice_buyer_tax_no: str | None,
) -> RulePredicateResult:
    """判断当前组织税号与发票购买方税号是否精确一致。"""

    if type(organization_tax_number) is not str or not organization_tax_number.strip():
        raise ValueError("organization_tax_number must be a non-blank exact str")
    _validate_optional_non_blank_str(
        invoice_buyer_tax_no,
        name="invoice_buyer_tax_no",
    )
    if invoice_buyer_tax_no is None:
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    status = (
        RuleExecutionStatus.PASSED
        if organization_tax_number == invoice_buyer_tax_no
        else RuleExecutionStatus.FAILED
    )
    return RulePredicateResult(status)


def evaluate_rule_003(
    has_confirmed_primary_contract: bool,
    cumulative_invoice_total: Decimal | None,
    effective_contract_amount: Decimal | None,
) -> RulePredicateResult:
    """判断累计发票价税合计是否不超过基准日期有效合同金额。"""

    _validate_exact_bool(
        has_confirmed_primary_contract,
        name="has_confirmed_primary_contract",
    )
    amounts = (cumulative_invoice_total, effective_contract_amount)
    if any(
        value is not None and (type(value) is not Decimal or not value.is_finite())
        for value in amounts
    ):
        raise ValueError("amounts must be finite exact Decimal values or None")
    if not has_confirmed_primary_contract or any(value is None for value in amounts):
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    assert cumulative_invoice_total is not None
    assert effective_contract_amount is not None
    status = (
        RuleExecutionStatus.FAILED
        if cumulative_invoice_total > effective_contract_amount
        else RuleExecutionStatus.PASSED
    )
    return RulePredicateResult(status)


def evaluate_rule_004(
    invoice_date: date | None,
    contract_effective_date: date | None,
    contract_expiry_date: date | None,
) -> RulePredicateResult:
    """判断开票日期是否处于主合同有效期的闭区间内。"""

    dates = (invoice_date, contract_effective_date, contract_expiry_date)
    if any(value is not None and type(value) is not date for value in dates):
        raise ValueError("dates must be exact datetime.date values or None")
    if (
        contract_effective_date is not None
        and contract_expiry_date is not None
        and contract_effective_date > contract_expiry_date
    ):
        raise ValueError("contract effective date must not be after expiry date")
    if any(value is None for value in dates):
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    assert invoice_date is not None
    assert contract_effective_date is not None
    assert contract_expiry_date is not None
    status = (
        RuleExecutionStatus.PASSED
        if contract_effective_date <= invoice_date <= contract_expiry_date
        else RuleExecutionStatus.FAILED
    )
    return RulePredicateResult(status)


def evaluate_rule_005(
    has_existing_exact_invoice_identity: bool | None,
) -> RulePredicateResult:
    """根据调用方冻结的精确发票身份重复事实进行判定。"""

    _validate_optional_exact_bool(
        has_existing_exact_invoice_identity,
        name="has_existing_exact_invoice_identity",
    )
    if has_existing_exact_invoice_identity is None:
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    status = (
        RuleExecutionStatus.FAILED
        if has_existing_exact_invoice_identity
        else RuleExecutionStatus.PASSED
    )
    return RulePredicateResult(status)


def evaluate_rule_006(
    has_confirmed_primary_contract: bool,
    contract_subjects_present: bool,
    contract_amount_present: bool,
    contract_currency_present: bool,
    contract_effective_date_present: bool,
) -> RulePredicateResult:
    """判断已确认主合同的四类规范核心事实是否完整。"""

    facts = (
        ("has_confirmed_primary_contract", has_confirmed_primary_contract),
        ("contract_subjects_present", contract_subjects_present),
        ("contract_amount_present", contract_amount_present),
        ("contract_currency_present", contract_currency_present),
        ("contract_effective_date_present", contract_effective_date_present),
    )
    for name, value in facts:
        _validate_exact_bool(value, name=name)
    if not has_confirmed_primary_contract:
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    core_facts = (
        contract_subjects_present,
        contract_amount_present,
        contract_currency_present,
        contract_effective_date_present,
    )
    status = RuleExecutionStatus.PASSED if all(core_facts) else RuleExecutionStatus.FAILED
    return RulePredicateResult(status)


def evaluate_rule_007(
    invoice_code: str | None,
    invoice_number: str | None,
    buyer_tax_no: str | None,
    seller_tax_no: str | None,
    invoice_date: date | None,
    total_amount: Decimal | None,
) -> RulePredicateResult:
    """判断单张发票的六个核心字段是否全部存在。"""

    string_fields = {
        "invoice_code": invoice_code,
        "invoice_number": invoice_number,
        "buyer_tax_no": buyer_tax_no,
        "seller_tax_no": seller_tax_no,
    }
    for name, value in string_fields.items():
        _validate_optional_non_blank_str(value, name=name)
    if invoice_date is not None and type(invoice_date) is not date:
        raise ValueError("invoice_date must be an exact datetime.date or None")
    if total_amount is not None and (
        type(total_amount) is not Decimal or not total_amount.is_finite()
    ):
        raise ValueError("total_amount must be a finite exact Decimal or None")

    required_facts = (*string_fields.values(), invoice_date, total_amount)
    status = (
        RuleExecutionStatus.PASSED
        if all(value is not None for value in required_facts)
        else RuleExecutionStatus.FAILED
    )
    return RulePredicateResult(status)


def evaluate_rule_008_currency_pair(
    has_confirmed_primary_contract: bool,
    contract_currency: str | None,
    invoice_currency: str | None,
) -> RulePredicateResult:
    """判断已确认主合同与单张发票的规范币种值是否精确一致。"""

    _validate_exact_bool(
        has_confirmed_primary_contract,
        name="has_confirmed_primary_contract",
    )
    _validate_optional_non_blank_str(contract_currency, name="contract_currency")
    _validate_optional_non_blank_str(invoice_currency, name="invoice_currency")
    if not has_confirmed_primary_contract:
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)
    if contract_currency is None or invoice_currency is None:
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    status = (
        RuleExecutionStatus.PASSED
        if contract_currency == invoice_currency
        else RuleExecutionStatus.FAILED
    )
    return RulePredicateResult(status)


def evaluate_rule_009(
    line_net_amount: Decimal | None,
    tax_amount: Decimal | None,
    total_amount: Decimal | None,
) -> RulePredicateResult:
    """判断发票明细不含税额加税额与总额的差值是否不超过 0.01。"""

    amounts = (line_net_amount, tax_amount, total_amount)
    if any(
        value is not None and (type(value) is not Decimal or not value.is_finite())
        for value in amounts
    ):
        raise ValueError("amounts must be finite exact Decimal values or None")
    if any(value is None for value in amounts):
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    assert line_net_amount is not None
    assert tax_amount is not None
    assert total_amount is not None
    difference = abs(Fraction(line_net_amount) + Fraction(tax_amount) - Fraction(total_amount))
    status = (
        RuleExecutionStatus.PASSED if difference <= Fraction(1, 100) else RuleExecutionStatus.FAILED
    )
    return RulePredicateResult(status)


def evaluate_rule_010(
    has_confirmed_primary_contract: bool,
) -> RulePredicateResult:
    """判断审核任务是否已确认主合同。"""

    _validate_exact_bool(
        has_confirmed_primary_contract,
        name="has_confirmed_primary_contract",
    )
    status = (
        RuleExecutionStatus.PASSED if has_confirmed_primary_contract else RuleExecutionStatus.FAILED
    )
    return RulePredicateResult(status)


def evaluate_rule_011(
    has_confirmed_primary_contract: bool,
    contract_no: str | None,
) -> RulePredicateResult:
    """判断已确认主合同是否提供了合同编号。"""

    _validate_exact_bool(
        has_confirmed_primary_contract,
        name="has_confirmed_primary_contract",
    )
    _validate_optional_non_blank_str(contract_no, name="contract_no")
    if not has_confirmed_primary_contract:
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    status = RuleExecutionStatus.PASSED if contract_no is not None else RuleExecutionStatus.FAILED
    return RulePredicateResult(status)


def evaluate_rule_012(
    has_confirmed_primary_contract: bool,
    has_effective_unconfirmed_supplementary_agreement: bool,
) -> RulePredicateResult:
    """判断主合同是否存在已生效但未确认的补充协议。"""

    _validate_exact_bool(
        has_confirmed_primary_contract,
        name="has_confirmed_primary_contract",
    )
    _validate_exact_bool(
        has_effective_unconfirmed_supplementary_agreement,
        name="has_effective_unconfirmed_supplementary_agreement",
    )
    if not has_confirmed_primary_contract:
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    status = (
        RuleExecutionStatus.FAILED
        if has_effective_unconfirmed_supplementary_agreement
        else RuleExecutionStatus.PASSED
    )
    return RulePredicateResult(status)


def evaluate_rule_013(
    requires_policy_citation: bool,
    retrieval_completed_successfully: bool,
    has_applicable_policy_citation: bool,
) -> RulePredicateResult:
    """判断正常完成检索后是否缺少规则要求的适用制度引用。"""

    facts = (
        ("requires_policy_citation", requires_policy_citation),
        ("retrieval_completed_successfully", retrieval_completed_successfully),
        ("has_applicable_policy_citation", has_applicable_policy_citation),
    )
    for name, value in facts:
        _validate_exact_bool(value, name=name)
    if not requires_policy_citation or not retrieval_completed_successfully:
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    status = (
        RuleExecutionStatus.PASSED if has_applicable_policy_citation else RuleExecutionStatus.FAILED
    )
    return RulePredicateResult(status)


def evaluate_rule_014_identity_pair(
    standard_name_a: str | None,
    standard_name_b: str | None,
    tax_identity_a: str | None,
    tax_identity_b: str | None,
) -> RulePredicateResult:
    """逐字比较上游标准名称与规范税务身份是否冲突。"""

    identity_facts = (
        ("standard_name_a", standard_name_a),
        ("standard_name_b", standard_name_b),
        ("tax_identity_a", tax_identity_a),
        ("tax_identity_b", tax_identity_b),
    )
    for name, value in identity_facts:
        _validate_optional_non_blank_str(value, name=name)
    if any(value is None for _, value in identity_facts):
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    status = (
        RuleExecutionStatus.FAILED
        if standard_name_a == standard_name_b and tax_identity_a != tax_identity_b
        else RuleExecutionStatus.PASSED
    )
    return RulePredicateResult(status)


def evaluate_rule_015(
    total_amount: Decimal | None,
    *,
    is_red_invoice: bool | None,
) -> RulePredicateResult:
    """判断普通发票价税合计是否为正数。"""

    if total_amount is not None and (
        type(total_amount) is not Decimal or not total_amount.is_finite()
    ):
        raise ValueError("total_amount must be a finite exact Decimal")
    if is_red_invoice is not None and type(is_red_invoice) is not bool:
        raise ValueError("is_red_invoice must be an exact bool")
    if total_amount is None or is_red_invoice is None:
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)
    if is_red_invoice:
        return RulePredicateResult(RuleExecutionStatus.NOT_APPLICABLE)

    status = RuleExecutionStatus.PASSED if total_amount > 0 else RuleExecutionStatus.FAILED
    return RulePredicateResult(status)
