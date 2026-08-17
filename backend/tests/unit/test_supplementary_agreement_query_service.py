import base64
from datetime import date
from typing import cast
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.repositories.financial_read import (
    FinancialReadRepository,
    SupplementaryAgreementReadView,
)
from app.schemas.contracts import SupplementaryAgreementHeaderListData
from app.services.supplementary_agreement_query import (
    SupplementaryAgreementQueryService,
    _decode_cursor,
    _encode_cursor_values,
    _project_header,
)

ORGANIZATION_ID = UUID("67000000-0000-4000-8000-000000000001")
CONTRACT_ID = UUID("67000000-0000-4000-8000-000000000002")
AGREEMENT_ID = UUID("67000000-0000-4000-8000-000000000003")


def _view(
    *,
    status: str = "confirmed",
    confirmation_status: str = "confirmed",
) -> SupplementaryAgreementReadView:
    return SupplementaryAgreementReadView(
        id=AGREEMENT_ID,
        organization_id=ORGANIZATION_ID,
        contract_id=CONTRACT_ID,
        agreement_no="S-001",
        name="补充协议 Header",
        signed_date=date(2026, 1, 1),
        effective_date=date(2026, 2, 1),
        status=status,
        confirmation_status=confirmation_status,
        confirmed_by=UUID("67000000-0000-4000-8000-000000000004"),
        confirmed_at=None,
        confirmation_reason="private reason",
        critical_fact_hash="a" * 64,
        row_version=8,
    )


def _service(
    repository: Mock, monkeypatch: pytest.MonkeyPatch
) -> SupplementaryAgreementQueryService:
    context = MagicMock()
    context.__enter__.return_value = Mock(spec=Session)
    monkeypatch.setattr(
        "app.services.supplementary_agreement_query.FinancialReadRepository",
        Mock(return_value=repository),
    )
    return SupplementaryAgreementQueryService(
        cast(sessionmaker[Session], Mock(return_value=context))
    )


def _raw_cursor(payload: str) -> str:
    return base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()


