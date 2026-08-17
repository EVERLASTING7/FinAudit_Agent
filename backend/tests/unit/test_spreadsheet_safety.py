from decimal import Decimal

import pytest

from app.reports.spreadsheet_safety import neutralize_spreadsheet_formula_text


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
        ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
        ("-1+2", "'-1+2"),
        ("@SUM(A1:A2)", "'@SUM(A1:A2)"),
        ("\t=SUM(A1:A2)", "'\t=SUM(A1:A2)"),
        ("\r=SUM(A1:A2)", "'\r=SUM(A1:A2)"),
        ("\n=SUM(A1:A2)", "'\n=SUM(A1:A2)"),
    ),
)
def test_neutralizes_exact_formula_prefixes(value: str, expected: str) -> None:
    assert neutralize_spreadsheet_formula_text(value) == expected


@pytest.mark.parametrize("value", ("", "普通文本", "123.45", "'=SUM(A1:A2)"))
def test_preserves_empty_ordinary_and_already_neutralized_text(value: str) -> None:
    assert neutralize_spreadsheet_formula_text(value) == value


@pytest.mark.parametrize("value", ("=1", "+1", "-1", "@A1", "\t=1", "\r=1", "\n=1"))
def test_neutralization_is_idempotent(value: str) -> None:
    neutralized = neutralize_spreadsheet_formula_text(value)

    assert neutralize_spreadsheet_formula_text(neutralized) == neutralized


class StringSubclass(str):
    pass


@pytest.mark.parametrize(
    "value",
    (None, True, 1, Decimal("1.00"), b"=1", StringSubclass("=1")),
)
def test_rejects_non_exact_strings(value: object) -> None:
    with pytest.raises(ValueError, match="exact str"):
        neutralize_spreadsheet_formula_text(value)  # type: ignore[arg-type]
