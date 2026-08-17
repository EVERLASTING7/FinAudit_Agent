from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import PurePosixPath
from uuid import UUID
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest

import app.reports.xlsx_writer as xlsx_writer_module
from app.reports.report_payload import (
    RISK_TABLE_COLUMNS,
    RULE_TABLE_COLUMNS,
    ReportMetadata,
    ReportPayload,
    ReportSummary,
    ReportTable,
)
from app.reports.xlsx_writer import (
    MAX_XLSX_BYTES,
    MAX_XLSX_CELL_CODEPOINTS,
    MAX_XLSX_DEGRADED_REASONS,
    MAX_XLSX_REFERENCE_IDS,
    MAX_XLSX_TOTAL_TEXT_CODEPOINTS,
    report_payload_xlsx_bytes,
)

_SPREADSHEET_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
_DUBLIN_TERMS_NAMESPACE = "http://purl.org/dc/terms/"
_RISK_ID = UUID(int=101)
_REFERENCE_IDS = (UUID(int=11), UUID(int=12))
_REFERENCE_TEXT = ";".join(str(reference_id) for reference_id in _REFERENCE_IDS)


def _rule_rows(
    *,
    actual: str = "含税金额=100.00",
    expected: str = "预期金额=90.00",
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            f"RULE-{number:03d}",
            "failed" if number == 1 else "passed",
            "hit" if number == 1 else "not_hit",
            actual if number == 1 else None,
            expected if number == 1 else None,
            str(_RISK_ID) if number == 1 else None,
            "high" if number == 1 else None,
            _REFERENCE_TEXT if number == 1 else "",
        )
        for number in range(1, 16)
    )


def _risk_rows(
    count: int = 1,
    *,
    actual: str = "含税金额=100.00",
    expected: str = "预期金额=90.00",
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            str(_RISK_ID),
            f"RULE-{number:03d}",
            "high",
            "high",
            "pending",
            actual,
            expected,
            _REFERENCE_TEXT,
        )
        for number in range(1, count + 1)
    )


