from __future__ import annotations

import stat
from importlib import resources
from pathlib import Path

import pytest

from app.ai.live_policy import (
    LIVE_POLICY_HASH,
    LIVE_POLICY_ID,
    LIVE_POLICY_RAW_SHA256,
    LIVE_POLICY_RESOURCE_NAME,
    LIVE_POLICY_RESOURCE_PACKAGE,
    validate_live_policy_bytes,
)
from app.ai.policy_loader import PolicyStartupError, load_validated_policy
from tests.unit.startup_policy_support import build_startup_settings


def _raw_policy() -> bytes:
    return (
        resources.files(LIVE_POLICY_RESOURCE_PACKAGE)
        .joinpath(LIVE_POLICY_RESOURCE_NAME)
        .read_bytes()
    )


def _live_settings(policy_file: Path):  # type: ignore[no-untyped-def]
    return build_startup_settings(
        policy_file,
        ai_provider_calls_enabled=True,
        llm_base_url="https://api.minimaxi.com/v1",
        llm_extraction_model="MiniMax-M3",
        llm_generation_model="MiniMax-M3",
        llm_fallback_model="MiniMax-M3",
        embedding_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        embedding_api_key="test-live-embedding-key",
        embedding_model="qwen3.7-text-embedding",
        embedding_vector_size=1024,
        embedding_batch_size=20,
    )


def test_fixed_live_policy_is_accepted_and_exposes_only_identity(tmp_path: Path) -> None:
    raw_policy = _raw_policy()
    policy_file = tmp_path / LIVE_POLICY_RESOURCE_NAME
    policy_file.write_bytes(raw_policy)
    policy_file.chmod(stat.S_IREAD)
    try:
        snapshot = load_validated_policy(_live_settings(policy_file))
    finally:
        policy_file.chmod(stat.S_IREAD | stat.S_IWRITE)

    assert validate_live_policy_bytes(raw_policy) is True
    assert snapshot.policy_hash == LIVE_POLICY_HASH
    assert snapshot.raw_sha256 == LIVE_POLICY_RAW_SHA256
    assert snapshot.provider_calls_enabled is True
    assert snapshot.runtime_profile_id == LIVE_POLICY_ID


def test_live_policy_tamper_fails_closed(tmp_path: Path) -> None:
    policy_file = tmp_path / LIVE_POLICY_RESOURCE_NAME
    policy_file.write_bytes(_raw_policy().replace(b"MiniMax-M3", b"MiniMax-X3", 1))
    policy_file.chmod(stat.S_IREAD)
    try:
        with pytest.raises(PolicyStartupError) as exc_info:
            load_validated_policy(_live_settings(policy_file))
    finally:
        policy_file.chmod(stat.S_IREAD | stat.S_IWRITE)

    assert exc_info.value.code == "AI_POLICY_IDENTITY_NOT_APPROVED"
