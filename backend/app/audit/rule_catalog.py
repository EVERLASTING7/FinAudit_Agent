"""P0 内置审核规则目录及显式、整批 PostgreSQL 发布器。"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, cast

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.audit.risk_summary import RiskLevel
from app.audit.rule_predicates import (
    evaluate_rule_001,
    evaluate_rule_002,
    evaluate_rule_003,
    evaluate_rule_004,
    evaluate_rule_005,
    evaluate_rule_006,
    evaluate_rule_007,
    evaluate_rule_008_currency_pair,
    evaluate_rule_009,
    evaluate_rule_010,
    evaluate_rule_011,
    evaluate_rule_012,
    evaluate_rule_013,
    evaluate_rule_014_identity_pair,
    evaluate_rule_015,
)
from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.models.audit import AuditRule

RULE_CATALOG_SIZE = 15
RULE_CATALOG_CODES = tuple(f"RULE-{number:03d}" for number in range(1, 16))
RULE_CATALOG_ADVISORY_LOCK = 67_221_801
_RELEASE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z", re.ASCII)

RulePredicate = Callable[..., object]


class RuleCatalogError(RuntimeError):
    """已发布目录与当前静态目录不能安全对齐。"""


@dataclass(frozen=True, slots=True)
class BuiltinAuditRule:
    rule_code: str
    name: str
    category: str
    input_schema_json: dict[str, object]
    implementation_key: str
    predicate: RulePredicate
    default_risk_level: RiskLevel
    explanation_template: str
    requires_policy_citation: bool = False


@dataclass(frozen=True, slots=True)
class CatalogRuleVersion:
    rule_code: str
    version: int
    name: str
    category: str
    input_schema_json: dict[str, object]
    implementation_key: str
    implementation_hash: str
    application_release: str
    catalog_manifest_sha256: str
    default_risk_level: str
    explanation_template: str
    requires_policy_citation: bool
    is_enabled: bool


@dataclass(frozen=True, slots=True)
class CatalogPublishResult:
    outcome: Literal["published", "noop"]
    version: int
    manifest_sha256: str


def _nullable(kind: str, *, format_name: str | None = None) -> dict[str, object]:
    schema: dict[str, object] = {"type": [kind, "null"]}
    if format_name is not None:
        schema["format"] = format_name
    return schema


def _strict_schema(**properties: dict[str, object]) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


_BOOL: dict[str, object] = {"type": "boolean"}
_TEXT: dict[str, object] = {"type": "string", "minLength": 1}
_OPTIONAL_TEXT = _nullable("string")
_OPTIONAL_NUMBER = _nullable("number")
_OPTIONAL_BOOL = _nullable("boolean")
_OPTIONAL_DATE = _nullable("string", format_name="date")

BUILTIN_AUDIT_RULES = (
    BuiltinAuditRule(
        "RULE-001",
        "发票销售方税务身份与合同乙方一致",
        "identity",
        _strict_schema(
            has_confirmed_primary_contract=_BOOL,
            contract_party_b_tax_no=_OPTIONAL_TEXT,
            invoice_seller_tax_no=_OPTIONAL_TEXT,
        ),
        "rule_predicates.evaluate_rule_001",
        evaluate_rule_001,
        RiskLevel.HIGH,
        "发票销售方税务身份与合同乙方不一致。",
    ),
    BuiltinAuditRule(
        "RULE-002",
        "发票购买方税务身份与本企业一致",
        "identity",
        _strict_schema(
            organization_tax_number=_TEXT,
            invoice_buyer_tax_no=_OPTIONAL_TEXT,
        ),
        "rule_predicates.evaluate_rule_002",
        evaluate_rule_002,
        RiskLevel.HIGH,
        "发票购买方税务身份与本企业不一致。",
    ),
    BuiltinAuditRule(
        "RULE-003",
        "累计开票金额不超过有效合同金额",
        "amount",
        _strict_schema(
            has_confirmed_primary_contract=_BOOL,
            cumulative_invoice_total=_OPTIONAL_NUMBER,
            effective_contract_amount=_OPTIONAL_NUMBER,
        ),
        "rule_predicates.evaluate_rule_003",
        evaluate_rule_003,
        RiskLevel.HIGH,
        "纳入计算的累计开票总额超过基准日期有效合同金额。",
    ),
    BuiltinAuditRule(
        "RULE-004",
        "开票日期处于合同有效期",
        "date",
        _strict_schema(
            invoice_date=_OPTIONAL_DATE,
            contract_effective_date=_OPTIONAL_DATE,
            contract_expiry_date=_OPTIONAL_DATE,
        ),
        "rule_predicates.evaluate_rule_004",
        evaluate_rule_004,
        RiskLevel.MEDIUM,
        "开票日期不在合同有效期。",
    ),
    BuiltinAuditRule(
        "RULE-005",
        "发票身份不重复",
        "identity",
        _strict_schema(has_existing_exact_invoice_identity=_OPTIONAL_BOOL),
        "rule_predicates.evaluate_rule_005",
        evaluate_rule_005,
        RiskLevel.HIGH,
        "发票代码、号码和销售方税务身份重复。",
    ),
    BuiltinAuditRule(
        "RULE-006",
        "合同核心字段完整",
        "completeness",
        _strict_schema(
            has_confirmed_primary_contract=_BOOL,
            contract_subjects_present=_BOOL,
            contract_amount_present=_BOOL,
            contract_currency_present=_BOOL,
            contract_effective_date_present=_BOOL,
        ),
        "rule_predicates.evaluate_rule_006",
        evaluate_rule_006,
        RiskLevel.MEDIUM,
        "合同主体、金额、币种或生效日期缺失。",
    ),
    BuiltinAuditRule(
        "RULE-007",
        "发票核心字段完整",
        "completeness",
        _strict_schema(
            invoice_code=_OPTIONAL_TEXT,
            invoice_number=_OPTIONAL_TEXT,
            invoice_buyer_tax_no=_OPTIONAL_TEXT,
            invoice_seller_tax_no=_OPTIONAL_TEXT,
            invoice_date=_OPTIONAL_DATE,
            invoice_total_amount=_OPTIONAL_NUMBER,
        ),
        "rule_predicates.evaluate_rule_007",
        evaluate_rule_007,
        RiskLevel.MEDIUM,
        "发票代码、号码、买卖方税务身份、日期或总额缺失。",
    ),
    BuiltinAuditRule(
        "RULE-008",
        "合同与发票币种一致",
        "currency",
        _strict_schema(
            has_confirmed_primary_contract=_BOOL,
            contract_currency=_OPTIONAL_TEXT,
            invoice_currency=_OPTIONAL_TEXT,
        ),
        "rule_predicates.evaluate_rule_008_currency_pair",
        evaluate_rule_008_currency_pair,
        RiskLevel.MEDIUM,
        "合同与发票币种不一致。",
    ),
    BuiltinAuditRule(
        "RULE-009",
        "发票明细与总额一致",
        "amount",
        _strict_schema(
            invoice_line_net_amount=_OPTIONAL_NUMBER,
            invoice_tax_amount=_OPTIONAL_NUMBER,
            invoice_total_amount=_OPTIONAL_NUMBER,
        ),
        "rule_predicates.evaluate_rule_009",
        evaluate_rule_009,
        RiskLevel.MEDIUM,
        "发票明细不含税额与税额之和同总额差异超过 0.01。",
    ),
    BuiltinAuditRule(
        "RULE-010",
        "主合同已确认",
        "relationship",
        _strict_schema(has_confirmed_primary_contract=_BOOL),
        "rule_predicates.evaluate_rule_010",
        evaluate_rule_010,
        RiskLevel.MEDIUM,
        "发票没有已确认主合同。",
    ),
    BuiltinAuditRule(
        "RULE-011",
        "合同编号完整",
        "completeness",
        _strict_schema(
            has_confirmed_primary_contract=_BOOL,
            contract_no=_OPTIONAL_TEXT,
        ),
        "rule_predicates.evaluate_rule_011",
        evaluate_rule_011,
        RiskLevel.NOTICE,
        "合同编号缺失。",
    ),
    BuiltinAuditRule(
        "RULE-012",
        "补充协议审核事实已确认",
        "relationship",
        _strict_schema(
            has_confirmed_primary_contract=_BOOL,
            has_effective_unconfirmed_supplementary_agreement=_BOOL,
        ),
        "rule_predicates.evaluate_rule_012",
        evaluate_rule_012,
        RiskLevel.MEDIUM,
        "存在影响审核事实但尚未确认的补充协议。",
    ),
    BuiltinAuditRule(
        "RULE-013",
        "需要的制度依据可追溯",
        "policy",
        _strict_schema(
            requires_policy_citation=_BOOL,
            retrieval_completed_successfully=_BOOL,
            has_applicable_policy_citation=_BOOL,
        ),
        "rule_predicates.evaluate_rule_013",
        evaluate_rule_013,
        RiskLevel.NOTICE,
        "检索正常完成但需要制度依据的规则没有找到适用证据。",
        requires_policy_citation=True,
    ),
    BuiltinAuditRule(
        "RULE-014",
        "相同名称的税务身份一致",
        "identity",
        _strict_schema(
            standard_name_a=_OPTIONAL_TEXT,
            standard_name_b=_OPTIONAL_TEXT,
            tax_identity_a=_OPTIONAL_TEXT,
            tax_identity_b=_OPTIONAL_TEXT,
        ),
        "rule_predicates.evaluate_rule_014_identity_pair",
        evaluate_rule_014_identity_pair,
        RiskLevel.HIGH,
        "名称相同但税务身份冲突。",
    ),
    BuiltinAuditRule(
        "RULE-015",
        "非红字发票总额为正",
        "amount",
        _strict_schema(
            invoice_total_amount=_OPTIONAL_NUMBER,
            is_red_invoice=_OPTIONAL_BOOL,
        ),
        "rule_predicates.evaluate_rule_015",
        evaluate_rule_015,
        RiskLevel.MEDIUM,
        "非红字发票总额不大于零。",
    ),
)

PREDICATE_ALLOWLIST = {rule.implementation_key: rule.predicate for rule in BUILTIN_AUDIT_RULES}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _implementation_hash(predicate: RulePredicate) -> str:
    return hashlib.sha256(inspect.getsource(predicate).encode("utf-8")).hexdigest()


def _manifest_document(rule: CatalogRuleVersion) -> dict[str, object]:
    return {
        "application_release": rule.application_release,
        "category": rule.category,
        "default_risk_level": rule.default_risk_level,
        "explanation_template": rule.explanation_template,
        "implementation_hash": rule.implementation_hash,
        "implementation_key": rule.implementation_key,
        "input_schema_json": rule.input_schema_json,
        "is_enabled": rule.is_enabled,
        "name": rule.name,
        "requires_policy_citation": rule.requires_policy_citation,
        "rule_code": rule.rule_code,
        "version": rule.version,
    }


def build_catalog(application_release: str, version: int) -> tuple[CatalogRuleVersion, ...]:
    if _RELEASE_PATTERN.fullmatch(application_release) is None:
        raise RuleCatalogError("application release is invalid")
    if type(version) is not int or version <= 0:
        raise RuleCatalogError("catalog version is invalid")
    if (
        len(BUILTIN_AUDIT_RULES) != RULE_CATALOG_SIZE
        or tuple(rule.rule_code for rule in BUILTIN_AUDIT_RULES) != RULE_CATALOG_CODES
        or len(PREDICATE_ALLOWLIST) != RULE_CATALOG_SIZE
        or len({rule.category for rule in BUILTIN_AUDIT_RULES}) != 7
    ):
        raise RuleCatalogError("builtin audit catalog is incomplete")

    unhashed = tuple(
        CatalogRuleVersion(
            rule_code=rule.rule_code,
            version=version,
            name=rule.name,
            category=rule.category,
            input_schema_json=rule.input_schema_json,
            implementation_key=rule.implementation_key,
            implementation_hash=_implementation_hash(rule.predicate),
            application_release=application_release,
            catalog_manifest_sha256="",
            default_risk_level=rule.default_risk_level.value,
            explanation_template=rule.explanation_template,
            requires_policy_citation=rule.requires_policy_citation,
            is_enabled=True,
        )
        for rule in BUILTIN_AUDIT_RULES
    )
    manifest = hashlib.sha256(
        _canonical_json([_manifest_document(rule) for rule in unhashed])
    ).hexdigest()
    return tuple(replace(rule, catalog_manifest_sha256=manifest) for rule in unhashed)


def _stored_rule(row: AuditRule) -> CatalogRuleVersion:
    return CatalogRuleVersion(
        rule_code=row.rule_code,
        version=row.version,
        name=row.name,
        category=row.category,
        input_schema_json=dict(row.input_schema_json),
        implementation_key=row.implementation_key,
        implementation_hash=row.implementation_hash,
        application_release=row.application_release,
        catalog_manifest_sha256=row.catalog_manifest_sha256,
        default_risk_level=row.default_risk_level,
        explanation_template=row.explanation_template,
        requires_policy_citation=row.requires_policy_citation,
        is_enabled=row.is_enabled,
    )


def _validate_stored_catalog(rows: tuple[AuditRule, ...]) -> int:
    if not rows:
        return 0
    versions = sorted({row.version for row in rows})
    if versions != list(range(1, versions[-1] + 1)):
        raise RuleCatalogError("stored catalog versions are not contiguous")
    for version in versions:
        version_rows = tuple(row for row in rows if row.version == version)
        if tuple(row.rule_code for row in version_rows) != RULE_CATALOG_CODES:
            raise RuleCatalogError("stored catalog is not a complete 15-rule release")
        stored = tuple(_stored_rule(row) for row in version_rows)
        manifests = {row.catalog_manifest_sha256 for row in stored}
        if len(manifests) != 1:
            raise RuleCatalogError("stored catalog manifest identities differ")
        calculated = hashlib.sha256(
            _canonical_json([_manifest_document(row) for row in stored])
        ).hexdigest()
        if manifests != {calculated}:
            raise RuleCatalogError("stored catalog manifest does not match its rows")
    return versions[-1]


def publish_builtin_catalog(
    session: Session,
    *,
    application_release: str,
    change_reason: str,
) -> CatalogPublishResult:
    """在调用方事务内发布完整目录；不会自行提交或重试。"""

    if type(change_reason) is not str or not change_reason.strip() or len(change_reason) > 500:
        raise RuleCatalogError("change reason is invalid")
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": RULE_CATALOG_ADVISORY_LOCK},
    )
    session.execute(text("LOCK TABLE public.audit_rules IN SHARE ROW EXCLUSIVE MODE"))
    rows = tuple(
        session.scalars(
            select(AuditRule).order_by(AuditRule.version, AuditRule.rule_code).with_for_update()
        )
    )
    current_version = _validate_stored_catalog(rows)
    if current_version > 0:
        current_rows = tuple(row for row in rows if row.version == current_version)
        current_release = {row.application_release for row in current_rows}
        if current_release == {application_release}:
            expected = build_catalog(application_release, current_version)
            if tuple(_stored_rule(row) for row in current_rows) != expected:
                raise RuleCatalogError("stored catalog drifted within the same application release")
            return CatalogPublishResult(
                "noop", current_version, expected[0].catalog_manifest_sha256
            )
        if any(row.application_release == application_release for row in rows):
            raise RuleCatalogError("application release was already published as an older version")

    target_version = current_version + 1
    target = build_catalog(application_release, target_version)
    published_at = cast(datetime, session.scalar(select(func.clock_timestamp())))
    session.add_all(
        AuditRule(
            rule_code=rule.rule_code,
            version=rule.version,
            name=rule.name,
            category=rule.category,
            input_schema_json=rule.input_schema_json,
            implementation_key=rule.implementation_key,
            implementation_hash=rule.implementation_hash,
            application_release=rule.application_release,
            catalog_manifest_sha256=rule.catalog_manifest_sha256,
            default_risk_level=rule.default_risk_level,
            explanation_template=rule.explanation_template,
            requires_policy_citation=rule.requires_policy_citation,
            is_enabled=rule.is_enabled,
            published_at=published_at,
            change_reason=change_reason.strip(),
            created_at=published_at,
        )
        for rule in target
    )
    session.flush()
    return CatalogPublishResult("published", target_version, target[0].catalog_manifest_sha256)


def main() -> None:
    parser = argparse.ArgumentParser(description="显式发布 FinAudit 内置 15 条审核规则")
    parser.add_argument("--application-release")
    parser.add_argument("--change-reason", required=True)
    arguments = parser.parse_args()
    settings = Settings()
    engine: Engine = create_application_engine(settings)
    try:
        factory = create_session_factory(engine)
        with factory.begin() as session:
            result = publish_builtin_catalog(
                session,
                application_release=arguments.application_release or settings.app_version,
                change_reason=arguments.change_reason,
            )
        print(
            f"AUDIT_RULE_CATALOG={result.outcome} "
            f"version={result.version} manifest={result.manifest_sha256}"
        )
    finally:
        engine.dispose()


__all__ = [
    "BUILTIN_AUDIT_RULES",
    "CatalogPublishResult",
    "CatalogRuleVersion",
    "PREDICATE_ALLOWLIST",
    "RULE_CATALOG_CODES",
    "RULE_CATALOG_SIZE",
    "RuleCatalogError",
    "build_catalog",
    "publish_builtin_catalog",
]
