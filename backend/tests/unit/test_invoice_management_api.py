from datetime import date
from pathlib import Path
from unittest.mock import ANY, Mock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.invoice_management import get_invoice_management_service
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.business_statuses import (
    ConfirmationStatus,
    InvoiceDuplicateStatus,
    InvoiceStatus,
)
from app.schemas.invoices import (
    InvoiceCorrectionHistoryData,
    InvoiceDetailData,
    InvoiceEvidenceResponseData,
    InvoiceMutationData,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.invoice_management import InvoiceManagementService, InvoiceMutationResult
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("97000000-0000-4000-8000-000000000001")
USER_ID = UUID("97000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("97000000-0000-4000-8000-000000000003")
INVOICE_ID = UUID("97000000-0000-4000-8000-000000000004")
CANDIDATE_ID = UUID("97000000-0000-4000-8000-000000000005")
BLOCK_ID = UUID("97000000-0000-4000-8000-000000000006")
PARSE_VERSION_ID = UUID("97000000-0000-4000-8000-000000000007")


def _detail() -> InvoiceDetailData:
    return InvoiceDetailData(
        id=INVOICE_ID,
        invoice_code="3100260001",
        invoice_number="00000001",
        invoice_type=None,
        is_red_invoice=False,
        invoice_date=date(2026, 6, 1),
        buyer_name=None,
        buyer_tax_no="91310000MA000001X1",
        seller_name=None,
        seller_tax_no="91310000MA000002X2",
        amount_excluding_tax="56603.77",
        tax_amount="3396.23",
        total_amount="60000.00",
        currency="CNY",
        confirmation_status=ConfirmationStatus.UNCONFIRMED,
        duplicate_status=InvoiceDuplicateStatus.SUSPECTED,
        status=InvoiceStatus.DRAFT,
        row_version="2",
        items=(),
    )


def _auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("finance_reviewer",),
        ("financial.read", "invoices.manage"),
    )
    current = CurrentUserData(
        id=USER_ID,
        display_name="发票复核员",
        roles=("finance_reviewer",),
        permissions=("financial.read", "invoices.manage"),
    )
    service.authenticate.return_value = actor, current
    return service


def _management_service() -> Mock:
    service = Mock(spec=InvoiceManagementService)
    service.get_evidence.return_value = InvoiceEvidenceResponseData(
        invoice_id=INVOICE_ID,
        row_version="1",
        field_evidence=(),
        item_evidence={},
    )
    service.get_history.return_value = InvoiceCorrectionHistoryData(
        invoice_id=INVOICE_ID,
        items=(),
    )
    mutation = InvoiceMutationResult(
        InvoiceMutationData(invoice=_detail(), duplicate_candidate_id=CANDIDATE_ID),
        False,
    )
    service.replace_facts.return_value = mutation
    service.decide.return_value = mutation
    service.check_duplicate.return_value = mutation
    service.decide_duplicate.return_value = mutation
    return service


def _application(policy_file: Path, auth: Mock, management: Mock) -> FastAPI:
    app = create_app(build_startup_settings(policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_invoice_management_service] = lambda: management
    return app


def _facts_body() -> dict[str, object]:
    return {
        "row_version": "1",
        "reason": "人工复核",
        "facts": {
            "invoice_code": "3100260001",
            "invoice_number": "00000001",
            "invoice_type": None,
            "is_red_invoice": False,
            "invoice_date": "2026-06-01",
            "buyer_name": None,
            "buyer_tax_no": "91310000MA000001X1",
            "seller_name": None,
            "seller_tax_no": "91310000MA000002X2",
            "amount_excluding_tax": "56603.77",
            "tax_amount": "3396.23",
            "total_amount": "60000.00",
            "currency": "CNY",
        },
        "field_evidence": [],
        "items": [],
    }


def _facts_body_with_evidence() -> dict[str, object]:
    body = _facts_body()
    body["field_evidence"] = [
        {
            "field_code": "invoice_code",
            "evidence": {
                "block_id": str(BLOCK_ID),
                "parse_version_id": str(PARSE_VERSION_ID),
                "page_no": 1,
                "quote_text": "发票代码: 3100260001",
                "bbox": None,
                "confidence": None,
            },
        }
    ]
    return body


def test_invoice_evidence_and_history_are_private(
    exact_policy_file: Path,
) -> None:
    auth = _auth_service()
    management = _management_service()
    with TestClient(_application(exact_policy_file, auth, management)) as client:
        for suffix in ("evidence", "history"):
            response = client.get(
                f"/api/v1/invoices/{INVOICE_ID}/{suffix}",
                headers={"Authorization": "Bearer token"},
            )
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "private, no-store"
    management.get_evidence.assert_called_once_with(ORGANIZATION_ID, INVOICE_ID)
    management.get_history.assert_called_once_with(ORGANIZATION_ID, INVOICE_ID)


def test_invoice_writes_are_idempotent_private_and_actor_scoped(
    exact_policy_file: Path,
) -> None:
    auth = _auth_service()
    management = _management_service()
    cases = (
        ("put", "facts", _facts_body(), "replace_facts"),
        (
            "post",
            "decision",
            {"row_version": "1", "decision": "confirmed", "reason": "证据一致"},
            "decide",
        ),
        (
            "post",
            "duplicate-check",
            {"row_version": "1", "reason": "重新检测"},
            "check_duplicate",
        ),
        (
            "post",
            "duplicate-decision",
            {
                "row_version": "1",
                "candidate_id": str(CANDIDATE_ID),
                "decision": "confirmed_duplicate",
                "reason": "人工核对",
            },
            "decide_duplicate",
        ),
    )
    with TestClient(_application(exact_policy_file, auth, management)) as client:
        for index, (method, suffix, body, service_method) in enumerate(cases):
            key = f"invoice-write-{index:02d}"
            response = client.request(
                method,
                f"/api/v1/invoices/{INVOICE_ID}/{suffix}",
                headers={"Authorization": "Bearer token", "Idempotency-Key": key},
                json=body,
            )
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["idempotency-replayed"] == "false"
            assert response.json()["data"]["invoice"]["id"] == str(INVOICE_ID)
            getattr(management, service_method).assert_called_once_with(
                ANY,
                INVOICE_ID,
                ANY,
                key,
                ANY,
            )


def test_invoice_write_forbidden_and_unknown_body_fail_before_service(
    exact_policy_file: Path,
) -> None:
    auth = _auth_service()
    management = _management_service()
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("audit_reviewer",),
        ("financial.read",),
    )
    auth.authenticate.return_value = actor, auth.authenticate.return_value[1]
    with TestClient(_application(exact_policy_file, auth, management)) as client:
        forbidden = client.post(
            f"/api/v1/invoices/{INVOICE_ID}/duplicate-check",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "invoice-forbidden-01",
            },
            json={"row_version": "1", "reason": "越权检测"},
        )
        assert forbidden.status_code == 403

        auth.authenticate.return_value = _auth_service().authenticate.return_value
        invalid = client.put(
            f"/api/v1/invoices/{INVOICE_ID}/facts",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "invoice-invalid-001",
            },
            json={**_facts_body(), "unexpected": True},
        )
        assert invalid.status_code == 422
    management.check_duplicate.assert_not_called()
    management.replace_facts.assert_not_called()


