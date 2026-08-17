from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.models import (
    CONFIRMATION_STATUSES,
    CONTRACT_INVOICE_STATUSES,
    CONTRACT_STATUSES,
    INVOICE_DUPLICATE_STATUSES,
    INVOICE_STATUSES,
    SUPPLEMENTARY_AGREEMENT_STATUSES,
    SUPPLIER_SOURCE_TYPES,
    SUPPLIER_STATUSES,
    Base,
)


def _column_contract(table_name: str) -> list[tuple[str, str, bool]]:
    table = Base.metadata.tables[table_name]
    dialect = postgresql.dialect()
    return [
        (column.name, column.type.compile(dialect=dialect), column.nullable) for column in table.c
    ]


def _server_defaults(table_name: str) -> dict[str, str]:
    table = Base.metadata.tables[table_name]
    return {
        column.name: str(column.server_default.arg)
        for column in table.c
        if column.server_default is not None
    }


def _check_sqltexts(table_name: str) -> dict[str, str]:
    dialect = postgresql.dialect()
    return {
        str(constraint.name): " ".join(str(constraint.sqltext.compile(dialect=dialect)).split())
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint)
    }


def _foreign_keys(table_name: str) -> dict[str | None, tuple[str, ...]]:
    return {
        constraint.name: tuple(element.target_fullname for element in constraint.elements)
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _index_sql(table_name: str) -> set[str]:
    dialect = postgresql.dialect()
    return {
        str(CreateIndex(index).compile(dialect=dialect))
        for index in Base.metadata.tables[table_name].indexes
    }


def _unique_constraints(table_name: str) -> dict[str | None, tuple[str, ...]]:
    return {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _assert_no_cascade(table_name: str) -> None:
    table = Base.metadata.tables[table_name]
    assert all(
        element.ondelete is None and element.onupdate is None
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        for element in constraint.elements
    )


def test_contract_model_contract_is_exact() -> None:
    assert CONTRACT_STATUSES == ("draft", "active", "expired", "terminated", "archived")
    assert CONFIRMATION_STATUSES == ("unconfirmed", "confirmed", "rejected")
    assert _column_contract("contracts") == [
        ("id", "UUID", False),
        ("organization_id", "UUID", False),
        ("contract_no", "VARCHAR(100)", True),
        ("name", "VARCHAR(300)", False),
        ("party_a_name", "VARCHAR(300)", True),
        ("party_a_tax_no", "VARCHAR(32)", True),
        ("party_b_name", "VARCHAR(300)", True),
        ("party_b_tax_no", "VARCHAR(32)", True),
        ("supplier_id", "UUID", True),
        ("amount", "NUMERIC(18, 2)", True),
        ("currency", "CHAR(3)", True),
        ("signed_date", "DATE", True),
        ("effective_date", "DATE", True),
        ("expiry_date", "DATE", True),
        ("payment_method", "VARCHAR(100)", True),
        ("payment_terms", "TEXT", True),
        ("confirmation_status", "VARCHAR(20)", False),
        ("status", "VARCHAR(20)", False),
        ("confirmed_by", "UUID", True),
        ("confirmed_at", "TIMESTAMP WITH TIME ZONE", True),
        ("critical_fact_hash", "CHAR(64)", False),
        ("row_version", "BIGINT", False),
        ("created_at", "TIMESTAMP WITH TIME ZONE", False),
        ("created_by", "UUID", True),
        ("updated_at", "TIMESTAMP WITH TIME ZONE", False),
        ("updated_by", "UUID", True),
        ("deleted_at", "TIMESTAMP WITH TIME ZONE", True),
        ("deleted_by", "UUID", True),
        ("delete_reason", "TEXT", True),
    ]
    assert _server_defaults("contracts") == {
        "id": "gen_random_uuid()",
        "row_version": "1",
        "created_at": "now()",
        "updated_at": "now()",
    }
    assert _check_sqltexts("contracts") == {
        "ck_contracts_amount_nonnegative": "amount IS NULL OR amount >= 0",
        "ck_contracts_confirmation_status_allowed": (
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')"
        ),
        "ck_contracts_contract_no_normalized": (
            'contract_no IS NULL OR ( (contract_no COLLATE "C") '
            '<> (\'\' COLLATE "C") AND (contract_no COLLATE "C") '
            "= (btrim(contract_no, ' ') COLLATE \"C\") AND "
            r"""(contract_no COLLATE "C") !~ U&'[\0001-\001F\007F-\009F]' )"""
        ),
        "ck_contracts_expiry_not_before_effective": (
            "expiry_date IS NULL OR effective_date IS NULL OR expiry_date >= effective_date"
        ),
        "ck_contracts_soft_delete_reason_required": (
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')"
        ),
        "ck_contracts_status_allowed": (
            "status IN ('draft', 'active', 'expired', 'terminated', 'archived')"
        ),
    }
    assert _foreign_keys("contracts") == {
        "fk_contracts_confirmed_by_users": ("users.id",),
        "fk_contracts_created_by_users": ("users.id",),
        "fk_contracts_deleted_by_users": ("users.id",),
        "fk_contracts_organization_id_organizations": ("organizations.id",),
        "fk_contracts_supplier_id_suppliers": ("suppliers.id",),
        "fk_contracts_updated_by_users": ("users.id",),
    }
    assert _index_sql("contracts") == {
        "CREATE INDEX idx_contracts_org_status ON contracts "
        "(organization_id, status, updated_at DESC)",
        "CREATE INDEX idx_contracts_party_b_tax ON contracts (organization_id, party_b_tax_no)",
        "CREATE UNIQUE INDEX uq_contracts_organization_contract_no ON contracts "
        '(organization_id, (contract_no COLLATE "C")) '
        "WHERE contract_no IS NOT NULL AND deleted_at IS NULL",
    }
    supplier_fk = next(iter(Base.metadata.tables["contracts"].c.supplier_id.foreign_keys))
    assert supplier_fk.constraint.use_alter is True
    _assert_no_cascade("contracts")


def test_invoice_model_contract_is_exact() -> None:
    assert INVOICE_STATUSES == ("draft", "confirmed", "voided", "archived")
    assert INVOICE_DUPLICATE_STATUSES == (
        "not_checked",
        "unique",
        "suspected",
        "confirmed_duplicate",
        "exception_approved",
    )
    assert _column_contract("invoices") == [
        ("id", "UUID", False),
        ("organization_id", "UUID", False),
        ("invoice_code", "VARCHAR(50)", True),
        ("invoice_number", "VARCHAR(50)", True),
        ("invoice_type", "VARCHAR(40)", True),
        ("is_red_invoice", "BOOLEAN", True),
        ("invoice_date", "DATE", True),
        ("buyer_name", "VARCHAR(300)", True),
        ("buyer_tax_no", "VARCHAR(32)", True),
        ("seller_name", "VARCHAR(300)", True),
        ("seller_tax_no", "VARCHAR(32)", True),
        ("supplier_id", "UUID", True),
        ("amount_excluding_tax", "NUMERIC(18, 2)", True),
        ("tax_amount", "NUMERIC(18, 2)", True),
        ("total_amount", "NUMERIC(18, 2)", True),
        ("currency", "CHAR(3)", True),
        ("confirmation_status", "VARCHAR(20)", False),
        ("duplicate_status", "VARCHAR(30)", False),
        ("status", "VARCHAR(20)", False),
        ("field_evidence_json", "JSONB", False),
        ("confirmed_by", "UUID", True),
        ("confirmed_at", "TIMESTAMP WITH TIME ZONE", True),
        ("critical_fact_hash", "CHAR(64)", False),
        ("row_version", "BIGINT", False),
        ("created_at", "TIMESTAMP WITH TIME ZONE", False),
        ("created_by", "UUID", True),
        ("updated_at", "TIMESTAMP WITH TIME ZONE", False),
        ("updated_by", "UUID", True),
        ("deleted_at", "TIMESTAMP WITH TIME ZONE", True),
        ("deleted_by", "UUID", True),
        ("delete_reason", "TEXT", True),
    ]
    assert _server_defaults("invoices") == {
        "id": "gen_random_uuid()",
        "duplicate_status": "'not_checked'",
        "field_evidence_json": "'{}'::jsonb",
        "row_version": "1",
        "created_at": "now()",
        "updated_at": "now()",
    }
    assert _check_sqltexts("invoices") == {
        "ck_invoices_confirmation_status_allowed": (
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')"
        ),
        "ck_invoices_duplicate_status_allowed": (
            "duplicate_status IN ('not_checked', 'unique', 'suspected', "
            "'confirmed_duplicate', 'exception_approved')"
        ),
        "ck_invoices_confirmed_currency_required": (
            "confirmation_status <> 'confirmed' OR currency IS NOT NULL"
        ),
        "ck_invoices_field_evidence_object": ("jsonb_typeof(field_evidence_json) = 'object'"),
        "ck_invoices_critical_fact_hash_format": ("critical_fact_hash ~ '^[0-9a-f]{64}$'"),
        "ck_invoices_row_version_positive": "row_version > 0",
        "ck_invoices_confirmation_matrix": (
            "(confirmation_status = 'unconfirmed' AND status = 'draft' "
            "AND confirmed_by IS NULL AND confirmed_at IS NULL) OR "
            "(confirmation_status = 'confirmed' AND status IN "
            "('confirmed', 'voided', 'archived') AND confirmed_by IS NOT NULL "
            "AND confirmed_at IS NOT NULL) OR "
            "(confirmation_status = 'rejected' AND status = 'draft' "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)"
        ),
        "ck_invoices_soft_delete_reason_required": (
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')"
        ),
        "ck_invoices_status_allowed": ("status IN ('draft', 'confirmed', 'voided', 'archived')"),
    }
    assert _foreign_keys("invoices") == {
        "fk_invoices_confirmed_by_users": ("users.id",),
        "fk_invoices_created_by_users": ("users.id",),
        "fk_invoices_deleted_by_users": ("users.id",),
        "fk_invoices_organization_id_organizations": ("organizations.id",),
        "fk_invoices_supplier_id_suppliers": ("suppliers.id",),
        "fk_invoices_updated_by_users": ("users.id",),
    }
    assert _index_sql("invoices") == {
        "CREATE INDEX idx_invoices_duplicate_lookup ON invoices "
        "(organization_id, invoice_code, invoice_number, seller_tax_no) "
        "WHERE deleted_at IS NULL AND status <> 'voided'",
        "CREATE INDEX idx_invoices_org_date ON invoices (organization_id, invoice_date DESC)",
        "CREATE INDEX idx_invoices_seller_tax ON invoices (organization_id, seller_tax_no)",
    }
    supplier_fk = next(iter(Base.metadata.tables["invoices"].c.supplier_id.foreign_keys))
    assert supplier_fk.constraint.use_alter is True
    _assert_no_cascade("invoices")


def test_supplier_model_contract_is_exact() -> None:
    assert SUPPLIER_SOURCE_TYPES == ("contract", "invoice", "manual")
    assert SUPPLIER_STATUSES == ("candidate", "active", "inactive")
    assert _column_contract("suppliers") == [
        ("id", "UUID", False),
        ("organization_id", "UUID", False),
        ("standard_name", "VARCHAR(300)", False),
        ("unified_social_credit_code", "VARCHAR(32)", True),
        ("tax_number", "VARCHAR(32)", True),
        ("source_type", "VARCHAR(30)", False),
        ("source_contract_id", "UUID", True),
        ("source_invoice_id", "UUID", True),
        ("confirmation_status", "VARCHAR(20)", False),
        ("status", "VARCHAR(20)", False),
        ("confirmed_by", "UUID", True),
        ("confirmed_at", "TIMESTAMP WITH TIME ZONE", True),
        ("row_version", "BIGINT", False),
        ("created_at", "TIMESTAMP WITH TIME ZONE", False),
        ("created_by", "UUID", True),
        ("updated_at", "TIMESTAMP WITH TIME ZONE", False),
        ("updated_by", "UUID", True),
        ("deleted_at", "TIMESTAMP WITH TIME ZONE", True),
        ("deleted_by", "UUID", True),
        ("delete_reason", "TEXT", True),
    ]
    assert _server_defaults("suppliers") == {
        "id": "gen_random_uuid()",
        "row_version": "1",
        "created_at": "now()",
        "updated_at": "now()",
    }
    assert _check_sqltexts("suppliers") == {
        "ck_suppliers_active_tax_identity_required": (
            "status <> 'active' OR COALESCE(unified_social_credit_code, tax_number) IS NOT NULL"
        ),
        "ck_suppliers_confirmation_status_allowed": (
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')"
        ),
        "ck_suppliers_confirmation_matrix": (
            "(confirmation_status = 'unconfirmed' AND status = 'candidate' "
            "AND confirmed_by IS NULL AND confirmed_at IS NULL) OR "
            "(confirmation_status = 'confirmed' AND status = 'active' "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL) OR "
            "(confirmation_status = 'rejected' AND status = 'inactive' "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)"
        ),
        "ck_suppliers_row_version_positive": "row_version > 0",
        "ck_suppliers_soft_delete_reason_required": (
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')"
        ),
        "ck_suppliers_source_reference_matches_type": (
            "(source_type = 'contract' AND source_contract_id IS NOT NULL "
            "AND source_invoice_id IS NULL) OR (source_type = 'invoice' "
            "AND source_contract_id IS NULL AND source_invoice_id IS NOT NULL) "
            "OR (source_type = 'manual' AND source_contract_id IS NULL "
            "AND source_invoice_id IS NULL)"
        ),
        "ck_suppliers_source_type_allowed": ("source_type IN ('contract', 'invoice', 'manual')"),
        "ck_suppliers_status_allowed": "status IN ('candidate', 'active', 'inactive')",
        "ck_suppliers_standard_name_normalized": (
            "btrim(standard_name) <> '' AND standard_name = btrim(standard_name) "
            r"AND standard_name !~ U&'[\0001-\001F\007F-\009F]'"
        ),
        "ck_suppliers_tax_identity_sources_equal": (
            "unified_social_credit_code IS NULL OR tax_number IS NULL OR "
            '(unified_social_credit_code COLLATE "C") '
            '= (tax_number COLLATE "C")'
        ),
        "ck_suppliers_tax_number_normalized": (
            'tax_number IS NULL OR ( (tax_number COLLATE "C") '
            '<> (\'\' COLLATE "C") AND (tax_number COLLATE "C") '
            "= (btrim(tax_number, ' ') COLLATE \"C\") AND "
            r"""(tax_number COLLATE "C") !~ U&'[\0001-\001F\007F-\009F]' )"""
        ),
        "ck_suppliers_unified_social_credit_code_normalized": (
            "unified_social_credit_code IS NULL OR "
            '( (unified_social_credit_code COLLATE "C") '
            "<> ('' COLLATE \"C\") AND "
            '(unified_social_credit_code COLLATE "C") '
            "= (btrim(unified_social_credit_code, ' ') COLLATE \"C\") AND "
            r"""(unified_social_credit_code COLLATE "C") !~ """
            r"""U&'[\0001-\001F\007F-\009F]' AND """
            r"""(unified_social_credit_code COLLATE "C") ~ '^[0-9A-Z]+$' )"""
        ),
    }
    assert _foreign_keys("suppliers") == {
        "fk_suppliers_confirmed_by_users": ("users.id",),
        "fk_suppliers_created_by_users": ("users.id",),
        "fk_suppliers_deleted_by_users": ("users.id",),
        "fk_suppliers_organization_id_organizations": ("organizations.id",),
        "fk_suppliers_source_contract_id_contracts": ("contracts.id",),
        "fk_suppliers_source_invoice_id_invoices": ("invoices.id",),
        "fk_suppliers_updated_by_users": ("users.id",),
    }
    assert _index_sql("suppliers") == {
        "CREATE UNIQUE INDEX uq_suppliers_organization_tax_identity ON suppliers "
        '(organization_id, (COALESCE(unified_social_credit_code, tax_number) COLLATE "C")) '
        "WHERE status = 'active' AND deleted_at IS NULL "
        "AND COALESCE(unified_social_credit_code, tax_number) IS NOT NULL",
        "CREATE UNIQUE INDEX uq_suppliers_organization_source_contract_candidate "
        "ON suppliers (organization_id, source_contract_id) WHERE status = 'candidate' "
        "AND deleted_at IS NULL AND source_contract_id IS NOT NULL",
        "CREATE UNIQUE INDEX uq_suppliers_organization_source_invoice_candidate "
        "ON suppliers (organization_id, source_invoice_id) WHERE status = 'candidate' "
        "AND deleted_at IS NULL AND source_invoice_id IS NOT NULL",
    }
    source_contract_fk = next(
        iter(Base.metadata.tables["suppliers"].c.source_contract_id.foreign_keys)
    )
    source_invoice_fk = next(
        iter(Base.metadata.tables["suppliers"].c.source_invoice_id.foreign_keys)
    )
    assert source_contract_fk.constraint.use_alter is True
    assert source_invoice_fk.constraint.use_alter is True
    _assert_no_cascade("suppliers")


