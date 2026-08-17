from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.invoices import get_invoice_query_service
from app.bootstrap import create_app
from app.core.errors import AppError
from app.schemas.auth import CurrentUserData
from app.schemas.business_statuses import (
    ConfirmationStatus,
    InvoiceDuplicateStatus,
    InvoiceStatus,
)
from app.schemas.invoices import (
    InvoiceDetailData,
    InvoiceDuplicateCandidateListData,
    InvoiceExactDuplicatePairData,
    InvoiceExactIdentityData,
    InvoiceItemData,
    InvoiceListData,
    InvoiceListItemData,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.invoice_query import InvoiceQueryService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401 - imported fixture registration
    build_startup_settings,
)

ORGANIZATION_ID = UUID("61000000-0000-4000-8000-000000000001")
USER_ID = UUID("61000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("61000000-0000-4000-8000-000000000003")
INVOICE_ID = UUID("61000000-0000-4000-8000-000000000004")
ITEM_ID = UUID("61000000-0000-4000-8000-000000000005")
DUPLICATE_ID = UUID("61000000-0000-4000-8000-000000000006")


def _detail() -> InvoiceDetailData:
    return InvoiceDetailData(
        id=INVOICE_ID,
        invoice_code="3100",
        invoice_number="0001",
        invoice_type="standard",
        is_red_invoice=False,
        invoice_date=None,
        buyer_name="购买方",
        buyer_tax_no=None,
        seller_name="销售方",
        seller_tax_no="91310000TEST00001X",
        amount_excluding_tax="1000.00",
        tax_amount="60.00",
        total_amount="1060.00",
        currency="CNY",
        confirmation_status=ConfirmationStatus.CONFIRMED,
        duplicate_status=InvoiceDuplicateStatus.UNIQUE,
        status=InvoiceStatus.CONFIRMED,
        row_version="2",
        items=(
            InvoiceItemData(
                id=ITEM_ID,
                line_no=1,
                item_name="服务费",
                specification=None,
                unit=None,
                quantity="1.000000",
                unit_price="1000.000000",
                amount_excluding_tax="1000.00",
                tax_rate="0.060000",
                tax_amount="60.00",
                total_amount="1060.00",
                row_version="1",
            ),
        ),
    )


def _list_data() -> InvoiceListData:
    return InvoiceListData(
        items=(
            InvoiceListItemData(
                id=INVOICE_ID,
                invoice_code="3100",
                invoice_number="0001",
                invoice_date=None,
                seller_name="销售方",
                total_amount="1060.00",
                currency="CNY",
                confirmation_status=ConfirmationStatus.CONFIRMED,
                duplicate_status=InvoiceDuplicateStatus.UNIQUE,
                status=InvoiceStatus.CONFIRMED,
            ),
        ),
        page_size=1,
        next_cursor="next_cursor_v1",
    )


def _duplicate_data() -> InvoiceDuplicateCandidateListData:
    return InvoiceDuplicateCandidateListData(
        basis_status="ready",
        items=(
            InvoiceListItemData(
                id=DUPLICATE_ID,
                invoice_code="3100",
                invoice_number="0001",
                invoice_date=None,
                seller_name="销售方",
                total_amount="1060.00",
                currency="CNY",
                confirmation_status=ConfirmationStatus.CONFIRMED,
                duplicate_status=InvoiceDuplicateStatus.SUSPECTED,
                status=InvoiceStatus.ARCHIVED,
            ),
        ),
        page_size=1,
        next_cursor="next_duplicate_cursor_v1",
    )


def _pair_data() -> InvoiceExactDuplicatePairData:
    return InvoiceExactDuplicatePairData(
        source=_list_data().items[0],
        candidate=_duplicate_data().items[0],
        exact_identity=InvoiceExactIdentityData(
            invoice_code="3100",
            invoice_number="0001",
            seller_tax_no="91310000TEST00001X",
        ),
    )


@pytest.fixture
def auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        session_id=SESSION_ID,
        roles=("finance_reviewer",),
        permissions=("financial.read",),
    )
    current_user = CurrentUserData(
        id=USER_ID,
        display_name="财务复核员",
        roles=("finance_reviewer",),
        permissions=("financial.read",),
    )
    service.authenticate.return_value = (actor, current_user)
    return service


