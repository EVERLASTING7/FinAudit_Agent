from collections.abc import Iterator
from datetime import date
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.effective_contracts import get_effective_contract_query_service
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import EffectiveContractData, EffectiveContractFieldData
from app.services.auth import AuthenticatedActor, AuthService
from app.services.effective_contract_query import EffectiveContractQueryService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORG = UUID("6b000000-0000-4000-8000-000000000001")
USER = UUID("6b000000-0000-4000-8000-000000000002")
SESSION = UUID("6b000000-0000-4000-8000-000000000003")
CONTRACT = UUID("6b000000-0000-4000-8000-000000000004")


@pytest.fixture
def client(exact_policy_file: Path) -> Iterator[tuple[TestClient, Mock, Mock]]:
    auth = Mock(spec=AuthService)
    auth.authenticate.return_value = (
        AuthenticatedActor(USER, ORG, SESSION, ("contract_admin",), ("financial.read",)),
        CurrentUserData(
            id=USER,
            display_name="合同管理员",
            roles=("contract_admin",),
            permissions=("financial.read",),
        ),
    )
    service = Mock(spec=EffectiveContractQueryService)
    service.get_effective_contract.return_value = EffectiveContractData(
        id=CONTRACT,
        baseline_date=date(2026, 12, 1),
        confirmation_status=ConfirmationStatus.CONFIRMED,
        fields=(
            EffectiveContractFieldData(
                field_code="amount",
                value_type="number",
                original_value="100.00",
                effective_value="120.00",
                source_agreement_id=UUID("6b000000-0000-4000-8000-000000000005"),
                source_effective_date=date(2026, 12, 1),
            ),
        ),
        applied_agreement_ids=(UUID("6b000000-0000-4000-8000-000000000005"),),
        row_version="2",
    )
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_effective_contract_query_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client, service, auth


def test_effective_contract_endpoint_is_strict_private_and_scoped(
    client: tuple[TestClient, Mock, Mock],
) -> None:
    test_client, service, _ = client
    response = test_client.get(
        f"/api/v1/contracts/{CONTRACT}/effective-fields?baseline_date=2026-12-01",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["data"]["fields"][0] == {
        "field_code": "amount",
        "value_type": "number",
        "original_value": "100.00",
        "effective_value": "120.00",
        "source_agreement_id": "6b000000-0000-4000-8000-000000000005",
        "source_effective_date": "2026-12-01",
    }
    service.get_effective_contract.assert_called_once_with(
        ORG,
        CONTRACT,
        date(2026, 12, 1),
    )


@pytest.mark.parametrize(
    "suffix",
    ["", "?baseline_date=2026-12-1", "?baseline_date=2026-12-01&extra=1"],
)
def test_effective_contract_endpoint_rejects_invalid_query(
    client: tuple[TestClient, Mock, Mock], suffix: str
) -> None:
    response = client[0].get(
        f"/api/v1/contracts/{CONTRACT}/effective-fields{suffix}",
        headers={"Authorization": "Bearer token"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    client[1].get_effective_contract.assert_not_called()


def test_effective_contract_endpoint_requires_financial_read(
    client: tuple[TestClient, Mock, Mock],
) -> None:
    test_client, service, auth = client
    auth.authenticate.return_value = (
        AuthenticatedActor(USER, ORG, SESSION, ("read_only",), ("audits.read",)),
        CurrentUserData(
            id=USER,
            display_name="只读用户",
            roles=("read_only",),
            permissions=("audits.read",),
        ),
    )
    response = test_client.get(
        f"/api/v1/contracts/{CONTRACT}/effective-fields?baseline_date=2026-12-01",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    service.get_effective_contract.assert_not_called()


def test_effective_contract_openapi_contract(client: tuple[TestClient, Mock, Mock]) -> None:
    operation = (
        client[0]
        .get("/openapi.json")
        .json()["paths"]["/api/v1/contracts/{contract_id}/effective-fields"]["get"]
    )
    assert operation["operationId"] == "get_effective_contract_fields_v1"
    assert set(operation["responses"]) == {"200", "401", "403", "404", "409", "422", "503"}