def test_supplementary_agreement_model_contract_is_exact() -> None:
    assert SUPPLEMENTARY_AGREEMENT_STATUSES == (
        "draft",
        "pending_confirmation",
        "confirmed",
        "rejected",
        "archived",
    )
    assert _column_contract("supplementary_agreements") == [
        ("id", "UUID", False),
        ("organization_id", "UUID", False),
        ("contract_id", "UUID", False),
        ("agreement_no", "VARCHAR(100)", True),
        ("name", "VARCHAR(300)", False),
        ("signed_date", "DATE", True),
        ("effective_date", "DATE", False),
        ("status", "VARCHAR(30)", False),
        ("confirmation_status", "VARCHAR(20)", False),
        ("confirmed_by", "UUID", True),
        ("confirmed_at", "TIMESTAMP WITH TIME ZONE", True),
        ("confirmation_reason", "TEXT", True),
        ("critical_fact_hash", "CHAR(64)", False),
        ("row_version", "BIGINT", False),
        ("created_at", "TIMESTAMP WITH TIME ZONE", False),
        ("created_by", "UUID", True),
        ("updated_at", "TIMESTAMP WITH TIME ZONE", False),
        ("updated_by", "UUID", True),
        ("deleted_at", "TIMESTAMP WITH TIME ZONE", True),
        ("deleted_by", "UUID", True),
        ("delete_reason", "TEXT", True),
    ]
    assert _server_defaults("supplementary_agreements") == {
        "id": "gen_random_uuid()",
        "row_version": "1",
        "created_at": "now()",
        "updated_at": "now()",
    }
    assert _check_sqltexts("supplementary_agreements") == {
        "ck_supplementary_agreements_confirmation_status_allowed": (
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')"
        ),
        "ck_supplementary_agreements_soft_delete_reason_required": (
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')"
        ),
        "ck_supplementary_agreements_status_allowed": (
            "status IN ('draft', 'pending_confirmation', 'confirmed', 'rejected', 'archived')"
        ),
    }
    assert _foreign_keys("supplementary_agreements") == {
        "fk_supplementary_agreements_confirmed_by_users": ("users.id",),
        "fk_supplementary_agreements_contract_id_contracts": ("contracts.id",),
        "fk_supplementary_agreements_created_by_users": ("users.id",),
        "fk_supplementary_agreements_deleted_by_users": ("users.id",),
        "fk_supplementary_agreements_organization_id_organizations": ("organizations.id",),
        "fk_supplementary_agreements_updated_by_users": ("users.id",),
    }
    assert _index_sql("supplementary_agreements") == {
        "CREATE INDEX idx_supplementary_agreements_contract_effective_status "
        "ON supplementary_agreements (contract_id, effective_date, status)"
    }
    _assert_no_cascade("supplementary_agreements")


