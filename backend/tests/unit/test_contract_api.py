from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.contracts import get_contract_query_service
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import (
    ContractDetailData,
    ContractListData,
    ContractListItemData,
    ContractStatus,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.contract_query import ContractQueryService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORG = UUID("64000000-0000-4000-8000-000000000001")
USER = UUID("64000000-0000-4000-8000-000000000002")
SESSION = UUID("64000000-0000-4000-8000-000000000003")
CONTRACT = UUID("64000000-0000-4000-8000-000000000004")


@pytest.fixture
def services(exact_policy_file: Path) -> tuple[TestClient, Mock, Mock]:
    auth = Mock(spec=AuthService)
    actor = AuthenticatedActor(USER, ORG, SESSION, ("contract_admin",), ("financial.read",))
    user = CurrentUserData(
        id=USER,
        display_name="合同管理员",
        roles=("contract_admin",),
        permissions=("financial.read",),
    )
    auth.authenticate.return_value = (actor, user)
    query = Mock(spec=ContractQueryService)
    item = ContractListItemData(
        id=CONTRACT,
        contract_no="HT-1",
        name="合同",
        party_b_name="乙方",
        amount="10.00",
        currency="CNY",
        effective_date=None,
        expiry_date=None,
        confirmation_status=ConfirmationStatus.CONFIRMED,
        status=ContractStatus.ACTIVE,
    )
    query.list_page.return_value = ContractListData(items=(item,), page_size=1, next_cursor="next")
    query.get_detail.return_value = ContractDetailData(
        id=CONTRACT,
        contract_no="HT-1",
        name="合同",
        party_a_name=None,
        party_a_tax_no=None,
        party_b_name="乙方",
        party_b_tax_no=None,
        amount="10.00",
        currency="CNY",
        signed_date=None,
        effective_date=None,
        expiry_date=None,
        payment_method=None,
        payment_terms=None,
        confirmation_status=ConfirmationStatus.CONFIRMED,
        status=ContractStatus.ACTIVE,
        row_version="1",
    )
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_contract_query_service] = lambda: query
    return TestClient(app), query, auth


@pytest.fixture
def client(services: tuple[TestClient, Mock, Mock]) -> Iterator[tuple[TestClient, Mock, Mock]]:
    test_client, query, auth = services
    with test_client:
        yield test_client, query, auth


def test_contract_list_and_detail_are_scoped_private_and_exact(
    client: tuple[TestClient, Mock, Mock],
) -> None:
    test_client, query, _ = client
    listing = test_client.get(
        "/api/v1/contracts?page_size=1", headers={"Authorization": "Bearer token"}
    )
    detail = test_client.get(
        f"/api/v1/contracts/{CONTRACT}", headers={"Authorization": "Bearer token"}
    )

    assert listing.status_code == detail.status_code == 200
    assert listing.headers["cache-control"] == "private, no-store"
    assert detail.headers["cache-control"] == "private, no-store"
    query.list_page.assert_called_once_with(ORG, None, 1)
    query.get_detail.assert_called_once_with(ORG, CONTRACT)
    assert set(listing.json()["data"]["items"][0]) == {
        "id",
        "contract_no",
        "name",
        "party_b_name",
        "amount",
        "currency",
        "effective_date",
        "expiry_date",
        "confirmation_status",
        "status",
    }


@pytest.mark.parametrize("query_string", ["page=1", "page_size=0", "cursor=abc%3D"])
def test_contract_list_rejects_out_of_contract_query(
    client: tuple[TestClient, Mock, Mock], query_string: str
) -> None:
    response = client[0].get(
        f"/api/v1/contracts?{query_string}", headers={"Authorization": "Bearer token"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_contract_detail_rejects_noncanonical_uuid(
    client: tuple[TestClient, Mock, Mock],
) -> None:
    response = client[0].get(
        "/api/v1/contracts/A4000000-0000-4000-8000-000000000004",
        headers={"Authorization": "Bearer token"},
    )
    assert response.status_code == 422


def test_contract_openapi_freezes_operations(client: tuple[TestClient, Mock, Mock]) -> None:
    paths = client[0].get("/openapi.json").json()["paths"]
    listing = paths["/api/v1/contracts"]["get"]
    detail = paths["/api/v1/contracts/{contract_id}"]["get"]
    assert listing["operationId"] == "list_contracts_v1"
    assert detail["operationId"] == "get_contract_detail_v1"
    assert set(listing["responses"]) == {"200", "401", "403", "422", "503"}
    assert set(detail["responses"]) == {"200", "401", "403", "404", "422", "503"}


def test_contract_reads_require_financial_read_without_calling_service(
    client: tuple[TestClient, Mock, Mock],
) -> None:
    test_client, query, auth = client
    actor = AuthenticatedActor(USER, ORG, SESSION, ("audit_reviewer",), ("audits.read",))
    current_user = CurrentUserData(
        id=USER,
        display_name="reviewer",
        roles=("audit_reviewer",),
        permissions=("audits.read",),
    )
    auth.authenticate.return_value = (actor, current_user)

    listing = test_client.get("/api/v1/contracts", headers={"Authorization": "Bearer token"})
    detail = test_client.get(
        f"/api/v1/contracts/{CONTRACT}", headers={"Authorization": "Bearer token"}
    )

    assert listing.status_code == detail.status_code == 403
    assert listing.json()["code"] == detail.json()["code"] == "AUTH_FORBIDDEN"
    query.list_page.assert_not_called()
    query.get_detail.assert_not_called()


def test_contract_projection_validation_error_is_redacted(
    client: tuple[TestClient, Mock, Mock],
) -> None:
    test_client, query, _ = client
    with pytest.raises(ValidationError) as captured:
        ContractListData(items=(), page_size=1, next_cursor="projection_sentinel")
    query.list_page.side_effect = captured.value

    response = test_client.get("/api/v1/contracts", headers={"Authorization": "Bearer token"})

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "projection_sentinel" not in response.text
