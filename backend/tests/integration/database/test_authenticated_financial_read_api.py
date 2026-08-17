from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap import create_app
from app.core.auth_security import hash_password
from app.core.config import Settings
from app.db.session import create_application_engine, create_session_factory
from app.models.auth import Organization, Role, User, UserRole
from app.models.documents import FilePrimaryBusinessObject, FileRecord
from app.models.financial import (
    Contract,
    ContractInvoice,
    Invoice,
    SupplementaryAgreement,
)
from app.repositories.auth import AuthRepository
from app.services.auth import AuthKeyring, AuthService
from app.services.invoice_query import InvoiceQueryService
from app.services.user_query import UserQueryService
from tests.integration.database.test_migrations import (
    configure_disposable_database,
    reset_disposable_database_to_head,
)

pytestmark = pytest.mark.integration

ORGANIZATION_ID = UUID("7a000000-0000-4000-8000-000000000001")
USER_ID = UUID("7a000000-0000-4000-8000-000000000002")
USER_ROLE_ID = UUID("7a000000-0000-4000-8000-000000000003")
ADMIN_USER_ID = UUID("7a000000-0000-4000-8000-000000000008")
ADMIN_USER_ROLE_ID = UUID("7a000000-0000-4000-8000-000000000009")
CONTRACT_ID = UUID("7a000000-0000-4000-8000-000000000004")
INVOICE_ID = UUID("7a000000-0000-4000-8000-000000000005")
DUPLICATE_INVOICE_ID = UUID("7a000000-0000-4000-8000-00000000000a")
AGREEMENT_ID = UUID("7a000000-0000-4000-8000-000000000006")
RELATION_ID = UUID("7a000000-0000-4000-8000-000000000007")
FILE_ID = UUID("7a000000-0000-4000-8000-00000000000b")
FILE_BINDING_ID = UUID("7a000000-0000-4000-8000-00000000000c")
UNKNOWN_CONTRACT_ID = UUID("7a000000-0000-4000-8000-000000000098")
UNKNOWN_INVOICE_ID = UUID("7a000000-0000-4000-8000-000000000099")
USERNAME = "financial.read.integration"
PASSWORD = "Synthetic-Financial-Read-2026!"
ADMIN_USERNAME = "admin.read.integration"
ADMIN_PASSWORD = "Synthetic-Admin-Read-2026!"


def _runtime_settings(database_url: URL) -> Settings:
    policy_file = resources.files("app.ai.artifacts.cr011_v1").joinpath(
        "ai-policy-v1.positive.json"
    )
    return Settings(
        _env_file=None,
        **{
            "app_env": "test",
            "secret_key": "financial-read-integration-signing-key",
            "database_url": database_url.render_as_string(hide_password=False),
            "redis_url": "redis://:test-password@redis:6379/0",
            "celery_broker_url": "redis://:test-password@redis:6379/0",
            "celery_result_backend": "redis://:test-password@redis:6379/1",
            "minio_access_key": "test-minio-access",
            "minio_secret_key": "test-minio-secret",
            "qdrant_collection": "finaudit_policy_chunks_test_e1024_v1",
            "ai_policy_file": str(policy_file),
            "llm_api_key": "test-llm-key",
            "llm_base_url": "http://synthetic-extraction:8000/v1",
            "llm_extraction_model": "synthetic-extraction-model",
            "llm_generation_model": "synthetic-generation-model",
            "llm_fallback_model": "synthetic-fallback-model",
            "embedding_base_url": "http://synthetic-embedding:8003/v1",
            "embedding_api_key": "test-embedding-key",
            "embedding_model": "synthetic-embedding-model",
            "metrics_internal_token": "test-metrics-token",
        },
    )


def _bound_transaction_waits(
    session: Session,
    transaction: object,
    connection: Connection,
) -> None:
    del session, transaction
    connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
    connection.exec_driver_sql("SET LOCAL statement_timeout = '10s'")


