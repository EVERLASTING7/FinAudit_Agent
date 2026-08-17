from __future__ import annotations

import copy
import json
import random
import socket
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, StrictInt, field_validator

from app.ai import structured_output
from app.ai.output_validation import RagAnswerOutput
from app.ai.structured_output import (
    StructuredOutputIssue,
    StructuredOutputIssueCategory,
    StructuredOutputValidationError,
    validate_structured_output,
)


class ExampleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: StrictInt
    status: Literal["ok", "rejected"]
    evidence: dict[str, StrictInt]


VALID_JSON = '{"amount":12,"status":"ok","evidence":{"line":3}}'


class FloatOutput(BaseModel):
    value: float


class StringOutput(BaseModel):
    value: str


@pytest.mark.parametrize(
    "raw_output",
    [
        VALID_JSON,
        f"```json\n{VALID_JSON}\n```",
        f"```\n{VALID_JSON}\n```",
        f"模型输出如下：\n{VALID_JSON}\n以上。",
        f"{VALID_JSON}\n以上。",
    ],
)
def test_deterministic_cleanup_accepts_only_one_object_without_network(
    monkeypatch: pytest.MonkeyPatch,
    raw_output: str,
) -> None:
    def fail_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("structured output cleanup must not open sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)

    result = validate_structured_output(raw_output, ExampleOutput)

    assert result == ExampleOutput(amount=12, status="ok", evidence={"line": 3})


@pytest.mark.parametrize(
    "raw_output",
    [
        "",
        "[]",
        '[{"amount":12,"status":"ok","evidence":{"line":3}}]',
        '{"amount":12',
        f'{{"wrapper":{VALID_JSON}',
        f"{VALID_JSON}\n{VALID_JSON}",
        f"```json\n{VALID_JSON}\n```\n```json\n{VALID_JSON}\n```",
        f"```json\n{VALID_JSON}\n``` trailing",
        f"prefix [{VALID_JSON}] suffix",
        f"prefix [[{VALID_JSON}]] suffix",
        f"```json\nprefix [{VALID_JSON}] suffix\n```",
        f'prefix {{"wrapper":{VALID_JSON}',
        f"prefix [{VALID_JSON}",
        f'{VALID_JSON} trailing [{{"second":1}}]',
        '{"amount":12,"amount":13,"status":"ok","evidence":{"line":3}}',
        '{"amount":12,"status":"ok","evidence":{"line":3,"\\u006cine":4}}',
        '{"amount":NaN,"status":"ok","evidence":{"line":3}}',
        '{"amount":Infinity,"status":"ok","evidence":{"line":3}}',
        '{"amount":-Infinity,"status":"ok","evidence":{"line":3}}',
    ],
)
def test_cleanup_rejects_invalid_ambiguous_or_non_object_json(raw_output: str) -> None:
    with pytest.raises(StructuredOutputValidationError) as exc_info:
        validate_structured_output(raw_output, ExampleOutput)

    assert exc_info.value.code == "AI_SCHEMA_VALIDATION_FAILED"
    assert exc_info.value.issues == (StructuredOutputIssue("", StructuredOutputIssueCategory.JSON),)
    assert exc_info.value.__context__ is None
    assert exc_info.value.__cause__ is None


def test_cleanup_rejects_many_disjoint_objects_without_quadratic_span_comparison() -> None:
    with pytest.raises(StructuredOutputValidationError):
        validate_structured_output("prefix " + "{} " * 10_000, ExampleOutput)


def test_cleanup_stops_after_first_malformed_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_decoder = structured_output._DECODER

    class CountingDecoder:
        calls = 0

        def raw_decode(self, value: str, index: int = 0) -> tuple[object, int]:
            self.calls += 1
            return original_decoder.raw_decode(value, index)

    decoder = CountingDecoder()
    monkeypatch.setattr(structured_output, "_DECODER", decoder)

    with pytest.raises(StructuredOutputValidationError):
        validate_structured_output("prefix " + "[" * 10_000 + "0", ExampleOutput)

    assert decoder.calls == 2


@pytest.mark.parametrize(
    "raw_output",
    ['{"value":"```"}', '```json\n{"value":"```"}\n```'],
)
def test_json_string_containing_backticks_is_not_treated_as_a_fence(
    raw_output: str,
) -> None:
    assert validate_structured_output(raw_output, StringOutput).value == "```"


def test_schema_errors_expose_only_pointer_and_safe_category() -> None:
    sentinel = "SENSITIVE_FAILURE_VALUE"
    raw_output = (
        '{"amount":"SENSITIVE_FAILURE_VALUE","status":"unknown",'
        '"evidence":{"line":"SENSITIVE_FAILURE_VALUE"},"secret":"SENSITIVE_FAILURE_VALUE"}'
    )

    with pytest.raises(StructuredOutputValidationError) as exc_info:
        validate_structured_output(raw_output, ExampleOutput)

    assert exc_info.value.issues == (
        StructuredOutputIssue("/*", StructuredOutputIssueCategory.SCHEMA),
        StructuredOutputIssue("/amount", StructuredOutputIssueCategory.TYPE),
        StructuredOutputIssue("/evidence/*", StructuredOutputIssueCategory.TYPE),
        StructuredOutputIssue("/status", StructuredOutputIssueCategory.ENUM),
    )
    assert sentinel not in str(exc_info.value)
    assert sentinel not in repr(exc_info.value)
    assert sentinel not in repr(exc_info.value.issues)
    assert exc_info.value.__context__ is None
    assert exc_info.value.__cause__ is None


def test_dynamic_or_control_character_keys_are_masked_from_safe_pointers() -> None:
    raw_output = (
        '{"amount":12,"status":"ok","evidence":{"SENSITIVE_DYNAMIC_KEY":"bad"},'
        '"SENSITIVE_EXTRA\\nKEY":1}'
    )

    with pytest.raises(StructuredOutputValidationError) as exc_info:
        validate_structured_output(raw_output, ExampleOutput)

    assert exc_info.value.issues == (
        StructuredOutputIssue("/*", StructuredOutputIssueCategory.SCHEMA),
        StructuredOutputIssue("/evidence/*", StructuredOutputIssueCategory.TYPE),
    )
    assert "SENSITIVE" not in repr(exc_info.value.issues)
    assert "\n" not in "".join(issue.pointer for issue in exc_info.value.issues)


def test_custom_validator_exceptions_are_normalized_without_leaking_values() -> None:
    sentinel = "SENSITIVE_VALIDATOR_VALUE"

    class ExplodingOutput(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def reject_value(cls, value: str) -> str:
            raise TypeError(f"validator rejected {value}")

    with pytest.raises(StructuredOutputValidationError) as exc_info:
        validate_structured_output(f'{{"value":"{sentinel}"}}', ExplodingOutput)

    assert exc_info.value.issues == (
        StructuredOutputIssue("", StructuredOutputIssueCategory.SCHEMA),
    )
    assert sentinel not in str(exc_info.value)
    assert sentinel not in repr(exc_info.value)
    assert exc_info.value.__context__ is None
    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize("value", ["1e999", "-1e999"])
def test_cleanup_rejects_numbers_that_overflow_to_non_finite_float(value: str) -> None:
    with pytest.raises(StructuredOutputValidationError) as exc_info:
        validate_structured_output(f'{{"value":{value}}}', FloatOutput)

    assert exc_info.value.issues == (StructuredOutputIssue("", StructuredOutputIssueCategory.JSON),)


@pytest.mark.parametrize(
    "raw_output",
    [
        '{"value":' + "1" * 5_000 + "}",
        '{"value":-' + "1" * 5_000 + "}",
        '{"value":' * 1_100 + "0" + "}" * 1_100,
        '{"value":' + "[" * 1_100 + "0" + "]" * 1_100 + "}",
        '{"value":"\\ud800"}',
        '{"value":"\\udc00"}',
    ],
)
def test_cleanup_normalizes_pathological_json_parser_failures(raw_output: str) -> None:
    with pytest.raises(StructuredOutputValidationError) as exc_info:
        validate_structured_output(raw_output, FloatOutput)

    assert exc_info.value.code == "AI_SCHEMA_VALIDATION_FAILED"
    assert exc_info.value.issues == (StructuredOutputIssue("", StructuredOutputIssueCategory.JSON),)


def test_missing_field_uses_required_category_and_masks_dynamic_pointer_tokens() -> None:
    class RequiredValue(BaseModel):
        required: StrictInt

    class PointerOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")

        value: dict[str, RequiredValue]

    with pytest.raises(StructuredOutputValidationError) as exc_info:
        validate_structured_output('{"value":{"a/b":{}}}', PointerOutput)

    assert exc_info.value.issues == (
        StructuredOutputIssue("/value/*/*", StructuredOutputIssueCategory.REQUIRED),
    )


def test_fixed_seed_schema_mutations_fail_closed_without_leaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("structured output validation must not open sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    baseline: dict[str, object] = {
        "answer_status": "answered",
        "answer": "Supported answer",
        "reason_code": None,
        "citations": [
            {
                "candidate_id": "10000000-0000-0000-0000-000000000001",
                "policy_document_id": "20000000-0000-0000-0000-000000000001",
                "policy_version": "1.0.0",
                "markdown_version_id": "30000000-0000-0000-0000-000000000001",
                "chunk_id": "40000000-0000-0000-0000-000000000001",
                "block_ids": ["60000000-0000-4000-8000-000000000001"],
                "index_version_id": "50000000-0000-0000-0000-000000000001",
                "page_range": "1-2",
                "title_path": ["Payments", "Approval"],
                "quote": "approved RAG evidence",
                "content_sha256": "a" * 64,
            }
        ],
        "confidence": "0.91",
        "warnings": [],
    }
    assert validate_structured_output(json.dumps(baseline), RagAnswerOutput)

    operators = ("missing", "enum", "type", "extra", "nested", "matrix")
    rng = random.Random(0xA1002)
    seen: set[str] = set()
    for case_index in range(24):
        operator = operators[case_index % len(operators)]
        seen.add(operator)
        sentinel = f"FUZZ_{case_index}_{rng.getrandbits(64):016x}"
        payload = copy.deepcopy(baseline)
        payload["answer"] = sentinel

        if operator == "missing":
            del payload["warnings"]
        elif operator == "enum":
            payload["answer_status"] = sentinel
        elif operator == "type":
            payload["citations"] = {"bad": sentinel}
        elif operator == "extra":
            payload[f"extra_{sentinel}"] = sentinel
        elif operator == "nested":
            citations = payload["citations"]
            assert isinstance(citations, list)
            citation = citations[0]
            assert isinstance(citation, dict)
            citation["candidate_id"] = sentinel
        else:
            payload["reason_code"] = "NO_RELEVANT_EVIDENCE"

        with pytest.raises(StructuredOutputValidationError) as exc_info:
            validate_structured_output(
                json.dumps(payload, ensure_ascii=False),
                RagAnswerOutput,
            )

        rendered = "\n".join(
            (str(exc_info.value), repr(exc_info.value), repr(exc_info.value.issues))
        )
        assert exc_info.value.code == "AI_SCHEMA_VALIDATION_FAILED"
        assert 0 < len(exc_info.value.issues) <= 32
        assert sentinel not in rendered
        assert exc_info.value.__context__ is None
        assert exc_info.value.__cause__ is None

    assert seen == set(operators)


@pytest.mark.parametrize("invalid_model_type", [object, BaseModel, 1, None])
def test_validation_rejects_invalid_model_types(invalid_model_type: object) -> None:
    with pytest.raises(TypeError):
        validate_structured_output(VALID_JSON, invalid_model_type)  # type: ignore[arg-type]


def test_validation_rejects_non_string_output() -> None:
    with pytest.raises(TypeError):
        validate_structured_output(b"{}", ExampleOutput)  # type: ignore[arg-type]
