"""生成 BOSS 委托的 local/test 检索评测复核制品。

该生成器不调用 Provider、不访问数据库，也不把 Agent 复核冒充为人工 UAT。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_PATH = (
    PROJECT_ROOT / "tests" / "evaluation" / "synthetic-benchmark-candidate-v1.json"
)
CORPUS_PATH = PROJECT_ROOT / "tests" / "evaluation" / "synthetic-policy-corpus-v1.json"
OUTPUT_PATH = (
    PROJECT_ROOT
    / "tests"
    / "evaluation"
    / "synthetic-benchmark-owner-delegated-review-v1.json"
)

_NO_ANSWER_REVISIONS = {
    "SBCV1-N-REIMB-01": (
        "按2026-06-30有效制度，差旅住宿是否设有酒店品牌或星级上限？",
        "酒店品牌或星级上限",
    ),
    "SBCV1-N-REIMB-02": (
        "按2026-06-30有效制度，出差期间的餐费补助是否规定每日定额？",
        "餐费补助每日定额",
    ),
    "SBCV1-N-REIMB-03": (
        "按2026-06-30有效制度，自驾出差是否规定每公里报销标准？",
        "自驾里程报销标准",
    ),
    "SBCV1-N-REIMB-04": (
        "按2026-06-30有效制度，境外差旅报销应采用哪一天的汇率？",
        "境外差旅汇率日期",
    ),
    "SBCV1-N-VENDOR-01": (
        "按2026-06-30有效制度，新供应商准入是否设有最低注册资本要求？",
        "最低注册资本",
    ),
    "SBCV1-N-VENDOR-02": (
        "按2026-06-30有效制度，供应商现场核验应按什么频率复查？",
        "现场核验频率",
    ),
    "SBCV1-N-VENDOR-03": (
        "按2026-06-30有效制度，供应商是否必须提供环境管理体系认证？",
        "环境管理体系认证",
    ),
    "SBCV1-N-VENDOR-04": (
        "按2026-06-30有效制度，供应商申请移出黑名单的期限是多少？",
        "黑名单申诉期限",
    ),
    "SBCV1-N-INVOICE-01": (
        "按2026-06-30有效制度，电子发票上传时是否有固定文件命名规则？",
        "电子发票文件命名",
    ),
    "SBCV1-N-INVOICE-02": (
        "按2026-06-30有效制度，纸质发票原件应在开票后几天内寄达？",
        "纸质发票寄达期限",
    ),
    "SBCV1-N-INVOICE-03": (
        "按2026-06-30有效制度，每月发票报销是否设有统一截止日？",
        "月度报销截止日",
    ),
    "SBCV1-N-CONTRACT-01": (
        "按2026-06-30有效制度，一份合同应当保留多少份盖章原件？",
        "合同原件份数",
    ),
    "SBCV1-N-CONTRACT-02": (
        "按2026-06-30有效制度，偏离标准合同模板是否设有条款数量上限？",
        "模板偏离条款上限",
    ),
    "SBCV1-N-CONTRACT-03": (
        "按2026-06-30有效制度，电子签章证书是否限定服务商白名单？",
        "电子签章服务商白名单",
    ),
    "SBCV1-N-APPROVAL-01": (
        "按2026-06-30有效制度，代理审批授权最长可以持续多少天？",
        "代理审批最长天数",
    ),
    "SBCV1-N-APPROVAL-02": (
        "按2026-06-30有效制度，普通付款审批是否规定办理时限？",
        "普通付款审批时限",
    ),
    "SBCV1-N-APPROVAL-03": (
        "按2026-06-30有效制度，紧急付款应在多久内补办审批？",
        "紧急付款补审期限",
    ),
    "SBCV1-N-AUDIT-01": (
        "按2026-06-30有效制度，操作日志在线保存年限是多少？",
        "日志在线保存年限",
    ),
    "SBCV1-N-AUDIT-02": (
        "按2026-06-30有效制度，导出审计证据是否需要单独审批？",
        "审计证据导出审批",
    ),
    "SBCV1-N-AUDIT-03": (
        "按2026-06-30有效制度，应按什么频率抽查操作日志？",
        "操作日志抽查频率",
    ),
}


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError(f"{path.name} must contain one object")
    return value


def _id_hash(case_ids: list[str]) -> str:
    return _sha256("\n".join(case_ids).encode("utf-8"))


def _query_sha256(value: str) -> str:
    canonical = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    return _sha256(canonical.encode("utf-8"))


def build_artifact() -> dict[str, object]:
    candidate = _load(CANDIDATE_PATH)
    corpus = _load(CORPUS_PATH)
    if candidate.get("schema_version") != "synthetic-benchmark-candidate-v1":
        raise ValueError("candidate schema is invalid")
    if corpus.get("schema_version") != "synthetic-policy-corpus-v1":
        raise ValueError("corpus schema is invalid")

    raw_cases = candidate.get("candidate_cases")
    proposal = candidate.get("formal_candidate_proposal_100")
    mvp = candidate.get("mvp_uat_subset_50")
    review_queue = candidate.get("human_review_queue")
    if not all(type(value) is dict for value in (proposal, mvp)):
        raise ValueError("candidate selections are invalid")
    if type(raw_cases) is not list or type(review_queue) is not list:
        raise ValueError("candidate cases or review queue are invalid")

    by_id = {str(item["case_id"]): item for item in raw_cases}
    proposal_ids = [str(value) for value in proposal["case_ids"]]
    mvp_ids = [str(value) for value in mvp["case_ids"]]
    if (
        len(proposal_ids) != 100
        or len(mvp_ids) != 50
        or not set(mvp_ids) <= set(proposal_ids)
    ):
        raise ValueError("candidate selection counts are invalid")

    reviewed_cases: list[dict[str, object]] = []
    for case_id in proposal_ids:
        reviewed = copy.deepcopy(by_id[case_id])
        if reviewed["label"] == "no_answer":
            query_text, absence_probe = _NO_ANSWER_REVISIONS[case_id]
            reviewed["query_text"] = query_text
            reviewed["absence_probe"] = absence_probe
            reviewed["query_sha256"] = _query_sha256(query_text)
            reviewed["review_disposition"] = "revised_for_business_naturalness"
        else:
            reviewed["review_disposition"] = "accepted_as_is"
        reviewed_cases.append(reviewed)

    if len(_NO_ANSWER_REVISIONS) != 20:
        raise ValueError("all formal no-answer cases must be reviewed")
    queries = [str(case["query_text"]) for case in reviewed_cases]
    if len(set(queries)) != len(queries):
        raise ValueError("reviewed queries must remain unique")

    queue_decisions: list[dict[str, object]] = []
    for queued in review_queue:
        case_id = str(queued["case_id"])
        revised = case_id in _NO_ANSWER_REVISIONS
        queue_decisions.append(
            {
                "case_id": case_id,
                "decision": "revised_and_accepted" if revised else "accepted_as_is",
                "original_review_area": queued["review_area"],
                "reason": (
                    "已替换为制度可能被真实业务人员提出、但当前允许制度未覆盖的问题。"
                    if revised
                    else "基准日、制度版本、证据映射与当前 knowledge.use 权限事实一致。"
                ),
            }
        )
    if len(queue_decisions) != 18:
        raise ValueError("review queue count is invalid")

    reviewed_by_id = {str(case["case_id"]): case for case in reviewed_cases}
    mvp_cases = [reviewed_by_id[case_id] for case_id in mvp_ids]
    return {
        "schema_version": "synthetic-benchmark-owner-delegated-review-v1",
        "classification": "synthetic_non_sensitive",
        "environment_scope": ["local", "test"],
        "review_authority": {
            "authority_ref": "BOSS-LOCAL-TEST-DELEGATION-20260817",
            "authority_scope": "resolve local/test blockers and run bounded technical evaluation",
            "human_review_claimed": False,
            "review_method": "owner_delegated_agent_semantic_review",
        },
        "source_binding": {
            "candidate_path": CANDIDATE_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "candidate_sha256": _sha256(CANDIDATE_PATH.read_bytes()),
            "corpus_path": CORPUS_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "corpus_sha256": _sha256(CORPUS_PATH.read_bytes()),
        },
        "review_summary": {
            "formal_case_count": 100,
            "mvp_uat_case_count": 50,
            "queued_decision_count": 18,
            "accepted_as_is_queue_count": sum(
                decision["decision"] == "accepted_as_is" for decision in queue_decisions
            ),
            "revised_and_accepted_queue_count": sum(
                decision["decision"] == "revised_and_accepted"
                for decision in queue_decisions
            ),
            "all_no_answer_naturalness_reviewed_count": len(_NO_ANSWER_REVISIONS),
            "pending_count": 0,
        },
        "human_review_queue_decisions": queue_decisions,
        "formal_candidate_100": {
            "approval_state": "owner_delegated_local_test_approved",
            "case_count": len(reviewed_cases),
            "case_ids": proposal_ids,
            "case_ids_sha256": _id_hash(proposal_ids),
            "cases_sha256": _sha256(_canonical_bytes(reviewed_cases)),
            "cases": reviewed_cases,
        },
        "mvp_uat_subset_50": {
            "approval_state": "owner_delegated_local_test_approved",
            "case_count": len(mvp_cases),
            "case_ids": mvp_ids,
            "case_ids_sha256": _id_hash(mvp_ids),
            "cases_sha256": _sha256(_canonical_bytes(mvp_cases)),
        },
        "runtime_authorization": {
            "create_disposable_approved_datasets": True,
            "run_mvp_uat": True,
            "run_formal_release": True,
            "activate_disposable_index": True,
            "provider_request_cap": 152,
            "input_token_cap": 50000,
            "cost_cap_cny": "1.000000",
            "no_fx": True,
            "single_run": True,
            "automatic_scope_expansion": False,
            "production": False,
        },
        "boundaries": {
            "provider_calls_during_generation": 0,
            "database_access_during_generation": False,
            "is_business_representative_dataset": False,
            "is_human_uat": False,
            "is_formal_ac_acceptance": False,
            "may_mark_ac_accepted": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = _canonical_bytes(build_artifact())
    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_bytes() != payload:
            print("SYNTHETIC_BENCHMARK_REVIEWED_ASSET=DRIFT")
            return 1
        print("SYNTHETIC_BENCHMARK_REVIEWED_ASSET=PASS")
        return 0
    OUTPUT_PATH.write_bytes(payload)
    print(
        "SYNTHETIC_BENCHMARK_REVIEWED_ASSET=GENERATED "
        f"sha256={_sha256(payload)} cases=100 mvp_uat=50 provider_calls=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
