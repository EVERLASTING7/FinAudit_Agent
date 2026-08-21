"""核验 DocuBench 多格式公开数据，并生成不含原始标签值的质量证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.adapters.ocr import NotConfiguredOcrEngine  # noqa: E402
from app.services.document_parser import DocumentParseError, DocumentParser  # noqa: E402

_DEFAULT_DATA_ROOT = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "FinAuditAgent"
    / "public-benchmark"
    / "docubench-43a3f3bc00e591e711075678ca6d154acfedcf42"
)
DATA_ROOT = Path(os.environ.get("FINAUDIT_PUBLIC_DOCUBENCH_ROOT", _DEFAULT_DATA_ROOT))
OUTPUT_PATH = (
    PROJECT_ROOT / "tests" / "evaluation" / "public-docubench-qualification-v1.json"
)

_UPSTREAM_COMMIT = "43a3f3bc00e591e711075678ca6d154acfedcf42"
_UPSTREAM_URL = "https://github.com/DocuPipe/DocuBench"
_SOURCES_BYTES = 31_703
_SOURCES_SHA256 = "B6DC608632CD135C555FB65E018C8D8D716F67086922E81D0E5BFB001F369892"
_DOCUMENT_AGGREGATE_SHA256 = (
    "ADC16A26A871B68C98BFECD07C08333224B20F89EF7EFC074C8D85DE179884BD"
)
_SCHEMA_AGGREGATE_SHA256 = (
    "D0C831D84B1732E1B4AB64A6B4C72635F3CE9763EB2075808D3B1C0DA33DC3B5"
)
_LABEL_AGGREGATE_SHA256 = (
    "B7FC49A83429CA505BE85B193924F6D1173DEBB6BDF32BF7047B028F742D8DA7"
)
_OWNER_INSTRUCTION = (
    "我无法提供仓库外的脱敏代表性业务数据路径及 approval_ref，覆盖合同、发票、"
    "重复标签、风险标准答案和复杂多格式文档，需要你自己去寻找"
)
_SUPPORTED_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
_HEBREW_INVOICE_ID = "nESapyAA"
_HEBREW_INVOICE_PROPERTIES = frozenset(
    {
        "documentType",
        "documentNumber",
        "issueDate",
        "vendorName",
        "vendorTaxId",
        "customerName",
        "customerAddress",
        "customerTaxId",
        "subscriptionPlan",
        "subtotalBeforeVat",
        "vatRatePercent",
        "vatAmount",
        "totalAmount",
        "currency",
        "lineItems",
        "payments",
    }
)
_CREDIT_AGREEMENT_ID = "BnftpXVQ"
_CREDIT_AGREEMENT_PROPERTIES = frozenset(
    {
        "agreementType",
        "aggregateCommitmentAmount",
        "agreementDate",
        "borrower",
        "syndicationAgent",
        "administrativeAgent",
        "lenders",
    }
)
_UPRIGHT_RECEIPT_ID = "vBIz5dut"
_ROTATED_RECEIPT_ID = "B0nA2c30"
_RECEIPT_LABEL_SHA256 = (
    "DBAE6AD1C80F92E16E5CEFED48FB560F07820DED098A2FEBC4137D6223B42791"
)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _mapping(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError("expected object")
    return cast(dict[str, object], value)


def _source_binding(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "bytes": len(payload),
        "sha256": _sha256(payload),
    }


def _aggregate_identity(directory: Path) -> str:
    rows = [
        f"{path.name}:{_sha256(path.read_bytes())}"
        for path in sorted(directory.iterdir())
        if path.is_file()
    ]
    return _sha256("\n".join(rows).encode("utf-8"))


def _source_rows() -> list[dict[str, object]]:
    path = DATA_ROOT / "sources.json"
    payload = path.read_bytes()
    if len(payload) != _SOURCES_BYTES or _sha256(payload) != _SOURCES_SHA256:
        raise ValueError("DocuBench source manifest identity drift")
    raw = json.loads(payload)
    if type(raw) is not list or len(raw) != 72:
        raise ValueError("DocuBench source manifest shape drift")
    rows = [_mapping(item) for item in raw]
    required = {
        "n",
        "doc_id",
        "name",
        "pages",
        "lang",
        "ftype",
        "source_url",
        "license",
        "hard_feature",
    }
    if any(not required <= set(row) for row in rows):
        raise ValueError("DocuBench source fields drift")
    return rows


def _schema(document_id: str) -> dict[str, object]:
    return _mapping(
        json.loads((DATA_ROOT / "schemas" / f"{document_id}.json").read_bytes())
    )


def _labels(document_id: str) -> dict[str, object]:
    return _mapping(
        json.loads((DATA_ROOT / "labels" / f"{document_id}.json").read_bytes())
    )


class _PypdfWarningCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _runtime_artifact(rows: list[dict[str, object]]) -> dict[str, object]:
    by_id = {str(row["doc_id"]): row for row in rows}
    parser = DocumentParser(ocr_engine=NotConfiguredOcrEngine(), pdf_renderer=None)
    outcomes: Counter[str] = Counter()
    outcomes_by_extension: dict[str, Counter[str]] = {}
    passed_page_counts: list[int] = []
    passed_block_counts: list[int] = []
    supported_count = 0

    pypdf_logger = logging.getLogger("pypdf")
    previous_level = pypdf_logger.level
    previous_propagate = pypdf_logger.propagate
    collector = _PypdfWarningCollector()
    pypdf_logger.addHandler(collector)
    pypdf_logger.setLevel(logging.WARNING)
    pypdf_logger.propagate = False
    try:
        for document_id, row in sorted(by_id.items()):
            extension = f".{str(row['ftype']).casefold()}"
            mime_type = _SUPPORTED_MIME.get(extension)
            if mime_type is None:
                continue
            supported_count += 1
            extension_outcomes = outcomes_by_extension.setdefault(extension, Counter())
            path = DATA_ROOT / "documents" / f"{document_id}{extension}"
            try:
                parsed = parser.parse(path.read_bytes(), mime_type=mime_type)
            except DocumentParseError as error:
                outcomes[error.code] += 1
                extension_outcomes[error.code] += 1
            else:
                outcomes["PASSED"] += 1
                extension_outcomes["PASSED"] += 1
                passed_page_counts.append(len(parsed.pages))
                passed_block_counts.append(
                    sum(len(page.blocks) for page in parsed.pages)
                )
    finally:
        pypdf_logger.removeHandler(collector)
        pypdf_logger.setLevel(previous_level)
        pypdf_logger.propagate = previous_propagate

    expected_outcomes = {
        "PASSED": 34,
        "PDF_OCR_RENDERER_NOT_CONFIGURED": 23,
        "PDF_PARSE_INVALID": 2,
        "OCR_NOT_CONFIGURED": 6,
    }
    if supported_count != 65 or outcomes != expected_outcomes:
        raise ValueError("DocuBench current parser outcome drift")
    if (
        sum(passed_page_counts),
        min(passed_page_counts),
        max(passed_page_counts),
        min(passed_block_counts),
        max(passed_block_counts),
    ) != (115, 1, 22, 2, 1326):
        raise ValueError("DocuBench current parser shape drift")
    rotated_warning = "Rotated text discovered. Output will be incomplete."
    if Counter(collector.messages) != {rotated_warning: 12}:
        raise ValueError("DocuBench parser warning drift")

    return {
        "supported_case_count": supported_count,
        "supported_extension_counts": {
            ".pdf": 58,
            ".jpeg": 5,
            ".png": 1,
            ".docx": 1,
        },
        "parser_outcome_counts": dict(sorted(outcomes.items())),
        "parser_outcome_counts_by_extension": {
            extension: dict(sorted(counts.items()))
            for extension, counts in sorted(outcomes_by_extension.items())
        },
        "parser_pass_count": outcomes["PASSED"],
        "parser_fail_count": supported_count - outcomes["PASSED"],
        "parser_pass_rate": f"{outcomes['PASSED'] / supported_count:.6f}",
        "passed_page_count_total": sum(passed_page_counts),
        "passed_page_count_range": [min(passed_page_counts), max(passed_page_counts)],
        "passed_block_count_range": [
            min(passed_block_counts),
            max(passed_block_counts),
        ],
        "warning_code_counts": {"PYPDF_ROTATED_TEXT_OUTPUT_INCOMPLETE": 12},
        "quality_status": "MEASURED_FAILED_OCR_DISABLED_AND_TWO_INVALID_PDFS",
    }


def build_artifact() -> dict[str, object]:
    rows = _source_rows()
    by_id = {str(row["doc_id"]): row for row in rows}
    document_ids = set(by_id)
    schema_ids = {path.stem for path in (DATA_ROOT / "schemas").glob("*.json")}
    label_ids = {path.stem for path in (DATA_ROOT / "labels").glob("*.json")}
    document_ids_on_disk = {path.stem for path in (DATA_ROOT / "documents").iterdir()}
    if (
        document_ids != schema_ids
        or document_ids != label_ids
        or document_ids != document_ids_on_disk
    ):
        raise ValueError("DocuBench document-schema-label binding drift")
    if _aggregate_identity(DATA_ROOT / "documents") != _DOCUMENT_AGGREGATE_SHA256:
        raise ValueError("DocuBench document aggregate drift")
    if _aggregate_identity(DATA_ROOT / "schemas") != _SCHEMA_AGGREGATE_SHA256:
        raise ValueError("DocuBench schema aggregate drift")
    if _aggregate_identity(DATA_ROOT / "labels") != _LABEL_AGGREGATE_SHA256:
        raise ValueError("DocuBench label aggregate drift")

    format_counts = Counter(str(row["ftype"]) for row in rows)
    language_counts = Counter(str(row["lang"]) for row in rows)
    hebrew_properties = set(_mapping(_schema(_HEBREW_INVOICE_ID)["properties"]))
    contract_properties = set(_mapping(_schema(_CREDIT_AGREEMENT_ID)["properties"]))
    if hebrew_properties != _HEBREW_INVOICE_PROPERTIES:
        raise ValueError("DocuBench tax invoice schema drift")
    if contract_properties != _CREDIT_AGREEMENT_PROPERTIES:
        raise ValueError("DocuBench credit agreement schema drift")
    if set(_labels(_HEBREW_INVOICE_ID)) != hebrew_properties:
        raise ValueError("DocuBench tax invoice labels drift")
    upright = (DATA_ROOT / "labels" / f"{_UPRIGHT_RECEIPT_ID}.json").read_bytes()
    rotated = (DATA_ROOT / "labels" / f"{_ROTATED_RECEIPT_ID}.json").read_bytes()
    if _sha256(upright) != _RECEIPT_LABEL_SHA256 or upright != rotated:
        raise ValueError("DocuBench rotated receipt pair drift")

    return {
        "schema_version": "public-docubench-qualification-v1",
        "classification": "public_hand_verified_multiformat_technical_proxy",
        "source": {
            "dataset_id": "DocuPipe/DocuBench",
            "upstream_commit": _UPSTREAM_COMMIT,
            "primary_url": _UPSTREAM_URL,
            "document_count": len(rows),
            "page_count": sum(int(row["pages"]) for row in rows),
            "schema_count": len(schema_ids),
            "label_count": len(label_ids),
            "document_format_count": len(format_counts),
            "format_counts": dict(format_counts),
            "language_count": len(language_counts),
            "language_counts": dict(language_counts),
            "code_license": "MIT",
            "label_schema_metadata_license": "CC-BY-4.0",
            "documents_retain_source_specific_terms": True,
            "ground_truth_method": "hand_verified_schema_shaped_labels",
            "source_manifest_bytes": _SOURCES_BYTES,
            "source_manifest_sha256": _SOURCES_SHA256,
            "document_aggregate_sha256": _DOCUMENT_AGGREGATE_SHA256,
            "schema_aggregate_sha256": _SCHEMA_AGGREGATE_SHA256,
            "label_aggregate_sha256": _LABEL_AGGREGATE_SHA256,
        },
        "selection_authority": {
            "approval_ref": f"public-dataset:DocuBench@{_UPSTREAM_COMMIT}",
            "approval_ref_kind": "public_dataset_revision_not_business_uat",
            "owner_instruction_sha256": _sha256(_OWNER_INSTRUCTION.encode("utf-8")),
            "human_review_claimed_by_finaudit": False,
            "upstream_labels_claim_hand_verified": True,
        },
        "source_binding": [
            _source_binding(Path(__file__)),
            _source_binding(BACKEND_ROOT / "app" / "services" / "document_parser.py"),
        ],
        "invoice_source_qualification": {
            "best_case_ref_sha256": _sha256(_HEBREW_INVOICE_ID.encode("ascii")),
            "language": str(by_id[_HEBREW_INVOICE_ID]["lang"]),
            "format": str(by_id[_HEBREW_INVOICE_ID]["ftype"]),
            "direct_product_field_count": 11,
            "derived_product_field_count": 1,
            "source_schema_absent_assumption_field_count": 1,
            "source_schema_absent_assumption_fields": ["invoice_code"],
            "derived_field_mapping": {"is_red_invoice": "documentType -> boolean"},
            "product_frozen_field_count": 13,
            "formal_13_field_gate_status": "NOT_COMPUTABLE_SOURCE_SCHEMA_MISSING_INVOICE_CODE",
        },
        "contract_source_qualification": {
            "best_case_ref_sha256": _sha256(_CREDIT_AGREEMENT_ID.encode("ascii")),
            "direct_product_field_count": 4,
            "product_frozen_field_count": 13,
            "formal_13_field_gate_status": "NOT_COMPUTABLE_INSUFFICIENT_SOURCE_FIELD_COVERAGE",
        },
        "duplicate_capture_proxy": {
            "upright_case_ref_sha256": _sha256(_UPRIGHT_RECEIPT_ID.encode("ascii")),
            "rotated_case_ref_sha256": _sha256(_ROTATED_RECEIPT_ID.encode("ascii")),
            "ground_truth_labels_identical": True,
            "label_sha256": _RECEIPT_LABEL_SHA256,
            "document_type": "receipt_not_invoice",
            "may_claim_duplicate_invoice_quality": False,
        },
        "current_default_profile_runtime": _runtime_artifact(rows),
        "remaining_quality_gaps": {
            "contract_13_field_source": "NOT_PRESENT",
            "invoice_code_ground_truth": "NOT_PRESENT",
            "duplicate_invoice_pairs": "NOT_PRESENT",
            "matching_finaudit_risk_dispositions": "NOT_PRESENT",
            "unsupported_source_formats": [
                ".tiff",
                ".xlsx",
                ".csv",
                ".xml",
                ".txt",
                ".html",
            ],
        },
        "quality_gate_summary": {
            "invoice_95": "NOT_COMPUTABLE_SOURCE_MISSING_INVOICE_CODE",
            "contract_85": "NOT_COMPUTABLE_INSUFFICIENT_13_FIELD_COVERAGE",
            "duplicate_invoice": "NOT_COMPUTABLE_RECEIPT_CAPTURE_PAIR_ONLY",
            "risk_rules": "NOT_COMPUTABLE_NO_MATCHING_DISPOSITIONS",
            "complex_multi_format": "FAILED_CURRENT_DEFAULT_PROFILE_34_OF_65_PARSED",
            "overall_status": "MEASURED_FAILED_WITH_STRONGER_MULTIFORMAT_SOURCE",
        },
        "privacy_and_storage": {
            "raw_data_path": (
                "%LOCALAPPDATA%/FinAuditAgent/public-benchmark/"
                "docubench-43a3f3bc00e591e711075678ca6d154acfedcf42/"
            ),
            "raw_data_git_ignored": True,
            "raw_documents_tracked": False,
            "raw_annotation_values_persisted_in_evidence": False,
            "business_identifiers_persisted_in_evidence": False,
            "tracked_output_contains_only_counts_hashes_status_and_field_codes": True,
        },
        "acceptance_boundary": {
            "is_public_cross_domain_technical_proxy": True,
            "is_customer_business_representative_dataset": False,
            "is_finaudit_human_uat": False,
            "is_formal_ac_acceptance": False,
            "may_claim_contract_85_passed": False,
            "may_claim_invoice_95_passed": False,
            "may_claim_duplicate_invoice_quality": False,
            "may_claim_risk_rule_quality": False,
            "may_mark_ac_accepted": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = _canonical_bytes(build_artifact())
    if args.check:
        if not OUTPUT_PATH.is_file() or OUTPUT_PATH.read_bytes() != payload:
            print("PUBLIC_DOCUBENCH_QUALIFICATION=DRIFT")
            return 1
        print("PUBLIC_DOCUBENCH_QUALIFICATION=MEASURED_FAILED_EVIDENCE_PASS")
        return 0
    OUTPUT_PATH.write_bytes(payload)
    print(
        "PUBLIC_DOCUBENCH_QUALIFICATION=MEASURED_FAILED "
        f"sha256={_sha256(payload)} raw_values_persisted=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
