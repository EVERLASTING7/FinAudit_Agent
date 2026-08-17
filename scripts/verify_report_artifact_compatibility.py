"""生成并复核固定正式报告，用于宿主与 Backend 镜像兼容性门禁。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree
from zipfile import ZipFile

from pypdf import PdfReader
from pypdf.generic import DictionaryObject

from app.audit.offline_preview import RulePreviewDisposition
from app.audit.risk_summary import RiskLevel, RiskReviewStatus
from app.audit.rule_predicates import RuleExecutionStatus
from app.reports.formal_payload import (
    FormalCitation,
    FormalReportContext,
    FormalRiskFact,
    FormalRuleFact,
    build_formal_report_payload,
)
from app.reports.pdf_writer import formal_report_pdf_bytes
from app.reports.report_payload import ReportMetadata
from app.reports.xlsx_writer import formal_report_xlsx_bytes

_PDF_NAME = "formal-report.pdf"
_XLSX_NAME = "formal-risk-details.xlsx"
_EXPECTED_SHEETS = ("Summary", "Rules", "Risks")
_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RELATIONSHIP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_RELATIONSHIP_NS = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)


@dataclass(frozen=True, slots=True)
class PdfInspection:
    sha256: str
    page_count: int
    text_sha256: str


@dataclass(frozen=True, slots=True)
class XlsxInspection:
    sha256: str
    sheets: tuple[str, ...]
    content_sha256: str


@dataclass(frozen=True, slots=True)
class CompatibilityInspection:
    schema_version: str
    python_version: str
    pdf: PdfInspection
    xlsx: XlsxInspection


def _fixture() -> tuple[
    ReportMetadata, FormalReportContext, tuple[FormalRuleFact, ...]
]:
    generated_at = datetime(2026, 8, 14, 8, 30, tzinfo=timezone.utc)
    risk = FormalRiskFact(
        risk_id=UUID(int=700),
        rule_code="RULE-001",
        original_level=RiskLevel.HIGH,
        effective_level=RiskLevel.MEDIUM,
        review_status=RiskReviewStatus.ADJUSTED,
        actual_value="'=SUM(1,1) 实际值",
        expected_value="合同限额 90.00",
        reviewed_by=UUID(int=11),
        reviewed_at=generated_at,
        review_reason="依据原始凭证调整为中风险",
    )
    context = FormalReportContext(
        task_id=UUID(int=31),
        task_no="AUD-2026-COMPAT-001",
        task_name="正式报告兼容性验证",
        execution_id=UUID(int=800),
        execution_version=2,
        baseline_date=date(2026, 8, 14),
        finance_reviewer_id=UUID(int=32),
        finance_reviewed_at=generated_at,
        audit_reviewer_id=UUID(int=33),
        audit_reviewed_at=generated_at,
        risks=(risk,),
        citations=(
            FormalCitation(
                risk_id=risk.risk_id,
                policy_document_id=UUID(int=21),
                markdown_version_id=UUID(int=22),
                chunk_id=UUID(int=23),
                index_version_id=UUID(int=24),
                start_page_no=3,
                end_page_no=4,
                title_path=("第三章", "付款控制"),
                quote="付款金额不得超过已审批合同限额。",
                content_sha256="a" * 64,
            ),
        ),
    )
    rules = tuple(
        FormalRuleFact(
            rule_code=f"RULE-{number:03d}",
            status=(
                RuleExecutionStatus.FAILED
                if number == 1
                else RuleExecutionStatus.PASSED
            ),
            disposition=(
                RulePreviewDisposition.HIT
                if number == 1
                else RulePreviewDisposition.NOT_HIT
            ),
            actual_value=risk.actual_value if number == 1 else None,
            expected_value=risk.expected_value if number == 1 else None,
            included_item_ids=(UUID(int=41),) if number == 1 else (),
        )
        for number in range(1, 16)
    )
    metadata = ReportMetadata(
        report_version_id=UUID(int=900),
        audit_version_id=context.execution_id,
        generated_at=generated_at,
        is_outdated=False,
        is_degraded=True,
        degraded_reasons=("AI_DECISION_DISABLED",),
    )
    return metadata, context, rules


def _inspect_pdf(content: bytes) -> PdfInspection:
    reader = PdfReader(BytesIO(content), strict=True)
    if not reader.pages:
        raise ValueError("formal PDF has no pages")
    text = "\n".join(page.extract_text() for page in reader.pages)
    for expected in (
        "FinAudit 正式审核报告",
        "AUD-2026-COMPAT-001",
        "付款金额不得超过已审批合同限额。",
    ):
        if expected not in text:
            raise ValueError("formal PDF content is incomplete")
    catalog = reader.trailer["/Root"].get_object()
    if not isinstance(catalog, DictionaryObject):
        raise ValueError("formal PDF catalog is invalid")
    for forbidden in ("/OpenAction", "/AA", "/JavaScript", "/EmbeddedFiles"):
        if forbidden in catalog:
            raise ValueError("formal PDF contains active content")
    return PdfInspection(
        sha256=sha256(content).hexdigest(),
        page_count=len(reader.pages),
        text_sha256=sha256(text.encode("utf-8")).hexdigest(),
    )


def _shared_strings(archive: ZipFile) -> tuple[str, ...]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return ()
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return tuple(
        "".join(node.text or "" for node in item.iter(f"{{{_SPREADSHEET_NS}}}t"))
        for item in root.findall(f"{{{_SPREADSHEET_NS}}}si")
    )


def _xlsx_cell_value(cell: ElementTree.Element, shared: tuple[str, ...]) -> str:
    cell_type = cell.attrib.get("t")
    value = cell.find(f"{{{_SPREADSHEET_NS}}}v")
    raw = "" if value is None or value.text is None else value.text
    if cell_type == "s":
        index = int(raw)
        if index < 0 or index >= len(shared):
            raise ValueError("XLSX shared string index is invalid")
        return shared[index]
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{_SPREADSHEET_NS}}}t"))
    if cell_type == "b":
        if raw not in {"0", "1"}:
            raise ValueError("XLSX Boolean cell is invalid")
        return "true" if raw == "1" else "false"
    return raw


def _xlsx_content(
    archive: ZipFile,
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationship_targets = {
        item.attrib["Id"]: item.attrib["Target"]
        for item in relationships.findall(f"{{{_PACKAGE_RELATIONSHIP_NS}}}Relationship")
    }
    shared = _shared_strings(archive)
    result: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for sheet in workbook.findall(f".//{{{_SPREADSHEET_NS}}}sheet"):
        relationship_id = sheet.attrib[f"{{{_RELATIONSHIP_NS}}}id"]
        target = relationship_targets[relationship_id].lstrip("/")
        path = target if target.startswith("xl/") else f"xl/{target}"
        sheet_root = ElementTree.fromstring(archive.read(path))
        cells = tuple(
            (cell.attrib["r"], _xlsx_cell_value(cell, shared))
            for cell in sheet_root.findall(f".//{{{_SPREADSHEET_NS}}}c")
        )
        result.append((sheet.attrib["name"], cells))
    return tuple(result)


def _inspect_xlsx(content: bytes) -> XlsxInspection:
    with ZipFile(BytesIO(content)) as archive:
        if archive.testzip() is not None:
            raise ValueError("formal XLSX archive is corrupt")
        workbook_content = _xlsx_content(archive)
        sheets = tuple(name for name, _cells in workbook_content)
        if sheets != _EXPECTED_SHEETS:
            raise ValueError("formal XLSX sheet contract differs")
        canonical = json.dumps(
            workbook_content,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    return XlsxInspection(
        sha256=sha256(content).hexdigest(),
        sheets=sheets,
        content_sha256=sha256(canonical).hexdigest(),
    )


def inspect_artifacts(directory: Path) -> CompatibilityInspection:
    pdf_content = (directory / _PDF_NAME).read_bytes()
    xlsx_content = (directory / _XLSX_NAME).read_bytes()
    return CompatibilityInspection(
        schema_version="report-artifact-compatibility-v1",
        python_version=".".join(str(value) for value in sys.version_info[:3]),
        pdf=_inspect_pdf(pdf_content),
        xlsx=_inspect_xlsx(xlsx_content),
    )


def generate_artifacts(directory: Path) -> CompatibilityInspection:
    directory.mkdir(parents=True, exist_ok=False)
    metadata, context, rules = _fixture()
    payload = build_formal_report_payload(metadata, context, rules)
    (directory / _PDF_NAME).write_bytes(formal_report_pdf_bytes(payload, context))
    (directory / _XLSX_NAME).write_bytes(formal_report_xlsx_bytes(payload))
    return inspect_artifacts(directory)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "inspect"))
    parser.add_argument("directory", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    inspection = (
        generate_artifacts(args.directory)
        if args.command == "generate"
        else inspect_artifacts(args.directory)
    )
    print(json.dumps(asdict(inspection), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
