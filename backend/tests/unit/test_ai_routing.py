import socket
import time
from collections.abc import Callable, MutableMapping
from dataclasses import FrozenInstanceError, replace
from inspect import Parameter, signature
from typing import cast

import pytest

import app.ai.routing as ai_routing
from app.ai.contracts import ModelRoute, ModelTarget
from app.ai.routing import (
    P0AiPurpose,
    P0AiRoutingConfig,
    P0RateLimitPool,
    build_p0_model_routes,
    rate_limit_pool_for_purpose,
)

CONFIG = P0AiRoutingConfig(
    llm_adapter_id="llm-compatible",
    embedding_adapter_id="embedding-compatible",
    extraction_model_id="extraction-model",
    generation_model_id="generation-model",
    fallback_model_id="fallback-model",
    report_draft_uses_fallback=False,
    embedding_model_id="embedding-model",
)

EXTRACTION_PURPOSES = {
    P0AiPurpose.CONTRACT_FIELD_EXTRACTION.value,
    P0AiPurpose.INVOICE_FIELD_EXTRACTION.value,
}
GENERATION_PURPOSES = {
    P0AiPurpose.RISK_EXPLANATION.value,
    P0AiPurpose.RAG_ANSWER.value,
    P0AiPurpose.REPORT_DRAFT.value,
}
REQUIRED_FALLBACK_PURPOSES = EXTRACTION_PURPOSES | {
    P0AiPurpose.RISK_EXPLANATION.value,
    P0AiPurpose.RAG_ANSWER.value,
}


@pytest.mark.parametrize(
    ("purpose", "expected"),
    [
        (P0AiPurpose.CONTRACT_FIELD_EXTRACTION, P0RateLimitPool.ASYNC_GENERATION),
        (P0AiPurpose.INVOICE_FIELD_EXTRACTION, P0RateLimitPool.ASYNC_GENERATION),
        (P0AiPurpose.RISK_EXPLANATION, P0RateLimitPool.ASYNC_GENERATION),
        (P0AiPurpose.RAG_ANSWER, P0RateLimitPool.RAG),
        (P0AiPurpose.REPORT_DRAFT, P0RateLimitPool.ASYNC_GENERATION),
        (P0AiPurpose.EMBEDDING, P0RateLimitPool.EMBEDDING),
    ],
)
def test_selects_approved_rate_limit_pool(
    purpose: P0AiPurpose,
    expected: P0RateLimitPool,
) -> None:
    assert rate_limit_pool_for_purpose(purpose) is expected


@pytest.mark.parametrize("invalid", ["rag_answer", "embedding", None, 1])
def test_rate_limit_pool_rejects_unregistered_or_wrong_types(invalid: object) -> None:
    with pytest.raises(ValueError, match="registered P0AiPurpose"):
        rate_limit_pool_for_purpose(cast(P0AiPurpose, invalid))


def test_rate_limit_pool_mapping_is_immutable() -> None:
    mutable_mapping = cast(
        MutableMapping[P0AiPurpose, P0RateLimitPool],
        ai_routing._RATE_LIMIT_POOL_BY_PURPOSE,
    )

    with pytest.raises(TypeError):
        mutable_mapping[P0AiPurpose.RAG_ANSWER] = P0RateLimitPool.ASYNC_GENERATION


def test_builds_all_six_routes_with_required_fallback() -> None:
    routes = build_p0_model_routes(CONFIG)
    fallback = ModelTarget(CONFIG.llm_adapter_id, CONFIG.fallback_model_id)

    assert set(routes) == {purpose.value for purpose in P0AiPurpose}
    assert all(route.purpose == purpose for purpose, route in routes.items())
    for purpose in EXTRACTION_PURPOSES:
        assert routes[purpose].candidates == (
            ModelTarget(CONFIG.llm_adapter_id, CONFIG.extraction_model_id),
            fallback,
        )
    for purpose in GENERATION_PURPOSES - {P0AiPurpose.REPORT_DRAFT.value}:
        assert routes[purpose].candidates == (
            ModelTarget(CONFIG.llm_adapter_id, CONFIG.generation_model_id),
            fallback,
        )
    assert routes[P0AiPurpose.REPORT_DRAFT.value].candidates == (
        ModelTarget(CONFIG.llm_adapter_id, CONFIG.generation_model_id),
    )
    assert routes[P0AiPurpose.EMBEDDING.value].candidates == (
        ModelTarget(CONFIG.embedding_adapter_id, CONFIG.embedding_model_id),
    )