def test_invoice_item_model_contract_is_exact() -> None:
    assert _column_contract("invoice_items") == [
        ("id", "UUID", False),
        ("invoice_id", "UUID", False),
        ("line_no", "INTEGER", False),
        ("item_name", "VARCHAR(500)", True),
        ("specification", "VARCHAR(300)", True),
        ("unit", "VARCHAR(50)", True),
        ("quantity", "NUMERIC(18, 6)", True),
        ("unit_price", "NUMERIC(18, 6)", True),
        ("amount_excluding_tax", "NUMERIC(18, 2)", True),
        ("tax_rate", "NUMERIC(8, 6)", True),
        ("tax_amount", "NUMERIC(18, 2)", True),
        ("total_amount", "NUMERIC(18, 2)", True),
        ("evidence_json", "JSONB", False),
        ("row_version", "BIGINT", False),
    ]
    assert _server_defaults("invoice_items") == {
        "id": "gen_random_uuid()",
        "evidence_json": "'{}'::jsonb",
        "row_version": "1",
    }
    assert _check_sqltexts("invoice_items") == {
        "ck_invoice_items_evidence_object": "jsonb_typeof(evidence_json) = 'object'",
        "ck_invoice_items_line_no_positive": "line_no > 0",
        "ck_invoice_items_row_version_positive": "row_version > 0",
        "ck_invoice_items_tax_rate_bounds": "tax_rate IS NULL OR tax_rate BETWEEN 0 AND 1",
    }
    assert _foreign_keys("invoice_items") == {
        "fk_invoice_items_invoice_id_invoices": ("invoices.id",)
    }
    assert _unique_constraints("invoice_items") == {
        "uq_invoice_items_invoice_id_line_no": ("invoice_id", "line_no")
    }
    assert _index_sql("invoice_items") == set()
    _assert_no_cascade("invoice_items")


