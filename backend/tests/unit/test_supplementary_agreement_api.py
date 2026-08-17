from collections.abc import Iterator
from datetime import date
from pathlib import Path
from unittest.mock import ANY, Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.supplementary_agreement_management import (
    get_supplementary_agreement_management_service,
)
from app.api.dependencies.supplementary_agreements import (
    get_supplementary_agreement_query_service,
)
from app.bootstrap import create_app
from app.core.errors import AppError
from app.schemas.auth import CurrentUserData
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import (
    SupplementaryAgreementChangeData,
    SupplementaryAgreementDetailData,
    SupplementaryAgreementHeaderData,
    SupplementaryAgreementHeaderListData,
    SupplementaryAgreementStatus,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.supplementary_agreement_management import (
    SupplementaryAgreementManagementService,
    SupplementaryAgreementMutationResult,
)
from app.services.supplementary_agreement_query import SupplementaryAgreementQueryService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("68000000-0000-4000-8000-000000000001")
USER_ID = UUID("68000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("68000000-0000-4000-8000-000000000003")
CONTRACT_ID = UUID("68000000-0000-4000-8000-000000000004")
AGREEMENT_ID = UUID("68000000-0000-4000-8000-000000000005")
EVIDENCE_BLOCK_ID = UUID("68000000-0000-4000-8000-000000000006")


@pytest.fixture
def auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("contract_admin",),
        ("contracts.manage", "financial.read"),
    )
    current = CurrentUserData(
        id=USER_ID,
        display_name="合同管理员",
        roles=("contract_admin",),
        permissions=("contracts.manage", "financial.read"),
    )
    service.authenticate.return_value = (actor, current)
    return service


@pytest.fixture
def query_service() -> Mock:
    service = Mock(spec=SupplementaryAgreementQueryService)
    service.list_headers.return_value = SupplementaryAgreementHeaderListData(
        items=(
            SupplementaryAgreementHeaderData(
                id=AGREEMENT_ID,
                agreement_no="S-001",
                name="补充协议 Header",
                signed_date=None,
                effective_date=date(2026, 2, 1),
                status=SupplementaryAgreementStatus.DRAFT,
                confirmation_status=ConfirmationStatus.UNCONFIRMED,
            ),
        ),
        page_size=1,
        next_cursor="next_cursor_v1",
    )
    return service


def _detail(
    *,
    status: SupplementaryAgreementStatus = SupplementaryAgreementStatus.PENDING_CONFIRMATION,
    confirmation_status: ConfirmationStatus = ConfirmationStatus.UNCONFIRMED,
    row_version: str = "2",
) -> SupplementaryAgreementDetailData:
    return SupplementaryAgreementDetailData(
        id=AGREEMENT_ID,
        contract_id=CONTRACT_ID,
        agreement_no="S-001",
        name="补充协议",
        signed_date=None,
        effective_date=date(2026, 2, 1),
        status=status,
        confirmation_status=confirmation_status,
        changes=(
            SupplementaryAgreementChangeData(
                id=UUID("68000000-0000-4000-8000-000000000007"),
                field_code="amount",
                value_type="number",
                old_value="100.00",
                new_value="120.00",
                evidence_block_id=EVIDENCE_BLOCK_ID,
                page_no=1,
                quote_text="合同金额调整为 120.00 元",
                bbox=None,
                confirmation_status=confirmation_status,
            ),
        ),
        row_version=row_version,
    )


@pytest.fixture
def management_service() -> Mock:
    service = Mock(spec=SupplementaryAgreementManagementService)
    service.get_detail.return_value = _detail()
    service.replace_changes.return_value = SupplementaryAgreementMutationResult(
        data=_detail(), replayed=False
    )
    service.decide.return_value = SupplementaryAgreementMutationResult(
        data=_detail(
            status=SupplementaryAgreementStatus.CONFIRMED,
            confirmation_status=ConfirmationStatus.CONFIRMED,
            row_version="3",
        ),
        replayed=False,
    )
    return service


@pytest.fixture
def application(
    exact_policy_file: Path,
    auth_service: Mock,
    query_service: Mock,
    management_service: Mock,
) -> FastAPI:
    app = create_app(build_startup_settings(exact_policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_supplementary_agreement_query_service] = lambda: query_service
    app.dependency_overrides[get_supplementary_agreement_management_service] = lambda: (
        management_service
    )
    return app


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application) as test_client:
        yield test_client


def test_header_list_is_actor_scoped_exact_and_private(
    client: TestClient,
    query_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements?page_size=1",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    query_service.list_headers.assert_called_once_with(
        ORGANIZATION_ID,
        CONTRACT_ID,
        None,
        1,
    )
    assert response.json()["data"] == {
        "items": [
            {
                "id": str(AGREEMENT_ID),
                "agreement_no": "S-001",
                "name": "补充协议 Header",
                "signed_date": None,
                "effective_date": "2026-02-01",
                "status": "draft",
                "confirmation_status": "unconfirmed",
            }
        ],
        "page_size": 1,
        "next_cursor": "next_cursor_v1",
    }


def test_header_list_returns_empty_page_for_visible_contract(
    client: TestClient,
    query_service: Mock,
) -> None:
    query_service.list_headers.return_value = SupplementaryAgreementHeaderListData(
        items=(), page_size=20, next_cursor=None
    )

    response = client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "items": [],
        "page_size": 20,
        "next_cursor": None,
    }


