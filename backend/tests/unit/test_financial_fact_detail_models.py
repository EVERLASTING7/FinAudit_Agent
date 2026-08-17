from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models import Base
from app.models.corrections import CORRECTION_TYPES
from app.models.financial import FINANCIAL_FIELD_VALUE_TYPES


def _columns(table_name: str) -> tuple[str, ...]:
    return tuple(column.name for column in Base.metadata.tables[table_name].columns)


def _unique_names(table_name: str) -> set[str]:
    return {
        constraint.name
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name is not None
    }


def _check_names(table_name: str) -> set[str]:
    return {
        constraint.name
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def test_contract_field_model_has_value_evidence_and_confirmation_boundaries() -> None:
    assert FINANCIAL_FIELD_VALUE_TYPES == ("string", "number", "date", "json")
    assert _columns("contract_fields") == (
        "id",
        "contract_id",
        "field_code",
        "value_type",
        "extracted_value_json",
        "confirmed_value_json",
        "confidence",
        "confirmation_status",
        "evidence_file_id",
        "evidence_parse_version_id",
        "evidence_block_id",
        "page_no",
        "quote_text",
        "bbox_json",
        "confirmed_by",
        "confirmed_at",
        "row_version",
    )
    assert _unique_names("contract_fields") == {"uq_contract_fields_contract_field"}
    assert {
        "ck_contract_fields_field_code_format",
        "ck_contract_fields_value_shape",
        "ck_contract_fields_evidence_matrix",
        "ck_contract_fields_confirmation_matrix",
        "ck_contract_fields_row_version_positive",
    } <= _check_names("contract_fields")


def test_supplementary_change_model_is_one_current_change_per_field() -> None:
    assert _columns("supplementary_agreement_changes") == (
        "id",
        "supplementary_agreement_id",
        "field_code",
        "value_type",
        "old_value_json",
        "new_value_json",
        "evidence_block_id",
        "page_no",
        "quote_text",
        "bbox_json",
        "confirmation_status",
        "confirmed_by",
        "confirmed_at",
    )
    assert _unique_names("supplementary_agreement_changes") == {
        "uq_supplementary_agreement_changes_agreement_field"
    }


def test_file_primary_business_object_model_is_mutually_exclusive() -> None:
    assert _columns("file_primary_business_objects") == (
        "id",
        "file_id",
        "business_type",
        "contract_id",
        "invoice_id",
        "supplementary_agreement_id",
        "policy_document_id",
        "bound_at",
        "bound_by",
    )
    assert _unique_names("file_primary_business_objects") == {
        "uq_file_primary_business_objects_file_id",
        "uq_file_primary_business_objects_contract_id",
        "uq_file_primary_business_objects_invoice_id",
        "uq_file_primary_business_objects_supplementary_agreement_id",
        "uq_file_primary_business_objects_policy_document_id",
    }
    assert "ck_file_primary_business_objects_business_object_matrix" in _check_names(
        "file_primary_business_objects"
    )


def test_user_correction_model_is_append_only_payload_shape() -> None:
    assert CORRECTION_TYPES == (
        "contract_field",
        "supplementary_agreement_changes",
        "invoice_field",
        "contract_invoice",
        "supplier_field",
        "audit_risk",
    )
    assert _columns("user_corrections") == (
        "id",
        "organization_id",
        "correction_type",
        "object_type",
        "object_id",
        "field_path",
        "before_value_json",
        "after_value_json",
        "reason",
        "actor_id",
        "actor_role_code",
        "related_execution_id",
        "caused_outdated",
        "created_at",
        "trace_id",
    )
    assert {
        "ck_user_corrections_value_present",
        "ck_user_corrections_value_objects",
        "ck_user_corrections_reason_nonempty",
    } <= _check_names("user_corrections")
