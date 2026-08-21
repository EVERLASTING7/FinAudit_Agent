"""核验 ExtractBench 公开企业文档，并生成不含原始业务值的质量证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from pypdf import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.adapters.ocr import NotConfiguredOcrEngine  # noqa: E402
from app.schemas.invoices import INVOICE_CORE_FIELD_CODES  # noqa: E402
from app.services.document_parser import (  # noqa: E402
    DocumentParseError,
    DocumentParser,
    ParsedDocument,
)
from app.services.invoice_extractor import (  # noqa: E402
    InvoiceSourceBlock,
    extract_invoice_candidate,
)

DATA_ROOT = PROJECT_ROOT / "data" / "public-benchmark" / "extractbench"
OUTPUT_PATH = (
    PROJECT_ROOT / "tests" / "evaluation" / "public-extractbench-qualification-v1.json"
)

_DATASET_REVISION = "f6180e917a050a84582e6366cff85b7dc1e84e58"
_DATASET_URL = "https://huggingface.co/datasets/llamaindex/ExtractBench"
_PAPER_REF = "arXiv:2607.29677"
_OWNER_INSTRUCTION = (
    "我无法提供仓库外的脱敏代表性业务数据路径及 approval_ref，覆盖合同、发票、"
    "重复标签、风险标准答案和复杂多格式文档，需要你自己去寻找"
)
_SPLITS = {
    "short": (
        29_881_640,
        "E4B07B3612F1D4BCF4157D5B97B8692D671AEDDAF96E5B5898338345B654E740",
        252,
    ),
    "medium": (
        62_894_509,
        "8AE0884D8E8DDDB1282EB98282D942B65C8D99B82DD37E650EDC53CD0F5BB5DF",
        98,
    ),
    "long": (
        159_965_789,
        "AC5B22BBF810548A5E086E792D4AFE0AA98DC572D24DECEAB820A2558570F3BD",
        20,
    ),
}
_INVOICE_SCHEMA_PROPERTIES = frozenset(
    {
        "invoice_number",
        "invoice_type",
        "original_invoice_number",
        "date",
        "due_date",
        "purchase_order_number",
        "order_number",
        "vendor",
        "customer",
        "line_items",
        "subtotal",
        "discount_total",
        "tax_total",
        "shipping",
        "total_amount",
        "payment_terms",
        "bank_details",
        "currency",
        "notes",
    }
)
_INVOICE_IDS = (
    "short/aclu_cdwg_invoice",
    "short/fort_bend_operativeiq_invoice",
    "short/grafton_isotrope_invoice_19503",
    "short/hingham-grainger-invoice",
    "short/hingham-wbmason-invoice",
    "short/mission-tx-tyler-invoice",
    "short/southampton-ny-york-env-invoice",
    "short/stephenville-axon-invoice",
)
_PDF_PROFILE = {
    "aclu_cdwg_invoice.pdf": (
        97_667,
        "8A87CFD1C8006B7F23C958DE052B65316B2D39C32E1699F98861D938510F1C0B",
    ),
    "fort_bend_operativeiq_invoice.pdf": (
        178_517,
        "B260A7591B54983E0E04F696A6A508F2FDFDE1DB2038EA3F77527C7EE79285B2",
    ),
    "grafton_isotrope_invoice_19503.pdf": (
        31_859,
        "7B6F8DBA51DA521091B8F14E46572FBA0A50B4069BAC899B51284E7970F1E519",
    ),
    "hingham-grainger-invoice.pdf": (
        82_842,
        "41CB782032CCA14B7625E7EB6EF41091B04F9AB62748B577C5011E8B66E401AB",
    ),
    "hingham-wbmason-invoice.pdf": (
        78_642,
        "AE91473D351DECD2CD36AD4B8486D62F16DADD2393B3E42C3684E3C23090D701",
    ),
    "mission-tx-tyler-invoice.pdf": (
        81_453,
        "E9F18A603C0F9CE128463D30E964B04058C22AAEDA7098CA0703FDABE874694A",
    ),
    "southampton-ny-york-env-invoice.pdf": (
        134_269,
        "C484F0F748A7A0CE705841824832B7FA7CBF4D1014DF18D8E291820B7665F069",
    ),
    "stephenville-axon-invoice.pdf": (
        130_127,
        "F2244076DE12708E1ED9713EC8D8383A3833EDC703671B5851E72D19501BA4AF",
    ),
}
_DIRECT_RULE_PATHS = {
    "invoice_number": "invoice_number",
    "invoice_type": "invoice_type",
    "invoice_date": "date",
    "buyer_name": "customer.name",
    "seller_name": "vendor.name",
    "seller_tax_no": "vendor.tax_id",
    "amount_excluding_tax": "subtotal",
    "tax_amount": "tax_total",
    "total_amount": "total_amount",
    "currency": "currency",
}
_ROW_KEYS = frozenset(
    {
        "category",
        "data_schema",
        "expected_output",
        "field_rules",
        "id",
        "pdf",
        "repeated_structure",
        "tags",
    }
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


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise ValueError("expected array")
    return cast(list[object], value)


def _source_binding(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "bytes": len(payload),
        "sha256": _sha256(payload),
    }


def _read_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    bindings: list[dict[str, object]] = []
    for split, (expected_bytes, expected_sha, expected_count) in _SPLITS.items():
        path = DATA_ROOT / f"{split}.jsonl"
        payload = path.read_bytes()
        if len(payload) != expected_bytes or _sha256(payload) != expected_sha:
            raise ValueError("ExtractBench split identity drift")
        split_rows = [_mapping(json.loads(line)) for line in payload.splitlines()]
        if len(split_rows) != expected_count or any(
            set(row) != _ROW_KEYS
            or not str(row["id"]).startswith(f"{split}/")
            or not str(row["pdf"]).startswith(f"docs/{split}/")
            for row in split_rows
        ):
            raise ValueError("ExtractBench split shape drift")
        rows.extend(split_rows)
        bindings.append(
            {
                "path": path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": len(payload),
                "sha256": expected_sha,
                "row_count": len(split_rows),
            }
        )
    if (
        len({str(row["id"]) for row in rows}) != 370
        or len({str(row["pdf"]) for row in rows}) != 370
    ):
        raise ValueError("ExtractBench document identity drift")
    return rows, bindings


def _schema(row: dict[str, object]) -> dict[str, object]:
    value = row["data_schema"]
    return _mapping(json.loads(value)) if type(value) is str else _mapping(value)


def _expected(row: dict[str, object]) -> dict[str, object]:
    value = row["expected_output"]
    return _mapping(json.loads(value)) if type(value) is str else _mapping(value)


def _rules(row: dict[str, object]) -> dict[str, object]:
    value = row["field_rules"]
    return _mapping(json.loads(value)) if type(value) is str else _mapping(value)


def _text(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split())
    return normalized or None


def _identifier(value: object) -> str | None:
    normalized = _text(value)
    return None if normalized is None else "".join(normalized.split()).upper()


def _tax_identifier(value: object) -> str | None:
    normalized = _identifier(value)
    return None if normalized is None else normalized.replace("-", "")


def _money(value: object) -> str | None:
    if value is None:
        return None
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _date(value: object) -> str | None:
    normalized = _text(value)
    if normalized is None:
        return None
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(normalized, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError("unsupported public benchmark date")


def _product_expected(row: dict[str, object]) -> dict[str, object]:
    value = _expected(row)
    vendor = _mapping(value["vendor"])
    customer = _mapping(value["customer"])
    invoice_type = _text(value["invoice_type"])
    if invoice_type is None or invoice_type.casefold() != "standard":
        raise ValueError("ExtractBench invoice type mapping drift")
    expected = {
        "invoice_code": None,
        "invoice_number": _identifier(value["invoice_number"]),
        "invoice_type": invoice_type,
        "is_red_invoice": False,
        "invoice_date": _date(value["date"]),
        "buyer_name": _text(customer["name"]),
        "buyer_tax_no": None,
        "seller_name": _text(vendor["name"]),
        "seller_tax_no": _tax_identifier(vendor["tax_id"]),
        "amount_excluding_tax": _money(value["subtotal"]),
        "tax_amount": _money(value["tax_total"]),
        "total_amount": _money(value["total_amount"]),
        "currency": _identifier(value["currency"]),
    }
    if set(expected) != set(INVOICE_CORE_FIELD_CODES):
        raise ValueError("product invoice field mapping drift")
    return expected


def _actual(parsed: ParsedDocument, *, namespace: str) -> dict[str, object]:
    parse_version_id = uuid5(NAMESPACE_URL, f"{namespace}/parse")
    blocks = tuple(
        InvoiceSourceBlock(
            id=uuid5(NAMESPACE_URL, f"{namespace}/block/{block.block_index}"),
            parse_version_id=parse_version_id,
            page_no=block.page_no,
            block_index=block.block_index,
            text=block.text,
            bbox=cast(dict[str, object] | None, block.bbox),
            confidence=block.confidence,
        )
        for page in parsed.pages
        for block in page.blocks
    )
    return extract_invoice_candidate(blocks).facts.model_dump(mode="json")


def _invoice_artifact(rows: list[dict[str, object]]) -> dict[str, object]:
    by_id = {str(row["id"]): row for row in rows}
    selected = [by_id[case_id] for case_id in _INVOICE_IDS]
    if any(
        set(_mapping(_schema(row)["properties"])) != _INVOICE_SCHEMA_PROPERTIES
        or "source:real" not in _list(row["tags"])
        or "challenge:T3.b" not in _list(row["tags"])
        for row in selected
    ):
        raise ValueError("ExtractBench invoice selection drift")

    verified_rule_count = evidence_rule_count = 0
    expected_non_null = Counter[str]()
    for row in selected:
        expected = _product_expected(row)
        expected_non_null.update(
            field for field, value in expected.items() if value is not None
        )
        rules = _rules(row)
        for rule_path in _DIRECT_RULE_PATHS.values():
            rule = _mapping(rules[rule_path])
            verified_rule_count += rule.get("verified") is True
            evidence_rule_count += rule.get("evidence_required") is True
    if verified_rule_count != 80 or evidence_rule_count != 80:
        raise ValueError("ExtractBench invoice rule verification drift")

    parser = DocumentParser(ocr_engine=NotConfiguredOcrEngine(), pdf_renderer=None)
    parser_outcomes: Counter[str] = Counter()
    page_counts: list[int] = []
    case_results: list[dict[str, object]] = []
    matched = matched_non_null = total = actual_non_null = valid_output_count = 0
    content_hashes: list[str] = []
    for row in selected:
        source_name = Path(str(row["pdf"])).name
        expected_bytes, expected_sha = _PDF_PROFILE[source_name]
        path = DATA_ROOT / "docs" / "short" / source_name
        payload = path.read_bytes()
        if len(payload) != expected_bytes or _sha256(payload) != expected_sha:
            raise ValueError("ExtractBench invoice PDF identity drift")
        content_hashes.append(expected_sha)
        page_count = len(PdfReader(path, strict=True).pages)
        page_counts.append(page_count)
        expected = _product_expected(row)
        try:
            parsed = parser.parse(payload, mime_type="application/pdf")
        except DocumentParseError as error:
            parser_outcomes[error.code] += 1
            actual = None
            source_type: str | None = None
        else:
            parser_outcomes["PASSED"] += 1
            valid_output_count += 1
            source_type = parsed.source_type
            actual = _actual(parsed, namespace=str(row["id"]))
            actual_non_null += sum(value is not None for value in actual.values())
        matched_fields = (
            []
            if actual is None
            else [
                field
                for field in INVOICE_CORE_FIELD_CODES
                if actual[field] == expected[field]
            ]
        )
        matched += len(matched_fields)
        matched_non_null += sum(expected[field] is not None for field in matched_fields)
        total += len(INVOICE_CORE_FIELD_CODES)
        case_results.append(
            {
                "case_ref_sha256": _sha256(str(row["id"]).encode("utf-8")),
                "page_count": page_count,
                "parser_status": "failed" if actual is None else "passed",
                "parser_failure_code": (
                    None if actual is not None else next(reversed(parser_outcomes))
                ),
                "source_type": source_type,
                "expected_non_null_field_count": sum(
                    value is not None for value in expected.values()
                ),
                "actual_non_null_field_count": (
                    0
                    if actual is None
                    else sum(value is not None for value in actual.values())
                ),
                "matched_field_count": len(matched_fields),
                "matched_field_codes": matched_fields,
            }
        )
    if parser_outcomes != {"PASSED": 6, "PDF_OCR_RENDERER_NOT_CONFIGURED": 2}:
        raise ValueError("ExtractBench current parser outcome drift")
    if (sum(page_counts), min(page_counts), max(page_counts)) != (18, 1, 9):
        raise ValueError("ExtractBench invoice page profile drift")
    if (valid_output_count, matched, matched_non_null, total, actual_non_null) != (
        6,
        48,
        32,
        104,
        38,
    ):
        raise ValueError("ExtractBench current invoice runtime drift")

    return {
        "source_qualification": {
            "case_count": len(selected),
            "real_document_count": len(selected),
            "page_count": sum(page_counts),
            "min_page_count": min(page_counts),
            "max_page_count": max(page_counts),
            "scanned_case_count": sum(
                "perception:P2" in _list(row["tags"]) for row in selected
            ),
            "multi_page_case_count": sum(page_count > 1 for page_count in page_counts),
            "selected_case_ids_sha256": _sha256(
                "\n".join(_INVOICE_IDS).encode("utf-8")
            ),
            "pdf_content_hashes_sha256": _sha256(
                "\n".join(sorted(content_hashes)).encode("ascii")
            ),
            "direct_source_field_count": len(_DIRECT_RULE_PATHS),
            "derived_field_count": 1,
            "source_schema_absent_assumption_field_count": 2,
            "derived_field_mapping": {
                "is_red_invoice": "invoice_type=standard -> false"
            },
            "source_schema_absent_assumption_fields": ["invoice_code", "buyer_tax_no"],
            "verified_direct_rule_count": verified_rule_count,
            "evidence_required_direct_rule_count": evidence_rule_count,
            "expected_non_null_counts": dict(sorted(expected_non_null.items())),
            "product_frozen_field_count": len(INVOICE_CORE_FIELD_CODES),
            "qualification_status": "QUALIFIED_WITH_TWO_SCHEMA_ABSENCE_ASSUMPTIONS",
            "formal_13_field_gate_status": "NOT_COMPUTABLE_SOURCE_SCHEMA_MISSING_TWO_FIELDS",
        },
        "current_default_profile_runtime": {
            "parser": "DocumentParser+NotConfiguredOcrEngine",
            "parser_outcome_counts": dict(sorted(parser_outcomes.items())),
            "valid_output_count": valid_output_count,
            "invalid_output_count": len(selected) - valid_output_count,
            "actual_non_null_field_count": actual_non_null,
            "matched_field_count_including_assumed_nulls": matched,
            "total_field_count": total,
            "provisional_13_field_accuracy": f"{matched / total:.6f}",
            "annotated_non_null_field_count": sum(expected_non_null.values()),
            "matched_annotated_non_null_field_count": matched_non_null,
            "annotated_non_null_field_accuracy": (
                f"{matched_non_null / sum(expected_non_null.values()):.6f}"
            ),
            "threshold": "0.950000",
            "threshold_status": "FAILED",
        },
        "cases": case_results,
    }


def build_artifact() -> dict[str, object]:
    rows, raw_bindings = _read_rows()
    tags = Counter(str(tag) for row in rows for tag in _list(row["tags"]))
    schema_hashes = {_sha256(_canonical_bytes(_schema(row))) for row in rows}
    expected_tag_counts = {
        "source:real": 325,
        "source:synthetic": 45,
        "perception:P1": 38,
        "perception:P2": 134,
        "perception:P3": 55,
        **{
            f"domain:D{index}": count
            for index, count in enumerate((145, 98, 49, 27, 20, 15, 10, 6), 1)
        },
    }
    if any(tags[key] != value for key, value in expected_tag_counts.items()):
        raise ValueError("ExtractBench published profile drift")

    invoice = _invoice_artifact(rows)
    return {
        "schema_version": "public-extractbench-qualification-v1",
        "classification": "public_enterprise_document_technical_proxy",
        "source": {
            "dataset_id": "llamaindex/ExtractBench",
            "dataset_revision": _DATASET_REVISION,
            "primary_url": _DATASET_URL,
            "paper_ref": _PAPER_REF,
            "license": "Apache-2.0",
            "publisher": "LlamaIndex",
            "declared_document_count": 370,
            "declared_page_count": 4869,
            "declared_document_type_count": 67,
            "observed_schema_hash_count": len(schema_hashes),
            "observed_row_count": len(rows),
            "real_document_count": tags["source:real"],
            "synthetic_document_count": tags["source:synthetic"],
            "domain_counts": {
                f"D{index}": tags[f"domain:D{index}"] for index in range(1, 9)
            },
            "perception_challenge_counts": {
                "rotated_or_image_only": tags["perception:P1"],
                "scanned": tags["perception:P2"],
                "handwriting": tags["perception:P3"],
            },
            "ground_truth_method": "verified deterministic field rules with source evidence",
            "raw_split_bindings": raw_bindings,
        },
        "selection_authority": {
            "approval_ref": f"public-dataset:{_PAPER_REF}@{_DATASET_REVISION}",
            "approval_ref_kind": "public_dataset_revision_not_business_uat",
            "owner_instruction_sha256": _sha256(_OWNER_INSTRUCTION.encode("utf-8")),
            "human_review_claimed": False,
        },
        "source_binding": [
            _source_binding(Path(__file__)),
            _source_binding(BACKEND_ROOT / "app" / "services" / "document_parser.py"),
            _source_binding(BACKEND_ROOT / "app" / "services" / "invoice_extractor.py"),
        ],
        "invoice": invoice,
        "remaining_quality_gaps": {
            "contract_13_field_source": "NOT_FOUND_IN_EXTRACTBENCH",
            "invoice_two_source_schema_fields": ["invoice_code", "buyer_tax_no"],
            "duplicate_invoice_labels": "NOT_PRESENT",
            "matching_risk_rule_dispositions": "NOT_PRESENT",
            "native_docx_cases": 0,
        },
        "quality_gate_summary": {
            "invoice_95": "FAILED_CURRENT_DEFAULT_PROFILE",
            "contract_85": "NOT_COMPUTABLE_NO_COMPLETE_13_FIELD_SOURCE",
            "duplicate_invoice": "NOT_COMPUTABLE_NO_LABELED_DUPLICATE_PAIRS",
            "risk_rules": "NOT_COMPUTABLE_NO_MATCHING_DISPOSITIONS",
            "complex_multi_format": "PARTIAL_COMPLEX_PDF_ONLY",
            "overall_status": "MEASURED_FAILED_WITH_STRONGER_INVOICE_SOURCE",
        },
        "privacy_and_storage": {
            "raw_data_path": "data/public-benchmark/extractbench/",
            "raw_data_git_ignored": True,
            "raw_documents_tracked": False,
            "raw_annotation_values_persisted_in_evidence": False,
            "business_identifiers_persisted_in_evidence": False,
            "tracked_output_contains_only_counts_hashes_status_and_field_codes": True,
        },
        "acceptance_boundary": {
            "is_public_cross_domain_technical_proxy": True,
            "is_customer_business_representative_dataset": False,
            "is_human_uat": False,
            "is_formal_ac_acceptance": False,
            "may_claim_invoice_95_passed": False,
            "may_claim_contract_85_passed": False,
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
            print("PUBLIC_EXTRACTBENCH_QUALIFICATION=DRIFT")
            return 1
        print("PUBLIC_EXTRACTBENCH_QUALIFICATION=MEASURED_FAILED_EVIDENCE_PASS")
        return 0
    OUTPUT_PATH.write_bytes(payload)
    print(
        "PUBLIC_EXTRACTBENCH_QUALIFICATION=MEASURED_FAILED "
        f"sha256={_sha256(payload)} raw_values_persisted=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