def test_report_false_keeps_report_and_embedding_on_single_candidates() -> None:
    routes = build_p0_model_routes(CONFIG)

    for purpose in REQUIRED_FALLBACK_PURPOSES:
        assert routes[purpose].candidates[1:] == (
            ModelTarget(CONFIG.llm_adapter_id, CONFIG.fallback_model_id),
        )
    assert routes[P0AiPurpose.REPORT_DRAFT.value].candidates == (
        ModelTarget(CONFIG.llm_adapter_id, CONFIG.generation_model_id),
    )
    assert routes[P0AiPurpose.EMBEDDING.value].candidates == (
        ModelTarget(CONFIG.embedding_adapter_id, CONFIG.embedding_model_id),
    )


def test_explicitly_enables_report_fallback() -> None:
    config = replace(
        CONFIG,
        report_draft_uses_fallback=True,
    )

    assert build_p0_model_routes(config)[P0AiPurpose.REPORT_DRAFT.value].candidates == (
        ModelTarget(config.llm_adapter_id, config.generation_model_id),
        ModelTarget(config.llm_adapter_id, config.fallback_model_id),
    )


def test_fallback_model_has_no_default() -> None:
    parameter = signature(P0AiRoutingConfig).parameters["fallback_model_id"]

    assert parameter.default is Parameter.empty


@pytest.mark.parametrize("invalid", [None, " ", 1])
def test_rejects_invalid_fallback_model(invalid: object) -> None:
    with pytest.raises(ValueError, match="fallback_model_id"):
        replace(CONFIG, fallback_model_id=cast(str, invalid))


@pytest.mark.parametrize("invalid", [0, 1, "true", None])
def test_rejects_non_boolean_report_fallback_flag(invalid: object) -> None:
    with pytest.raises(ValueError, match="must be a bool"):
        replace(CONFIG, report_draft_uses_fallback=cast(bool, invalid))


def test_config_and_route_mapping_are_immutable() -> None:
    routes = build_p0_model_routes(CONFIG)

    with pytest.raises(FrozenInstanceError):
        P0AiRoutingConfig.__setattr__(CONFIG, "extraction_model_id", "changed")
    mutable_routes = cast(MutableMapping[str, ModelRoute], routes)
    with pytest.raises(TypeError):
        mutable_routes["new"] = routes[P0AiPurpose.EMBEDDING.value]


@pytest.mark.parametrize(
    ("field", "invalid_config"),
    [
        ("llm_adapter_id", lambda: replace(CONFIG, llm_adapter_id=" ")),
        ("embedding_adapter_id", lambda: replace(CONFIG, embedding_adapter_id=" ")),
        ("extraction_model_id", lambda: replace(CONFIG, extraction_model_id=" ")),
        ("generation_model_id", lambda: replace(CONFIG, generation_model_id=" ")),
        ("embedding_model_id", lambda: replace(CONFIG, embedding_model_id=" ")),
        ("fallback_model_id", lambda: replace(CONFIG, fallback_model_id=" ")),
    ],
)
def test_rejects_blank_fields(
    field: str,
    invalid_config: Callable[[], P0AiRoutingConfig],
) -> None:
    with pytest.raises(ValueError, match=field):
        invalid_config()


@pytest.mark.parametrize(
    ("field", "invalid_config"),
    [
        ("llm_adapter_id", lambda: replace(CONFIG, llm_adapter_id=cast(str, 1))),
        (
            "embedding_adapter_id",
            lambda: replace(CONFIG, embedding_adapter_id=cast(str, 1)),
        ),
        ("extraction_model_id", lambda: replace(CONFIG, extraction_model_id=cast(str, 1))),
        ("generation_model_id", lambda: replace(CONFIG, generation_model_id=cast(str, 1))),
        ("embedding_model_id", lambda: replace(CONFIG, embedding_model_id=cast(str, 1))),
        ("fallback_model_id", lambda: replace(CONFIG, fallback_model_id=cast(str, 1))),
    ],
)
def test_rejects_non_string_ids(
    field: str,
    invalid_config: Callable[[], P0AiRoutingConfig],
) -> None:
    with pytest.raises(ValueError, match=field):
        invalid_config()


@pytest.mark.parametrize("primary", ["extraction_model_id", "generation_model_id"])
def test_rejects_duplicate_primary_and_fallback_targets(primary: str) -> None:
    with pytest.raises(ValueError, match="fallback target"):
        replace(CONFIG, fallback_model_id=getattr(CONFIG, primary))


def test_route_building_does_not_use_network_or_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("route building must not use network or sleep")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(time, "sleep", fail)

    routes = build_p0_model_routes(CONFIG)
    pool = rate_limit_pool_for_purpose(P0AiPurpose.RAG_ANSWER)

    assert len(routes) == 6
    assert pool is P0RateLimitPool.RAG
