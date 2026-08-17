from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import URL, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from app.db.migration import create_migration_engine
from tests.integration.database.test_migrations import (
    INVOICE_FACTS_REVISION,
    SUPPLIER_RUNTIME_REVISION,
    configure_disposable_database,
    current_revision,
    execute_database_statement,
    financial_constraint_contract,
    financial_index_contract,
    reset_disposable_database_to_head,
    safe_database_error_signature,
    user_trigger_names,
)

pytestmark = pytest.mark.integration


def _correction_type_definition(database_url: URL) -> str:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            return str(
                connection.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid, true) FROM pg_constraint "
                        "WHERE conrelid = 'user_corrections'::regclass "
                        "AND conname = 'ck_user_corrections_correction_type_allowed'"
                    )
                ).scalar_one()
            )
    finally:
        engine.dispose()


def _supplier_binding_function(database_url: URL) -> tuple[bool, str, str, str] | None:
    engine = create_migration_engine(database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT prosecdef, provolatile, proparallel, pg_get_functiondef(oid) "
                    "FROM pg_proc WHERE proname = 'enforce_financial_supplier_binding_v1'"
                )
            ).one_or_none()
            if row is None:
                return None
            return bool(row[0]), str(row[1]), str(row[2]), str(row[3])
    finally:
        engine.dispose()


def test_supplier_runtime_migration_catalog_and_empty_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    command.downgrade(alembic_config, SUPPLIER_RUNTIME_REVISION)

    assert current_revision(database_url) == SUPPLIER_RUNTIME_REVISION
    assert {
        "ck_suppliers_standard_name_normalized",
        "ck_suppliers_row_version_positive",
        "ck_suppliers_confirmation_matrix",
    } <= set(financial_constraint_contract(database_url, "suppliers"))
    assert {
        "uq_suppliers_organization_source_contract_candidate",
        "uq_suppliers_organization_source_invoice_candidate",
    } <= set(financial_index_contract(database_url, "suppliers"))
    assert "trg_contracts_supplier_binding_v1" in user_trigger_names(database_url, "contracts")
    assert "trg_invoices_supplier_binding_v1" in user_trigger_names(database_url, "invoices")
    function_contract = _supplier_binding_function(database_url)
    assert function_contract is not None
    assert function_contract[:3] == (False, "v", "u")
    assert "SET search_path TO 'pg_catalog', 'pg_temp'" in function_contract[3]
    assert "supplier_field" in _correction_type_definition(database_url)

    command.downgrade(alembic_config, INVOICE_FACTS_REVISION)
    assert current_revision(database_url) == INVOICE_FACTS_REVISION
    assert not {
        "ck_suppliers_standard_name_normalized",
        "ck_suppliers_row_version_positive",
        "ck_suppliers_confirmation_matrix",
    } & set(financial_constraint_contract(database_url, "suppliers"))
    assert not {
        "uq_suppliers_organization_source_contract_candidate",
        "uq_suppliers_organization_source_invoice_candidate",
    } & set(financial_index_contract(database_url, "suppliers"))
    assert "trg_contracts_supplier_binding_v1" not in user_trigger_names(database_url, "contracts")
    assert "trg_invoices_supplier_binding_v1" not in user_trigger_names(database_url, "invoices")
    assert _supplier_binding_function(database_url) is None
    assert "supplier_field" not in _correction_type_definition(database_url)

    command.upgrade(alembic_config, SUPPLIER_RUNTIME_REVISION)
    assert current_revision(database_url) == SUPPLIER_RUNTIME_REVISION


def test_supplier_correction_blocks_revision_017_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, alembic_config = configure_disposable_database(monkeypatch)
    reset_disposable_database_to_head(database_url, alembic_config)
    command.downgrade(alembic_config, SUPPLIER_RUNTIME_REVISION)
    organization_id = str(uuid4())
    actor_id = str(uuid4())
    correction_id = str(uuid4())
    execute_database_statement(
        database_url,
        "INSERT INTO organizations (id, name, unified_social_credit_code, tax_number, status) "
        "VALUES (:id, 'supplier downgrade organization', "
        "'SUPPLIER-DOWNGRADE-USCC', 'SUPPLIER-DOWNGRADE-TAX', 'active')",
        {"id": organization_id},
    )
    execute_database_statement(
        database_url,
        "INSERT INTO users (id, organization_id, username, display_name, password_hash, "
        "status, password_changed_at, token_invalid_before) VALUES "
        "(:id, :organization_id, 'supplier.downgrade.actor', 'supplier downgrade actor', "
        "'synthetic-password-hash', 'active', now(), now())",
        {"id": actor_id, "organization_id": organization_id},
    )
    execute_database_statement(
        database_url,
        "INSERT INTO user_corrections (id, organization_id, correction_type, object_type, "
        "object_id, field_path, after_value_json, reason, actor_id, actor_role_code, trace_id) "
        "VALUES (:id, :organization_id, 'supplier_field', 'supplier', :object_id, "
        "'standard_name', '{\"standard_name\":\"after\"}'::jsonb, "
        "'synthetic supplier correction', :actor_id, 'contract_admin', :trace_id)",
        {
            "id": correction_id,
            "organization_id": organization_id,
            "object_id": str(uuid4()),
            "actor_id": actor_id,
            "trace_id": str(uuid4()),
        },
    )

    with pytest.raises(DBAPIError) as downgrade_error:
        command.downgrade(alembic_config, INVOICE_FACTS_REVISION)
    assert safe_database_error_signature(downgrade_error.value) == ("55000", None)
    assert current_revision(database_url) == SUPPLIER_RUNTIME_REVISION

    engine = create_migration_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE user_corrections DISABLE TRIGGER USER"))
            connection.execute(
                text("DELETE FROM user_corrections WHERE id = :id"), {"id": correction_id}
            )
            connection.execute(text("ALTER TABLE user_corrections ENABLE TRIGGER USER"))
            connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": actor_id})
            connection.execute(
                text("DELETE FROM organizations WHERE id = :id"), {"id": organization_id}
            )
    finally:
        engine.dispose()

    command.downgrade(alembic_config, INVOICE_FACTS_REVISION)
    assert current_revision(database_url) == INVOICE_FACTS_REVISION
    command.upgrade(alembic_config, SUPPLIER_RUNTIME_REVISION)
