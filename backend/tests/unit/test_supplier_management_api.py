from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import ANY, Mock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.suppliers import get_supplier_management_service
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.suppliers import (
    SupplierData,
    SupplierListData,
    SupplierMutationData,
    SupplierResolveData,
    SupplierSourceType,
    SupplierStatus,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.supplier_management import (
    SupplierManagementService,
    SupplierMutationResult,
    SupplierResolveResult,
)
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("9a000000-0000-4000-8000-000000000001")
USER_ID = UUID("9a000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("9a000000-0000-4000-8000-000000000003")
SUPPLIER_ID = UUID("9a000000-0000-4000-8000-000000000004")
SOURCE_ID = UUID("9a000000-0000-4000-8000-000000000005")
CORRECTION_ID = UUID("9a000000-0000-4000-8000-000000000006")


def _supplier(*, active: bool = False) -> SupplierData:
    return SupplierData(
        id=SUPPLIER_ID,
        standard_name="示例供应商",
        tax_number="Tax-01",
        source_type=SupplierSourceType.CONTRACT,
        source_contract_id=SOURCE_ID,
        source_invoice_id=None,
        confirmation_status=(
            ConfirmationStatus.CONFIRMED if active else ConfirmationStatus.UNCONFIRMED
        ),
        status=SupplierStatus.ACTIVE if active else SupplierStatus.CANDIDATE,
        confirmed_by=USER_ID if active else None,
        confirmed_at=datetime(2026, 8, 14, tzinfo=timezone.utc) if active else None,
        row_version="2" if active else "1",
    )


def _auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("contract_admin",),
        ("financial.read", "suppliers.correct"),
    )
    current = CurrentUserData(
        id=USER_ID,
        display_name="合同管理员",
        roles=("contract_admin",),
        permissions=("financial.read", "suppliers.correct"),
    )
    service.authenticate.return_value = actor, current
    return service


def _supplier_service() -> Mock:
    service = Mock(spec=SupplierManagementService)
    service.list_page.return_value = SupplierListData(
        items=(_supplier(),),
        page_size=20,
        next_cursor=None,
    )
    service.get_detail.return_value = _supplier()
    service.resolve_source.return_value = SupplierResolveResult(
        SupplierResolveData(
            supplier=_supplier(),
            source_row_version="7",
            created=True,
            reused=False,
        ),
        False,
    )
    service.update_candidate.return_value = SupplierMutationResult(
        SupplierMutationData(
            supplier=_supplier(active=True),
            candidate_id=SUPPLIER_ID,
            candidate_row_version="2",
            source_row_version="8",
            correction_id=CORRECTION_ID,
            reused=False,
        ),
        False,
    )
    return service


def _application(policy_file: Path, auth: Mock, suppliers: Mock) -> FastAPI:
    app = create_app(build_startup_settings(policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_supplier_management_service] = lambda: suppliers
    return app


def test_supplier_reads_are_private_and_actor_scoped(exact_policy_file: Path) -> None:
    auth = _auth_service()
    suppliers = _supplier_service()
    with TestClient(_application(exact_policy_file, auth, suppliers)) as client:
        listing = client.get(
            "/api/v1/suppliers?page_size=20",
            headers={"Authorization": "Bearer token"},
        )
        detail = client.get(
            f"/api/v1/suppliers/{SUPPLIER_ID}",
            headers={"Authorization": "Bearer token"},
        )
    assert listing.status_code == 200, listing.text
    assert detail.status_code == 200, detail.text
    assert listing.headers["cache-control"] == "private, no-store"
    assert detail.headers["cache-control"] == "private, no-store"
    assert detail.json()["data"]["tax_number"] == "Tax-01"
    suppliers.list_page.assert_called_once_with(ORGANIZATION_ID, None, 20)
    suppliers.get_detail.assert_called_once_with(ORGANIZATION_ID, SUPPLIER_ID)


def test_supplier_resolve_and_update_are_idempotent(exact_policy_file: Path) -> None:
    auth = _auth_service()
    suppliers = _supplier_service()
    with TestClient(_application(exact_policy_file, auth, suppliers)) as client:
        resolved = client.post(
            "/api/v1/suppliers/source-candidates",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "supplier-resolve-01",
            },
            json={
                "source_type": "contract",
                "source_id": str(SOURCE_ID),
                "row_version": "7",
            },
        )
        updated = client.patch(
            f"/api/v1/suppliers/{SUPPLIER_ID}",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "supplier-update-01",
            },
            json={
                "row_version": "1",
                "reason": "人工核对",
                "decision": "confirmed",
            },
        )
    assert resolved.status_code == 200, resolved.text
    assert updated.status_code == 200, updated.text
    assert resolved.headers["idempotency-replayed"] == "false"
    assert updated.headers["idempotency-replayed"] == "false"
    assert updated.json()["data"]["correction_id"] == str(CORRECTION_ID)
    suppliers.resolve_source.assert_called_once_with(
        ANY,
        ANY,
        "supplier-resolve-01",
        ANY,
    )
    suppliers.update_candidate.assert_called_once_with(
        ANY,
        SUPPLIER_ID,
        ANY,
        "supplier-update-01",
        ANY,
    )


def test_supplier_write_forbidden_and_unknown_body_fail_before_service(
    exact_policy_file: Path,
) -> None:
    auth = _auth_service()
    suppliers = _supplier_service()
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("audit_reviewer",),
        ("financial.read",),
    )
    auth.authenticate.return_value = actor, auth.authenticate.return_value[1]
    with TestClient(_application(exact_policy_file, auth, suppliers)) as client:
        forbidden = client.patch(
            f"/api/v1/suppliers/{SUPPLIER_ID}",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "supplier-denied-01",
            },
            json={"row_version": "1", "reason": "越权", "decision": "confirmed"},
        )
        assert forbidden.status_code == 403

        auth.authenticate.return_value = _auth_service().authenticate.return_value
        invalid = client.post(
            "/api/v1/suppliers/source-candidates",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "supplier-invalid-01",
            },
            json={
                "source_type": "contract",
                "source_id": str(SOURCE_ID),
                "row_version": "1",
                "unknown": True,
            },
        )
        assert invalid.status_code == 422
    suppliers.update_candidate.assert_not_called()
    suppliers.resolve_source.assert_not_called()


def test_supplier_openapi_freezes_operations(exact_policy_file: Path) -> None:
    app = _application(exact_policy_file, _auth_service(), _supplier_service())
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/v1/suppliers": ("get", "list_suppliers_v1"),
        "/api/v1/suppliers/source-candidates": (
            "post",
            "resolve_supplier_source_candidate_v1",
        ),
        "/api/v1/suppliers/{supplier_id}": ("patch", "update_supplier_candidate_v1"),
    }
    for path, (method, operation_id) in expected.items():
        assert paths[path][method]["operationId"] == operation_id
    assert paths["/api/v1/suppliers/{supplier_id}"]["get"]["operationId"] == "get_supplier_v1"
    for path, (method, _) in tuple(expected.items())[1:]:
        assert "Idempotency-Key" in {
            parameter["name"] for parameter in paths[path][method]["parameters"]
        }
