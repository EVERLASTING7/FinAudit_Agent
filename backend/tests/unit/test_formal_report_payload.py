from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from io import BytesIO
from uuid import UUID
from zipfile import ZipFile

import pytest
from pypdf import PdfReader

from app.ai.report_draft import ReportDraftOutput
from app.audit.offline_preview import RulePreviewDisposition
from app.audit.risk_summary import RiskLevel, RiskReviewStatus
from app.audit.rule_predicates import RuleExecutionStatus
from app.reports.artifact_payload import (
    validate_formal_report_payload,
    validate_report_payload,
)
from app.reports.formal_payload import (
    FormalCitation,
    FormalReportContext,
    FormalRiskFact,
    FormalRuleFact,
    build_formal_report_payload,
    formal_report_payload_json_bytes,
)
from app.reports.pdf_writer import formal_report_pdf_bytes
from app.reports.report_payload import ReportMetadata
from app.reports.xlsx_writer import formal_report_xlsx_bytes

_REPORT_ID = UUID(int=900)
_EXECUTION_ID = UUID(int=800)
_RISK_ID = UUID(int=700)
_GENERATED_AT = datetime(2026, 8, 14, 8, 30, tzinfo=timezone.utc)


def _facts() -> tuple[
    ReportMetadata,
    FormalReportContext,
    tuple[FormalRuleFact, ...],
]:
    risk = FormalRiskFact(
        risk_id=_RISK_ID,
        rule_code="RULE-001",
        original_level=RiskLevel.HIGH,
        effective_level=RiskLevel.MEDIUM,
        review_status=RiskReviewStatus.ADJUSTED,
        actual_value="'=SUM(1,1) 实际值",
        expected_value="合同限额 90.00",
        reviewed_by=UUID(int=11),
        reviewed_at=_GENERATED_AT,
        review_reason="依据原始凭证调整为中风险",
    )
    citation = FormalCitation(
        risk_id=_RISK_ID,
        policy_document_id=UUID(int=21),
        markdown_version_id=UUID(int=22),
        chunk_id=UUID(int=23),
        index_version_id=UUID(int=24),
        start_page_no=3,
        end_page_no=4,
        title_path=("第三章", "付款控制"),
        quote="付款金额不得超过已审批合同限额。",
        content_sha256="a" * 64,
    )
    context = FormalReportContext(
        task_id=UUID(int=31),
        task_no="AUD-2026-001",
        task_name="采购付款专项审核",
        execution_id=_EXECUTION_ID,
        execution_version=2,
        baseline_date=date(2026, 8, 14),
        finance_reviewer_id=UUID(int=32),
        finance_reviewed_at=_GENERATED_AT,
        audit_reviewer_id=UUID(int=33),
        audit_reviewed_at=_GENERATED_AT,
        risks=(risk,),
        citations=(citation,),
    )
    rules = tuple(
        FormalRuleFact(
            rule_code=f"RULE-{number:03d}",
            status=(RuleExecutionStatus.FAILED if number == 1 else RuleExecutionStatus.PASSED),
            disposition=(
                RulePreviewDisposition.HIT if number == 1 else RulePreviewDisposition.NOT_HIT
            ),
            actual_value=risk.actual_value if number == 1 else None,
            expected_value=risk.expected_value if number == 1 else None,
            included_item_ids=(UUID(int=41),) if number == 1 else (),
        )
        for number in range(1, 16)
    )
    metadata = ReportMetadata(
        report_version_id=_REPORT_ID,
        audit_version_id=_EXECUTION_ID,
        generated_at=_GENERATED_AT,
        is_outdated=False,
        is_degraded=True,
        degraded_reasons=("AI_DECISION_DISABLED",),
    )
    return metadata, context, rules


