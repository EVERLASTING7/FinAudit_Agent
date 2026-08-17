"""CR-012-R3 合同、发票与供应商主数据模型。"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

CONFIRMATION_STATUSES = ("unconfirmed", "confirmed", "rejected")
CONTRACT_INVOICE_STATUSES = ("candidate", "suggested", "confirmed_primary", "cancelled")
CONTRACT_STATUSES = ("draft", "active", "expired", "terminated", "archived")
INVOICE_DUPLICATE_STATUSES = (
    "not_checked",
    "unique",
    "suspected",
    "confirmed_duplicate",
    "exception_approved",
)
INVOICE_STATUSES = ("draft", "confirmed", "voided", "archived")
SUPPLIER_SOURCE_TYPES = ("contract", "invoice", "manual")
SUPPLIER_STATUSES = ("candidate", "active", "inactive")
SUPPLEMENTARY_AGREEMENT_STATUSES = (
    "draft",
    "pending_confirmation",
    "confirmed",
    "rejected",
    "archived",
)
FINANCIAL_FIELD_VALUE_TYPES = ("string", "number", "date", "json")


class Contract(Base):
    """组织内可软删除的合同主数据。"""

    __tablename__ = "contracts"
    __table_args__ = (
        CheckConstraint(
            """
            contract_no IS NULL OR (
                (contract_no COLLATE "C") <> ('' COLLATE "C")
                AND (contract_no COLLATE "C")
                    = (btrim(contract_no, ' ') COLLATE "C")
                AND (contract_no COLLATE "C")
                    !~ U&'[\\0001-\\001F\\007F-\\009F]'
            )
            """,
            name="contract_no_normalized",
        ),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount_nonnegative"),
        CheckConstraint(
            "expiry_date IS NULL OR effective_date IS NULL OR expiry_date >= effective_date",
            name="expiry_not_before_effective",
        ),
        CheckConstraint(
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'expired', 'terminated', 'archived')",
            name="status_allowed",
        ),
        CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        Index(
            "uq_contracts_organization_contract_no",
            "organization_id",
            text('(contract_no COLLATE "C")'),
            unique=True,
            postgresql_where=text("contract_no IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "idx_contracts_org_status",
            "organization_id",
            "status",
            text("updated_at DESC"),
        ),
        Index(
            "idx_contracts_party_b_tax",
            "organization_id",
            "party_b_tax_no",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_contracts_organization_id_organizations"),
        nullable=False,
    )
    contract_no: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    party_a_name: Mapped[str | None] = mapped_column(String(300))
    party_a_tax_no: Mapped[str | None] = mapped_column(String(32))
    party_b_name: Mapped[str | None] = mapped_column(String(300))
    party_b_tax_no: Mapped[str | None] = mapped_column(String(32))
    supplier_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "suppliers.id",
            name="fk_contracts_supplier_id_suppliers",
            use_alter=True,
        ),
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    signed_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    payment_method: Mapped[str | None] = mapped_column(String(100))
    payment_terms: Mapped[str | None] = mapped_column(Text)
    confirmation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    confirmed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_contracts_confirmed_by_users"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    critical_fact_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_contracts_created_by_users"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_contracts_updated_by_users"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_contracts_deleted_by_users"),
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)


class Invoice(Base):
    """保留重复事实的发票主数据。"""

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        CheckConstraint(
            "duplicate_status IN ('not_checked', 'unique', 'suspected', "
            "'confirmed_duplicate', 'exception_approved')",
            name="duplicate_status_allowed",
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'voided', 'archived')",
            name="status_allowed",
        ),
        CheckConstraint(
            "confirmation_status <> 'confirmed' OR currency IS NOT NULL",
            name="confirmed_currency_required",
        ),
        CheckConstraint(
            "jsonb_typeof(field_evidence_json) = 'object'",
            name="field_evidence_object",
        ),
        CheckConstraint(
            "critical_fact_hash ~ '^[0-9a-f]{64}$'",
            name="critical_fact_hash_format",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        CheckConstraint(
            "(confirmation_status = 'unconfirmed' AND status = 'draft' "
            "AND confirmed_by IS NULL AND confirmed_at IS NULL) OR "
            "(confirmation_status = 'confirmed' AND status IN "
            "('confirmed', 'voided', 'archived') AND confirmed_by IS NOT NULL "
            "AND confirmed_at IS NOT NULL) OR "
            "(confirmation_status = 'rejected' AND status = 'draft' "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="confirmation_matrix",
        ),
        CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        Index(
            "idx_invoices_duplicate_lookup",
            "organization_id",
            "invoice_code",
            "invoice_number",
            "seller_tax_no",
            postgresql_where=text("deleted_at IS NULL AND status <> 'voided'"),
        ),
        Index(
            "idx_invoices_org_date",
            "organization_id",
            text("invoice_date DESC"),
        ),
        Index("idx_invoices_seller_tax", "organization_id", "seller_tax_no"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_invoices_organization_id_organizations"),
        nullable=False,
    )
    invoice_code: Mapped[str | None] = mapped_column(String(50))
    invoice_number: Mapped[str | None] = mapped_column(String(50))
    invoice_type: Mapped[str | None] = mapped_column(String(40))
    is_red_invoice: Mapped[bool | None] = mapped_column(Boolean)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    buyer_name: Mapped[str | None] = mapped_column(String(300))
    buyer_tax_no: Mapped[str | None] = mapped_column(String(32))
    seller_name: Mapped[str | None] = mapped_column(String(300))
    seller_tax_no: Mapped[str | None] = mapped_column(String(32))
    supplier_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "suppliers.id",
            name="fk_invoices_supplier_id_suppliers",
            use_alter=True,
        ),
    )
    amount_excluding_tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    confirmation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    duplicate_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'not_checked'")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    field_evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    confirmed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_invoices_confirmed_by_users"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    critical_fact_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_invoices_created_by_users"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_invoices_updated_by_users"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_invoices_deleted_by_users"),
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)


class Supplier(Base):
    """候选、活动或停用供应商主数据。"""

    __tablename__ = "suppliers"
    __table_args__ = (
        CheckConstraint(
            """
            unified_social_credit_code IS NULL OR (
                (unified_social_credit_code COLLATE "C") <> ('' COLLATE "C")
                AND (unified_social_credit_code COLLATE "C")
                    = (btrim(unified_social_credit_code, ' ') COLLATE "C")
                AND (unified_social_credit_code COLLATE "C")
                    !~ U&'[\\0001-\\001F\\007F-\\009F]'
                AND (unified_social_credit_code COLLATE "C") ~ '^[0-9A-Z]+$'
            )
            """,
            name="unified_social_credit_code_normalized",
        ),
        CheckConstraint(
            """
            tax_number IS NULL OR (
                (tax_number COLLATE "C") <> ('' COLLATE "C")
                AND (tax_number COLLATE "C") = (btrim(tax_number, ' ') COLLATE "C")
                AND (tax_number COLLATE "C")
                    !~ U&'[\\0001-\\001F\\007F-\\009F]'
            )
            """,
            name="tax_number_normalized",
        ),
        CheckConstraint(
            "unified_social_credit_code IS NULL OR tax_number IS NULL OR "
            '(unified_social_credit_code COLLATE "C") '
            '= (tax_number COLLATE "C")',
            name="tax_identity_sources_equal",
        ),
        CheckConstraint(
            "status <> 'active' OR COALESCE(unified_social_credit_code, tax_number) IS NOT NULL",
            name="active_tax_identity_required",
        ),
        CheckConstraint(
            "btrim(standard_name) <> '' AND standard_name = btrim(standard_name) "
            "AND standard_name !~ U&'[\\0001-\\001F\\007F-\\009F]'",
            name="standard_name_normalized",
        ),
        CheckConstraint(
            "source_type IN ('contract', 'invoice', 'manual')",
            name="source_type_allowed",
        ),
        CheckConstraint(
            """
            (source_type = 'contract'
                AND source_contract_id IS NOT NULL
                AND source_invoice_id IS NULL)
            OR (source_type = 'invoice'
                AND source_contract_id IS NULL
                AND source_invoice_id IS NOT NULL)
            OR (source_type = 'manual'
                AND source_contract_id IS NULL
                AND source_invoice_id IS NULL)
            """,
            name="source_reference_matches_type",
        ),
        CheckConstraint(
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        CheckConstraint(
            "status IN ('candidate', 'active', 'inactive')",
            name="status_allowed",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        CheckConstraint(
            "(confirmation_status = 'unconfirmed' AND status = 'candidate' "
            "AND confirmed_by IS NULL AND confirmed_at IS NULL) OR "
            "(confirmation_status = 'confirmed' AND status = 'active' "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL) OR "
            "(confirmation_status = 'rejected' AND status = 'inactive' "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="confirmation_matrix",
        ),
        CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        Index(
            "uq_suppliers_organization_tax_identity",
            "organization_id",
            text('(COALESCE(unified_social_credit_code, tax_number) COLLATE "C")'),
            unique=True,
            postgresql_where=text(
                "status = 'active' AND deleted_at IS NULL AND "
                "COALESCE(unified_social_credit_code, tax_number) IS NOT NULL"
            ),
        ),
        Index(
            "uq_suppliers_organization_source_contract_candidate",
            "organization_id",
            "source_contract_id",
            unique=True,
            postgresql_where=text(
                "status = 'candidate' AND deleted_at IS NULL AND source_contract_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_suppliers_organization_source_invoice_candidate",
            "organization_id",
            "source_invoice_id",
            unique=True,
            postgresql_where=text(
                "status = 'candidate' AND deleted_at IS NULL AND source_invoice_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_suppliers_organization_id_organizations"),
        nullable=False,
    )
    standard_name: Mapped[str] = mapped_column(String(300), nullable=False)
    unified_social_credit_code: Mapped[str | None] = mapped_column(String(32))
    tax_number: Mapped[str | None] = mapped_column(String(32))
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_contract_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "contracts.id",
            name="fk_suppliers_source_contract_id_contracts",
            use_alter=True,
        ),
    )
    source_invoice_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "invoices.id",
            name="fk_suppliers_source_invoice_id_invoices",
            use_alter=True,
        ),
    )
    confirmation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    confirmed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_suppliers_confirmed_by_users"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_suppliers_created_by_users"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_suppliers_updated_by_users"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_suppliers_deleted_by_users"),
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)


class SupplementaryAgreement(Base):
    """关联主合同且保留独立确认事实的补充协议。"""

    __tablename__ = "supplementary_agreements"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'pending_confirmation', 'confirmed', 'rejected', 'archived')",
            name="status_allowed",
        ),
        CheckConstraint(
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        CheckConstraint(
            "deleted_at IS NULL OR (delete_reason IS NOT NULL AND btrim(delete_reason) <> '')",
            name="soft_delete_reason_required",
        ),
        Index(
            "idx_supplementary_agreements_contract_effective_status",
            "contract_id",
            "effective_date",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            name="fk_supplementary_agreements_organization_id_organizations",
        ),
        nullable=False,
    )
    contract_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contracts.id", name="fk_supplementary_agreements_contract_id_contracts"),
        nullable=False,
    )
    agreement_no: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    signed_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    confirmation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    confirmed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_supplementary_agreements_confirmed_by_users"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_reason: Mapped[str | None] = mapped_column(Text)
    critical_fact_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_supplementary_agreements_created_by_users"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_supplementary_agreements_updated_by_users"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_supplementary_agreements_deleted_by_users"),
    )
    delete_reason: Mapped[str | None] = mapped_column(Text)


class ContractField(Base):
    """合同扩展字段的候选、确认值与原文证据。"""

    __tablename__ = "contract_fields"
    __table_args__ = (
        CheckConstraint(
            "(field_code COLLATE \"C\") ~ '^[a-z][a-z0-9_.]{0,79}$'",
            name="field_code_format",
        ),
        CheckConstraint(
            "value_type IN ('string', 'number', 'date', 'json')",
            name="value_type_allowed",
        ),
        CheckConstraint(
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="confidence_range",
        ),
        CheckConstraint("page_no IS NULL OR page_no > 0", name="page_no_positive"),
        CheckConstraint(
            "(evidence_file_id IS NULL AND evidence_parse_version_id IS NULL "
            "AND evidence_block_id IS NULL AND page_no IS NULL AND quote_text IS NULL "
            "AND bbox_json IS NULL) OR "
            "(evidence_file_id IS NOT NULL AND evidence_parse_version_id IS NOT NULL "
            "AND evidence_block_id IS NOT NULL AND page_no IS NOT NULL "
            "AND quote_text IS NOT NULL AND btrim(quote_text) <> '')",
            name="evidence_matrix",
        ),
        CheckConstraint(
            "bbox_json IS NULL OR jsonb_typeof(bbox_json) = 'object'",
            name="bbox_object",
        ),
        CheckConstraint(
            "extracted_value_json IS NOT NULL OR confirmed_value_json IS NOT NULL",
            name="value_present",
        ),
        CheckConstraint(
            "(confirmation_status = 'unconfirmed' AND confirmed_value_json IS NULL "
            "AND confirmed_by IS NULL AND confirmed_at IS NULL) OR "
            "(confirmation_status = 'confirmed' AND confirmed_value_json IS NOT NULL "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL "
            "AND evidence_block_id IS NOT NULL) OR "
            "(confirmation_status = 'rejected' AND confirmed_value_json IS NULL "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="confirmation_matrix",
        ),
        CheckConstraint(
            "(extracted_value_json IS NULL OR "
            "CASE value_type "
            "WHEN 'string' THEN jsonb_typeof(extracted_value_json) = 'string' "
            "WHEN 'number' THEN jsonb_typeof(extracted_value_json) = 'string' "
            "AND (extracted_value_json #>> '{}') ~ "
            "'^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$' "
            "WHEN 'date' THEN jsonb_typeof(extracted_value_json) = 'string' "
            "AND (extracted_value_json #>> '{}') ~ '^\\d{4}-\\d{2}-\\d{2}$' "
            "WHEN 'json' THEN jsonb_typeof(extracted_value_json) IN "
            "('object', 'array', 'boolean') ELSE false END) "
            "AND (confirmed_value_json IS NULL OR "
            "CASE value_type "
            "WHEN 'string' THEN jsonb_typeof(confirmed_value_json) = 'string' "
            "WHEN 'number' THEN jsonb_typeof(confirmed_value_json) = 'string' "
            "AND (confirmed_value_json #>> '{}') ~ "
            "'^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$' "
            "WHEN 'date' THEN jsonb_typeof(confirmed_value_json) = 'string' "
            "AND (confirmed_value_json #>> '{}') ~ '^\\d{4}-\\d{2}-\\d{2}$' "
            "WHEN 'json' THEN jsonb_typeof(confirmed_value_json) IN "
            "('object', 'array', 'boolean') ELSE false END)",
            name="value_shape",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        UniqueConstraint(
            "contract_id",
            "field_code",
            name="uq_contract_fields_contract_field",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    contract_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contracts.id", name="fk_contract_fields_contract_id_contracts"),
        nullable=False,
    )
    field_code: Mapped[str] = mapped_column(String(80), nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)
    extracted_value_json: Mapped[object | None] = mapped_column(JSONB(none_as_null=True))
    confirmed_value_json: Mapped[object | None] = mapped_column(JSONB(none_as_null=True))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    confirmation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_file_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("files.id", name="fk_contract_fields_evidence_file_id_files"),
    )
    evidence_parse_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "document_parse_versions.id",
            name="fk_contract_fields_evidence_parse",
        ),
    )
    evidence_block_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "document_blocks.id",
            name="fk_contract_fields_evidence_block",
        ),
    )
    page_no: Mapped[int | None] = mapped_column()
    quote_text: Mapped[str | None] = mapped_column(Text)
    bbox_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    confirmed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_contract_fields_confirmed_by_users"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")


class SupplementaryAgreementChange(Base):
    """补充协议对单个合同字段的当前变更事实。"""

    __tablename__ = "supplementary_agreement_changes"
    __table_args__ = (
        CheckConstraint(
            "(field_code COLLATE \"C\") ~ '^[a-z][a-z0-9_.]{0,79}$'",
            name="field_code_format",
        ),
        CheckConstraint(
            "value_type IN ('string', 'number', 'date', 'json')",
            name="value_type_allowed",
        ),
        CheckConstraint(
            "confirmation_status IN ('unconfirmed', 'confirmed', 'rejected')",
            name="confirmation_status_allowed",
        ),
        CheckConstraint("page_no IS NULL OR page_no > 0", name="page_no_positive"),
        CheckConstraint(
            "(evidence_block_id IS NULL AND page_no IS NULL AND quote_text IS NULL "
            "AND bbox_json IS NULL) OR "
            "(evidence_block_id IS NOT NULL AND page_no IS NOT NULL "
            "AND quote_text IS NOT NULL AND btrim(quote_text) <> '')",
            name="evidence_matrix",
        ),
        CheckConstraint(
            "bbox_json IS NULL OR jsonb_typeof(bbox_json) = 'object'",
            name="bbox_object",
        ),
        CheckConstraint(
            "(confirmation_status = 'unconfirmed' AND confirmed_by IS NULL "
            "AND confirmed_at IS NULL) OR "
            "(confirmation_status = 'confirmed' AND confirmed_by IS NOT NULL "
            "AND confirmed_at IS NOT NULL AND evidence_block_id IS NOT NULL) OR "
            "(confirmation_status = 'rejected' AND confirmed_by IS NOT NULL "
            "AND confirmed_at IS NOT NULL)",
            name="confirmation_matrix",
        ),
        CheckConstraint(
            "(old_value_json IS NULL OR jsonb_typeof(old_value_json) = 'null' OR "
            "CASE value_type "
            "WHEN 'string' THEN jsonb_typeof(old_value_json) = 'string' "
            "WHEN 'number' THEN jsonb_typeof(old_value_json) = 'string' "
            "AND (old_value_json #>> '{}') ~ '^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$' "
            "WHEN 'date' THEN jsonb_typeof(old_value_json) = 'string' "
            "AND (old_value_json #>> '{}') ~ '^\\d{4}-\\d{2}-\\d{2}$' "
            "WHEN 'json' THEN jsonb_typeof(old_value_json) IN "
            "('object', 'array', 'boolean') ELSE false END) "
            "AND (jsonb_typeof(new_value_json) = 'null' OR CASE value_type "
            "WHEN 'string' THEN jsonb_typeof(new_value_json) = 'string' "
            "WHEN 'number' THEN jsonb_typeof(new_value_json) = 'string' "
            "AND (new_value_json #>> '{}') ~ '^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$' "
            "WHEN 'date' THEN jsonb_typeof(new_value_json) = 'string' "
            "AND (new_value_json #>> '{}') ~ '^\\d{4}-\\d{2}-\\d{2}$' "
            "WHEN 'json' THEN jsonb_typeof(new_value_json) IN "
            "('object', 'array', 'boolean') ELSE false END)",
            name="value_shape",
        ),
        UniqueConstraint(
            "supplementary_agreement_id",
            "field_code",
            name="uq_supplementary_agreement_changes_agreement_field",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    supplementary_agreement_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "supplementary_agreements.id",
            name="fk_sagr_changes_agreement",
        ),
        nullable=False,
    )
    field_code: Mapped[str] = mapped_column(String(80), nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)
    old_value_json: Mapped[object | None] = mapped_column(JSONB)
    new_value_json: Mapped[object | None] = mapped_column(JSONB, nullable=False)
    evidence_block_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "document_blocks.id",
            name="fk_sagr_changes_evidence_block",
        ),
    )
    page_no: Mapped[int | None] = mapped_column()
    quote_text: Mapped[str | None] = mapped_column(Text)
    bbox_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    confirmation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    confirmed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            name="fk_sagr_changes_confirmed_by",
        ),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvoiceItem(Base):
    """发票明细行与字段证据。"""

    __tablename__ = "invoice_items"
    __table_args__ = (
        CheckConstraint("line_no > 0", name="line_no_positive"),
        CheckConstraint(
            "tax_rate IS NULL OR tax_rate BETWEEN 0 AND 1",
            name="tax_rate_bounds",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_json) = 'object'",
            name="evidence_object",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        UniqueConstraint(
            "invoice_id",
            "line_no",
            name="uq_invoice_items_invoice_id_line_no",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("invoices.id", name="fk_invoice_items_invoice_id_invoices"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(nullable=False)
    item_name: Mapped[str | None] = mapped_column(String(500))
    specification: Mapped[str | None] = mapped_column(String(300))
    unit: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    amount_excluding_tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")


class ContractInvoice(Base):
    """合同与发票之间保留历史的候选或主合同关系。"""

    __tablename__ = "contract_invoices"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'suggested', 'confirmed_primary', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint(
            "suggested_by IS NULL OR suggested_by IN ('system', 'user')",
            name="suggested_by_allowed",
        ),
        CheckConstraint(
            "status <> 'cancelled' OR (cancel_reason IS NOT NULL AND btrim(cancel_reason) <> '')",
            name="cancel_reason_required",
        ),
        Index(
            "uq_contract_invoice_pair_active",
            "contract_id",
            "invoice_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND status <> 'cancelled'"),
        ),
        Index(
            "uq_invoice_confirmed_primary_contract",
            "invoice_id",
            unique=True,
            postgresql_where=text("status = 'confirmed_primary' AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    contract_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contracts.id", name="fk_contract_invoices_contract_id_contracts"),
        nullable=False,
    )
    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("invoices.id", name="fk_contract_invoices_invoice_id_invoices"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    match_reasons_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    suggested_by: Mapped[str | None] = mapped_column(String(20))
    confirmed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_contract_invoices_confirmed_by_users"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_contract_invoices_cancelled_by_users"),
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_contract_invoices_created_by_users"),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