def _build_auth_service(factory: sessionmaker[Session]) -> AuthService:
    private_key = Ed25519PrivateKey.generate()
    return AuthService(
        factory,
        AuthKeyring(
            active_kid="financial-read-integration-v1",
            private_key=private_key,
            public_keys={"financial-read-integration-v1": private_key.public_key()},
        ),
        hash_password("Synthetic-Dummy-Password-2026!"),
    )


def _seed_subject_and_financial_facts(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        now = AuthRepository(session).database_now()
        session.add(
            Organization(
                id=ORGANIZATION_ID,
                name="Synthetic financial read organization",
                unified_social_credit_code="SYNTH-FINANCIAL-READ-USCC",
                tax_number="SYNTH-FINANCIAL-READ-TAX",
                status="active",
            )
        )
        session.flush()
        session.add_all(
            [
                User(
                    id=USER_ID,
                    organization_id=ORGANIZATION_ID,
                    username=USERNAME,
                    display_name="Synthetic finance reviewer",
                    password_hash=hash_password(PASSWORD),
                    status="active",
                    password_changed_at=now,
                ),
                User(
                    id=ADMIN_USER_ID,
                    organization_id=ORGANIZATION_ID,
                    username=ADMIN_USERNAME,
                    display_name="Synthetic system administrator",
                    password_hash=hash_password(ADMIN_PASSWORD),
                    status="active",
                    password_changed_at=now,
                ),
            ]
        )
        session.flush()
        finance_role = session.execute(
            select(Role).where(Role.code == "finance_reviewer")
        ).scalar_one()
        admin_role = session.execute(select(Role).where(Role.code == "system_admin")).scalar_one()
        session.add_all(
            [
                UserRole(
                    id=USER_ROLE_ID,
                    user_id=USER_ID,
                    role_id=finance_role.id,
                    assigned_by=None,
                    assignment_source="bootstrap",
                    assignment_reason="system_bootstrap",
                ),
                UserRole(
                    id=ADMIN_USER_ROLE_ID,
                    user_id=ADMIN_USER_ID,
                    role_id=admin_role.id,
                    assigned_by=None,
                    assignment_source="bootstrap",
                    assignment_reason="system_bootstrap",
                ),
            ]
        )
        session.add_all(
            [
                Contract(
                    id=CONTRACT_ID,
                    organization_id=ORGANIZATION_ID,
                    contract_no="CONTRACT-INTEGRATION-001",
                    name="Synthetic integration contract",
                    party_a_name="Synthetic buyer",
                    party_a_tax_no="SYNTH-BUYER-TAX",
                    party_b_name="Synthetic seller",
                    party_b_tax_no="SYNTH-SELLER-TAX",
                    amount=Decimal("100.25"),
                    currency="CNY",
                    signed_date=date(2026, 1, 1),
                    effective_date=date(2026, 1, 1),
                    expiry_date=date(2026, 12, 31),
                    payment_method="bank_transfer",
                    payment_terms="30 days",
                    confirmation_status="confirmed",
                    status="active",
                    confirmed_by=USER_ID,
                    confirmed_at=now,
                    critical_fact_hash="a" * 64,
                    created_by=USER_ID,
                ),
                Invoice(
                    id=INVOICE_ID,
                    organization_id=ORGANIZATION_ID,
                    invoice_code="INV-CODE-INTEGRATION",
                    invoice_number="INV-NUMBER-INTEGRATION",
                    invoice_type="standard",
                    invoice_date=date(2026, 6, 1),
                    buyer_name="Synthetic buyer",
                    buyer_tax_no="SYNTH-BUYER-TAX",
                    seller_name="Synthetic seller",
                    seller_tax_no="SYNTH-SELLER-TAX",
                    amount_excluding_tax=Decimal("80.12"),
                    tax_amount=Decimal("20.13"),
                    total_amount=Decimal("100.25"),
                    currency="CNY",
                    confirmation_status="confirmed",
                    duplicate_status="unique",
                    status="confirmed",
                    field_evidence_json={},
                    confirmed_by=USER_ID,
                    confirmed_at=now,
                    critical_fact_hash="b" * 64,
                    created_by=USER_ID,
                ),
                Invoice(
                    id=DUPLICATE_INVOICE_ID,
                    organization_id=ORGANIZATION_ID,
                    invoice_code="INV-CODE-INTEGRATION",
                    invoice_number="INV-NUMBER-INTEGRATION",
                    invoice_type="standard",
                    invoice_date=date(2026, 6, 1),
                    buyer_name="Synthetic buyer",
                    buyer_tax_no="SYNTH-BUYER-TAX",
                    seller_name="Synthetic seller duplicate",
                    seller_tax_no="SYNTH-SELLER-TAX",
                    amount_excluding_tax=Decimal("80.12"),
                    tax_amount=Decimal("20.13"),
                    total_amount=Decimal("100.25"),
                    currency="CNY",
                    confirmation_status="confirmed",
                    duplicate_status="suspected",
                    status="archived",
                    field_evidence_json={},
                    confirmed_by=USER_ID,
                    confirmed_at=now,
                    critical_fact_hash="d" * 64,
                    created_by=USER_ID,
                ),
            ]
        )
        session.flush()
        file_record = FileRecord(
            id=FILE_ID,
            organization_id=ORGANIZATION_ID,
            original_name="synthetic-invoice.pdf",
            extension=".pdf",
            mime_type="application/pdf",
            detected_mime_type="application/pdf",
            size_bytes=128,
            sha256="e" * 64,
            minio_bucket="quarantine",
            minio_object_key=f"{ORGANIZATION_ID}/{FILE_ID}/quarantine",
            original_minio_bucket=None,
            original_minio_object_key=None,
            status="uploaded",
            intended_business_type="invoice",
            target_knowledge_base_id=None,
            auto_process_requested=True,
            security_scan_status="pending",
            rejection_code=None,
            rejection_message=None,
            uploaded_by=USER_ID,
            stored_at=None,
            archived_at=None,
            created_by=USER_ID,
            updated_by=USER_ID,
        )
        session.add(file_record)
        session.flush()
        file_record.status = "validating"
        file_record.row_version += 1
        session.flush()
        file_record.status = "stored"
        file_record.security_scan_status = "clean"
        file_record.original_minio_bucket = "originals"
        file_record.original_minio_object_key = f"{ORGANIZATION_ID}/{FILE_ID}/original"
        file_record.stored_at = now
        file_record.row_version += 1
        session.flush()
        session.add(
            SupplementaryAgreement(
                id=AGREEMENT_ID,
                organization_id=ORGANIZATION_ID,
                contract_id=CONTRACT_ID,
                agreement_no="AGREEMENT-INTEGRATION-001",
                name="Synthetic supplementary agreement",
                signed_date=date(2026, 2, 1),
                effective_date=date(2026, 3, 1),
                status="confirmed",
                confirmation_status="confirmed",
                confirmed_by=USER_ID,
                confirmed_at=now,
                confirmation_reason="synthetic integration confirmation",
                critical_fact_hash="c" * 64,
                created_by=USER_ID,
            )
        )
        session.add(
            FilePrimaryBusinessObject(
                id=FILE_BINDING_ID,
                file_id=FILE_ID,
                business_type="invoice",
                contract_id=None,
                invoice_id=INVOICE_ID,
                supplementary_agreement_id=None,
                policy_document_id=None,
                bound_by=USER_ID,
            )
        )
        relation = ContractInvoice(
            id=RELATION_ID,
            contract_id=CONTRACT_ID,
            invoice_id=INVOICE_ID,
            status="suggested",
            match_reasons_json={
                "tax_no": {"status": "matched", "code": "tax_no_matched"},
                "name": {"status": "matched", "code": "name_matched"},
                "date": {"status": "matched", "code": "date_in_range"},
            },
            suggested_by="system",
            confirmed_by=None,
            confirmed_at=None,
            created_at=now,
            created_by=USER_ID,
        )
        session.add(relation)
        session.flush()
        relation.status = "confirmed_primary"
        relation.confirmed_by = USER_ID
        relation.confirmed_at = now
        relation.row_version += 1


def _clear_owned_test_facts(engine: Engine) -> None:
    """Delete only this test's fixed synthetic rows before later directory tests run."""

    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE operation_logs DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM operation_logs WHERE actor_id IN (%s, %s) OR actor_kind = 'anonymous'",
                (USER_ID, ADMIN_USER_ID),
            )
        finally:
            connection.exec_driver_sql("ALTER TABLE operation_logs ENABLE TRIGGER USER")
        connection.exec_driver_sql("ALTER TABLE contract_invoices DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM contract_invoices WHERE id = %s",
                (RELATION_ID,),
            )
        finally:
            connection.exec_driver_sql("ALTER TABLE contract_invoices ENABLE TRIGGER USER")
        connection.exec_driver_sql("ALTER TABLE file_primary_business_objects DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM file_primary_business_objects WHERE id = %s",
                (FILE_BINDING_ID,),
            )
        finally:
            connection.exec_driver_sql(
                "ALTER TABLE file_primary_business_objects ENABLE TRIGGER USER"
            )
        connection.exec_driver_sql(
            "DELETE FROM supplementary_agreements WHERE id = %s",
            (AGREEMENT_ID,),
        )
        connection.exec_driver_sql("ALTER TABLE invoice_items DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM invoice_items WHERE invoice_id = %s",
                (INVOICE_ID,),
            )
        finally:
            connection.exec_driver_sql("ALTER TABLE invoice_items ENABLE TRIGGER USER")
        connection.exec_driver_sql("ALTER TABLE token_sessions DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM token_sessions WHERE user_id IN (%s, %s)",
                (USER_ID, ADMIN_USER_ID),
            )
        finally:
            connection.exec_driver_sql("ALTER TABLE token_sessions ENABLE TRIGGER USER")
        connection.exec_driver_sql("ALTER TABLE user_roles DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM user_roles WHERE id IN (%s, %s)",
                (USER_ROLE_ID, ADMIN_USER_ROLE_ID),
            )
        finally:
            connection.exec_driver_sql("ALTER TABLE user_roles ENABLE TRIGGER USER")
        connection.exec_driver_sql("ALTER TABLE invoices DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql(
                "DELETE FROM invoices WHERE id IN (%s, %s)",
                (INVOICE_ID, DUPLICATE_INVOICE_ID),
            )
        finally:
            connection.exec_driver_sql("ALTER TABLE invoices ENABLE TRIGGER USER")
        connection.exec_driver_sql("ALTER TABLE files DISABLE TRIGGER USER")
        try:
            connection.exec_driver_sql("DELETE FROM files WHERE id = %s", (FILE_ID,))
        finally:
            connection.exec_driver_sql("ALTER TABLE files ENABLE TRIGGER USER")
        connection.exec_driver_sql("DELETE FROM contracts WHERE id = %s", (CONTRACT_ID,))
        connection.exec_driver_sql(
            "DELETE FROM users WHERE id IN (%s, %s)",
            (USER_ID, ADMIN_USER_ID),
        )
        connection.exec_driver_sql(
            "DELETE FROM organizations WHERE id = %s",
            (ORGANIZATION_ID,),
        )