def test_invoice_facts_write_accepts_canonical_evidence_uuids_from_json(
    exact_policy_file: Path,
) -> None:
    auth = _auth_service()
    management = _management_service()
    with TestClient(_application(exact_policy_file, auth, management)) as client:
        response = client.put(
            f"/api/v1/invoices/{INVOICE_ID}/facts",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "invoice-evidence-uuid-01",
            },
            json=_facts_body_with_evidence(),
        )

    assert response.status_code == 200, response.text
    payload = management.replace_facts.call_args.args[2]
    evidence = payload.field_evidence[0].evidence
    assert evidence.block_id == BLOCK_ID
    assert evidence.parse_version_id == PARSE_VERSION_ID


def test_invoice_management_openapi_freezes_all_operations(exact_policy_file: Path) -> None:
    app = _application(exact_policy_file, _auth_service(), _management_service())
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
    base = "/api/v1/invoices/{invoice_id}"
    expected = {
        f"{base}/evidence": ("get", "get_invoice_evidence_v1"),
        f"{base}/history": ("get", "get_invoice_correction_history_v1"),
        f"{base}/facts": ("put", "replace_invoice_facts_v1"),
        f"{base}/decision": ("post", "decide_invoice_v1"),
        f"{base}/duplicate-check": ("post", "check_invoice_duplicate_v1"),
        f"{base}/duplicate-decision": ("post", "decide_invoice_duplicate_v1"),
    }
    for path, (method, operation_id) in expected.items():
        assert paths[path][method]["operationId"] == operation_id
    for path, (method, _) in tuple(expected.items())[2:]:
        assert "Idempotency-Key" in {
            parameter["name"] for parameter in paths[path][method]["parameters"]
        }