@pytest.mark.parametrize(
    "query",
    ["page=1", "status=confirmed", "page_size=0", "cursor=abc%3D"],
)
def test_header_list_rejects_unknown_or_invalid_query(
    client: TestClient,
    query_service: Mock,
    query: str,
) -> None:
    response = client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements?{query}",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    query_service.list_headers.assert_not_called()


@pytest.mark.parametrize(
    "contract_id",
    ["A8000000-0000-4000-8000-000000000004", CONTRACT_ID.hex, "{" + str(CONTRACT_ID) + "}"],
)
def test_header_list_rejects_noncanonical_contract_uuid(
    client: TestClient,
    query_service: Mock,
    contract_id: str,
) -> None:
    response = client.get(
        f"/api/v1/contracts/{contract_id}/supplementary-agreements",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422
    query_service.list_headers.assert_not_called()


def test_header_list_requires_bearer_authentication(
    client: TestClient,
    query_service: Mock,
) -> None:
    response = client.get(f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements")

    assert response.status_code == 401
    query_service.list_headers.assert_not_called()


def test_header_list_requires_financial_read_before_service(
    client: TestClient,
    auth_service: Mock,
    query_service: Mock,
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
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    query_service.list_headers.assert_not_called()


def test_header_list_preserves_non_enumerating_parent_not_found(
    client: TestClient,
    query_service: Mock,
) -> None:
    query_service.list_headers.side_effect = AppError(
        status_code=404,
        code="RESOURCE_NOT_FOUND",
        message="目标资源不存在或不可见",
    )

    response = client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


def test_header_list_reports_unconfigured_service(application: FastAPI) -> None:
    application.dependency_overrides.pop(get_supplementary_agreement_query_service)
    with TestClient(application) as client:
        response = client.get(
            f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements",
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "FINANCIAL_NOT_CONFIGURED"


def test_header_list_redacts_invalid_public_projection(
    application: FastAPI,
    query_service: Mock,
) -> None:
    with pytest.raises(ValidationError) as captured:
        SupplementaryAgreementHeaderListData(items=(), page_size=1, next_cursor="private_sentinel")
    query_service.list_headers.side_effect = captured.value
    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements",
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "private_sentinel" not in response.text


def test_header_list_openapi_freezes_operation(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/api/v1/contracts/{contract_id}/supplementary-agreements"
    ]["get"]

    assert operation["operationId"] == "list_supplementary_agreement_headers_v1"
    assert operation["summary"] == "读取补充协议 Header 列表"
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "contract_id",
        "cursor",
        "page_size",
    ]
    assert "不计算生效" in operation["description"]
    assert set(operation["responses"]) == {"200", "401", "403", "404", "422", "503"}


def test_supplementary_detail_is_private_and_actor_scoped(
    client: TestClient,
    management_service: Mock,
) -> None:
    response = client.get(
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/{AGREEMENT_ID}",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["data"] == _detail().model_dump(mode="json")
    management_service.get_detail.assert_called_once_with(ANY, CONTRACT_ID, AGREEMENT_ID)


def test_replace_changes_is_strict_idempotent_and_exact(
    client: TestClient,
    management_service: Mock,
) -> None:
    response = client.put(
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/{AGREEMENT_ID}/changes",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "supplementary-replace-01",
        },
        json={
            "row_version": "1",
            "reason": "按已核对原文替换字段",
            "changes": [
                {
                    "field_code": "amount",
                    "value_type": "number",
                    "new_value": "120.00",
                    "evidence_block_id": str(EVIDENCE_BLOCK_ID),
                    "page_no": 1,
                    "quote_text": "合同金额调整为 120.00 元",
                    "bbox": None,
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["idempotency-replayed"] == "false"
    management_service.replace_changes.assert_called_once_with(
        ANY,
        CONTRACT_ID,
        AGREEMENT_ID,
        ANY,
        "supplementary-replace-01",
        ANY,
    )


def test_decision_is_strict_idempotent_and_exact(
    client: TestClient,
    management_service: Mock,
) -> None:
    response = client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/{AGREEMENT_ID}/decision",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "supplementary-decision-01",
        },
        json={"row_version": "2", "decision": "confirmed", "reason": "证据已复核"},
    )

    assert response.status_code == 200
    assert response.headers["idempotency-replayed"] == "false"
    assert response.json()["data"]["confirmation_status"] == "confirmed"
    management_service.decide.assert_called_once_with(
        ANY,
        CONTRACT_ID,
        AGREEMENT_ID,
        ANY,
        "supplementary-decision-01",
        ANY,
    )


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        (
            "put",
            "/changes?unexpected=true",
            {
                "row_version": "1",
                "reason": "字段替换",
                "changes": [
                    {
                        "field_code": "amount",
                        "value_type": "number",
                        "new_value": "120.00",
                        "evidence_block_id": None,
                        "page_no": None,
                        "quote_text": None,
                        "bbox": None,
                    }
                ],
            },
        ),
        (
            "put",
            "/changes",
            {
                "row_version": "1",
                "reason": "字段替换",
                "changes": [
                    {
                        "field_code": "amount",
                        "value_type": "number",
                        "new_value": 120.0,
                        "evidence_block_id": None,
                        "page_no": None,
                        "quote_text": None,
                        "bbox": None,
                    }
                ],
            },
        ),
        (
            "put",
            "/changes",
            {
                "row_version": "1",
                "reason": "字段替换",
                "changes": [
                    {
                        "field_code": "amount",
                        "value_type": "number",
                        "new_value": "120.00",
                        "evidence_block_id": None,
                        "page_no": None,
                        "quote_text": None,
                        "bbox": {"x": 1},
                    }
                ],
            },
        ),
        (
            "post",
            "/decision",
            {"row_version": "2", "decision": "accepted", "reason": "无效决定"},
        ),
    ],
)
def test_supplementary_writes_reject_unknown_or_invalid_input(
    client: TestClient,
    management_service: Mock,
    method: str,
    suffix: str,
    body: dict[str, object],
) -> None:
    response = client.request(
        method,
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/{AGREEMENT_ID}{suffix}",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "supplementary-invalid-01",
        },
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    management_service.replace_changes.assert_not_called()
    management_service.decide.assert_not_called()


def test_supplementary_write_requires_contracts_manage(
    client: TestClient,
    auth_service: Mock,
    management_service: Mock,
) -> None:
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("read_only",),
        ("financial.read",),
    )
    auth_service.authenticate.return_value = (actor, auth_service.authenticate.return_value[1])
    response = client.post(
        f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements/{AGREEMENT_ID}/decision",
        headers={
            "Authorization": "Bearer token",
            "Idempotency-Key": "supplementary-forbidden-01",
        },
        json={"row_version": "2", "decision": "confirmed", "reason": "证据已复核"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"
    management_service.decide.assert_not_called()


def test_supplementary_write_openapi_freezes_operations(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    detail_path = "/api/v1/contracts/{contract_id}/supplementary-agreements/{agreement_id}"
    changes_path = f"{detail_path}/changes"
    decision_path = f"{detail_path}/decision"

    assert paths[detail_path]["get"]["operationId"] == "get_supplementary_agreement_detail_v1"
    assert paths[changes_path]["put"]["operationId"] == (
        "replace_supplementary_agreement_changes_v1"
    )
    assert paths[decision_path]["post"]["operationId"] == "decide_supplementary_agreement_v1"
    for operation in (paths[changes_path]["put"], paths[decision_path]["post"]):
        assert "Idempotency-Key" in {parameter["name"] for parameter in operation["parameters"]}
        assert set(operation["responses"]) == {"200", "401", "403", "404", "409", "422", "503"}
