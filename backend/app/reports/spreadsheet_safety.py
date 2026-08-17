"""电子表格文本输出的安全边界。"""

_FORMULA_PREFIXES = frozenset("=+-@\t\r\n")


def neutralize_spreadsheet_formula_text(value: str) -> str:
    """中和用户文本开头的电子表格公式触发字符。"""

    if type(value) is not str:
        raise ValueError("value must be an exact str")
    if value[:1] in _FORMULA_PREFIXES:
        return f"'{value}"
    return value
