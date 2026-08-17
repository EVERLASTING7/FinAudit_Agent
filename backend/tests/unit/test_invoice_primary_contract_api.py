from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.invoice_primary_contract import (
    get_invoice_primary_contract_query_service,
)
from app.bootstrap import create_app
from app.core.errors import AppError
from app.schemas.auth import CurrentUserData
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import ContractListItemData, ContractStatus
from app.schemas.invoices import InvoicePrimaryContractData
from app.services.auth import AuthenticatedActor, AuthService
from app.services.invoice_primary_contract_query import InvoicePrimaryContractQueryService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("66000000-0000-4000-8000-000000000001")
USER_ID = UUID("66000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("66000000-0000-4000-8000-000000000003")
INVOICE_ID = UUID("66000000-0000-4000-8000-000000000004")
CONTRACT_ID = UUID("66000000-0000-4000-8000-000000000005")


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
def primary_service() -> Mock:
    service = Mock(spec=InvoicePrimaryContractQueryService)
    service.get.return_value = InvoicePrimaryContractData(
        primary_contract=ContractListItemData(
            id=CONTRACT_ID,
            contract_no="HT-001",
            name="采购合同",
            party_b_name="乙方",
            amount="1000.00",
            currency="CNY",
            effective_date=None,
            expiry_date=None,
            confirmation_status=ConfirmationStatus.CONFIRMED,
            status=ContractStatus.ACTIVE,
        )
    )
    return service


@pytest.fixture
def application(
    exact_policy_file: Path,
    auth_service: Mock,
    primary_service: Mock,
) -> FastAPI:
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_invoice_primary_contract_query_service] = lambda: primary_service
    return app


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_primary_contract_is_actor_scoped_exact_and_private(
    client: TestClient,
    primary_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/primary-contract",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    primary_service.get.assert_called_once_with(ORGANIZATION_ID, INVOICE_ID)
    assert response.json()["data"] == {
        "primary_contract": {
            "id": str(CONTRACT_ID),
            "contract_no": "HT-001",
            "name": "采购合同",
            "party_b_name": "乙方",
            "amount": "1000.00",
            "currency": "CNY",
            "effective_date": None,
            "expiry_date": None,
            "confirmation_status": "confirmed",
            "status": "active",
        }
    }


def test_primary_contract_allows_visible_invoice_without_primary(
    client: TestClient,
    primary_service: Mock,
) -> None:
    primary_service.get.return_value = InvoicePrimaryContractData(primary_contract=None)

    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/primary-contract",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"primary_contract": None}


def test_primary_contract_rejects_query_parameters_without_calling_service(
    client: TestClient,
    primary_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/primary-contract?cursor=secret",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "secret" not in response.text
    primary_service.get.assert_not_called()


@pytest.mark.parametrize(
    "invoice_id",
    [
        "A6000000-0000-4000-8000-000000000004",
        INVOICE_ID.hex,
        "{" + str(INVOICE_ID) + "}",
    ],
)
def test_primary_contract_rejects_noncanonical_invoice_uuid(
    client: TestClient,
    primary_service: Mock,
    invoice_id: str,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{invoice_id}/primary-contract",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    primary_service.get.assert_not_called()


def test_primary_contract_requires_financial_read_before_service(
    client: TestClient,
    auth_service: Mock,
    primary_service: Mock,
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
        f"/api/v1/invoices/{INVOICE_ID}/primary-contract",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    primary_service.get.assert_not_called()


def test_primary_contract_requires_bearer_authentication(
    client: TestClient,
    primary_service: Mock,
) -> None:
    response = client.get(f"/api/v1/invoices/{INVOICE_ID}/primary-contract")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_ACCESS_EXPIRED"
    primary_service.get.assert_not_called()


def test_primary_contract_preserves_non_enumerating_not_found(
    client: TestClient,
    primary_service: Mock,
) -> None:
    primary_service.get.side_effect = AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )

    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/primary-contract",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


def test_primary_contract_reports_unconfigured_service(
    application: FastAPI,
) -> None:
    application.dependency_overrides.pop(get_invoice_primary_contract_query_service)
    with TestClient(application) as client:
        response = client.get(
            f"/api/v1/invoices/{INVOICE_ID}/primary-contract",
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "FINANCIAL_NOT_CONFIGURED"


def test_primary_contract_redacts_invalid_public_projection(
    application: FastAPI,
    primary_service: Mock,
) -> None:
    with pytest.raises(ValidationError) as captured:
        InvoicePrimaryContractData(primary_contract={"sentinel": "private"})  # type: ignore[arg-type]
    primary_service.get.side_effect = captured.value
    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            f"/api/v1/invoices/{INVOICE_ID}/primary-contract",
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "sentinel" not in response.text
    assert "private" not in response.text


def test_primary_contract_openapi_freezes_operation(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/api/v1/invoices/{invoice_id}/primary-contract"
    ]["get"]

    assert operation["operationId"] == "get_invoice_primary_contract_v1"
    assert operation["summary"] == "读取发票当前主合同"
    assert [parameter["name"] for parameter in operation["parameters"]] == ["invoice_id"]
    assert set(operation["responses"]) == {"200", "401", "403", "404", "422", "503"}
