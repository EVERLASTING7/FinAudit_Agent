from pathlib import Path
from typing import cast
from unittest.mock import ANY, Mock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.contract_management import get_contract_management_service
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.business_statuses import ConfirmationStatus
from app.schemas.contracts import (
    CONTRACT_CORE_FIELD_CODES,
    ContractCorrectionHistoryData,
    ContractDetailData,
    ContractEvidenceResponseData,
    ContractFieldCandidateData,
    ContractMutationData,
    ContractStatus,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.contract_facts import CONTRACT_FIELD_VALUE_TYPES
from app.services.contract_management import ContractManagementService, ContractMutationResult
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("97000000-0000-4000-8000-000000000101")
USER_ID = UUID("97000000-0000-4000-8000-000000000102")
SESSION_ID = UUID("97000000-0000-4000-8000-000000000103")
CONTRACT_ID = UUID("97000000-0000-4000-8000-000000000104")
FILE_ID = UUID("97000000-0000-4000-8000-000000000105")
BLOCK_ID = UUID("97000000-0000-4000-8000-000000000106")
PARSE_VERSION_ID = UUID("97000000-0000-4000-8000-000000000107")


def _detail() -> ContractDetailData:
    return ContractDetailData(
        id=CONTRACT_ID,
        contract_no=None,
        name="",
        party_a_name=None,
        party_a_tax_no=None,
        party_b_name=None,
        party_b_tax_no=None,
        amount=None,
        currency=None,
        signed_date=None,
        effective_date=None,
        expiry_date=None,
        payment_method=None,
        payment_terms=None,
        confirmation_status=ConfirmationStatus.UNCONFIRMED,
        status=ContractStatus.DRAFT,
        row_version="1",
    )


def _auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("contract_admin",),
        ("financial.read", "contracts.manage"),
    )
    current = CurrentUserData(
        id=USER_ID,
        display_name="合同管理员",
        roles=("contract_admin",),
        permissions=("contracts.manage", "financial.read"),
    )
    service.authenticate.return_value = actor, current
    return service


def _management_service() -> Mock:
    service = Mock(spec=ContractManagementService)
    service.get_evidence.return_value = ContractEvidenceResponseData(
        contract_id=CONTRACT_ID,
        file_id=FILE_ID,
        row_version="1",
        fields=tuple(
            ContractFieldCandidateData(
                field_code=field_code,
                value_type=CONTRACT_FIELD_VALUE_TYPES[field_code],
                candidate_value=None,
                confirmed_value=None,
                confirmation_status=ConfirmationStatus.UNCONFIRMED,
                evidence=None,
            )
            for field_code in CONTRACT_CORE_FIELD_CODES
        ),
    )
    service.get_history.return_value = ContractCorrectionHistoryData(
        contract_id=CONTRACT_ID,
        items=(),
    )
    mutation = ContractMutationResult(ContractMutationData(contract=_detail()), False)
    service.replace_facts.return_value = mutation
    service.decide.return_value = mutation
    return service


def _application(policy_file: Path, auth: Mock, management: Mock) -> FastAPI:
    app = create_app(build_startup_settings(policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_contract_management_service] = lambda: management
    return app


def _empty_facts_body() -> dict[str, object]:
    return {
        "row_version": "1",
        "reason": "人工复核为空候选",
        "facts": {field_code: None for field_code in CONTRACT_CORE_FIELD_CODES},
        "field_evidence": [],
    }


def _evidence_facts_body() -> dict[str, object]:
    body = _empty_facts_body()
    facts = cast(dict[str, object], body["facts"]).copy()
    facts["contract_no"] = "SYNTH-CONTRACT-001"
    body["facts"] = facts
    body["field_evidence"] = [
        {
            "field_code": "contract_no",
            "evidence": {
                "block_id": str(BLOCK_ID),
                "parse_version_id": str(PARSE_VERSION_ID),
                "page_no": 1,
                "quote_text": "合同编号: SYNTH-CONTRACT-001",
                "bbox": None,
                "confidence": None,
            },
        }
    ]
    return body


def test_contract_evidence_history_and_writes_are_private(exact_policy_file: Path) -> None:
    auth = _auth_service()
    management = _management_service()
    with TestClient(_application(exact_policy_file, auth, management)) as client:
        for suffix in ("evidence", "history"):
            response = client.get(
                f"/api/v1/contracts/{CONTRACT_ID}/{suffix}",
                headers={"Authorization": "Bearer token"},
            )
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "private, no-store"

        cases = (
            ("put", "facts", _empty_facts_body(), "replace_facts"),
            (
                "post",
                "decision",
                {"row_version": "1", "decision": "rejected", "reason": "证据不足"},
                "decide",
            ),
        )
        for index, (method, suffix, body, service_method) in enumerate(cases):
            key = f"contract-write-{index:02d}"
            response = client.request(
                method,
                f"/api/v1/contracts/{CONTRACT_ID}/{suffix}",
                headers={"Authorization": "Bearer token", "Idempotency-Key": key},
                json=body,
            )
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["idempotency-replayed"] == "false"
            getattr(management, service_method).assert_called_once_with(
                ANY,
                CONTRACT_ID,
                ANY,
                key,
                ANY,
            )


def test_contract_write_permission_and_schema_fail_closed(exact_policy_file: Path) -> None:
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
            f"/api/v1/contracts/{CONTRACT_ID}/decision",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "contract-forbidden-01",
            },
            json={"row_version": "1", "decision": "confirmed", "reason": "越权"},
        )
        assert forbidden.status_code == 403

        auth.authenticate.return_value = _auth_service().authenticate.return_value
        invalid = client.put(
            f"/api/v1/contracts/{CONTRACT_ID}/facts",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "contract-invalid-001",
            },
            json={**_empty_facts_body(), "unexpected": True},
        )
        assert invalid.status_code == 422
    management.decide.assert_not_called()
    management.replace_facts.assert_not_called()


def test_contract_facts_write_accepts_canonical_evidence_uuids_from_json(
    exact_policy_file: Path,
) -> None:
    auth = _auth_service()
    management = _management_service()
    with TestClient(_application(exact_policy_file, auth, management)) as client:
        response = client.put(
            f"/api/v1/contracts/{CONTRACT_ID}/facts",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "contract-evidence-uuid-01",
            },
            json=_evidence_facts_body(),
        )

    assert response.status_code == 200, response.text
    payload = management.replace_facts.call_args.args[2]
    evidence = payload.field_evidence[0].evidence
    assert evidence.block_id == BLOCK_ID
    assert evidence.parse_version_id == PARSE_VERSION_ID


def test_contract_management_openapi_freezes_operations(exact_policy_file: Path) -> None:
    app = _application(exact_policy_file, _auth_service(), _management_service())
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
    base = "/api/v1/contracts/{contract_id}"
    expected = {
        f"{base}/evidence": ("get", "get_contract_evidence_v1"),
        f"{base}/history": ("get", "get_contract_correction_history_v1"),
        f"{base}/facts": ("put", "replace_contract_facts_v1"),
        f"{base}/decision": ("post", "decide_contract_v1"),
    }
    for path, (method, operation_id) in expected.items():
        assert paths[path][method]["operationId"] == operation_id
    for path, (method, _) in tuple(expected.items())[2:]:
        assert "Idempotency-Key" in {
            parameter["name"] for parameter in paths[path][method]["parameters"]
        }