def _alias_pad_bits(cursor: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    index = alphabet.index(cursor[-1])
    return cursor[:-1] + alphabet[index | 1]


def test_header_projection_is_exact_and_does_not_claim_effectivity() -> None:
    payload = _project_header(_view()).model_dump(mode="json")

    assert payload == {
        "id": str(AGREEMENT_ID),
        "agreement_no": "S-001",
        "name": "补充协议 Header",
        "signed_date": "2026-01-01",
        "effective_date": "2026-02-01",
        "status": "confirmed",
        "confirmation_status": "confirmed",
    }
    assert set(payload).isdisjoint(
        {
            "organization_id",
            "contract_id",
            "row_version",
            "confirmation_reason",
            "critical_fact_hash",
            "confirmed_by",
            "is_effective",
            "is_applicable",
        }
    )


@pytest.mark.parametrize(
    ("status", "confirmation_status"),
    [("invalid", "confirmed"), ("draft", "invalid")],
)
def test_header_projection_rejects_invalid_persisted_statuses(
    status: str,
    confirmation_status: str,
) -> None:
    with pytest.raises(ValueError):
        _project_header(_view(status=status, confirmation_status=confirmation_status))


def test_header_service_pages_and_maps_invisible_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock()
    repository.read_supplementary_agreement_header_page.return_value = ((_view(),), True)
    service = _service(repository, monkeypatch)

    result = service.list_headers(ORGANIZATION_ID, CONTRACT_ID, None, 1)

    repository.read_supplementary_agreement_header_page.assert_called_once_with(
        ORGANIZATION_ID, CONTRACT_ID, 1, None, None
    )
    assert result.next_cursor is not None
    assert _decode_cursor(result.next_cursor) == (date(2026, 2, 1), AGREEMENT_ID)

    repository.read_supplementary_agreement_header_page.return_value = None
    with pytest.raises(AppError) as captured:
        service.list_headers(ORGANIZATION_ID, CONTRACT_ID, None, 20)
    assert captured.value.status_code == 404
    assert captured.value.code == "RESOURCE_NOT_FOUND"


def test_header_list_schema_rejects_partial_cursor_page() -> None:
    with pytest.raises(ValidationError):
        SupplementaryAgreementHeaderListData(
            items=(),
            page_size=1,
            next_cursor="inconsistent",
        )


def test_header_service_fails_closed_on_inconsistent_repository_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock()
    repository.read_supplementary_agreement_header_page.return_value = ((_view(),), True)

    with pytest.raises(ValidationError):
        _service(repository, monkeypatch).list_headers(
            ORGANIZATION_ID,
            CONTRACT_ID,
            None,
            2,
        )


@pytest.mark.parametrize(
    "cursor",
    [
        "not+url",
        "abc=",
        "a" * 257,
        "e30",
        _alias_pad_bits("e30"),
        _raw_cursor(
            '{"effective_date":"2026-02-01","id":'
            '"67000000-0000-4000-8000-000000000003","v":1,"v":1}'
        ),
        _raw_cursor(
            '{"effective_date":"2026-02-01","extra":null,"id":'
            '"67000000-0000-4000-8000-000000000003","v":1}'
        ),
        _raw_cursor(
            '{"effective_date":"2026-02-01","id":"67000000-0000-4000-8000-000000000003","v":true}'
        ),
        _raw_cursor(
            '{"effective_date":"2026-02-01","id":"67000000-0000-4000-8000-000000000003","v":2}'
        ),
        _raw_cursor('{"effective_date":null,"id":"67000000-0000-4000-8000-000000000003","v":1}'),
        _raw_cursor(
            '{"effective_date":"2026-02-30","id":"67000000-0000-4000-8000-000000000003","v":1}'
        ),
        _raw_cursor(
            '{"effective_date":"2026-2-1","id":"67000000-0000-4000-8000-000000000003","v":1}'
        ),
        _raw_cursor(
            '{"effective_date":"2026-02-01","id":"67000000-0000-4000-8000-00000000000A","v":1}'
        ),
        _raw_cursor(
            '{ "v": 1, "id": "67000000-0000-4000-8000-000000000003", '
            '"effective_date": "2026-02-01" }'
        ),
    ],
)
def test_header_service_rejects_untrusted_cursor(cursor: str) -> None:
    service = SupplementaryAgreementQueryService(cast(sessionmaker[Session], Mock()))

    with pytest.raises(AppError) as captured:
        service.list_headers(ORGANIZATION_ID, CONTRACT_ID, cursor, 20)

    assert captured.value.status_code == 422
    assert captured.value.code == "VALIDATION_ERROR"
    assert captured.value.details == [{"field": "query.cursor", "reason": "invalid"}]


def test_header_cursor_round_trips_canonical_values() -> None:
    cursor = _encode_cursor_values(date(2026, 2, 1), AGREEMENT_ID)

    assert "=" not in cursor
    assert _decode_cursor(cursor) == (date(2026, 2, 1), AGREEMENT_ID)


def test_header_repository_statements_enforce_parent_and_child_boundaries() -> None:
    session = Mock(spec=Session)
    session.scalar.return_value = CONTRACT_ID
    session.scalars.return_value.all.return_value = []
    repository = FinancialReadRepository(session)

    result = repository.read_supplementary_agreement_header_page(
        ORGANIZATION_ID,
        CONTRACT_ID,
        2,
    )

    assert result == ((), False)
    anchor_sql = str(session.scalar.call_args.args[0])
    child_sql = str(
        session.scalars.call_args.args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "contracts.organization_id" in anchor_sql
    assert "contracts.deleted_at IS NULL" in anchor_sql
    assert "supplementary_agreements.organization_id" in child_sql
    assert "supplementary_agreements.contract_id" in child_sql
    assert "supplementary_agreements.deleted_at IS NULL" in child_sql
    assert "contracts.organization_id" in child_sql
    assert "contracts.deleted_at IS NULL" in child_sql
    assert "LIMIT 3" in child_sql
