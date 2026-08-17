from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.chunking.config import (
    CHUNK_PROFILE_HASH,
    CHUNK_PROFILE_VERSION,
    P0_CHUNK_PROFILE,
    P0InitialChunkingConfig,
    chunk_profile_hash,
    chunk_profile_payload,
)


def valid_payload() -> dict[str, object]:
    return {
        "strategy": "markdown_ast_structural",
        "target_length": 700,
        "max_length": 1200,
        "min_length": 50,
        "overlap_length": 100,
        "title_handling": {"inherit_title_path": True},
        "table_handling": {
            "keep_whole_if_under_max": True,
            "repeat_header_on_split": True,
        },
        "noise_handling": {"exclude_approved_noise": True},
    }


def test_approved_initial_chunking_config_is_accepted_without_defaults() -> None:
    payload = valid_payload()

    config = P0InitialChunkingConfig.model_validate(payload)

    assert config.model_dump() == payload
    assert set(P0InitialChunkingConfig.model_json_schema()["required"]) == set(payload)


@pytest.mark.parametrize(
    ("path", "invalid_value"),
    [
        (("strategy",), "other"),
        (("target_length",), 701),
        (("max_length",), 1201),
        (("min_length",), 51),
        (("overlap_length",), 101),
        (("title_handling", "inherit_title_path"), False),
        (("table_handling", "keep_whole_if_under_max"), False),
        (("table_handling", "repeat_header_on_split"), False),
        (("noise_handling", "exclude_approved_noise"), False),
    ],
)
def test_contract_drift_is_rejected(path: tuple[str, ...], invalid_value: object) -> None:
    payload = deepcopy(valid_payload())
    target = payload
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = invalid_value

    with pytest.raises(ValidationError, match="P0 首版合同"):
        P0InitialChunkingConfig.model_validate(payload)


@pytest.mark.parametrize("invalid_value", [700.0, "700", True])
def test_numeric_contract_values_use_exact_integer_types(invalid_value: object) -> None:
    payload = valid_payload()
    payload["target_length"] = invalid_value

    with pytest.raises(ValidationError):
        P0InitialChunkingConfig.model_validate(payload)


@pytest.mark.parametrize(
    ("container", "field"),
    [
        (None, "unexpected"),
        ("title_handling", "unexpected"),
        ("table_handling", "unexpected"),
        ("noise_handling", "unexpected"),
    ],
)
def test_unknown_fields_are_rejected(container: str | None, field: str) -> None:
    payload = valid_payload()
    if container is None:
        payload[field] = True
    else:
        nested = payload[container]
        assert isinstance(nested, dict)
        nested[field] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        P0InitialChunkingConfig.model_validate(payload)


def test_initial_chunking_config_is_immutable() -> None:
    config = P0InitialChunkingConfig.model_validate(valid_payload())

    with pytest.raises(ValidationError, match="Instance is frozen"):
        config.target_length = 701


def test_application_profile_has_stable_versioned_identity() -> None:
    assert CHUNK_PROFILE_VERSION == "chunk-profile-v1"
    assert CHUNK_PROFILE_HASH == "e3b2036ad044420ab53ba94e5a7b51582259133cb2273afe2fe56afc17795e99"
    assert chunk_profile_hash(P0_CHUNK_PROFILE) == CHUNK_PROFILE_HASH
    assert chunk_profile_payload(P0_CHUNK_PROFILE)["profile_version"] == CHUNK_PROFILE_VERSION
