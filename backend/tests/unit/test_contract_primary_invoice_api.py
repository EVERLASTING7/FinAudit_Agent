from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.contract_primary_invoices import (
    get_contract_primary_invoice_query_service,
)
from app.api.v1.endpoints.contracts import router as contract_router
from app.bootstrap import create_app
from app.core.errors import AppError
from app.schemas.auth import CurrentUserData
from app.schemas.business_statuses import (
    ConfirmationStatus,
    InvoiceDuplicateStatus,
    InvoiceStatus,
)
from app.schemas.invoices import ContractPrimaryInvoiceListData, InvoiceListItemData
from app.services.auth import AuthenticatedActor, AuthService
from app.services.contract_primary_invoice_query import ContractPrimaryInvoiceQueryService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("69000000-0000-4000-8000-000000000001")
USER_ID = UUID("69000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("69000000-0000-4000-8000-000000000003")
CONTRACT_ID = UUID("69000000-0000-4000-8000-000000000004")
INVOICE_ID = UUID("69000000-0000-4000-8000-000000000005")


@pytest.fixture
def auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("finance_reviewer",),
        ("financial.read",),
    )
    current = CurrentUserData(
        id=USER_ID,
        display_name="财务复核员",
        roles=("finance_reviewer",),
        permissions=("financial.read",),
    )
    service.authenticate.return_value = (actor, current)
    return service


@pytest.fixture
def primary_invoice_service() -> Mock:
    service = Mock(spec=ContractPrimaryInvoiceQueryService)
    service.list_page.return_value = ContractPrimaryInvoiceListData(
        items=(
            InvoiceListItemData(
                id=INVOICE_ID,
                invoice_code="INV-CODE",
                invoice_number="INV-NUMBER",
                invoice_date=None,
                seller_name="seller",
                total_amount="100.25",
                currency="CNY",
                confirmation_status=ConfirmationStatus.CONFIRMED,
                duplicate_status=InvoiceDuplicateStatus.UNIQUE,
                status=InvoiceStatus.CONFIRMED,
            ),
        ),
        page_size=20,
        next_cursor=None,
    )
    return service


@pytest.fixture
def application(
    exact_policy_file: Path,
    auth_service: Mock,
    primary_invoice_service: Mock,
) -> FastAPI:
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_contract_primary_invoice_query_service] = lambda: (
        primary_invoice_service
    )
    return app


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_primary_invoice_list_is_actor_scoped_exact_and_private(
    client: TestClient,
    primary_invoice_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/primary-invoices?page_size=20",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    primary_invoice_service.list_page.assert_called_once_with(
        ORGANIZATION_ID, CONTRACT_ID, None, 20
    )
    assert response.json()["data"] == {
        "items": [
            {
                "id": str(INVOICE_ID),
                "invoice_code": "INV-CODE",
                "invoice_number": "INV-NUMBER",
                "invoice_date": None,
                "seller_name": "seller",
                "total_amount": "100.25",
                "currency": "CNY",
                "confirmation_status": "confirmed",
                "duplicate_status": "unique",
                "status": "confirmed",
            }
        ],
        "page_size": 20,
        "next_cursor": None,
    }


@pytest.mark.parametrize(
    "query",
    ["page=1", "sort=id", "page_size=0", "page_size=101", "cursor=abc="],
)
def test_primary_invoice_list_rejects_unknown_or_invalid_query_without_service(
    client: TestClient,
    primary_invoice_service: Mock,
    query: str,
) -> None:
    response = client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/primary-invoices?{query}",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    primary_invoice_service.list_page.assert_not_called()


@pytest.mark.parametrize(
    "contract_id",
    [
        "A9000000-0000-4000-8000-000000000004",
        CONTRACT_ID.hex,
        "{" + str(CONTRACT_ID) + "}",
    ],
)
def test_primary_invoice_list_rejects_noncanonical_contract_uuid(
    client: TestClient,
    primary_invoice_service: Mock,
    contract_id: str,
) -> None:
    response = client.get(
        f"/api/v1/contracts/{contract_id}/primary-invoices",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    primary_invoice_service.list_page.assert_not_called()


def test_primary_invoice_list_requires_financial_read_before_service(
    client: TestClient,
    auth_service: Mock,
    primary_invoice_service: Mock,
) -> None:
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("read_only",),
        ("audits.read",),
    )
    auth_service.authenticate.return_value = (actor, auth_service.authenticate.return_value[1])

    response = client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/primary-invoices",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    primary_invoice_service.list_page.assert_not_called()


def test_primary_invoice_list_requires_bearer_authentication(
    client: TestClient,
    primary_invoice_service: Mock,
) -> None:
    response = client.get(f"/api/v1/contracts/{CONTRACT_ID}/primary-invoices")

    assert response.status_code == 401
    primary_invoice_service.list_page.assert_not_called()


def test_primary_invoice_list_preserves_not_found(
    client: TestClient,
    primary_invoice_service: Mock,
) -> None:
    primary_invoice_service.list_page.side_effect = AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )

    response = client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/primary-invoices",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


def test_primary_invoice_list_reports_unconfigured_service(application: FastAPI) -> None:
    application.dependency_overrides.pop(get_contract_primary_invoice_query_service)
    with TestClient(application) as client:
        response = client.get(
            f"/api/v1/contracts/{CONTRACT_ID}/primary-invoices",
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "FINANCIAL_NOT_CONFIGURED"


def test_primary_invoice_list_redacts_invalid_projection(
    application: FastAPI,
    primary_invoice_service: Mock,
) -> None:
    with pytest.raises(ValidationError) as captured:
        ContractPrimaryInvoiceListData(items="sentinel-private", page_size=20)  # type: ignore[arg-type]
    primary_invoice_service.list_page.side_effect = captured.value
    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            f"/api/v1/contracts/{CONTRACT_ID}/primary-invoices",
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "sentinel" not in response.text
    assert "private" not in response.text


def test_primary_invoice_list_openapi_freezes_operation(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/api/v1/contracts/{contract_id}/primary-invoices"
    ]["get"]

    assert operation["operationId"] == "list_contract_primary_invoices_v1"
    assert operation["summary"] == "读取合同当前主发票列表"
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "contract_id",
        "cursor",
        "page_size",
    ]
    assert set(operation["responses"]) == {"200", "401", "403", "404", "422", "503"}


def test_primary_invoice_route_is_registered_before_contract_detail() -> None:
    paths = [getattr(route, "path", None) for route in contract_router.routes]

    assert paths.index("/contracts/{contract_id}/primary-invoices") < paths.index(
        "/contracts/{contract_id}"
    )