@pytest.fixture
def invoice_service() -> Mock:
    service = Mock(spec=InvoiceQueryService)
    service.get_detail.return_value = _detail()
    service.list_page.return_value = _list_data()
    service.list_duplicate_candidates.return_value = _duplicate_data()
    service.get_exact_duplicate_pair.return_value = _pair_data()
    return service


@pytest.fixture
def application(
    exact_policy_file: Path,
    auth_service: Mock,
    invoice_service: Mock,
) -> FastAPI:
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_invoice_query_service] = lambda: invoice_service
    return app


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_invoice_detail_is_actor_scoped_and_exposes_only_frozen_fields(
    client: TestClient,
    invoice_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    invoice_service.get_detail.assert_called_once_with(ORGANIZATION_ID, INVOICE_ID)
    assert response.json()["data"] == {
        "id": str(INVOICE_ID),
        "invoice_code": "3100",
        "invoice_number": "0001",
        "invoice_type": "standard",
        "is_red_invoice": False,
        "invoice_date": None,
        "buyer_name": "购买方",
        "buyer_tax_no": None,
        "seller_name": "销售方",
        "seller_tax_no": "91310000TEST00001X",
        "amount_excluding_tax": "1000.00",
        "tax_amount": "60.00",
        "total_amount": "1060.00",
        "currency": "CNY",
        "confirmation_status": "confirmed",
        "duplicate_status": "unique",
        "status": "confirmed",
        "row_version": "2",
        "items": [
            {
                "id": str(ITEM_ID),
                "line_no": 1,
                "item_name": "服务费",
                "specification": None,
                "unit": None,
                "quantity": "1.000000",
                "unit_price": "1000.000000",
                "amount_excluding_tax": "1000.00",
                "tax_rate": "0.060000",
                "tax_amount": "60.00",
                "total_amount": "1060.00",
                "row_version": "1",
            }
        ],
    }


def test_invoice_list_is_actor_scoped_bounded_and_private(
    client: TestClient,
    invoice_service: Mock,
) -> None:
    response = client.get(
        "/api/v1/invoices?cursor=current_cursor_v1&page_size=1",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    invoice_service.list_page.assert_called_once_with(ORGANIZATION_ID, "current_cursor_v1", 1)
    assert response.json()["data"] == {
        "items": [
            {
                "id": str(INVOICE_ID),
                "invoice_code": "3100",
                "invoice_number": "0001",
                "invoice_date": None,
                "seller_name": "销售方",
                "total_amount": "1060.00",
                "currency": "CNY",
                "confirmation_status": "confirmed",
                "duplicate_status": "unique",
                "status": "confirmed",
            }
        ],
        "page_size": 1,
        "next_cursor": "next_cursor_v1",
    }


def test_invoice_duplicate_candidates_are_actor_scoped_exact_and_private(
    client: TestClient,
    invoice_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates"
        "?cursor=current_duplicate_cursor&page_size=1",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    invoice_service.list_duplicate_candidates.assert_called_once_with(
        ORGANIZATION_ID,
        INVOICE_ID,
        "current_duplicate_cursor",
        1,
    )
    assert response.json()["data"] == {
        "basis_status": "ready",
        "items": [
            {
                "id": str(DUPLICATE_ID),
                "invoice_code": "3100",
                "invoice_number": "0001",
                "invoice_date": None,
                "seller_name": "销售方",
                "total_amount": "1060.00",
                "currency": "CNY",
                "confirmation_status": "confirmed",
                "duplicate_status": "suspected",
                "status": "archived",
            }
        ],
        "page_size": 1,
        "next_cursor": "next_duplicate_cursor_v1",
    }


@pytest.mark.parametrize(
    "query",
    [
        "page=1",
        "sort=id",
        "page_size=0",
        "page_size=101",
        "cursor=abc%3D",
        "cursor=" + "a" * 257,
    ],
)
def test_invoice_duplicate_candidates_reject_unknown_or_invalid_query(
    client: TestClient,
    invoice_service: Mock,
    query: str,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates?{query}",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    invoice_service.list_duplicate_candidates.assert_not_called()


@pytest.mark.parametrize(
    "invoice_id",
    [
        "A1000000-0000-4000-8000-000000000004",
        INVOICE_ID.hex,
        "{" + str(INVOICE_ID) + "}",
    ],
)
def test_invoice_duplicate_candidates_reject_noncanonical_uuid(
    client: TestClient,
    invoice_service: Mock,
    invoice_id: str,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{invoice_id}/duplicate-candidates",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    invoice_service.list_duplicate_candidates.assert_not_called()


def test_invoice_duplicate_candidates_require_bearer_authentication(
    client: TestClient,
    invoice_service: Mock,
) -> None:
    response = client.get(f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_ACCESS_EXPIRED"
    invoice_service.list_duplicate_candidates.assert_not_called()


def test_invoice_duplicate_candidates_require_financial_read(
    client: TestClient,
    auth_service: Mock,
    invoice_service: Mock,
) -> None:
    actor = AuthenticatedActor(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        session_id=SESSION_ID,
        roles=("read_only",),
        permissions=("audits.read", "reports.read"),
    )
    auth_service.authenticate.return_value = (actor, auth_service.authenticate.return_value[1])

    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    invoice_service.list_duplicate_candidates.assert_not_called()


def test_invoice_duplicate_candidates_preserve_non_enumerating_not_found(
    client: TestClient,
    invoice_service: Mock,
) -> None:
    invoice_service.list_duplicate_candidates.side_effect = AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )

    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    assert response.json()["trace_id"] == response.headers["X-Trace-ID"]


def test_invoice_duplicate_candidates_report_unconfigured_service(
    application: FastAPI,
    invoice_service: Mock,
) -> None:
    application.dependency_overrides.pop(get_invoice_query_service)
    with TestClient(application) as test_client:
        response = test_client.get(
            f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "FINANCIAL_NOT_CONFIGURED"
    invoice_service.list_duplicate_candidates.assert_not_called()


def test_invoice_duplicate_candidates_redact_invalid_projection(
    application: FastAPI,
    invoice_service: Mock,
) -> None:
    with pytest.raises(ValidationError) as captured:
        InvoiceDuplicateCandidateListData(
            basis_status="source_voided",
            items=(_duplicate_data().items[0],),
            page_size=20,
            next_cursor=None,
        )
    invoice_service.list_duplicate_candidates.side_effect = captured.value
    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get(
            f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "source_voided" not in response.text


def test_invoice_exact_duplicate_pair_is_actor_scoped_and_private(
    client: TestClient,
    invoice_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates/{DUPLICATE_ID}",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    invoice_service.get_exact_duplicate_pair.assert_called_once_with(
        ORGANIZATION_ID,
        INVOICE_ID,
        DUPLICATE_ID,
    )
    assert response.json()["data"] == {
        "source": {
            "id": str(INVOICE_ID),
            "invoice_code": "3100",
            "invoice_number": "0001",
            "invoice_date": None,
            "seller_name": "销售方",
            "total_amount": "1060.00",
            "currency": "CNY",
            "confirmation_status": "confirmed",
            "duplicate_status": "unique",
            "status": "confirmed",
        },
        "candidate": {
            "id": str(DUPLICATE_ID),
            "invoice_code": "3100",
            "invoice_number": "0001",
            "invoice_date": None,
            "seller_name": "销售方",
            "total_amount": "1060.00",
            "currency": "CNY",
            "confirmation_status": "confirmed",
            "duplicate_status": "suspected",
            "status": "archived",
        },
        "exact_identity": {
            "invoice_code": "3100",
            "invoice_number": "0001",
            "seller_tax_no": "91310000TEST00001X",
        },
    }


def test_invoice_exact_duplicate_pair_rejects_query_parameters(
    client: TestClient,
    invoice_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates/{DUPLICATE_ID}?expand=secret",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    invoice_service.get_exact_duplicate_pair.assert_not_called()


@pytest.mark.parametrize(
    ("invoice_id", "candidate_id"),
    [
        ("A1000000-0000-4000-8000-000000000004", str(DUPLICATE_ID)),
        (INVOICE_ID.hex, str(DUPLICATE_ID)),
        (str(INVOICE_ID), "A1000000-0000-4000-8000-000000000006"),
        (str(INVOICE_ID), DUPLICATE_ID.hex),
    ],
)
def test_invoice_exact_duplicate_pair_rejects_noncanonical_uuid(
    client: TestClient,
    invoice_service: Mock,
    invoice_id: str,
    candidate_id: str,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{invoice_id}/duplicate-candidates/{candidate_id}",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    invoice_service.get_exact_duplicate_pair.assert_not_called()


def test_invoice_exact_duplicate_pair_self_comparison_is_not_found(
    client: TestClient,
    invoice_service: Mock,
) -> None:
    invoice_service.get_exact_duplicate_pair.side_effect = AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )

    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates/{INVOICE_ID}",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    invoice_service.get_exact_duplicate_pair.assert_called_once_with(
        ORGANIZATION_ID,
        INVOICE_ID,
        INVOICE_ID,
    )


def test_invoice_exact_duplicate_pair_requires_authentication(
    client: TestClient,
    invoice_service: Mock,
) -> None:
    response = client.get(f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates/{DUPLICATE_ID}")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_ACCESS_EXPIRED"
    invoice_service.get_exact_duplicate_pair.assert_not_called()


def test_invoice_exact_duplicate_pair_requires_financial_read(
    client: TestClient,
    auth_service: Mock,
    invoice_service: Mock,
) -> None:
    actor = AuthenticatedActor(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        session_id=SESSION_ID,
        roles=("read_only",),
        permissions=("audits.read", "reports.read"),
    )
    auth_service.authenticate.return_value = (actor, auth_service.authenticate.return_value[1])

    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates/{DUPLICATE_ID}",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    invoice_service.get_exact_duplicate_pair.assert_not_called()


def test_invoice_exact_duplicate_pair_redacts_invalid_repository_projection(
    application: FastAPI,
    invoice_service: Mock,
) -> None:
    invoice_service.get_exact_duplicate_pair.side_effect = ValueError(
        "swapped invoice ids with private sentinel"
    )
    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get(
            f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates/{DUPLICATE_ID}",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "sentinel" not in response.text
    assert "swapped" not in response.text


@pytest.mark.parametrize(
    "query",
    [
        "page=1",
        "page_size=0",
        "page_size=101",
        "keyword=secret",
        "cursor=abc%3D",
        "cursor=" + "a" * 257,
    ],
)
def test_invoice_list_rejects_out_of_contract_query_parameters(
    client: TestClient,
    invoice_service: Mock,
    query: str,
) -> None:
    response = client.get(
        f"/api/v1/invoices?{query}",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    invoice_service.list_page.assert_not_called()


def test_invoice_list_requires_financial_read(
    client: TestClient,
    auth_service: Mock,
    invoice_service: Mock,
) -> None:
    actor = AuthenticatedActor(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        session_id=SESSION_ID,
        roles=("read_only",),
        permissions=("audits.read", "reports.read"),
    )
    auth_service.authenticate.return_value = (actor, auth_service.authenticate.return_value[1])

    response = client.get(
        "/api/v1/invoices",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    invoice_service.list_page.assert_not_called()


def test_invoice_list_redacts_invalid_public_projection(
    application: FastAPI,
    invoice_service: Mock,
) -> None:
    with pytest.raises(ValidationError) as captured:
        InvoiceListData(
            items=(),
            page_size=1,
            next_cursor="private_projection_sentinel",
        )
    invoice_service.list_page.side_effect = captured.value
    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get(
            "/api/v1/invoices",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "private_projection_sentinel" not in response.text


@pytest.mark.parametrize(
    "invoice_id",
    [
        "A1000000-0000-4000-8000-000000000004",
        INVOICE_ID.hex,
        "{" + str(INVOICE_ID) + "}",
    ],
)
def test_invoice_detail_rejects_noncanonical_uuid(
    client: TestClient,
    invoice_service: Mock,
    invoice_id: str,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{invoice_id}",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    invoice_service.get_detail.assert_not_called()


def test_invoice_detail_preserves_non_enumerating_not_found(
    client: TestClient,
    invoice_service: Mock,
) -> None:
    invoice_service.get_detail.side_effect = AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )

    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    assert response.json()["trace_id"] == response.headers["X-Trace-ID"]


def test_invoice_detail_requires_bearer_authentication(
    client: TestClient,
    invoice_service: Mock,
) -> None:
    response = client.get(f"/api/v1/invoices/{INVOICE_ID}")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_ACCESS_EXPIRED"
    invoice_service.get_detail.assert_not_called()


def test_invoice_detail_requires_financial_read(
    client: TestClient,
    auth_service: Mock,
    invoice_service: Mock,
) -> None:
    actor = AuthenticatedActor(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        session_id=SESSION_ID,
        roles=("read_only",),
        permissions=("audits.read", "reports.read"),
    )
    auth_service.authenticate.return_value = (actor, auth_service.authenticate.return_value[1])

    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}",
        headers={"Authorization": "Bearer access-token"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    invoice_service.get_detail.assert_not_called()


def test_invoice_detail_reports_unconfigured_query_service(
    application: FastAPI,
    invoice_service: Mock,
) -> None:
    application.dependency_overrides.pop(get_invoice_query_service)
    with TestClient(application) as test_client:
        response = test_client.get(
            f"/api/v1/invoices/{INVOICE_ID}",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "FINANCIAL_NOT_CONFIGURED"
    invoice_service.get_detail.assert_not_called()


def test_invoice_detail_redacts_invalid_persisted_projection(
    application: FastAPI,
    invoice_service: Mock,
) -> None:
    invoice_service.get_detail.side_effect = ValueError("database secret sentinel")
    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get(
            f"/api/v1/invoices/{INVOICE_ID}",
            headers={"Authorization": "Bearer access-token"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "sentinel" not in response.text


def test_invoice_detail_openapi_freezes_operation_and_error_contract(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/invoices/{invoice_id}"]["get"]

    assert operation["operationId"] == "get_invoice_detail_v1"
    assert operation["summary"] == "读取发票详情"
    assert "404" in operation["description"]
    assert set(operation["responses"]) == {"200", "401", "403", "404", "422", "503"}


def test_invoice_list_openapi_freezes_query_and_error_contract(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/invoices"]["get"]

    assert operation["operationId"] == "list_invoices_v1"
    assert operation["summary"] == "读取发票列表"
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "cursor",
        "page_size",
    ]
    assert set(operation["responses"]) == {"200", "401", "403", "422", "503"}


def test_invoice_duplicate_candidates_openapi_freezes_contract(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/api/v1/invoices/{invoice_id}/duplicate-candidates"
    ]["get"]

    assert operation["operationId"] == "list_invoice_duplicate_candidates_v1"
    assert operation["summary"] == "读取发票精确重复候选"
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "invoice_id",
        "cursor",
        "page_size",
    ]
    assert set(operation["responses"]) == {"200", "401", "403", "404", "422", "503"}


def test_invoice_exact_duplicate_pair_openapi_freezes_contract(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/api/v1/invoices/{invoice_id}/duplicate-candidates/{candidate_id}"
    ]["get"]

    assert operation["operationId"] == "get_invoice_exact_duplicate_pair_v1"
    assert operation["summary"] == "读取发票精确重复对"
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "invoice_id",
        "candidate_id",
    ]
    assert set(operation["responses"]) == {"200", "401", "403", "404", "422", "503"}
