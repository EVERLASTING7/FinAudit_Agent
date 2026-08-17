from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.files import FileUploadIntent, IntendedBusinessType

EXPECTED_BUSINESS_TYPES = (
    "contract",
    "supplementary_agreement",
    "invoice",
    "policy",
)
KNOWLEDGE_BASE_ID = UUID("50000000-0000-0000-0000-000000000001")


def test_upload_intent_schema_has_exact_business_types_and_forbids_extra_fields() -> None:
    schema = FileUploadIntent.model_json_schema()

    assert tuple(item.value for item in IntendedBusinessType) == EXPECTED_BUSINESS_TYPES
    assert schema["$defs"]["IntendedBusinessType"]["enum"] == list(EXPECTED_BUSINESS_TYPES)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["target_knowledge_base_id"]["anyOf"] == [
        {"format": "uuid", "type": "string"},
        {"type": "null"},
    ]
    assert schema["properties"]["auto_process_requested"]["default"] is True
    assert schema["properties"]["auto_process_requested"]["type"] == "boolean"


@pytest.mark.parametrize(
    "business_type",
    [
        IntendedBusinessType.CONTRACT,
        IntendedBusinessType.SUPPLEMENTARY_AGREEMENT,
        IntendedBusinessType.INVOICE,
    ],
)
def test_non_policy_uploads_require_a_null_knowledge_base_target(
    business_type: IntendedBusinessType,
) -> None:
    intent = FileUploadIntent.model_validate({"intended_business_type": business_type.value})

    assert intent.intended_business_type is business_type
    assert intent.target_knowledge_base_id is None
    assert intent.auto_process_requested is True


def test_policy_upload_requires_and_parses_a_uuid_knowledge_base_target() -> None:
    intent = FileUploadIntent.model_validate(
        {
            "intended_business_type": "policy",
            "target_knowledge_base_id": str(KNOWLEDGE_BASE_ID),
            "auto_process_requested": False,
        }
    )

    assert intent.intended_business_type is IntendedBusinessType.POLICY
    assert intent.target_knowledge_base_id == KNOWLEDGE_BASE_ID
    assert intent.auto_process_requested is False
    assert intent.model_dump(mode="json") == {
        "intended_business_type": "policy",
        "target_knowledge_base_id": str(KNOWLEDGE_BASE_ID),
        "auto_process_requested": False,
    }


def test_policy_upload_rejects_a_missing_or_null_knowledge_base_target() -> None:
    payload: dict[str, object] = {
        "intended_business_type": "policy",
        "target_knowledge_base_id": None,
    }
    with pytest.raises(ValidationError):
        FileUploadIntent.model_validate(payload)

    payload.pop("target_knowledge_base_id")
    with pytest.raises(ValidationError):
        FileUploadIntent.model_validate(payload)


@pytest.mark.parametrize(
    "business_type",
    ["contract", "supplementary_agreement", "invoice"],
)
def test_non_policy_upload_rejects_a_knowledge_base_target(business_type: str) -> None:
    with pytest.raises(ValidationError):
        FileUploadIntent.model_validate(
            {
                "intended_business_type": business_type,
                "target_knowledge_base_id": str(KNOWLEDGE_BASE_ID),
            }
        )


@pytest.mark.parametrize(
    "invalid_business_type",
    ["POLICY", "agreement", "", None, True, 1],
)
def test_upload_intent_rejects_unknown_or_wrong_typed_business_types(
    invalid_business_type: object,
) -> None:
    with pytest.raises(ValidationError):
        FileUploadIntent.model_validate(
            {
                "intended_business_type": invalid_business_type,
                "target_knowledge_base_id": str(KNOWLEDGE_BASE_ID),
            }
        )


@pytest.mark.parametrize("invalid_value", ["true", "false", 1, 0, None, [], {}])
def test_auto_process_requested_is_a_strict_boolean(invalid_value: object) -> None:
    with pytest.raises(ValidationError):
        FileUploadIntent.model_validate(
            {
                "intended_business_type": "contract",
                "auto_process_requested": invalid_value,
            }
        )


def test_upload_intent_rejects_invalid_uuid_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        FileUploadIntent.model_validate(
            {
                "intended_business_type": "policy",
                "target_knowledge_base_id": "not-a-uuid",
            }
        )

    with pytest.raises(ValidationError):
        FileUploadIntent.model_validate(
            {
                "intended_business_type": "contract",
                "unexpected": "value",
            }
        )