def test_contract_invoice_model_contract_is_exact() -> None:
    assert CONTRACT_INVOICE_STATUSES == (
        "candidate",
        "suggested",
        "confirmed_primary",
        "cancelled",
    )
    assert _column_contract("contract_invoices") == [
        ("id", "UUID", False),
        ("contract_id", "UUID", False),
        ("invoice_id", "UUID", False),
        ("status", "VARCHAR(30)", False),
        ("match_reasons_json", "JSONB", False),
        ("suggested_by", "VARCHAR(20)", True),
        ("confirmed_by", "UUID", True),
        ("confirmed_at", "TIMESTAMP WITH TIME ZONE", True),
        ("cancelled_by", "UUID", True),
        ("cancelled_at", "TIMESTAMP WITH TIME ZONE", True),
        ("cancel_reason", "TEXT", True),
        ("row_version", "BIGINT", False),
        ("created_at", "TIMESTAMP WITH TIME ZONE", False),
        ("created_by", "UUID", False),
        ("deleted_at", "TIMESTAMP WITH TIME ZONE", True),
    ]
    assert _server_defaults("contract_invoices") == {
        "id": "gen_random_uuid()",
        "row_version": "1",
        "created_at": "now()",
    }
    assert _check_sqltexts("contract_invoices") == {
        "ck_contract_invoices_cancel_reason_required": (
            "status <> 'cancelled' OR (cancel_reason IS NOT NULL AND btrim(cancel_reason) <> '')"
        ),
        "ck_contract_invoices_status_allowed": (
            "status IN ('candidate', 'suggested', 'confirmed_primary', 'cancelled')"
        ),
        "ck_contract_invoices_suggested_by_allowed": (
            "suggested_by IS NULL OR suggested_by IN ('system', 'user')"
        ),
    }
    assert _foreign_keys("contract_invoices") == {
        "fk_contract_invoices_cancelled_by_users": ("users.id",),
        "fk_contract_invoices_confirmed_by_users": ("users.id",),
        "fk_contract_invoices_contract_id_contracts": ("contracts.id",),
        "fk_contract_invoices_created_by_users": ("users.id",),
        "fk_contract_invoices_invoice_id_invoices": ("invoices.id",),
    }
    assert _index_sql("contract_invoices") == {
        "CREATE UNIQUE INDEX uq_contract_invoice_pair_active ON contract_invoices "
        "(contract_id, invoice_id) WHERE deleted_at IS NULL AND status <> 'cancelled'",
        "CREATE UNIQUE INDEX uq_invoice_confirmed_primary_contract ON contract_invoices "
        "(invoice_id) WHERE status = 'confirmed_primary' AND deleted_at IS NULL",
    }
    _assert_no_cascade("contract_invoices")
