from __future__ import annotations

import builtins
import os
import socket
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest

from app.ai.policy_resolver import (
    OperationValue,
    PolicyResolutionError,
    ProfileValue,
    ResolvedOperation,
    ResolvedTargetIdentity,
    resolve_policy_operations,
)


def profiles() -> tuple[ProfileValue, ...]:
    return (
        ProfileValue(
            "embedding_primary",
            "openai_embeddings_v1",
            "synthetic-internal-embedding-001",
            "synthetic-embedding-model",
            ("embedding",),
        ),
        ProfileValue(
            "llm_extraction_primary",
            "openai_chat_completions_v1",
            "synthetic-internal-extraction-001",
            "synthetic-extraction-model",
            ("llm_extraction",),
        ),
        ProfileValue(
            "llm_fallback",
            "openai_chat_completions_v1",
            "synthetic-internal-fallback-001",
            "synthetic-fallback-model",
            ("llm_extraction", "llm_generation"),
        ),
        ProfileValue(
            "llm_generation_primary",
            "openai_chat_completions_v1",
            "synthetic-internal-generation-001",
            "synthetic-generation-model",
            ("llm_generation",),
        ),
    )


def operations() -> tuple[OperationValue, ...]:
    return (
        OperationValue(
            "contract_field_extraction",
            "llm_extraction_primary",
            "llm_fallback",
            False,
        ),
        OperationValue("embedding", "embedding_primary", None, False),
        OperationValue(
            "invoice_field_extraction",
            "llm_extraction_primary",
            "llm_fallback",
            False,
        ),
        OperationValue("rag_answer", "llm_generation_primary", "llm_fallback", False),
        OperationValue("report_draft", "llm_generation_primary", None, False),
        OperationValue(
            "risk_explanation",
            "llm_generation_primary",
            "llm_fallback",
            False,
        ),
    )


def resolve(
    *,
    profile_values: tuple[ProfileValue, ...] | None = None,
    operation_values: tuple[OperationValue, ...] | None = None,
) -> tuple[ResolvedOperation, ...]:
    return resolve_policy_operations(
        profiles=profiles() if profile_values is None else profile_values,
        operations=operations() if operation_values is None else operation_values,
    )


def replace_operation(operation_id: str, **changes: object) -> tuple[OperationValue, ...]:
    return tuple(
        replace(operation, **cast(Any, changes))
        if operation.operation_id == operation_id
        else operation
        for operation in operations()
    )


def test_fixed_six_operation_graph_resolves_immutable_target_identities() -> None:
    routes = resolve()

    assert tuple(route.operation_id for route in routes) == (
        "contract_field_extraction",
        "embedding",
        "invoice_field_extraction",
        "rag_answer",
        "report_draft",
        "risk_explanation",
    )
    by_id = {route.operation_id: route for route in routes}
    assert by_id["contract_field_extraction"].primary == ResolvedTargetIdentity(
        "llm_extraction_primary",
        "openai_chat_completions_v1",
        "synthetic-internal-extraction-001",
        "synthetic-extraction-model",
    )
    assert by_id["contract_field_extraction"].fallback == ResolvedTargetIdentity(
        "llm_fallback",
        "openai_chat_completions_v1",
        "synthetic-internal-fallback-001",
        "synthetic-fallback-model",
    )
    assert by_id["embedding"].fallback is None
    assert by_id["report_draft"].fallback is None

    primary = by_id["embedding"].primary
    with pytest.raises(AttributeError):
        object.__setattr__(primary, "model_id", "mutation")
    assert by_id["embedding"].primary == primary

    with pytest.raises(AttributeError):
        object.__setattr__(by_id["embedding"], "primary", by_id["report_draft"].primary)
    assert by_id["embedding"].primary == primary


def test_stable_endpoint_id_accepts_200_and_rejects_201_ascii_characters() -> None:
    valid = list(profiles())
    valid[0] = replace(valid[0], endpoint_id="e" * 200)
    routes = resolve(profile_values=tuple(valid))
    embedding = next(route for route in routes if route.operation_id == "embedding")
    assert embedding.primary.endpoint_id == "e" * 200

    invalid = list(profiles())
    invalid[0] = replace(invalid[0], endpoint_id="e" * 201)
    with pytest.raises(PolicyResolutionError):
        resolve(profile_values=tuple(invalid))


def test_uninitialized_profile_is_reported_as_fixed_resolution_error() -> None:
    incomplete = object.__new__(ProfileValue)

    with pytest.raises(PolicyResolutionError) as exc_info:
        resolve(profile_values=(incomplete,))

    assert str(exc_info.value) == "AI_POLICY_ROUTE_GRAPH_INVALID"


def test_uninitialized_operation_is_reported_as_fixed_resolution_error() -> None:
    incomplete = object.__new__(OperationValue)

    with pytest.raises(PolicyResolutionError) as exc_info:
        resolve(operation_values=(incomplete,) + operations()[1:])

    assert str(exc_info.value) == "AI_POLICY_ROUTE_GRAPH_INVALID"


@pytest.mark.parametrize(
    "operation_values",
    [
        operations()[:-1],
        operations() + (OperationValue("extra", "embedding_primary", None, False),),
        operations() + (operations()[0],),
    ],
)
def test_operation_set_must_be_exactly_six_and_unique(
    operation_values: tuple[OperationValue, ...],
) -> None:
    with pytest.raises(PolicyResolutionError):
        resolve(operation_values=operation_values)