def _payload(
    *,
    actual: str = "含税金额=100.00",
    expected: str = "预期金额=90.00",
    rules: tuple[tuple[object, ...], ...] | None = None,
    risks: tuple[tuple[object, ...], ...] | None = None,
) -> ReportPayload:
    return ReportPayload(
        metadata=ReportMetadata(
            report_version_id=UUID(int=900),
            audit_version_id=UUID(int=800),
            generated_at=datetime(2026, 8, 13, 1, 2, 3, 4, tzinfo=timezone.utc),
            is_outdated=True,
            is_degraded=True,
            degraded_reasons=("AI 已禁用",),
        ),
        preview_id=UUID(int=700),
        ai_status="disabled",
        summary=ReportSummary(
            overall_level="high",
            active_risk_count=1,
            dismissed_risk_count=0,
            has_effective_high=True,
            has_unreviewed_high=True,
        ),
        rules=ReportTable(
            columns=RULE_TABLE_COLUMNS,
            rows=_rule_rows(actual=actual, expected=expected) if rules is None else rules,  # type: ignore[arg-type]
        ),
        risks=ReportTable(
            columns=RISK_TABLE_COLUMNS,
            rows=(_risk_rows(actual=actual, expected=expected) if risks is None else risks),  # type: ignore[arg-type]
        ),
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def test_xlsx_is_byte_stable_openable_and_contains_only_three_visible_sheets() -> None:
    payload = _payload(actual="'=1+1 与 中文金额")

    first = report_payload_xlsx_bytes(payload)
    second = report_payload_xlsx_bytes(payload)

    assert first == second
    assert first.startswith(b"PK\x03\x04")
    assert len(first) <= MAX_XLSX_BYTES

    with ZipFile(BytesIO(first)) as archive:
        assert archive.testzip() is None
        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert len(names) == len(set(names))
        assert sum(info.file_size for info in infos) <= 8 * 1024 * 1024
        for name in names:
            path = PurePosixPath(name)
            assert not path.is_absolute()
            assert ".." not in path.parts
            assert "\\" not in name

        for name in names:
            if name.endswith(".xml") or name.endswith(".rels"):
                ElementTree.fromstring(archive.read(name))

        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.findall(f".//{{{_SPREADSHEET_NAMESPACE}}}sheet")
        assert [sheet.attrib["name"] for sheet in sheets] == ["Summary", "Rules", "Risks"]
        assert all(sheet.attrib.get("state", "visible") == "visible" for sheet in sheets)

        core = ElementTree.fromstring(archive.read("docProps/core.xml"))
        created = core.find(f"{{{_DUBLIN_TERMS_NAMESPACE}}}created")
        modified = core.find(f"{{{_DUBLIN_TERMS_NAMESPACE}}}modified")
        assert created is not None and created.text == "2026-08-13T01:02:03Z"
        assert modified is not None and modified.text == "2026-08-13T01:02:03Z"


def test_xlsx_contains_unicode_but_no_formulas_links_external_content_or_macros() -> None:
    content = report_payload_xlsx_bytes(
        _payload(actual="=SUM(1,1) 中文", expected="https://example.invalid/制度证据")
    )

    with ZipFile(BytesIO(content)) as archive:
        names = archive.namelist()
        assert not any("externalLinks" in name or "vbaProject" in name for name in names)
        assert not any(name.startswith("xl/media/") or "drawings" in name for name in names)
        assert not any(name.endswith(".bin") for name in names)

        xml_roots = {
            name: ElementTree.fromstring(archive.read(name))
            for name in names
            if name.endswith(".xml") or name.endswith(".rels")
        }
        assert all(
            _local_name(element.tag) != "f"
            for root in xml_roots.values()
            for element in root.iter()
        )
        assert all(
            _local_name(element.tag)
            not in {"hyperlink", "externalLink", "definedName", "definedNames"}
            for root in xml_roots.values()
            for element in root.iter()
        )
        for name, root in xml_roots.items():
            if not name.endswith(".rels"):
                continue
            for relationship in root.findall(f".//{{{_RELATIONSHIP_NAMESPACE}}}Relationship"):
                assert relationship.attrib.get("TargetMode") != "External"

        shared_strings = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        text = "\n".join(
            element.text or "" for element in shared_strings.iter(f"{{{_SPREADSHEET_NAMESPACE}}}t")
        )
        assert "中文" in text
        assert "'=SUM(1,1) 中文" in text
        assert "https://example.invalid/制度证据" in text
        assert _REFERENCE_TEXT in text


@pytest.mark.parametrize(
    "rules",
    (
        _rule_rows()[:-1],
        (("RULE-999", *_rule_rows()[0][1:]), *_rule_rows()[1:]),
    ),
)
def test_xlsx_rejects_non_exact_rule_catalog(rules: tuple[tuple[object, ...], ...]) -> None:
    with pytest.raises(ValueError, match="rules must"):
        report_payload_xlsx_bytes(_payload(rules=rules))


def test_xlsx_rejects_more_than_fifteen_risks() -> None:
    with pytest.raises(ValueError, match="at most 15"):
        report_payload_xlsx_bytes(_payload(risks=_risk_rows(16)))


def test_xlsx_rejects_invalid_enum_uuid_reference_and_risk_mapping() -> None:
    base_rules = _rule_rows()
    base_risks = _risk_rows()
    invalid_cases = (
        (
            ((base_rules[0][0], "unknown", *base_rules[0][2:]), *base_rules[1:]),
            base_risks,
            "enum string",
        ),
        (
            ((*base_rules[0][:5], "1", *base_rules[0][6:]), *base_rules[1:]),
            base_risks,
            "canonical UUID",
        ),
        (
            ((*base_rules[0][:7], "https://example.invalid/ref"), *base_rules[1:]),
            base_risks,
            "canonical UUID",
        ),
        (
            base_rules,
            ((base_risks[0][0], "RULE-002", *base_risks[0][2:]),),
            "match hit rules",
        ),
        (
            base_rules,
            ((*base_risks[0][:5], "different", *base_risks[0][6:]),),
            "match hit rules",
        ),
    )

    for rules, risks, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            report_payload_xlsx_bytes(_payload(rules=rules, risks=risks))


def test_xlsx_rejects_summary_that_does_not_match_risk_rows() -> None:
    payload = _payload()
    object.__setattr__(
        payload,
        "summary",
        ReportSummary(
            overall_level="none",
            active_risk_count=0,
            dismissed_risk_count=0,
            has_effective_high=False,
            has_unreviewed_high=False,
        ),
    )

    with pytest.raises(ValueError, match="summary must match risks"):
        report_payload_xlsx_bytes(payload)


@pytest.mark.parametrize(
    "invalid", ("\x00", "\x01", "\x08", "\ud800", "\udfff", "\ufffe", "\uffff")
)
def test_xlsx_rejects_invalid_xml_characters(invalid: str) -> None:
    with pytest.raises(ValueError, match="invalid XML"):
        report_payload_xlsx_bytes(_payload(actual=f"unsafe{invalid}text"))


def test_xlsx_rejects_cell_and_total_text_over_limits() -> None:
    assert len(report_payload_xlsx_bytes(_payload(actual="x" * MAX_XLSX_CELL_CODEPOINTS))) <= (
        MAX_XLSX_BYTES
    )
    with pytest.raises(ValueError, match="cell codepoint"):
        report_payload_xlsx_bytes(_payload(actual="x" * (MAX_XLSX_CELL_CODEPOINTS + 1)))
    formula_boundary_payload = _payload()
    boundary_formula = "=" + "x" * (MAX_XLSX_CELL_CODEPOINTS - 1)
    first_rule = formula_boundary_payload.rules.rows[0]
    first_risk = formula_boundary_payload.risks.rows[0]
    object.__setattr__(
        formula_boundary_payload.rules,
        "rows",
        (
            (*first_rule[:3], boundary_formula, *first_rule[4:]),
            *formula_boundary_payload.rules.rows[1:],
        ),
    )
    object.__setattr__(
        formula_boundary_payload.risks,
        "rows",
        ((*first_risk[:5], boundary_formula, *first_risk[6:]),),
    )
    with pytest.raises(ValueError, match="protected text"):
        report_payload_xlsx_bytes(formula_boundary_payload)

    payload_with_mutated_large_cell = _payload()
    first_rule = payload_with_mutated_large_cell.rules.rows[0]
    object.__setattr__(
        payload_with_mutated_large_cell.rules,
        "rows",
        (
            (
                *first_rule[:3],
                "=" + "x" * (MAX_XLSX_CELL_CODEPOINTS * 100),
                *first_rule[4:],
            ),
            *payload_with_mutated_large_cell.rules.rows[1:],
        ),
    )
    with pytest.raises(ValueError, match="cell codepoint"):
        report_payload_xlsx_bytes(payload_with_mutated_large_cell)

    large = "界" * MAX_XLSX_CELL_CODEPOINTS
    references = ";".join(str(UUID(int=1_000 + number)) for number in range(100))
    rule_rows = tuple(
        (
            f"RULE-{number:03d}",
            "failed",
            "hit",
            large,
            large,
            str(UUID(int=200 + number)),
            "high",
            references,
        )
        for number in range(1, 16)
    )
    risk_rows = tuple(
        (
            str(UUID(int=200 + number)),
            f"RULE-{number:03d}",
            "high",
            "high",
            "pending",
            large,
            large,
            references,
        )
        for number in range(1, 16)
    )
    payload = _payload(rules=rule_rows, risks=risk_rows)
    object.__setattr__(
        payload,
        "summary",
        ReportSummary(
            overall_level="high",
            active_risk_count=15,
            dismissed_risk_count=0,
            has_effective_high=True,
            has_unreviewed_high=True,
        ),
    )
    assert 15 * (4 * len(large) + 2 * len(references)) > MAX_XLSX_TOTAL_TEXT_CODEPOINTS
    with pytest.raises(ValueError, match="workbook codepoint"):
        report_payload_xlsx_bytes(payload)


def test_xlsx_rejects_reference_count_before_splitting() -> None:
    rules = _rule_rows()
    excessive = ";" * MAX_XLSX_REFERENCE_IDS
    mutated_rules = ((*rules[0][:7], excessive), *rules[1:])

    with pytest.raises(ValueError, match="count limit"):
        report_payload_xlsx_bytes(_payload(rules=mutated_rules))


def test_xlsx_rejects_degraded_reason_count_and_joined_length_before_joining() -> None:
    excessive_count = _payload()
    object.__setattr__(
        excessive_count.metadata,
        "degraded_reasons",
        ("x",) * (MAX_XLSX_DEGRADED_REASONS + 1),
    )
    with pytest.raises(ValueError, match="degraded_reasons exceed the count limit"):
        report_payload_xlsx_bytes(excessive_count)

    excessive_joined_length = _payload()
    object.__setattr__(
        excessive_joined_length.metadata,
        "degraded_reasons",
        ("x" * 2_100, "y" * 2_100),
    )
    with pytest.raises(ValueError, match="joined cell limit"):
        report_payload_xlsx_bytes(excessive_joined_length)


def test_xlsx_rejects_unbounded_integer_and_oversized_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    object.__setattr__(
        payload,
        "summary",
        ReportSummary(
            overall_level="high",
            active_risk_count=10**400,
            dismissed_risk_count=0,
            has_effective_high=True,
            has_unreviewed_high=True,
        ),
    )
    with pytest.raises(ValueError, match="summary must match risks"):
        report_payload_xlsx_bytes(payload)

    monkeypatch.setattr(xlsx_writer_module, "MAX_XLSX_BYTES", 1)
    with pytest.raises(ValueError, match="byte limit"):
        report_payload_xlsx_bytes(_payload())


class _FailedWorksheet:
    def write_string(self, row: int, column: int, value: str) -> int:
        return -2

    def write_boolean(self, row: int, column: int, value: bool) -> int:
        return -2

    def write_number(self, row: int, column: int, value: int) -> int:
        return -2

    def write_blank(self, row: int, column: int, value: None) -> int:
        return -2


def test_xlsx_cell_writer_rejects_nonzero_library_return_code() -> None:
    with pytest.raises(RuntimeError, match="cell write failed"):
        xlsx_writer_module._write_cell(_FailedWorksheet(), 0, 0, "text")


def test_xlsx_rejects_non_exact_summary_scalar_types() -> None:
    payload = _payload()
    object.__setattr__(
        payload,
        "summary",
        ReportSummary(
            overall_level="high",
            active_risk_count=True,  # type: ignore[arg-type]
            dismissed_risk_count=0,
            has_effective_high=True,
            has_unreviewed_high=True,
        ),
    )

    with pytest.raises(ValueError, match="risk counts"):
        report_payload_xlsx_bytes(payload)