def _assert_private_success(client: TestClient, path: str) -> dict[str, Any]:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    payload: object = response.json()
    assert isinstance(payload, dict)
    assert set(payload) == {"code", "message", "data", "trace_id", "timestamp"}
    assert payload.get("code") == "OK"
    assert payload.get("message") == "success"
    data: object = payload.get("data")
    assert isinstance(data, dict)
    return data


def test_real_access_token_reaches_all_frozen_read_chains(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)

    active_kid = "bootstrap-financial-read-v1"
    private_key_file = tmp_path / "auth-private.pem"
    public_keyring_file = tmp_path / "auth-public-keyring.json"
    seed_engine: Engine | None = None
    seeded = False
    try:
        private_key = Ed25519PrivateKey.generate()
        private_key_file.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_keyring_file.write_text(
            json.dumps({active_kid: public_pem.decode("ascii")}, separators=(",", ":")),
            encoding="utf-8",
        )
        settings_values = _runtime_settings(database_url).model_dump()
        settings_values.update(
            {
                "auth_jwt_active_kid": active_kid,
                "auth_jwt_private_key_file": str(private_key_file),
                "auth_jwt_public_keyring_file": str(public_keyring_file),
                "auth_public_origin": "https://testserver",
            }
        )
        settings = Settings(_env_file=None, **settings_values)
        seed_engine = create_application_engine(settings)
        seed_factory = create_session_factory(seed_engine)
        event.listen(seed_factory, "after_begin", _bound_transaction_waits)

        _seed_subject_and_financial_facts(seed_factory)
        seeded = True
        application = create_app(settings)
        assert application.dependency_overrides == {}
        assert not hasattr(application.state, "auth_service")
        assert not hasattr(application.state, "invoice_query_service")
        assert not hasattr(application.state, "user_query_service")

        with TestClient(application, base_url="https://testserver") as client:
            assert isinstance(application.state.auth_service, AuthService)
            assert isinstance(application.state.invoice_query_service, InvoiceQueryService)
            assert isinstance(application.state.user_query_service, UserQueryService)
            assert application.dependency_overrides == {}

            login = client.post(
                "/api/v1/auth/login",
                headers={"Origin": "https://testserver"},
                json={"username": USERNAME, "password": PASSWORD, "remember_me": False},
            )
            assert login.status_code == 200
            assert login.headers["cache-control"] == "no-store"
            refresh_cookie = login.headers["set-cookie"]
            assert "HttpOnly" in refresh_cookie
            assert "Secure" in refresh_cookie
            assert "SameSite=strict" in refresh_cookie
            assert "Path=/api/v1/auth" in refresh_cookie
            login_data = login.json()["data"]
            assert login_data["user"]["roles"] == ["finance_reviewer"]
            assert "financial.read" in login_data["user"]["permissions"]
            client.headers.update({"Authorization": f"Bearer {login_data['access_token']}"})

            invoice_list = _assert_private_success(client, "/api/v1/invoices")
            assert [item["id"] for item in invoice_list["items"]] == [
                str(DUPLICATE_INVOICE_ID),
                str(INVOICE_ID),
            ]
            assert invoice_list["next_cursor"] is None

            invoice_detail = _assert_private_success(client, f"/api/v1/invoices/{INVOICE_ID}")
            assert invoice_detail["id"] == str(INVOICE_ID)
            assert invoice_detail["items"] == []

            invoice_evidence = _assert_private_success(
                client,
                f"/api/v1/invoices/{INVOICE_ID}/evidence",
            )
            assert invoice_evidence == {
                "invoice_id": str(INVOICE_ID),
                "row_version": "1",
                "field_evidence": [],
                "item_evidence": {},
            }
            invoice_history = _assert_private_success(
                client,
                f"/api/v1/invoices/{INVOICE_ID}/history",
            )
            assert invoice_history == {
                "invoice_id": str(INVOICE_ID),
                "items": [],
            }

            duplicate_candidates = _assert_private_success(
                client,
                f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates",
            )
            assert duplicate_candidates == {
                "basis_status": "ready",
                "items": [
                    {
                        "id": str(DUPLICATE_INVOICE_ID),
                        "invoice_code": "INV-CODE-INTEGRATION",
                        "invoice_number": "INV-NUMBER-INTEGRATION",
                        "invoice_date": "2026-06-01",
                        "seller_name": "Synthetic seller duplicate",
                        "total_amount": "100.25",
                        "currency": "CNY",
                        "confirmation_status": "confirmed",
                        "duplicate_status": "suspected",
                        "status": "archived",
                    }
                ],
                "page_size": 20,
                "next_cursor": None,
            }
            duplicate_pair = _assert_private_success(
                client,
                f"/api/v1/invoices/{INVOICE_ID}/duplicate-candidates/{DUPLICATE_INVOICE_ID}",
            )
            assert duplicate_pair["source"]["id"] == str(INVOICE_ID)
            assert duplicate_pair["candidate"]["id"] == str(DUPLICATE_INVOICE_ID)
            assert duplicate_pair["exact_identity"] == {
                "invoice_code": "INV-CODE-INTEGRATION",
                "invoice_number": "INV-NUMBER-INTEGRATION",
                "seller_tax_no": "SYNTH-SELLER-TAX",
            }

            contract_list = _assert_private_success(client, "/api/v1/contracts")
            assert [item["id"] for item in contract_list["items"]] == [str(CONTRACT_ID)]
            assert contract_list["next_cursor"] is None

            contract_detail = _assert_private_success(client, f"/api/v1/contracts/{CONTRACT_ID}")
            assert contract_detail["id"] == str(CONTRACT_ID)

            primary_contract = _assert_private_success(
                client, f"/api/v1/invoices/{INVOICE_ID}/primary-contract"
            )
            assert primary_contract["primary_contract"]["id"] == str(CONTRACT_ID)

            agreements = _assert_private_success(
                client,
                f"/api/v1/contracts/{CONTRACT_ID}/supplementary-agreements",
            )
            assert [item["id"] for item in agreements["items"]] == [str(AGREEMENT_ID)]
            assert agreements["next_cursor"] is None

            primary_invoices = _assert_private_success(
                client,
                f"/api/v1/contracts/{CONTRACT_ID}/primary-invoices",
            )
            assert [item["id"] for item in primary_invoices["items"]] == [str(INVOICE_ID)]
            assert primary_invoices["next_cursor"] is None

            for path in (
                f"/api/v1/invoices/{UNKNOWN_INVOICE_ID}",
                f"/api/v1/contracts/{UNKNOWN_CONTRACT_ID}",
            ):
                hidden = client.get(path)
                assert hidden.status_code == 404
                assert hidden.json()["code"] == "RESOURCE_NOT_FOUND"
                assert str(UNKNOWN_INVOICE_ID) not in hidden.text
                assert str(UNKNOWN_CONTRACT_ID) not in hidden.text

            logout = client.post(
                "/api/v1/auth/logout",
                headers={"Origin": "https://testserver"},
            )
            assert logout.status_code == 204
            refresh_after_logout = client.post(
                "/api/v1/auth/refresh",
                headers={"Origin": "https://testserver"},
            )
            assert refresh_after_logout.status_code == 401
            assert refresh_after_logout.json()["code"] == "AUTH_REFRESH_EXPIRED"

            admin_login = client.post(
                "/api/v1/auth/login",
                headers={"Origin": "https://testserver"},
                json={
                    "username": ADMIN_USERNAME,
                    "password": ADMIN_PASSWORD,
                    "remember_me": False,
                },
            )
            assert admin_login.status_code == 200
            admin_login_data = admin_login.json()["data"]
            assert admin_login_data["user"]["roles"] == ["system_admin"]
            assert "users.manage" in admin_login_data["user"]["permissions"]
            admin_access_token = admin_login_data["access_token"]
            client.headers.update({"Authorization": f"Bearer {admin_access_token}"})

            users_response = client.get("/api/v1/users")
            assert users_response.status_code == 200
            assert users_response.headers["cache-control"] == "private, no-store"
            assert admin_access_token not in users_response.text
            users_payload = users_response.json()
            assert set(users_payload) == {"code", "message", "data", "trace_id", "timestamp"}
            assert users_payload["code"] == "OK"
            assert users_payload["data"] == {
                "items": [
                    {
                        "id": str(ADMIN_USER_ID),
                        "username": ADMIN_USERNAME,
                        "display_name": "Synthetic system administrator",
                        "status": "active",
                        "fixed_roles": ["system_admin"],
                        "row_version": "2",
                    },
                    {
                        "id": str(USER_ID),
                        "username": USERNAME,
                        "display_name": "Synthetic finance reviewer",
                        "status": "active",
                        "fixed_roles": ["finance_reviewer"],
                        "row_version": "2",
                    },
                ],
                "page_size": 20,
                "next_cursor": None,
            }
    finally:
        try:
            if seed_engine is not None:
                try:
                    if seeded:
                        _clear_owned_test_facts(seed_engine)
                finally:
                    seed_engine.dispose()
        finally:
            private_key_file.unlink(missing_ok=True)
            public_keyring_file.unlink(missing_ok=True)
            assert not private_key_file.exists()
            assert not public_keyring_file.exists()
