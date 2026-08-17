from collections.abc import Iterator
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import ANY, Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.contract_invoice_management import (
    get_contract_invoice_management_service,
)
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import ContractListItemData, ContractStatus
from app.schemas.invoices import (
    ContractInvoiceCandidateData,
    ContractInvoiceCandidateListData,
    ContractInvoiceHistoryData,
    ContractInvoiceLinkData,
    ContractInvoiceMatchReasonData,
    ContractInvoiceMatchReasonsData,
    ContractInvoiceMutationData,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.contract_invoice_management import (
    ContractInvoiceManagementService,
    ContractInvoiceMutationResult,
)
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("69000000-0000-4000-8000-000000000001")
USER_ID = UUID("69000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("69000000-0000-4000-8000-000000000003")
INVOICE_ID = UUID("69000000-0000-4000-8000-000000000004")
CONTRACT_ID = UUID("69000000-0000-4000-8000-000000000005")
RELATION_ID = UUID("69000000-0000-4000-8000-000000000006")
NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


def _match_reasons() -> ContractInvoiceMatchReasonsData:
    return ContractInvoiceMatchReasonsData(
        tax_no=ContractInvoiceMatchReasonData(
            status="matched",
            code="tax_no_matched",
        ),
        name=ContractInvoiceMatchReasonData(
            status="mismatched",
            code="name_mismatched",
        ),
        date=ContractInvoiceMatchReasonData(
            status="unavailable",
            code="date_unavailable",
        ),
    )


def _link(status: str = "suggested") -> ContractInvoiceLinkData:
    return ContractInvoiceLinkData.model_validate(
        {
            "id": RELATION_ID,
            "contract_id": CONTRACT_ID,
            "status": status,
            "match_reasons": _match_reasons(),
            "suggested_at": NOW,
            "confirmed_at": NOW if status == "confirmed_primary" else None,
            "cancelled_at": NOW if status == "cancelled" else None,
            "cancel_reason": "业务取消" if status == "cancelled" else None,
            "row_version": "2" if status != "suggested" else "1",
        }
    )


@pytest.fixture
def auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("contract_admin", "finance_reviewer"),
        ("financial.read", "links.manage_primary", "links.suggest"),
    )
    current = CurrentUserData(
        id=USER_ID,
        display_name="合同发票复核员",
        roles=("contract_admin", "finance_reviewer"),
        permissions=("financial.read", "links.manage_primary", "links.suggest"),
    )
    service.authenticate.return_value = (actor, current)
    return service


@pytest.fixture
def management_service() -> Mock:
    service = Mock(spec=ContractInvoiceManagementService)
    candidate = ContractInvoiceCandidateData(
        contract=ContractListItemData(
            id=CONTRACT_ID,
            contract_no="HT-001",
            name="采购合同",
            party_b_name="供应方",
            amount="1000.00",
            currency="CNY",
            effective_date=date(2026, 1, 1),
            expiry_date=None,
            confirmation_status=ConfirmationStatus.CONFIRMED,
            status=ContractStatus.ACTIVE,
        ),
        match_reasons=_match_reasons(),
    )
    service.list_candidates.return_value = ContractInvoiceCandidateListData(
        invoice_id=INVOICE_ID,
        invoice_row_version="1",
        items=(candidate,),
    )
    service.get_history.return_value = ContractInvoiceHistoryData(
        invoice_id=INVOICE_ID,
        items=(_link(),),
    )
    mutation = ContractInvoiceMutationResult(
        data=ContractInvoiceMutationData(
            invoice_id=INVOICE_ID,
            invoice_row_version="2",
            relation=_link(),
            previous_primary_relation_id=None,
        ),
        replayed=False,
    )
    service.suggest.return_value = mutation
    service.set_primary.return_value = mutation
    service.cancel_primary.return_value = mutation
    return service


@pytest.fixture
def application(
    exact_policy_file: Path,
    auth_service: Mock,
    management_service: Mock,
) -> FastAPI:
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_contract_invoice_management_service] = lambda: management_service
    return app


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_contract_candidates_are_actor_scoped_explainable_and_private(
    client: TestClient,
    management_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/contract-candidates",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    management_service.list_candidates.assert_called_once_with(ORGANIZATION_ID, INVOICE_ID)
    data = response.json()["data"]
    assert data["invoice_row_version"] == "1"
    assert data["items"][0]["match_reasons"] == {
        "tax_no": {"status": "matched", "code": "tax_no_matched"},
        "name": {"status": "mismatched", "code": "name_mismatched"},
        "date": {"status": "unavailable", "code": "date_unavailable"},
    }
    assert "score" not in response.text


def test_contract_link_history_is_private_and_stably_projected(
    client: TestClient,
    management_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/invoices/{INVOICE_ID}/contract-link-history",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    management_service.get_history.assert_called_once_with(ORGANIZATION_ID, INVOICE_ID)
    assert response.json()["data"]["items"][0]["id"] == str(RELATION_ID)
    assert str(USER_ID) not in response.text


@pytest.mark.parametrize(
    ("method", "suffix", "body", "service_method"),
    [
        (
            "post",
            "contract-link-suggestions",
            {
                "contract_id": str(CONTRACT_ID),
                "invoice_row_version": "1",
                "reason": "人工建议",
            },
            "suggest",
        ),
        (
            "put",
            "primary-contract",
            {
                "suggestion_id": str(RELATION_ID),
                "invoice_row_version": "1",
                "relation_row_version": "1",
                "reason": "确认主合同",
            },
            "set_primary",
        ),
        (
            "post",
            "primary-contract/cancel",
            {
                "invoice_row_version": "1",
                "relation_row_version": "1",
                "reason": "业务取消",
            },
            "cancel_primary",
        ),
    ],
)
def test_contract_link_writes_freeze_idempotent_private_envelope(
    client: TestClient,
    management_service: Mock,
    method: str,
    suffix: str,
    body: dict[str, object],
    service_method: str,
) -> None:
    response = client.request(
        method,
        f"/api/v1/invoices/{INVOICE_ID}/{suffix}",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": f"link-{service_method}-001",
        },
        json=body,
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["idempotency-replayed"] == "false"
    assert response.json()["data"]["relation"]["id"] == str(RELATION_ID)
    getattr(management_service, service_method).assert_called_once_with(
        ANY,
        INVOICE_ID,
        ANY,
        f"link-{service_method}-001",
        ANY,
    )


def test_contract_link_writes_reject_unknown_input_before_service(
    client: TestClient,
    management_service: Mock,
) -> None:
    response = client.post(
        f"/api/v1/invoices/{INVOICE_ID}/contract-link-suggestions?unexpected=true",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "link-invalid-001",
        },
        json={
            "contract_id": str(CONTRACT_ID),
            "invoice_row_version": "1",
            "reason": "人工建议",
            "match_reasons": {"client": "forbidden"},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    management_service.suggest.assert_not_called()


def test_contract_admin_cannot_confirm_primary(
    client: TestClient,
    auth_service: Mock,
    management_service: Mock,
) -> None:
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("contract_admin",),
        ("financial.read", "links.suggest"),
    )
    auth_service.authenticate.return_value = (actor, auth_service.authenticate.return_value[1])

    response = client.put(
        f"/api/v1/invoices/{INVOICE_ID}/primary-contract",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "link-forbidden-001",
        },
        json={
            "suggestion_id": str(RELATION_ID),
            "invoice_row_version": "1",
            "relation_row_version": "1",
            "reason": "越权确认",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    management_service.set_primary.assert_not_called()


def test_match_reason_schema_rejects_status_code_mismatch() -> None:
    with pytest.raises(ValidationError, match="incompatible"):
        ContractInvoiceMatchReasonsData(
            tax_no=ContractInvoiceMatchReasonData(
                status="matched",
                code="tax_no_mismatched",
            ),
            name=ContractInvoiceMatchReasonData(status="matched", code="name_matched"),
            date=ContractInvoiceMatchReasonData(status="matched", code="date_in_range"),
        )


def test_contract_link_openapi_freezes_operations(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    base = "/api/v1/invoices/{invoice_id}"
    expected = {
        f"{base}/contract-candidates": ("get", "list_invoice_contract_candidates_v1"),
        f"{base}/contract-link-suggestions": (
            "post",
            "suggest_invoice_contract_link_v1",
        ),
        f"{base}/contract-link-history": ("get", "get_invoice_contract_link_history_v1"),
        f"{base}/primary-contract": ("put", "set_invoice_primary_contract_v1"),
        f"{base}/primary-contract/cancel": (
            "post",
            "cancel_invoice_primary_contract_v1",
        ),
    }
    for path, (method, operation_id) in expected.items():
        assert paths[path][method]["operationId"] == operation_id
    for path, method in (
        (f"{base}/contract-link-suggestions", "post"),
        (f"{base}/primary-contract", "put"),
        (f"{base}/primary-contract/cancel", "post"),
    ):
        operation = paths[path][method]
        assert "Idempotency-Key" in {parameter["name"] for parameter in operation["parameters"]}
        assert set(operation["responses"]) == {
            "200",
            "401",
            "403",
            "404",
            "409",
            "422",
            "503",
        }
