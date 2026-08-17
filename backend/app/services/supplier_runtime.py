"""供应商公开税务投影和状态不变量。"""

from __future__ import annotations

from uuid import UUID


def public_tax_number(
    unified_social_credit_code: str | None,
    tax_number: str | None,
) -> str | None:
    """返回公开 COALESCE 投影，并对双来源漂移失败关闭。"""

    if (
        unified_social_credit_code is not None
        and tax_number is not None
        and unified_social_credit_code != tax_number
    ):
        raise ValueError("tax identity sources conflict")
    return unified_social_credit_code if unified_social_credit_code is not None else tax_number


def validate_supplier_state(
    confirmation_status: str,
    status: str,
    *,
    confirmed_by: object,
    confirmed_at_present: bool,
) -> None:
    """验证 frozen supplier-runtime-v1 三态及确认元数据矩阵。"""

    valid_status = {
        "unconfirmed": "candidate",
        "confirmed": "active",
        "rejected": "inactive",
    }.get(confirmation_status)
    has_actor = type(confirmed_by) is UUID
    expected_metadata = confirmation_status != "unconfirmed"
    if (
        valid_status != status
        or has_actor != expected_metadata
        or confirmed_at_present != expected_metadata
    ):
        raise ValueError("supplier state matrix is invalid")


__all__ = ["public_tax_number", "validate_supplier_state"]