@pytest.mark.parametrize(
    "operation_id",
    [
        "contract_field_extraction",
        "invoice_field_extraction",
        "rag_answer",
        "risk_explanation",
    ],
)
def test_four_llm_operations_require_a_distinct_fallback(operation_id: str) -> None:
    with pytest.raises(PolicyResolutionError):
        resolve(operation_values=replace_operation(operation_id, fallback_profile_id=None))
    primary = next(
        value.primary_profile_id for value in operations() if value.operation_id == operation_id
    )
    with pytest.raises(PolicyResolutionError):
        resolve(operation_values=replace_operation(operation_id, fallback_profile_id=primary))


@pytest.mark.parametrize(
    "operation_values",
    [
        replace_operation("report_draft", report_use_fallback=True),
        replace_operation("report_draft", fallback_profile_id="llm_fallback"),
        replace_operation("risk_explanation", report_use_fallback=True),
        replace_operation("embedding", fallback_profile_id="llm_fallback"),
    ],
)
def test_report_flag_and_embedding_fallback_fail_closed(
    operation_values: tuple[OperationValue, ...],
) -> None:
    with pytest.raises(PolicyResolutionError):
        resolve(operation_values=operation_values)


def test_report_fallback_resolves_when_flag_and_capability_match() -> None:
    routes = resolve(
        operation_values=replace_operation(
            "report_draft",
            fallback_profile_id="llm_fallback",
            report_use_fallback=True,
        )
    )
    report = next(route for route in routes if route.operation_id == "report_draft")
    assert report.fallback is not None
    assert report.fallback.profile_id == "llm_fallback"


@pytest.mark.parametrize(
    "operation_values",
    [
        replace_operation("embedding", primary_profile_id="missing"),
        replace_operation("rag_answer", fallback_profile_id="missing"),
        replace_operation("embedding", primary_profile_id="llm_generation_primary"),
        replace_operation("rag_answer", primary_profile_id="llm_extraction_primary"),
        replace_operation(
            "contract_field_extraction",
            fallback_profile_id="llm_generation_primary",
        ),
    ],
)
def test_missing_references_and_capability_mismatches_fail_closed(
    operation_values: tuple[OperationValue, ...],
) -> None:
    with pytest.raises(PolicyResolutionError):
        resolve(operation_values=operation_values)


def test_unused_profile_and_duplicate_target_identity_fail_closed() -> None:
    unused = ProfileValue(
        "unused",
        "openai_chat_completions_v1",
        "unused-endpoint",
        "unused-model",
        ("llm_generation",),
    )
    with pytest.raises(PolicyResolutionError):
        resolve(profile_values=profiles() + (unused,))

    duplicate = replace(profiles()[0], profile_id="embedding_duplicate")
    with pytest.raises(PolicyResolutionError):
        resolve(profile_values=profiles() + (duplicate,))

    duplicate_profile_id = replace(
        profiles()[0],
        endpoint_id="different-endpoint",
        model_id="different-model",
    )
    with pytest.raises(PolicyResolutionError):
        resolve(profile_values=profiles() + (duplicate_profile_id,))


@pytest.mark.parametrize(
    ("profile_index", "profile_value"),
    [
        (0, replace(profiles()[0], profile_id="UPPERCASE")),
        (0, replace(profiles()[0], adapter_id=cast(Any, "unknown"))),
        (0, replace(profiles()[0], capabilities=cast(Any, "embedding"))),
        (0, replace(profiles()[0], capabilities=cast(Any, ("llm_generation",)))),
        (1, replace(profiles()[1], capabilities=cast(Any, ("embedding",)))),
        (1, replace(profiles()[1], endpoint_id="")),
        (1, replace(profiles()[1], model_id=cast(Any, 1))),
    ],
)
def test_profile_type_and_adapter_capability_matrix_fail_closed(
    profile_index: int,
    profile_value: ProfileValue,
) -> None:
    mutated = list(profiles())
    mutated[profile_index] = profile_value
    with pytest.raises(PolicyResolutionError):
        resolve(profile_values=tuple(mutated))


def test_bare_collections_and_wrong_operation_types_fail_closed() -> None:
    with pytest.raises(PolicyResolutionError):
        resolve_policy_operations(
            profiles=cast(Any, "profiles"),
            operations=operations(),
        )
    with pytest.raises(PolicyResolutionError):
        resolve_policy_operations(
            profiles=profiles(),
            operations=cast(Any, list(operations())),
        )
    wrong = replace(operations()[0], report_use_fallback=cast(Any, 0))
    with pytest.raises(PolicyResolutionError):
        resolve(operation_values=(wrong,) + operations()[1:])


def test_errors_do_not_render_raw_identifiers() -> None:
    sentinel = "synthetic-secret-route-must-not-be-rendered"
    operation_values = replace_operation("embedding", primary_profile_id=sentinel)

    with pytest.raises(PolicyResolutionError) as exc_info:
        resolve(operation_values=operation_values)

    assert str(exc_info.value) == "AI_POLICY_ROUTE_GRAPH_INVALID"
    assert sentinel not in str(exc_info.value)


def test_resolver_uses_no_runtime_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_call(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise AssertionError("policy resolver must use only injected pure values")

    monkeypatch.setattr(builtins, "open", unexpected_call)
    monkeypatch.setattr(os, "getenv", unexpected_call)
    monkeypatch.setattr(Path, "read_bytes", unexpected_call)
    monkeypatch.setattr(socket, "socket", unexpected_call)
    monkeypatch.setattr(socket, "create_connection", unexpected_call)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected_call)
    monkeypatch.setattr(time, "sleep", unexpected_call)

    assert len(resolve()) == 6
