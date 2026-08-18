"""Generate deterministic fictional policy corpus and benchmark candidates.

The generator is local/test only. It reads checked-in permission and pricing
facts, writes two JSON assets, and never loads Settings, opens a socket, calls a
Provider, accesses a database, or changes index/evaluation approval state.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = Path(__file__).resolve()
PERMISSIONS_PATH = ROOT / "backend" / "app" / "core" / "permissions.py"
PRICING_POLICY_PATH = (
    ROOT
    / "backend"
    / "app"
    / "ai"
    / "artifacts"
    / "minimax_m3_bailian_qwen37_local_v2"
    / "live-ai-policy-v2.json"
)
CORPUS_OUTPUT_PATH = ROOT / "tests" / "evaluation" / "synthetic-policy-corpus-v1.json"
BENCHMARK_OUTPUT_PATH = (
    ROOT / "tests" / "evaluation" / "synthetic-benchmark-candidate-v1.json"
)

CORPUS_SCHEMA_VERSION = "synthetic-policy-corpus-v1"
BENCHMARK_SCHEMA_VERSION = "synthetic-benchmark-candidate-v1"
HISTORICAL_BENCHMARK_DATE = "2025-06-30"
CURRENT_BENCHMARK_DATE = "2026-06-30"
REQUIRED_PERMISSION = "knowledge.use"
TOP_K = 5
JsonObject = dict[str, Any]


DOMAIN_SPECS: tuple[dict[str, Any], ...] = (
    {
        "code": "REIMB",
        "domain": "reimbursement",
        "title": "费用报销",
        "versions": (
            {
                "version": 1,
                "valid_from": "2025-01-01",
                "valid_to": "2025-12-31",
                "clauses": (
                    (
                        "1.1",
                        "报销提交时限",
                        "普通费用报销的提交期限",
                        "虚构测试组织的普通费用报销应在支出发生后20个自然日内提交，并附合成用途说明与合法票据。",
                    ),
                    (
                        "1.2",
                        "较大金额复核",
                        "单笔超过人民币3000元的费用报销",
                        "单笔虚构费用超过人民币3000元时，应先由成本中心负责人复核，再进入财务复核。",
                    ),
                    (
                        "1.3",
                        "交通凭证一致性",
                        "差旅交通凭证的核对",
                        "差旅交通凭证的日期与申请人应和合成行程记录一致；不一致时不得直接提交付款。",
                    ),
                ),
            },
            {
                "version": 2,
                "valid_from": "2026-01-01",
                "valid_to": None,
                "clauses": (
                    (
                        "1.1",
                        "报销提交时限",
                        "普通费用报销的提交期限",
                        "虚构测试组织的普通费用报销应在支出发生后15个自然日内提交；逾期时须附书面原因并由独立财务人员记录复核意见。",
                    ),
                    (
                        "1.2",
                        "较大金额复核",
                        "单笔超过人民币2500元的费用报销",
                        "单笔虚构费用超过人民币2500元时，应依次完成成本中心负责人复核和财务复核，两项记录均须保留。",
                    ),
                    (
                        "1.3",
                        "电子票据查重",
                        "电子票据重复风险的处理",
                        "电子票据须按代码和号码执行重复检查；疑似重复时应转人工复核，不得自动认定为违规。",
                    ),
                ),
            },
        ),
        "no_answer": (
            ("差旅酒店星级上限", "酒店星级"),
            ("午餐补贴每日金额", "午餐补贴"),
            ("停车券兑换规则", "停车券"),
            ("团建活动礼品额度", "团建礼品"),
        ),
    },
    {
        "code": "VENDOR",
        "domain": "vendor",
        "title": "供应商管理",
        "versions": (
            {
                "version": 1,
                "valid_from": "2025-01-01",
                "valid_to": "2025-12-31",
                "clauses": (
                    (
                        "2.1",
                        "准入资料",
                        "新供应商准入资料",
                        "新供应商准入须具备合成资质声明、收款主体名称和账户归属核验记录，缺一项不得启用。",
                    ),
                    (
                        "2.2",
                        "收款账户变更",
                        "供应商收款账户变更",
                        "供应商收款账户变更须由提交人与复核人分别操作，并保留双人确认记录。",
                    ),
                    (
                        "2.3",
                        "休眠供应商",
                        "长期无交易供应商的处理",
                        "连续12个月没有合成交易的供应商应标记为休眠，重新使用前须复核准入资料。",
                    ),
                ),
            },
            {
                "version": 2,
                "valid_from": "2026-01-01",
                "valid_to": None,
                "clauses": (
                    (
                        "2.1",
                        "准入资料",
                        "新供应商准入资料",
                        "新供应商准入须具备合成资质声明、收款主体与账户一致性核验、利益冲突声明和风险分级记录。",
                    ),
                    (
                        "2.2",
                        "收款账户变更",
                        "供应商收款账户变更",
                        "供应商收款账户变更须通过既有可信联系渠道回访，并由不同人员提交和复核，回访结论应留痕。",
                    ),
                    (
                        "2.3",
                        "休眠供应商",
                        "长期无交易供应商的处理",
                        "连续9个月没有合成交易的供应商应标记为休眠，完成资料与账户重新核验后方可恢复使用。",
                    ),
                ),
            },
        ),
        "no_answer": (
            ("供应商办公场所装修颜色", "装修颜色"),
            ("供应商社交媒体粉丝数量", "粉丝数量"),
            ("供应商负责人星座", "负责人星座"),
            ("供应商员工制服款式", "制服款式"),
        ),
    },
    {
        "code": "INVOICE",
        "domain": "invoice",
        "title": "发票核验",
        "versions": (
            {
                "version": 1,
                "valid_from": "2025-01-01",
                "valid_to": "2025-12-31",
                "clauses": (
                    (
                        "3.1",
                        "关键字段核对",
                        "发票关键字段核对",
                        "发票核验应检查代码、号码、销售方识别号、价税合计和开票日期五项合成字段。",
                    ),
                    (
                        "3.2",
                        "重复候选",
                        "疑似重复发票的处理",
                        "代码、号码和销售方识别号相同的发票应列为疑似重复候选，交由人工复核，不得自动驳回。",
                    ),
                    (
                        "3.3",
                        "作废票据",
                        "作废或红冲发票的使用",
                        "已作废或已红冲的发票不得作为付款依据，相关状态与处理理由应留痕。",
                    ),
                ),
            },
            {
                "version": 2,
                "valid_from": "2026-01-01",
                "valid_to": None,
                "clauses": (
                    (
                        "3.1",
                        "关键字段核对",
                        "发票金额与明细核对",
                        "发票除核对五项合成关键字段外，还须核对明细金额与税额汇总是否等于价税合计。",
                    ),
                    (
                        "3.2",
                        "重复候选",
                        "疑似重复发票的处理",
                        "疑似重复发票须同时展示原票与候选票的关键字段差异，并由人工记录确认或排除理由。",
                    ),
                    (
                        "3.3",
                        "缺失币种",
                        "发票币种缺少证据时的处理",
                        "发票币种没有来源证据时应保持为空，不得由模型猜测或自动补全。",
                    ),
                ),
            },
        ),
        "no_answer": (
            ("发票纸张颜色偏好", "纸张颜色"),
            ("发票邮寄快递品牌", "快递品牌"),
            ("发票装订孔数量", "装订孔"),
            ("发票文件名使用的字体", "文件名字体"),
        ),
    },
    {
        "code": "CONTRACT",
        "domain": "contract",
        "title": "合同控制",
        "versions": (
            {
                "version": 1,
                "valid_from": "2025-01-01",
                "valid_to": "2025-12-31",
                "clauses": (
                    (
                        "4.1",
                        "付款前置",
                        "合同付款前置条件",
                        "合同付款前须存在已生效合同，且合同相对方应与合成付款对象一致。",
                    ),
                    (
                        "4.2",
                        "补充协议生效",
                        "补充协议对合同字段的影响",
                        "补充协议只有在完成确认且到达生效日后，才可改变对应合同字段。",
                    ),
                    (
                        "4.3",
                        "合同金额控制",
                        "累计发票金额超过合同上限",
                        "累计已确认发票金额不得超过合同金额上限；出现超额时应暂停付款并转人工复核。",
                    ),
                ),
            },
            {
                "version": 2,
                "valid_from": "2026-01-01",
                "valid_to": None,
                "clauses": (
                    (
                        "4.1",
                        "基准日投影",
                        "基准日合同版本的选择",
                        "基准日合同视图应采用当日已确认且已生效的最新版本，不得带入未来生效的补充协议。",
                    ),
                    (
                        "4.2",
                        "同日冲突",
                        "同日补充协议修改同一字段",
                        "两份同日生效的补充协议修改同一字段且结果不一致时，应标记冲突，在解决前均不得生效。",
                    ),
                    (
                        "4.3",
                        "主合同关系",
                        "发票主合同关系的唯一性",
                        "每张发票在同一时点只能有一个已确认的主合同关系，替换时须保留历史关系。",
                    ),
                ),
            },
        ),
        "no_answer": (
            ("合同封面颜色", "封面颜色"),
            ("合同正文默认字号", "默认字号"),
            ("签约用笔颜色", "签约用笔"),
            ("签约会议室编号", "会议室编号"),
        ),
    },
    {
        "code": "APPROVAL",
        "domain": "approval_authority",
        "title": "审批权限",
        "versions": (
            {
                "version": 1,
                "valid_from": "2025-01-01",
                "valid_to": "2025-12-31",
                "clauses": (
                    (
                        "5.1",
                        "风险分级复核",
                        "普通付款和高风险付款的复核分工",
                        "普通付款由财务复核，高风险付款还须由独立审计复核后才能完成。",
                    ),
                    (
                        "5.2",
                        "职责分离",
                        "制度提交人与审批人的职责分离",
                        "同一人员不得同时提交并审批同一制度变更，审批记录须能识别两名不同操作人。",
                    ),
                    (
                        "5.3",
                        "系统管理边界",
                        "系统管理员参与业务审批",
                        "系统管理员只负责系统配置与发布操作，不得替代财务或审计人员作出业务审批决定。",
                    ),
                ),
            },
            {
                "version": 2,
                "valid_from": "2026-01-01",
                "valid_to": None,
                "clauses": (
                    (
                        "5.1",
                        "高风险双人复核",
                        "高风险任务的完成条件",
                        "高风险任务须先由财务复核，再由不同的审计复核人独立确认，二者缺一不得完成。",
                    ),
                    (
                        "5.2",
                        "临时授权",
                        "临时提升权限的控制",
                        "临时提升权限须设置明确到期时间、独立审批记录和完整操作留痕，到期后自动失效。",
                    ),
                    (
                        "5.3",
                        "只读限制",
                        "只读角色的操作边界",
                        "只读角色只能查看获准内容，不得修改业务事实、执行审批或导出受限报告。",
                    ),
                ),
            },
        ),
        "no_answer": (
            ("审批人生日月份", "生日月份"),
            ("审批人停车位数量", "停车位数量"),
            ("审批界面头像样式", "头像样式"),
            ("审批提醒铃声", "提醒铃声"),
        ),
    },
    {
        "code": "AUDIT",
        "domain": "audit_trail",
        "title": "审计留痕",
        "versions": (
            {
                "version": 1,
                "valid_from": "2025-01-01",
                "valid_to": "2025-12-31",
                "clauses": (
                    (
                        "6.1",
                        "操作日志字段",
                        "业务状态变化的日志字段",
                        "业务状态变化须记录操作人、时间、动作、结果和追踪标识，且不得写入密钥或原始敏感内容。",
                    ),
                    (
                        "6.2",
                        "日志不可变",
                        "已写入操作日志的修改或删除",
                        "操作日志采用追加式记录，已写入条目不得通过业务接口修改、删除或截断。",
                    ),
                    (
                        "6.3",
                        "模型调用审计",
                        "模型调用需要保留的审计字段",
                        "模型调用须记录模型、用途、输入Token数和费用摘要，但不得保存密钥、原始提示或向量。",
                    ),
                ),
            },
            {
                "version": 2,
                "valid_from": "2026-01-01",
                "valid_to": None,
                "clauses": (
                    (
                        "6.1",
                        "事务审计",
                        "关键业务写入与审计失败的处理",
                        "关键业务写入与对应审计记录须在同一事务中采用；审计写入失败时，业务写入也必须回滚。",
                    ),
                    (
                        "6.2",
                        "费用币种",
                        "不同币种模型费用的汇总",
                        "不同币种的模型费用必须分别记录和汇总，未获批准时不得换汇或跨币种相加。",
                    ),
                    (
                        "6.3",
                        "迟到结果",
                        "模型迟到完成结果的采用",
                        "模型迟到完成结果只有在持久调用尝试仍有效且审计关联完整时才可采用，否则必须丢弃。",
                    ),
                ),
            },
        ),
        "no_answer": (
            ("审计日志界面主题色", "主题色"),
            ("日志导出纸张品牌", "纸张品牌"),
            ("审计人员午休时段", "午休时段"),
            ("日志列表动画效果", "动画效果"),
        ),
    },
)


class AssetGenerationError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AssetGenerationError(f"INVALID_SOURCE_JSON:{path.name}") from error
    if type(value) is not dict:
        raise AssetGenerationError(f"INVALID_SOURCE_SHAPE:{path.name}")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_query(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _query_sha256(value: str) -> str:
    return _sha256(_canonical_query(value).encode("utf-8"))


def _source_entry(path: Path, role: str) -> dict[str, object]:
    if not path.is_file():
        raise AssetGenerationError(f"SOURCE_FILE_MISSING:{path.name}")
    return {
        "file": path.relative_to(ROOT).as_posix(),
        "role": role,
        "sha256": _sha256(path.read_bytes()),
    }


def _role_permissions() -> dict[str, tuple[str, ...]]:
    try:
        tree = ast.parse(PERMISSIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        raise AssetGenerationError("PERMISSION_SOURCE_INVALID") from error
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_ROLE_PERMISSIONS"
            and node.value is not None
        ):
            try:
                raw = ast.literal_eval(node.value)
            except (ValueError, TypeError) as error:
                raise AssetGenerationError("PERMISSION_SOURCE_INVALID") from error
            if type(raw) is not dict:
                break
            result: dict[str, tuple[str, ...]] = {}
            for role, permissions in raw.items():
                if (
                    type(role) is not str
                    or type(permissions) is not tuple
                    or any(type(permission) is not str for permission in permissions)
                ):
                    raise AssetGenerationError("PERMISSION_SOURCE_INVALID")
                result[role] = permissions
            if len(result) != 5:
                raise AssetGenerationError("PERMISSION_ROLE_COUNT_DRIFT")
            return result
    raise AssetGenerationError("PERMISSION_SOURCE_MISSING")


def _policy_ref(code: str, version: int) -> str:
    return f"SPCV1-{code}-V{version}"


def _policy_inventory(policy_families: list[dict[str, Any]]) -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    for family in policy_families:
        for policy in family["policy_versions"]:
            inventory.append(
                {
                    "clause_count": len(policy["clauses"]),
                    "content_sha256": policy["content_sha256"],
                    "domain": family["domain"],
                    "policy_ref": policy["policy_ref"],
                    "title": policy["title"],
                    "valid_from": policy["valid_from"],
                    "valid_to": policy["valid_to"],
                }
            )
    return inventory


def _validate_corpus(policy_families: list[dict[str, Any]]) -> list[dict[str, object]]:
    if len(policy_families) != 6:
        raise AssetGenerationError("POLICY_FAMILY_COUNT_DRIFT")
    policy_refs: set[str] = set()
    clause_refs: set[str] = set()
    clause_hashes: set[str] = set()
    policy_count = 0
    clause_count = 0
    for family in policy_families:
        versions = family["policy_versions"]
        if len(versions) != 2:
            raise AssetGenerationError("POLICY_VERSION_COUNT_DRIFT")
        previous_to: date | None = None
        for expected_version, policy in enumerate(versions, start=1):
            policy_count += 1
            policy_ref = policy["policy_ref"]
            if policy["version_no"] != expected_version or policy_ref in policy_refs:
                raise AssetGenerationError("POLICY_VERSION_IDENTITY_INVALID")
            policy_refs.add(policy_ref)
            valid_from = date.fromisoformat(policy["valid_from"])
            valid_to = (
                date.fromisoformat(policy["valid_to"]) if policy["valid_to"] else None
            )
            if valid_to is not None and valid_to < valid_from:
                raise AssetGenerationError("POLICY_PERIOD_INVALID")
            if (
                previous_to is not None
                and previous_to + timedelta(days=1) != valid_from
            ):
                raise AssetGenerationError("POLICY_PERIOD_GAP_OR_OVERLAP")
            previous_to = valid_to
            for clause in policy["clauses"]:
                clause_count += 1
                clause_ref = clause["clause_ref"]
                clause_hash = clause["evidence_sha256"]
                if clause_ref in clause_refs or clause_hash in clause_hashes:
                    raise AssetGenerationError("POLICY_CLAUSE_DUPLICATE")
                if clause_hash != _sha256(clause["text"].encode("utf-8")):
                    raise AssetGenerationError("POLICY_CLAUSE_HASH_INVALID")
                clause_refs.add(clause_ref)
                clause_hashes.add(clause_hash)
    if policy_count != 12 or clause_count != 36:
        raise AssetGenerationError("POLICY_CORPUS_SIZE_DRIFT")
    return [
        {
            "check_id": "policy_identity_uniqueness",
            "observed_duplicates": 0,
            "status": "passed",
        },
        {
            "check_id": "clause_text_and_reference_uniqueness",
            "observed_duplicates": 0,
            "status": "passed",
        },
        {
            "check_id": "version_period_non_overlap_and_contiguity",
            "observed_conflicts": 0,
            "status": "passed",
        },
        {
            "check_id": "fictional_data_safety_envelope",
            "observed_real_records": 0,
            "status": "passed",
        },
    ]


def build_corpus_payload() -> JsonObject:
    role_permissions = _role_permissions()
    authorized_roles = tuple(
        sorted(
            role
            for role, permissions in role_permissions.items()
            if REQUIRED_PERMISSION in permissions
        )
    )
    unauthorized_roles = tuple(sorted(set(role_permissions) - set(authorized_roles)))
    if authorized_roles != ("audit_reviewer", "contract_admin", "finance_reviewer"):
        raise AssetGenerationError("KNOWLEDGE_USE_ROLE_DRIFT")
    if unauthorized_roles != ("read_only", "system_admin"):
        raise AssetGenerationError("KNOWLEDGE_DENY_ROLE_DRIFT")

    policy_families: list[dict[str, Any]] = []
    for spec in DOMAIN_SPECS:
        family_ref = f"SPCV1-{spec['code']}"
        versions: list[dict[str, Any]] = []
        for version_spec in spec["versions"]:
            version_no = version_spec["version"]
            policy_ref = _policy_ref(spec["code"], version_no)
            clauses: list[JsonObject] = []
            for section, heading, topic, text in version_spec["clauses"]:
                clauses.append(
                    {
                        "clause_ref": f"{policy_ref}#{section}",
                        "evidence_sha256": _sha256(text.encode("utf-8")),
                        "heading": heading,
                        "section": section,
                        "text": text,
                        "topic": topic,
                    }
                )
            policy: dict[str, Any] = {
                "allowed_role_labels": list(authorized_roles),
                "clauses": clauses,
                "family_ref": family_ref,
                "policy_ref": policy_ref,
                "required_permission": REQUIRED_PERMISSION,
                "status_at_generation": (
                    "historical_test_version"
                    if version_no == 1
                    else "current_test_version"
                ),
                "supersedes_policy_ref": (
                    None
                    if version_no == 1
                    else _policy_ref(spec["code"], version_no - 1)
                ),
                "title": f"虚构测试组织{spec['title']}制度（第{version_no}版）",
                "valid_from": version_spec["valid_from"],
                "valid_to": version_spec["valid_to"],
                "version_no": version_no,
            }
            policy["content_sha256"] = _sha256(_canonical_bytes(policy))
            versions.append(policy)
        policy_families.append(
            {
                "domain": spec["domain"],
                "family_ref": family_ref,
                "policy_versions": versions,
                "title": spec["title"],
            }
        )

    checks = _validate_corpus(policy_families)
    return {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "synthetic": True,
        "classification": "fictional_policy_corpus_non_acceptance",
        "environment_scope": ["local", "test"],
        "controls": {
            "approved_dataset_created": False,
            "approval_state": "not_submitted",
            "index_activation": "not_run",
            "provider_calls_executed": 0,
            "release_gate_execution": "not_run",
            "runtime_tier": None,
        },
        "data_safety": {
            "fictional_monetary_thresholds_only": True,
            "fictional_only": True,
            "real_company_data_included": False,
            "real_financial_records_included": False,
            "real_person_data_included": False,
            "synthetic_organization_label": "虚构测试组织",
        },
        "source_manifest": [
            _source_entry(SCRIPT_PATH, "deterministic_synthetic_authoring_source"),
            _source_entry(PERMISSIONS_PATH, "role_and_permission_label_source"),
        ],
        "access_model": {
            "authorized_role_labels": list(authorized_roles),
            "required_permission": REQUIRED_PERMISSION,
            "test_metadata_only": True,
            "unauthorized_role_labels": list(unauthorized_roles),
            "valid_role_labels": sorted(role_permissions),
        },
        "policy_families": policy_families,
        "source_inventory": _policy_inventory(policy_families),
        "inventory": {
            "clause_count": 36,
            "domain_count": 6,
            "policy_family_count": 6,
            "policy_version_count": 12,
        },
        "quality_verification": {
            "checks": checks,
            "status": "passed",
        },
    }


def _corpus_indexes(
    corpus: JsonObject,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
    policies: dict[str, dict[str, Any]] = {}
    clauses: dict[str, dict[str, Any]] = {}
    policy_domains: dict[str, str] = {}
    for family in corpus["policy_families"]:
        domain = family["domain"]
        for policy in family["policy_versions"]:
            policy_ref = policy["policy_ref"]
            policies[policy_ref] = policy
            policy_domains[policy_ref] = domain
            for clause in policy["clauses"]:
                clauses[clause["clause_ref"]] = clause
    return policies, clauses, policy_domains


def _case(
    *,
    case_id: str,
    label: str,
    domain: str,
    query_text: str,
    benchmark_date: str,
    actor_role: str,
    actor_permissions: tuple[str, ...],
    allowed_policy_refs: list[str],
    expected_evidence_refs: list[str],
    expected_evidence_sha256: list[str],
    forbidden_evidence_refs: list[str],
    policy_family_ref: str,
    policy_version_ref: str,
    scenario_tags: list[str],
    absence_probe: str | None = None,
    paraphrase_group_id: str | None = None,
) -> JsonObject:
    if query_text != query_text.strip() or not query_text:
        raise AssetGenerationError("QUERY_NOT_NORMALIZED")
    return {
        "absence_probe": absence_probe,
        "actor_effective_permissions": list(actor_permissions),
        "actor_role_labels": [actor_role],
        "allowed_policy_refs": allowed_policy_refs,
        "benchmark_date": benchmark_date,
        "case_id": case_id,
        "domain": domain,
        "expected_evidence_refs": expected_evidence_refs,
        "expected_evidence_sha256": expected_evidence_sha256,
        "forbidden_evidence_refs": forbidden_evidence_refs,
        "label": label,
        "paraphrase_group_id": paraphrase_group_id,
        "policy_family_ref": policy_family_ref,
        "policy_version_ref": policy_version_ref,
        "query_sha256": _query_sha256(query_text),
        "query_text": query_text,
        "required_permission": REQUIRED_PERMISSION,
        "scenario_tags": scenario_tags,
        "top_k": TOP_K,
    }


def _build_candidates(
    corpus: JsonObject, role_permissions: dict[str, tuple[str, ...]]
) -> list[JsonObject]:
    policies, clauses, _ = _corpus_indexes(corpus)
    authorized_roles = corpus["access_model"]["authorized_role_labels"]
    unauthorized_roles = corpus["access_model"]["unauthorized_role_labels"]
    candidates: list[JsonObject] = []
    for domain_no, spec in enumerate(DOMAIN_SPECS, start=1):
        family_ref = f"SPCV1-{spec['code']}"
        answerable_no = 0
        for version_spec in spec["versions"]:
            version_no = version_spec["version"]
            policy_ref = _policy_ref(spec["code"], version_no)
            benchmark_date = (
                HISTORICAL_BENCHMARK_DATE if version_no == 1 else CURRENT_BENCHMARK_DATE
            )
            for section, _, topic, _ in version_spec["clauses"]:
                clause_ref = f"{policy_ref}#{section}"
                other_version_no = 2 if version_no == 1 else 1
                other_version_clause_ref = (
                    f"{_policy_ref(spec['code'], other_version_no)}#{section}"
                )
                group_id = (
                    f"SBCV1-P-{spec['code']}-V{version_no}-{section.replace('.', '')}"
                )
                questions = (
                    f"按{benchmark_date}有效制度，关于{topic}的要求是什么？",
                    f"以{benchmark_date}为基准，{topic}应当如何处理？",
                )
                for variant, query_text in enumerate(questions, start=1):
                    answerable_no += 1
                    actor_role = authorized_roles[
                        (answerable_no + domain_no - 2) % len(authorized_roles)
                    ]
                    candidates.append(
                        _case(
                            case_id=(
                                f"SBCV1-A-{spec['code']}-V{version_no}-"
                                f"{section.replace('.', '')}-{variant}"
                            ),
                            label="answerable",
                            domain=spec["domain"],
                            query_text=query_text,
                            benchmark_date=benchmark_date,
                            actor_role=actor_role,
                            actor_permissions=role_permissions[actor_role],
                            allowed_policy_refs=[policy_ref],
                            expected_evidence_refs=[clause_ref],
                            expected_evidence_sha256=[
                                clauses[clause_ref]["evidence_sha256"]
                            ],
                            forbidden_evidence_refs=[other_version_clause_ref],
                            policy_family_ref=family_ref,
                            policy_version_ref=policy_ref,
                            scenario_tags=(
                                ["effective_date", "policy_version", "synonym_rewrite"]
                                if variant == 2
                                else ["effective_date", "policy_version"]
                            ),
                            paraphrase_group_id=group_id,
                        )
                    )

        current_policy_ref = _policy_ref(spec["code"], 2)
        for case_no, (topic, absence_probe) in enumerate(spec["no_answer"], start=1):
            actor_role = authorized_roles[
                (case_no + domain_no - 2) % len(authorized_roles)
            ]
            candidates.append(
                _case(
                    case_id=f"SBCV1-N-{spec['code']}-{case_no:02d}",
                    label="no_answer",
                    domain=spec["domain"],
                    query_text=(
                        f"按{CURRENT_BENCHMARK_DATE}有效制度，关于{topic}有什么规定？"
                    ),
                    benchmark_date=CURRENT_BENCHMARK_DATE,
                    actor_role=actor_role,
                    actor_permissions=role_permissions[actor_role],
                    allowed_policy_refs=[current_policy_ref],
                    expected_evidence_refs=[],
                    expected_evidence_sha256=[],
                    forbidden_evidence_refs=[
                        clause["clause_ref"]
                        for clause in policies[current_policy_ref]["clauses"]
                    ],
                    policy_family_ref=family_ref,
                    policy_version_ref=current_policy_ref,
                    scenario_tags=["no_answer", "effective_date", "policy_version"],
                    absence_probe=absence_probe,
                )
            )

        forbidden_plan = (
            (1, spec["versions"][0]["clauses"][0]),
            (1, spec["versions"][0]["clauses"][2]),
            (2, spec["versions"][1]["clauses"][1]),
            (2, spec["versions"][1]["clauses"][2]),
        )
        for case_no, (version_no, clause_spec) in enumerate(forbidden_plan, start=1):
            section, _, topic, _ = clause_spec
            policy_ref = _policy_ref(spec["code"], version_no)
            benchmark_date = (
                HISTORICAL_BENCHMARK_DATE if version_no == 1 else CURRENT_BENCHMARK_DATE
            )
            actor_role = unauthorized_roles[
                (case_no + domain_no - 2) % len(unauthorized_roles)
            ]
            candidates.append(
                _case(
                    case_id=f"SBCV1-U-{spec['code']}-{case_no:02d}",
                    label="unauthorized",
                    domain=spec["domain"],
                    query_text=(
                        f"请说明{benchmark_date}时{topic}适用的内部要求是什么？"
                    ),
                    benchmark_date=benchmark_date,
                    actor_role=actor_role,
                    actor_permissions=role_permissions[actor_role],
                    allowed_policy_refs=[],
                    expected_evidence_refs=[],
                    expected_evidence_sha256=[],
                    forbidden_evidence_refs=[f"{policy_ref}#{section}"],
                    policy_family_ref=family_ref,
                    policy_version_ref=policy_ref,
                    scenario_tags=[
                        "unauthorized",
                        "cross_permission",
                        "effective_date",
                        "policy_version",
                    ],
                )
            )

    if len(candidates) != 120:
        raise AssetGenerationError("CANDIDATE_COUNT_DRIFT")
    return candidates


def _select_case_sets(
    candidates: list[JsonObject],
) -> tuple[list[JsonObject], list[JsonObject], list[JsonObject]]:
    answerable_indices = (0, 1, 2, 4, 5, 6, 7, 8, 10, 11)
    no_answer_quotas = (4, 4, 3, 3, 3, 3)
    unauthorized_quotas = (3, 3, 4, 4, 3, 3)
    fixed_no_answer_quotas = (2, 2, 2, 2, 1, 1)
    fixed_unauthorized_quotas = (1, 1, 2, 2, 2, 2)
    proposed_ids: set[str] = set()
    fixed_ids: set[str] = set()
    for domain_no, spec in enumerate(DOMAIN_SPECS):
        domain_cases = [case for case in candidates if case["domain"] == spec["domain"]]
        answerable = [case for case in domain_cases if case["label"] == "answerable"]
        no_answer = [case for case in domain_cases if case["label"] == "no_answer"]
        unauthorized = [
            case for case in domain_cases if case["label"] == "unauthorized"
        ]
        selected_answerable = [answerable[index] for index in answerable_indices]
        for case in (
            selected_answerable
            + no_answer[: no_answer_quotas[domain_no]]
            + unauthorized[: unauthorized_quotas[domain_no]]
        ):
            proposed_ids.add(str(case["case_id"]))
        fixed_answerable_indices = (
            (0, 1, 2, 5, 7) if domain_no % 2 == 0 else (0, 2, 5, 7, 9)
        )
        for case in (
            [selected_answerable[index] for index in fixed_answerable_indices]
            + no_answer[: fixed_no_answer_quotas[domain_no]]
            + unauthorized[: fixed_unauthorized_quotas[domain_no]]
        ):
            fixed_ids.add(str(case["case_id"]))

    proposed = [case for case in candidates if case["case_id"] in proposed_ids]
    fixed = [case for case in candidates if case["case_id"] in fixed_ids]
    not_proposed = [case for case in candidates if case["case_id"] not in proposed_ids]
    if len(proposed) != 100 or len(fixed) != 50 or len(not_proposed) != 20:
        raise AssetGenerationError("PROPOSAL_SELECTION_COUNT_DRIFT")
    if not fixed_ids.issubset(proposed_ids):
        raise AssetGenerationError("MVP_UAT_NOT_SUBSET")
    return proposed, fixed, not_proposed


def _coverage(cases: list[JsonObject]) -> dict[str, object]:
    labels = Counter(str(case["label"]) for case in cases)
    domains = Counter(str(case["domain"]) for case in cases)
    roles = Counter(str(case["actor_role_labels"][0]) for case in cases)
    tags = Counter(tag for case in cases for tag in case["scenario_tags"])
    versions = Counter(str(case["policy_version_ref"]) for case in cases)
    return {
        "actor_role_counts": dict(sorted(roles.items())),
        "domain_counts": dict(sorted(domains.items())),
        "label_counts": {
            "answerable": labels["answerable"],
            "no_answer": labels["no_answer"],
            "unauthorized": labels["unauthorized"],
        },
        "policy_version_counts": dict(sorted(versions.items())),
        "scenario_tag_counts": dict(sorted(tags.items())),
        "total": len(cases),
    }


def _active_policy_refs(
    policies: dict[str, dict[str, Any]], domain_policies: list[str], benchmark_date: str
) -> list[str]:
    day = date.fromisoformat(benchmark_date)
    active: list[str] = []
    for policy_ref in domain_policies:
        policy = policies[policy_ref]
        valid_from = date.fromisoformat(policy["valid_from"])
        valid_to = (
            date.fromisoformat(policy["valid_to"]) if policy["valid_to"] else None
        )
        if valid_from <= day and (valid_to is None or day <= valid_to):
            active.append(policy_ref)
    return active


def _natural_question(query_text: str) -> bool:
    if not 18 <= len(query_text) <= 90 or not query_text.endswith("？"):
        return False
    if any(token in query_text for token in ("SPCV1", "{{", "}}", "#")):
        return False
    return any(
        token in query_text for token in ("什么", "如何", "多少", "是否", "哪", "规定")
    )


def _quality_checks(
    *,
    corpus: JsonObject,
    candidates: list[JsonObject],
    proposed: list[JsonObject],
    fixed: list[JsonObject],
) -> list[dict[str, object]]:
    policies, clauses, policy_domains = _corpus_indexes(corpus)
    case_ids = [str(case["case_id"]) for case in candidates]
    query_hashes = [str(case["query_sha256"]) for case in candidates]
    if len(set(case_ids)) != 120 or len(set(query_hashes)) != 120:
        raise AssetGenerationError("CANDIDATE_DUPLICATE")

    contradiction_count = 0
    evidence_missing_count = 0
    permission_label_error_count = 0
    no_answer_probe_error_count = 0
    naturalness_error_count = 0
    access_model = corpus["access_model"]
    valid_roles = set(access_model["valid_role_labels"])
    authorized_roles = set(access_model["authorized_role_labels"])
    for case in candidates:
        policy_ref = str(case["policy_version_ref"])
        domain_policy_refs = [
            ref for ref, domain in policy_domains.items() if domain == case["domain"]
        ]
        active_refs = _active_policy_refs(
            policies, domain_policy_refs, str(case["benchmark_date"])
        )
        if active_refs != [policy_ref]:
            contradiction_count += 1
        actor_roles = case["actor_role_labels"]
        if (
            len(actor_roles) != 1
            or actor_roles[0] not in valid_roles
            or case["required_permission"] != REQUIRED_PERMISSION
        ):
            permission_label_error_count += 1
        if not _natural_question(str(case["query_text"])):
            naturalness_error_count += 1

        label = case["label"]
        if label == "answerable":
            refs = case["expected_evidence_refs"]
            forbidden = case["forbidden_evidence_refs"]
            if (
                len(refs) != 1
                or refs[0] not in clauses
                or policy_ref not in case["allowed_policy_refs"]
                or clauses[refs[0]]["evidence_sha256"]
                not in case["expected_evidence_sha256"]
                or actor_roles[0] not in authorized_roles
                or REQUIRED_PERMISSION not in case["actor_effective_permissions"]
                or len(forbidden) != 1
                or forbidden[0] not in clauses
                or str(forbidden[0]).split("#", maxsplit=1)[-1]
                != str(refs[0]).split("#", maxsplit=1)[-1]
                or str(forbidden[0]).split("#", maxsplit=1)[0]
                in case["allowed_policy_refs"]
            ):
                evidence_missing_count += 1
        elif label == "no_answer":
            expected_forbidden = [
                clause["clause_ref"]
                for allowed_policy_ref in case["allowed_policy_refs"]
                for clause in policies[allowed_policy_ref]["clauses"]
            ]
            allowed_text = "\n".join(
                clause["text"]
                for allowed_policy_ref in case["allowed_policy_refs"]
                for clause in policies[allowed_policy_ref]["clauses"]
            )
            if (
                case["expected_evidence_refs"]
                or case["forbidden_evidence_refs"] != expected_forbidden
                or actor_roles[0] not in authorized_roles
                or not case["absence_probe"]
                or str(case["absence_probe"]) in allowed_text
            ):
                no_answer_probe_error_count += 1
        elif label == "unauthorized":
            forbidden = case["forbidden_evidence_refs"]
            if (
                case["allowed_policy_refs"]
                or case["expected_evidence_refs"]
                or len(forbidden) != 1
                or forbidden[0] not in clauses
                or actor_roles[0] in authorized_roles
                or REQUIRED_PERMISSION in case["actor_effective_permissions"]
            ):
                permission_label_error_count += 1
        else:
            raise AssetGenerationError("CANDIDATE_LABEL_INVALID")

    if any(
        (
            contradiction_count,
            evidence_missing_count,
            permission_label_error_count,
            no_answer_probe_error_count,
            naturalness_error_count,
        )
    ):
        raise AssetGenerationError("BENCHMARK_QUALITY_CHECK_FAILED")
    if _coverage(proposed)["label_counts"] != {
        "answerable": 60,
        "no_answer": 20,
        "unauthorized": 20,
    }:
        raise AssetGenerationError("PROPOSED_COVERAGE_INVALID")
    if _coverage(fixed)["label_counts"] != {
        "answerable": 30,
        "no_answer": 10,
        "unauthorized": 10,
    }:
        raise AssetGenerationError("MVP_UAT_COVERAGE_INVALID")

    return [
        {
            "check_id": "candidate_id_and_canonical_query_duplicates",
            "observed_duplicates": 0,
            "status": "passed",
        },
        {
            "check_id": "effective_period_and_version_contradictions",
            "observed_conflicts": contradiction_count,
            "status": "passed",
        },
        {
            "check_id": "expected_and_forbidden_evidence_integrity",
            "observed_missing_or_mismatched": evidence_missing_count,
            "status": "passed",
        },
        {
            "check_id": "no_answer_absence_probes",
            "observed_probe_conflicts": no_answer_probe_error_count,
            "status": "passed",
        },
        {
            "check_id": "permission_labels_and_cross_permission_boundaries",
            "observed_label_errors": permission_label_error_count,
            "status": "passed",
        },
        {
            "check_id": "question_naturalness_heuristic",
            "observed_heuristic_failures": naturalness_error_count,
            "status": "passed",
        },
        {
            "check_id": "proposal_100_and_mvp_uat_50_counts",
            "observed_count_errors": 0,
            "status": "passed",
        },
        {
            "check_id": "non_acceptance_and_zero_provider_controls",
            "observed_boundary_errors": 0,
            "status": "passed",
        },
    ]


def _human_review_queue(candidates: list[JsonObject]) -> list[dict[str, str]]:
    queue: list[dict[str, str]] = []
    for spec in DOMAIN_SPECS:
        domain_cases = [case for case in candidates if case["domain"] == spec["domain"]]
        answerable = [case for case in domain_cases if case["label"] == "answerable"]
        no_answer = [case for case in domain_cases if case["label"] == "no_answer"]
        unauthorized = [
            case for case in domain_cases if case["label"] == "unauthorized"
        ]
        queue.extend(
            (
                {
                    "case_id": str(answerable[1]["case_id"]),
                    "priority": "medium",
                    "review_area": "version_and_paraphrase_semantics",
                    "reason": "确认同义改写与历史版本证据语义等价，且不会误命中当前版本。",
                    "status": "pending_human_review",
                },
                {
                    "case_id": str(no_answer[0]["case_id"]),
                    "priority": "medium",
                    "review_area": "plausible_absence",
                    "reason": "确认问题在真实业务中自然且当前允许制度确实不应回答。",
                    "status": "pending_human_review",
                },
                {
                    "case_id": str(unauthorized[0]["case_id"]),
                    "priority": "high",
                    "review_area": "cross_permission_boundary",
                    "reason": "确认角色权限标签与禁止命中证据符合最终人工批准的访问矩阵。",
                    "status": "pending_human_review",
                },
            )
        )
    return queue


def _ceil_cost_microunits(input_tokens: int, price: int) -> int:
    return (input_tokens * price + 1_000_000 - 1) // 1_000_000


def _budget_step(
    *, name: str, request_count: int, input_token_upper_bound: int, price: int
) -> dict[str, object]:
    cost = _ceil_cost_microunits(input_token_upper_bound, price)
    return {
        "actual_cost_microunits": None,
        "actual_input_tokens": None,
        "estimated_max_cost_cny": f"{cost / 1_000_000:.6f}",
        "estimated_max_cost_microunits": cost,
        "input_token_upper_bound": input_token_upper_bound,
        "name": name,
        "provider_request_count": request_count,
        "retries_included": 0,
    }


def _paid_run_budget(
    *,
    corpus: JsonObject,
    proposed: list[JsonObject],
    fixed: list[JsonObject],
    pricing_policy: dict[str, Any],
) -> dict[str, object]:
    embedding_profile = pricing_policy.get("embedding_profile")
    operations = pricing_policy.get("operations")
    if type(embedding_profile) is not dict or type(operations) is not dict:
        raise AssetGenerationError("EMBEDDING_POLICY_INVALID")
    embedding_operation = operations.get("embedding")
    if type(embedding_operation) is not dict:
        raise AssetGenerationError("EMBEDDING_POLICY_INVALID")
    price = embedding_profile.get("input_price_microunits_per_million")
    batch_size = embedding_operation.get("max_batch_size")
    if (
        embedding_profile.get("cost_currency") != "CNY"
        or type(price) is not int
        or type(batch_size) is not int
        or price <= 0
        or batch_size <= 0
    ):
        raise AssetGenerationError("EMBEDDING_PRICING_INVALID")

    _, clauses, _ = _corpus_indexes(corpus)
    index_bytes = sum(
        len(str(clause["text"]).encode("utf-8")) for clause in clauses.values()
    )
    fixed_bytes = sum(len(str(case["query_text"]).encode("utf-8")) for case in fixed)
    proposed_bytes = sum(
        len(str(case["query_text"]).encode("utf-8")) for case in proposed
    )
    index_requests = (len(clauses) + batch_size - 1) // batch_size
    steps = [
        _budget_step(
            name="synthetic_policy_corpus_index_once",
            request_count=index_requests,
            input_token_upper_bound=index_bytes,
            price=price,
        ),
        _budget_step(
            name="mvp_uat_50_evaluation",
            request_count=len(fixed),
            input_token_upper_bound=fixed_bytes,
            price=price,
        ),
        _budget_step(
            name="proposed_100_evaluation",
            request_count=len(proposed),
            input_token_upper_bound=proposed_bytes,
            price=price,
        ),
        _budget_step(
            name="two_evaluations_reuse_compatible_ready_index",
            request_count=len(fixed) + len(proposed),
            input_token_upper_bound=fixed_bytes + proposed_bytes,
            price=price,
        ),
        _budget_step(
            name="index_once_then_two_evaluations",
            request_count=index_requests + len(fixed) + len(proposed),
            input_token_upper_bound=index_bytes + fixed_bytes + proposed_bytes,
            price=price,
        ),
    ]
    return {
        "actual_run_status": "not_run",
        "cost_currency": "CNY",
        "embedding_model_id": embedding_profile.get("model_id"),
        "input_price_microunits_per_million": price,
        "input_token_upper_bound_method": "utf8_byte_count_v1",
        "no_fx": True,
        "notes": [
            "Current evaluation executor sends one Embedding request per evaluation case.",
            "The fixed 50 cases are evaluated again inside the later 100-case run, so query requests total 150.",
            "The 36-clause corpus needs two index batches at the approved max batch size of 20.",
            "No retry or Chat request is included; Provider-reported usage remains authoritative.",
        ],
        "pricing_policy_id": pricing_policy.get("policy_id"),
        "steps_and_scenarios": steps,
    }


def build_benchmark_payload(
    corpus: JsonObject, corpus_bytes: bytes | None = None
) -> JsonObject:
    role_permissions = _role_permissions()
    pricing_policy = _read_json(PRICING_POLICY_PATH)
    rendered_corpus = (
        corpus_bytes if corpus_bytes is not None else render_payload(corpus)
    )
    candidates = _build_candidates(corpus, role_permissions)
    proposed, fixed, not_proposed = _select_case_sets(candidates)
    checks = _quality_checks(
        corpus=corpus,
        candidates=candidates,
        proposed=proposed,
        fixed=fixed,
    )
    proposed_ids = [str(case["case_id"]) for case in proposed]
    fixed_ids = [str(case["case_id"]) for case in fixed]
    not_proposed_ids = [str(case["case_id"]) for case in not_proposed]
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "synthetic": True,
        "classification": "benchmark_candidate_non_acceptance",
        "environment_scope": ["local", "test"],
        "controls": {
            "ac_status_changes": 0,
            "approved_dataset_created": False,
            "approval_state": "not_submitted",
            "index_activation": "not_run",
            "provider_calls_executed": 0,
            "release_gate_execution": "not_run",
            "runtime_tier": None,
        },
        "source_manifest": [
            {
                "file": CORPUS_OUTPUT_PATH.relative_to(ROOT).as_posix(),
                "role": "fictional_policy_evidence_source",
                "sha256": _sha256(rendered_corpus),
            },
            _source_entry(SCRIPT_PATH, "deterministic_candidate_generator"),
            _source_entry(PERMISSIONS_PATH, "role_and_permission_label_source"),
            _source_entry(PRICING_POLICY_PATH, "embedding_pricing_and_batch_source"),
        ],
        "policy_source_inventory": corpus["source_inventory"],
        "candidate_cases": candidates,
        "formal_candidate_proposal_100": {
            "approval_state": "not_submitted",
            "case_count": len(proposed_ids),
            "case_ids": proposed_ids,
            "case_ids_sha256": _sha256(_canonical_bytes(proposed_ids)),
            "not_proposed_case_count": len(not_proposed_ids),
            "not_proposed_case_ids": not_proposed_ids,
            "selection_basis": (
                "deterministic domain/label/version balance; proposal only pending human review"
            ),
            "status": "proposal_only",
        },
        "mvp_uat_subset_50": {
            "approval_state": "not_submitted",
            "case_count": len(fixed_ids),
            "case_ids": fixed_ids,
            "case_ids_sha256": _sha256(_canonical_bytes(fixed_ids)),
            "selection_basis": (
                "fixed deterministic subset of the proposed 100 with 30/10/10 label balance"
            ),
            "status": "fixed_candidate_subset",
        },
        "coverage_matrix": {
            "candidate_120": _coverage(candidates),
            "formal_candidate_proposal_100": _coverage(proposed),
            "mvp_uat_subset_50": _coverage(fixed),
        },
        "quality_report": {
            "automated_checks": checks,
            "automated_status": "passed",
            "human_review_required_before_approval": True,
            "human_review_status": "pending",
            "limitations": [
                "Automated contradiction checks cover identifiers, evidence links, and effective periods, not every possible semantic interpretation.",
                "Naturalness is checked by deterministic heuristics and still requires business review.",
                "Synthetic coverage does not establish representative business quality or runtime behavior.",
            ],
        },
        "human_review_queue": _human_review_queue(candidates),
        "paid_run_budget_estimate": _paid_run_budget(
            corpus=corpus,
            proposed=proposed,
            fixed=fixed,
            pricing_policy=pricing_policy,
        ),
    }


def render_payload(payload: JsonObject) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_assets() -> tuple[JsonObject, bytes, JsonObject, bytes]:
    corpus = build_corpus_payload()
    corpus_bytes = render_payload(corpus)
    benchmark = build_benchmark_payload(corpus, corpus_bytes)
    benchmark_bytes = render_payload(benchmark)
    _, clauses, _ = _corpus_indexes(corpus)
    authored_text = "\n".join(
        [str(clause["text"]) for clause in clauses.values()]
        + [str(case["query_text"]) for case in benchmark["candidate_cases"]]
    )
    if any(
        pattern.search(authored_text)
        for pattern in (
            re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
            re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
        )
    ):
        raise AssetGenerationError("POTENTIAL_REAL_IDENTIFIER_DETECTED")
    return corpus, corpus_bytes, benchmark, benchmark_bytes


def _summary(corpus_bytes: bytes, benchmark_bytes: bytes) -> str:
    return (
        "SYNTHETIC_POLICY_BENCHMARK_V1=PASS corpus=6/12/36 "
        "candidates=120 proposal=100 mvp_uat=50 provider_calls=0 "
        f"corpus_sha256={_sha256(corpus_bytes)} "
        f"benchmark_sha256={_sha256(benchmark_bytes)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--write", action="store_true", help="write both deterministic JSON assets"
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="compare both assets with regenerated bytes",
    )
    args = parser.parse_args()
    try:
        _, corpus_bytes, _, benchmark_bytes = build_assets()
        if args.write:
            CORPUS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            CORPUS_OUTPUT_PATH.write_bytes(corpus_bytes)
            BENCHMARK_OUTPUT_PATH.write_bytes(benchmark_bytes)
        elif (
            not CORPUS_OUTPUT_PATH.is_file()
            or CORPUS_OUTPUT_PATH.read_bytes() != corpus_bytes
            or not BENCHMARK_OUTPUT_PATH.is_file()
            or BENCHMARK_OUTPUT_PATH.read_bytes() != benchmark_bytes
        ):
            print(
                "SYNTHETIC_POLICY_BENCHMARK_V1=FAIL artifact_mismatch", file=sys.stderr
            )
            return 1
        print(_summary(corpus_bytes, benchmark_bytes))
        return 0
    except AssetGenerationError as error:
        print(f"SYNTHETIC_POLICY_BENCHMARK_V1=FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
