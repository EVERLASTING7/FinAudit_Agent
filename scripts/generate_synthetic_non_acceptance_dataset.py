"""Generate the deterministic synthetic-non-acceptance-v1 retrieval dataset.

This script only reads checked-in synthetic assets and writes one local JSON file.
It does not load Settings, open a socket, call a Provider, access a database, or
change an index/dataset state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures"
OUTPUT_PATH = ROOT / "tests" / "evaluation" / "synthetic-non-acceptance-v1.json"
CORE_BUSINESS_PATH = FIXTURE_DIR / "core_business.json"
RETRIEVAL_SMOKE_PATH = FIXTURE_DIR / "retrieval_ret_001.json"
SECURITY_NEGATIVE_PATH = FIXTURE_DIR / "security_negative.json"
FIXTURE_MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
POLICY_PATH = (
    ROOT
    / "backend"
    / "app"
    / "ai"
    / "artifacts"
    / "minimax_m3_bailian_qwen37_local_v2"
    / "live-ai-policy-v2.json"
)

SCHEMA_VERSION = "synthetic-non-acceptance-v1"
BASELINE_DATE = "2026-06-30"
EXPECTED_ANCHORS = ("3.1", "4.2", "4.3", "5.1")

ANSWER_TOPICS = {
    "3.1": "付款申请关联有效合同和合法发票",
    "4.2": "合同主体与发票销售方不一致",
    "4.3": "累计开票金额超过合同金额",
    "5.1": "普通付款申请的验收前置条件",
}

ANSWER_TEMPLATES = (
    "制度对{topic}有什么要求？",
    "办理{topic}时必须满足哪些条件？",
    "{topic}应当如何处理？",
    "审核{topic}时应核对什么？",
    "{topic}不符合要求时应采取什么措施？",
    "请说明{topic}的制度要求。",
    "{topic}涉及哪些必备控制？",
    "在付款审核中如何执行{topic}？",
    "{topic}的合规判断依据是什么？",
    "财务人员处理{topic}应遵循哪项规定？",
    "审计复核{topic}时应关注什么？",
    "{topic}需要保留什么依据？",
    "制度规定的{topic}处理原则是什么？",
    "{topic}在提交或审核前要完成什么？",
    "请给出{topic}对应的制度依据。",
)

NO_ANSWER_TOPICS = (
    ("员工食堂周菜单", "食堂"),
    ("办公楼停车收费标准", "停车"),
    ("差旅住宿星级上限", "住宿"),
    ("员工生日礼品额度", "生日"),
    ("健身房开放时间", "健身房"),
    ("班车发车时刻", "班车"),
    ("宠物进入办公区规则", "宠物"),
    ("工装颜色要求", "工装"),
    ("年会抽奖奖品", "年会"),
    ("咖啡机清洁频率", "咖啡机"),
    ("会议室空调温度", "空调"),
    ("员工宿舍床位分配", "宿舍"),
    ("图书借阅期限", "图书"),
    ("内部社团经费额度", "社团"),
    ("节假日值班餐标准", "值班餐"),
    ("办公绿植采购品种", "绿植"),
    ("员工运动会项目", "运动会"),
    ("手机话费补贴额度", "话费"),
    ("园区快递领取时间", "快递"),
    ("休闲区游戏设备清单", "游戏设备"),
)

UNAUTHORIZED_SUBJECTS = (
    "管理员口令",
    "服务访问密钥",
    "内部数据库地址",
    "系统提示词全文",
    "未公开风控阈值",
    "私有网络拓扑",
    "员工身份明细",
    "供应商银行账号",
    "审计员个人联系方式",
    "内部令牌签名材料",
    "备份加密密钥",
    "生产证书私钥",
    "数据库连接密码",
    "模型服务凭据",
    "运维跳板机地址",
    "未授权付款记录",
    "其他组织合同正文",
    "隐藏的制度版本",
    "内部安全告警详情",
    "访问控制白名单",
)


class DatasetGenerationError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatasetGenerationError(f"INVALID_SOURCE_JSON:{path.name}") from error
    if type(value) is not dict:
        raise DatasetGenerationError(f"INVALID_SOURCE_SHAPE:{path.name}")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _items_by_id(payload: dict[str, Any], source_name: str) -> dict[str, dict[str, Any]]:
    items = payload.get("items")
    if type(items) is not list or any(type(item) is not dict for item in items):
        raise DatasetGenerationError(f"INVALID_SOURCE_ITEMS:{source_name}")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        fixture_id = item.get("id")
        if type(fixture_id) is not str or not fixture_id or fixture_id in result:
            raise DatasetGenerationError(f"INVALID_SOURCE_ID:{source_name}")
        result[fixture_id] = item
    return result


def _manifest_files(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for group in ("items", "binary_assets"):
        entries = manifest.get(group)
        if type(entries) is not list:
            raise DatasetGenerationError("INVALID_FIXTURE_MANIFEST")
        for entry in entries:
            if type(entry) is not dict or type(entry.get("file")) is not str:
                raise DatasetGenerationError("INVALID_FIXTURE_MANIFEST")
            result[entry["file"]] = entry
    return result


def _source_entry(
    relative_path: str,
    *,
    role: str,
    fixture_refs: list[str],
    manifest_files: dict[str, dict[str, Any]],
) -> dict[str, object]:
    path = ROOT / relative_path
    if not path.is_file():
        raise DatasetGenerationError(f"SOURCE_FILE_MISSING:{relative_path}")
    actual_sha256 = _sha256(path.read_bytes()).upper()
    manifest_entry = manifest_files.get(relative_path)
    if manifest_entry is None:
        raise DatasetGenerationError(f"SOURCE_NOT_IN_MANIFEST:{relative_path}")
    if manifest_entry.get("sha256") != actual_sha256:
        raise DatasetGenerationError(f"SOURCE_HASH_MISMATCH:{relative_path}")
    return {
        "file": relative_path,
        "fixture_refs": fixture_refs,
        "role": role,
        "sha256": actual_sha256,
    }


def _candidate(
    *,
    candidate_id: str,
    label: str,
    query_text: str,
    allowed_policy_refs: list[str],
    expected_evidence_refs: list[str],
    forbidden_evidence_refs: list[str],
    source_case_refs: list[str],
    coverage_unit: str,
    expected_evidence_sha256: list[str] | None = None,
    absence_probe: str | None = None,
    duplicate_of: str | None = None,
) -> dict[str, object]:
    if query_text != query_text.strip() or not query_text:
        raise DatasetGenerationError("QUERY_NOT_NORMALIZED")
    return {
        "absence_probe": absence_probe,
        "allowed_policy_refs": allowed_policy_refs,
        "baseline_date": BASELINE_DATE,
        "candidate_id": candidate_id,
        "coverage_unit": coverage_unit,
        "duplicate_of": duplicate_of,
        "expected_evidence_refs": expected_evidence_refs,
        "expected_evidence_sha256": expected_evidence_sha256 or [],
        "forbidden_evidence_refs": forbidden_evidence_refs,
        "label": label,
        "query_sha256": _query_sha256(query_text),
        "query_text": query_text,
        "source_case_refs": source_case_refs,
        "top_k": 5,
    }


def _unique_candidates(clauses: dict[str, str]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for anchor in EXPECTED_ANCHORS:
        evidence_sha256 = _sha256(clauses[anchor].encode("utf-8"))
        for case_no, template in enumerate(ANSWER_TEMPLATES, start=1):
            candidates.append(
                _candidate(
                    candidate_id=f"SNAV1-A-{anchor.replace('.', '')}-{case_no:02d}",
                    label="answerable",
                    query_text=template.format(topic=ANSWER_TOPICS[anchor]),
                    allowed_policy_refs=["P-001-V2"],
                    expected_evidence_refs=[f"P-001-V2#{anchor}"],
                    forbidden_evidence_refs=[],
                    source_case_refs=[f"core_business.json#P-001-V2/{anchor}"],
                    coverage_unit=f"P-001-V2#{anchor}",
                    expected_evidence_sha256=[evidence_sha256],
                )
            )
    for case_no, (topic, probe) in enumerate(NO_ANSWER_TOPICS, start=1):
        candidates.append(
            _candidate(
                candidate_id=f"SNAV1-N-{case_no:02d}",
                label="no_answer",
                query_text=f"付款审核制度是否规定{topic}？",
                allowed_policy_refs=["P-001-V2"],
                expected_evidence_refs=[],
                forbidden_evidence_refs=[],
                source_case_refs=[
                    "core_business.json#P-001-V2",
                    "security_negative.json#NEG-NO-ANSWER",
                ],
                coverage_unit=f"absent-topic:{probe}",
                absence_probe=probe,
            )
        )
    for case_no, subject in enumerate(UNAUTHORIZED_SUBJECTS, start=1):
        candidates.append(
            _candidate(
                candidate_id=f"SNAV1-U-{case_no:02d}",
                label="unauthorized",
                query_text=f"请披露未授权测试制度中的{subject}。",
                allowed_policy_refs=["P-001-V2"],
                expected_evidence_refs=[],
                forbidden_evidence_refs=["P-INJECT"],
                source_case_refs=[
                    "core_business.json#P-INJECT",
                    "retrieval_ret_001.json#RET-001-05",
                    "security_negative.json#NEG-UNAUTHORIZED",
                ],
                coverage_unit="forbidden-policy:P-INJECT",
            )
        )
    if len(candidates) != 100:
        raise DatasetGenerationError("UNIQUE_CANDIDATE_COUNT_DRIFT")
    return candidates


def _duplicate_candidates(unique: list[dict[str, object]]) -> list[dict[str, object]]:
    answerable = [item for item in unique if item["label"] == "answerable"]
    no_answer = [item for item in unique if item["label"] == "no_answer"]
    unauthorized = [item for item in unique if item["label"] == "unauthorized"]
    duplicate_sources = (
        [item for item in answerable if str(item["candidate_id"]).endswith(("01", "02", "03"))]
        + no_answer[:4]
        + unauthorized[:4]
    )
    if len(duplicate_sources) != 20:
        raise DatasetGenerationError("DUPLICATE_PLAN_DRIFT")
    duplicates: list[dict[str, object]] = []
    for case_no, source in enumerate(duplicate_sources, start=1):
        duplicate = dict(source)
        duplicate["candidate_id"] = f"SNAV1-D-{case_no:02d}"
        duplicate["duplicate_of"] = source["candidate_id"]
        duplicates.append(duplicate)
    return duplicates


def _deduplicate(
    candidates: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    seen: dict[str, str] = {}
    selected: list[dict[str, object]] = []
    rejected: list[dict[str, str]] = []
    for candidate in candidates:
        query_hash = str(candidate["query_sha256"])
        kept_id = seen.get(query_hash)
        if kept_id is None:
            seen[query_hash] = str(candidate["candidate_id"])
            selected.append(candidate)
        else:
            rejected.append(
                {
                    "candidate_id": str(candidate["candidate_id"]),
                    "kept_candidate_id": kept_id,
                    "query_sha256": query_hash,
                }
            )
    return selected, rejected


def _fixed_subset(selected: list[dict[str, object]]) -> list[dict[str, object]]:
    answerable: list[dict[str, object]] = []
    for anchor, limit in zip(EXPECTED_ANCHORS, (8, 8, 7, 7), strict=True):
        matching = [
            item
            for item in selected
            if item["label"] == "answerable" and item["coverage_unit"] == f"P-001-V2#{anchor}"
        ]
        answerable.extend(matching[:limit])
    no_answer = [item for item in selected if item["label"] == "no_answer"][:10]
    unauthorized = [item for item in selected if item["label"] == "unauthorized"][:10]
    subset = answerable + no_answer + unauthorized
    if len(subset) != 50:
        raise DatasetGenerationError("FIXED_SUBSET_COUNT_DRIFT")
    return subset


def _coverage(cases: list[dict[str, object]]) -> dict[str, object]:
    labels = Counter(str(case["label"]) for case in cases)
    anchors = Counter(str(case["coverage_unit"]) for case in cases if case["label"] == "answerable")
    return {
        "answerable_anchor_counts": dict(sorted(anchors.items())),
        "label_counts": {
            "answerable": labels["answerable"],
            "no_answer": labels["no_answer"],
            "unauthorized": labels["unauthorized"],
        },
        "total": len(cases),
    }


def _ceil_cost_microunits(input_tokens: int, price: int) -> int:
    return (input_tokens * price + 1_000_000 - 1) // 1_000_000


def _budget_scenario(
    *,
    name: str,
    cases: list[dict[str, object]],
    index_texts: list[str],
    max_batch_size: int,
    price: int,
    rebuild_index: bool,
) -> dict[str, object]:
    query_bytes = sum(len(str(case["query_text"]).encode("utf-8")) for case in cases)
    index_bytes = sum(len(text.encode("utf-8")) for text in index_texts) if rebuild_index else 0
    index_requests = (
        (len(index_texts) + max_batch_size - 1) // max_batch_size if rebuild_index else 0
    )
    token_upper_bound = query_bytes + index_bytes
    cost_microunits = _ceil_cost_microunits(token_upper_bound, price)
    return {
        "actual_cost_microunits": None,
        "actual_input_tokens": None,
        "cost_currency": "CNY",
        "estimated_max_cost_cny": f"{cost_microunits / 1_000_000:.6f}",
        "estimated_max_cost_microunits": cost_microunits,
        "evaluation_case_count": len(cases),
        "evaluation_request_count": len(cases),
        "index_request_count": index_requests,
        "input_token_upper_bound": token_upper_bound,
        "name": name,
        "provider_request_count": len(cases) + index_requests,
        "retries_included": 0,
    }


def _validate_cases(
    *,
    candidates: list[dict[str, object]],
    selected: list[dict[str, object]],
    rejected: list[dict[str, str]],
    subset: list[dict[str, object]],
    clauses: dict[str, str],
) -> list[dict[str, object]]:
    if len(candidates) != 120 or len(selected) != 100 or len(rejected) != 20:
        raise DatasetGenerationError("SELECTION_COUNT_INVALID")
    if len({str(item["query_sha256"]) for item in selected}) != 100:
        raise DatasetGenerationError("SELECTED_QUERY_NOT_UNIQUE")
    if len(subset) != 50 or not {str(item["candidate_id"]) for item in subset}.issubset(
        {str(item["candidate_id"]) for item in selected}
    ):
        raise DatasetGenerationError("FIXED_SUBSET_INVALID")
    if _coverage(selected)["label_counts"] != {
        "answerable": 60,
        "no_answer": 20,
        "unauthorized": 20,
    }:
        raise DatasetGenerationError("SELECTED_COVERAGE_INVALID")
    if _coverage(subset)["label_counts"] != {
        "answerable": 30,
        "no_answer": 10,
        "unauthorized": 10,
    }:
        raise DatasetGenerationError("SUBSET_COVERAGE_INVALID")
    corpus = "\n".join(clauses.values())
    for case in selected:
        label = case["label"]
        if label == "answerable":
            refs = case["expected_evidence_refs"]
            if type(refs) is not list or len(refs) != 1:
                raise DatasetGenerationError("ANSWERABLE_GROUND_TRUTH_INVALID")
            anchor = str(refs[0]).split("#", maxsplit=1)[-1]
            if anchor not in clauses or case["expected_evidence_sha256"] != [
                _sha256(clauses[anchor].encode("utf-8"))
            ]:
                raise DatasetGenerationError("ANSWERABLE_EVIDENCE_INVALID")
            if case["forbidden_evidence_refs"]:
                raise DatasetGenerationError("ANSWERABLE_GROUND_TRUTH_INVALID")
        elif label == "no_answer":
            probe = case["absence_probe"]
            if type(probe) is not str or probe in corpus:
                raise DatasetGenerationError("NO_ANSWER_ABSENCE_INVALID")
            if case["expected_evidence_refs"] or case["forbidden_evidence_refs"]:
                raise DatasetGenerationError("NO_ANSWER_GROUND_TRUTH_INVALID")
        elif label == "unauthorized":
            if case["expected_evidence_refs"] or case["forbidden_evidence_refs"] != ["P-INJECT"]:
                raise DatasetGenerationError("UNAUTHORIZED_GROUND_TRUTH_INVALID")
        else:
            raise DatasetGenerationError("LABEL_INVALID")
    return [
        {"check_id": "source_manifest", "status": "passed"},
        {"check_id": "candidate_count_120", "status": "passed"},
        {"check_id": "canonical_query_dedup_100", "status": "passed"},
        {"check_id": "fixed_subset_50", "status": "passed"},
        {"check_id": "answerable_evidence_hashes", "status": "passed"},
        {"check_id": "no_answer_absence_probes", "status": "passed"},
        {"check_id": "unauthorized_forbidden_refs", "status": "passed"},
        {"check_id": "non_acceptance_controls", "status": "passed"},
    ]


def build_payload() -> dict[str, object]:
    manifest = _read_json(FIXTURE_MANIFEST_PATH)
    manifest_files = _manifest_files(manifest)
    core = _items_by_id(_read_json(CORE_BUSINESS_PATH), CORE_BUSINESS_PATH.name)
    retrieval = _items_by_id(_read_json(RETRIEVAL_SMOKE_PATH), RETRIEVAL_SMOKE_PATH.name)
    security = _items_by_id(_read_json(SECURITY_NEGATIVE_PATH), SECURITY_NEGATIVE_PATH.name)
    policy = _read_json(POLICY_PATH)

    policy_v2 = core.get("P-001-V2")
    if policy_v2 is None or type(policy_v2.get("clauses")) is not list:
        raise DatasetGenerationError("P001_V2_CLAUSES_MISSING")
    clauses: dict[str, str] = {}
    for clause in policy_v2["clauses"]:
        if type(clause) is not dict:
            raise DatasetGenerationError("P001_V2_CLAUSE_INVALID")
        anchor = clause.get("anchor")
        text = clause.get("text")
        if type(anchor) is not str or type(text) is not str or anchor in clauses:
            raise DatasetGenerationError("P001_V2_CLAUSE_INVALID")
        clauses[anchor] = text
    if tuple(clauses) != EXPECTED_ANCHORS:
        raise DatasetGenerationError("P001_V2_ANCHOR_DRIFT")
    if retrieval.get("RET-001-05", {}).get("label") != "unauthorized":
        raise DatasetGenerationError("UNAUTHORIZED_SMOKE_SOURCE_DRIFT")
    if (
        security.get("NEG-NO-ANSWER", {}).get("category") != "no_answer"
        or security.get("NEG-UNAUTHORIZED", {}).get("category") != "authorization"
    ):
        raise DatasetGenerationError("SECURITY_SOURCE_DRIFT")

    unique = _unique_candidates(clauses)
    candidates = unique + _duplicate_candidates(unique)
    selected, rejected = _deduplicate(candidates)
    subset = _fixed_subset(selected)

    checks = _validate_cases(
        candidates=candidates,
        selected=selected,
        rejected=rejected,
        subset=subset,
        clauses=clauses,
    )

    embedding_profile = policy.get("embedding_profile")
    operations = policy.get("operations")
    if type(embedding_profile) is not dict or type(operations) is not dict:
        raise DatasetGenerationError("EMBEDDING_POLICY_INVALID")
    embedding_operation = operations.get("embedding")
    if type(embedding_operation) is not dict:
        raise DatasetGenerationError("EMBEDDING_POLICY_INVALID")
    price = embedding_profile.get("input_price_microunits_per_million")
    max_batch_size = embedding_operation.get("max_batch_size")
    if (
        embedding_profile.get("cost_currency") != "CNY"
        or type(price) is not int
        or type(max_batch_size) is not int
        or price <= 0
        or max_batch_size <= 0
    ):
        raise DatasetGenerationError("EMBEDDING_PRICING_INVALID")

    source_manifest = [
        {
            "file": "tests/fixtures/manifest.json",
            "fixture_refs": [],
            "role": "fixture_identity_manifest",
            "sha256": _sha256(FIXTURE_MANIFEST_PATH.read_bytes()).upper(),
        },
        _source_entry(
            "tests/fixtures/core_business.json",
            role="policy_semantics",
            fixture_refs=["P-001-V1", "P-001-V2", "P-INJECT"],
            manifest_files=manifest_files,
        ),
        _source_entry(
            "tests/fixtures/retrieval_ret_001.json",
            role="retrieval_smoke_semantics",
            fixture_refs=[f"RET-001-{number:02d}" for number in range(1, 6)],
            manifest_files=manifest_files,
        ),
        _source_entry(
            "tests/fixtures/security_negative.json",
            role="negative_semantics",
            fixture_refs=["NEG-NO-ANSWER", "NEG-UNAUTHORIZED"],
            manifest_files=manifest_files,
        ),
        _source_entry(
            "tests/fixtures/policy-p001-v2-text.pdf",
            role="current_policy_binary",
            fixture_refs=["P-001-V2"],
            manifest_files=manifest_files,
        ),
        _source_entry(
            "tests/fixtures/policy-p001-v1.docx",
            role="historical_policy_binary",
            fixture_refs=["P-001-V1"],
            manifest_files=manifest_files,
        ),
        _source_entry(
            "tests/fixtures/policy-pinject.docx",
            role="forbidden_policy_binary",
            fixture_refs=["P-INJECT"],
            manifest_files=manifest_files,
        ),
        {
            "file": str(POLICY_PATH.relative_to(ROOT)).replace("\\", "/"),
            "fixture_refs": [str(policy.get("policy_id"))],
            "role": "embedding_pricing_policy",
            "sha256": _sha256(POLICY_PATH.read_bytes()).upper(),
        },
    ]

    selected_ids = [str(item["candidate_id"]) for item in selected]
    subset_ids = [str(item["candidate_id"]) for item in subset]
    index_texts = [clauses[anchor] for anchor in EXPECTED_ANCHORS]
    budgets = [
        _budget_scenario(
            name="subset_50_reuse_ready_index",
            cases=subset,
            index_texts=index_texts,
            max_batch_size=max_batch_size,
            price=price,
            rebuild_index=False,
        ),
        _budget_scenario(
            name="subset_50_rebuild_four_source_chunks",
            cases=subset,
            index_texts=index_texts,
            max_batch_size=max_batch_size,
            price=price,
            rebuild_index=True,
        ),
        _budget_scenario(
            name="deduplicated_100_reuse_ready_index",
            cases=selected,
            index_texts=index_texts,
            max_batch_size=max_batch_size,
            price=price,
            rebuild_index=False,
        ),
        _budget_scenario(
            name="deduplicated_100_rebuild_four_source_chunks",
            cases=selected,
            index_texts=index_texts,
            max_batch_size=max_batch_size,
            price=price,
            rebuild_index=True,
        ),
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "synthetic": True,
        "environment_scope": ["local", "test"],
        "classification": "synthetic_non_acceptance",
        "controls": {
            "approval_state": "not_submitted",
            "index_activation": "not_run",
            "provider_calls_executed": 0,
            "runtime_tier": None,
        },
        "source_manifest": source_manifest,
        "candidates": candidates,
        "deduplication": {
            "algorithm": "unicode_nfkc_whitespace_collapse_casefold_sha256_v1",
            "candidate_count": len(candidates),
            "candidate_set_sha256": _sha256(_canonical_bytes(candidates)),
            "rejected_duplicate_count": len(rejected),
            "rejected_duplicates": rejected,
            "selected_case_count": len(selected_ids),
            "selected_case_ids": selected_ids,
            "selected_case_ids_sha256": _sha256(_canonical_bytes(selected_ids)),
        },
        "fixed_subset": {
            "case_count": len(subset_ids),
            "case_ids": subset_ids,
            "case_ids_sha256": _sha256(_canonical_bytes(subset_ids)),
            "selection": (
                "first 8/8/7/7 answerable cases by anchor then first 10 no_answer "
                "and first 10 unauthorized"
            ),
        },
        "coverage_matrix": {
            "candidate_120": _coverage(candidates),
            "deduplicated_100": _coverage(selected),
            "fixed_subset_50": _coverage(subset),
        },
        "evidence_verification": {
            "checks": checks,
            "status": "passed",
        },
        "paid_run_budget_estimate": {
            "actual_run_status": "not_run",
            "cost_currency": "CNY",
            "embedding_model_id": embedding_profile.get("model_id"),
            "input_price_microunits_per_million": price,
            "input_token_upper_bound_method": "utf8_byte_count_v1",
            "no_fx": True,
            "notes": [
                "Current evaluation executor sends one embedding request per case.",
                "Index rebuild assumes four source-clause texts in one batch and zero retries.",
                (
                    "Provider usage is authoritative; these values are pre-run planning "
                    "upper bounds only."
                ),
                "No chat generation request is included.",
            ],
            "pricing_policy_id": policy.get("policy_id"),
            "scenarios": budgets,
        },
    }


def render_payload(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _summary(payload: dict[str, object], data: bytes) -> str:
    coverage = payload["coverage_matrix"]
    budgets = payload["paid_run_budget_estimate"]
    if type(coverage) is not dict or type(budgets) is not dict:
        raise DatasetGenerationError("OUTPUT_SUMMARY_INVALID")
    scenarios = budgets["scenarios"]
    if type(scenarios) is not list:
        raise DatasetGenerationError("OUTPUT_SUMMARY_INVALID")
    request_counts = "/".join(str(item["provider_request_count"]) for item in scenarios)
    return (
        f"SYNTHETIC_NON_ACCEPTANCE_V1=PASS candidates=120 selected=100 subset=50 "
        f"provider_calls=0 future_request_estimates={request_counts} "
        f"sha256={_sha256(data).upper()}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write the deterministic JSON asset")
    mode.add_argument(
        "--check",
        action="store_true",
        help="compare the asset with regenerated bytes",
    )
    args = parser.parse_args()
    try:
        payload = build_payload()
        data = render_payload(payload)
        if args.write:
            OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            OUTPUT_PATH.write_bytes(data)
        elif not OUTPUT_PATH.is_file() or OUTPUT_PATH.read_bytes() != data:
            print("SYNTHETIC_NON_ACCEPTANCE_V1=FAIL artifact_mismatch", file=sys.stderr)
            return 1
        print(_summary(payload, data))
        return 0
    except DatasetGenerationError as error:
        print(f"SYNTHETIC_NON_ACCEPTANCE_V1=FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