def test_formal_payload_is_deterministic_and_includes_review_and_citation_hash_input() -> None:
    metadata, context, rules = _facts()
    payload = build_formal_report_payload(metadata, context, rules)

    first = formal_report_payload_json_bytes(payload, context)
    second = formal_report_payload_json_bytes(payload, context)
    changed_context = replace(
        context,
        risks=(replace(context.risks[0], review_reason="复核原因已更新"),),
    )

    assert first == second
    assert first != formal_report_payload_json_bytes(payload, changed_context)
    document = json.loads(first)
    assert document["profile"] == "formal-report-runtime-v1"
    assert document["context"]["risk_reviews"][0]["review_status"] == "adjusted"
    assert document["context"]["citations"][0]["quote"] == context.citations[0].quote
    assert validate_formal_report_payload(payload) == "AI_DECISION_DISABLED"
    with pytest.raises(ValueError, match="pending status"):
        validate_report_payload(payload)


def test_formal_pdf_contains_reviewers_decisions_and_policy_evidence() -> None:
    metadata, context, rules = _facts()
    payload = build_formal_report_payload(metadata, context, rules)

    content = formal_report_pdf_bytes(payload, context)
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)

    assert "FinAudit 正式审核报告" in text
    assert "Review Decisions" in text
    assert "Policy Evidence" in text
    assert str(context.finance_reviewer_id) in text
    assert str(context.audit_reviewer_id) in text
    assert context.risks[0].review_reason in text
    assert context.citations[0].quote in text
    assert "内部离线预览（非正式审核报告）" not in text


def test_formal_xlsx_keeps_reviewed_status_and_contains_no_formula_cells() -> None:
    metadata, context, rules = _facts()
    payload = build_formal_report_payload(metadata, context, rules)

    content = formal_report_xlsx_bytes(payload)

    with ZipFile(BytesIO(content)) as archive:
        xml = b"\n".join(
            archive.read(name)
            for name in archive.namelist()
            if name.endswith(".xml") or name.endswith(".rels")
        )
    assert b"<f>" not in xml
    assert b"<f " not in xml
    assert b"adjusted" in xml
    assert b"SUM(1,1)" in xml


def test_formal_pdf_and_xlsx_label_and_formula_protect_ai_draft() -> None:
    metadata, context, rules = _facts()
    payload = build_formal_report_payload(metadata, context, rules)
    draft = ReportDraftOutput(
        report_id=str(_REPORT_ID),
        execution_id=str(_EXECUTION_ID),
        overall_level="medium",
        active_risk_count=1,
        dismissed_risk_count=0,
        has_effective_high=False,
        has_unreviewed_high=False,
        executive_summary="=SUM(1,1) AI 仅生成文字草稿。",
        scope_summary="覆盖当前冻结执行版本。",
        risk_summary="一项活动风险已由人工调整为中风险。",
        recommendations=("由授权审核人复核正式结论。",),
        warnings=("AI 草稿未审批，不替代规则和人工复核。",),
    )

    pdf = formal_report_pdf_bytes(payload, context, draft)
    pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    assert "AI Draft (Unapproved)" in pdf_text
    assert "以下文字由 AI 生成，仅作草稿，不替代规则结果与人工复核。" in pdf_text
    assert "=SUM(1,1) AI 仅生成文字草稿。" in pdf_text

    xlsx = formal_report_xlsx_bytes(payload, draft)
    with ZipFile(BytesIO(xlsx)) as archive:
        workbook = archive.read("xl/workbook.xml")
        shared_strings = archive.read("xl/sharedStrings.xml")
        xml = b"\n".join(
            archive.read(name)
            for name in archive.namelist()
            if name.endswith(".xml") or name.endswith(".rels")
        )
    assert b'name="AI Draft"' in workbook
    assert "'=SUM(1,1) AI 仅生成文字草稿。".encode() in shared_strings
    assert b"<f>" not in xml
    assert b"<f " not in xml


def test_formal_risk_rejects_pending_review() -> None:
    _metadata, context, _rules = _facts()

    with pytest.raises(ValueError, match="must be reviewed"):
        replace(context.risks[0], review_status=RiskReviewStatus.PENDING)
