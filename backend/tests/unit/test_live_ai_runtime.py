from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.ai.adapters.openai_compatible import (
    OPENAI_CHAT_COMPLETIONS_ADAPTER_ID,
    OPENAI_EMBEDDINGS_ADAPTER_ID,
)
from app.ai.live_policy import (
    LIVE_EMBEDDING_POLICY,
    LIVE_LLM_POLICY,
    LIVE_POLICY_HASH,
    LIVE_POLICY_ID,
    LIVE_POLICY_RAW_SHA256,
)
from app.ai.live_runtime import create_live_ai_runtime
from app.ai.policy_loader import ValidatedPolicySnapshot
from tests.unit.startup_policy_support import build_startup_settings


def test_live_runtime_constructs_chat_and_bailian_embedding_without_network(
    tmp_path: Path,
) -> None:
    settings = build_startup_settings(
        tmp_path / "unused-policy.json",
        ai_provider_calls_enabled=True,
        llm_base_url=LIVE_LLM_POLICY.base_url,
        llm_extraction_model=LIVE_LLM_POLICY.model_id,
        llm_generation_model=LIVE_LLM_POLICY.model_id,
        llm_fallback_model=LIVE_LLM_POLICY.model_id,
        embedding_base_url=LIVE_EMBEDDING_POLICY.base_url,
        embedding_api_key="test-live-embedding-key",
        embedding_model=LIVE_EMBEDDING_POLICY.model_id,
        embedding_vector_size=LIVE_EMBEDDING_POLICY.embedding_dimension,
        embedding_batch_size=LIVE_EMBEDDING_POLICY.operation.max_batch_size,
    )
    runtime = create_live_ai_runtime(
        settings=settings,
        session_factory=sessionmaker[Session](),
        policy_snapshot=ValidatedPolicySnapshot(
            policy_version=2,
            policy_hash=LIVE_POLICY_HASH,
            raw_sha256=LIVE_POLICY_RAW_SHA256,
            provider_calls_enabled=True,
            runtime_profile_id=LIVE_POLICY_ID,
        ),
    )
    try:
        assert runtime.chat_adapter.target.adapter_id == OPENAI_CHAT_COMPLETIONS_ADAPTER_ID
        assert runtime.embedding.target == runtime.embedding_adapter.target
        assert runtime.embedding.target.adapter_id == OPENAI_EMBEDDINGS_ADAPTER_ID
        assert runtime.embedding.target.model_id == "qwen3.7-text-embedding"
        assert runtime.embedding.transport_policy.total_timeout_seconds == 30
        assert runtime.embedding.runtime_control is runtime.runtime_control
        assert runtime.invoker._runtime_control is runtime.runtime_control
    finally:
        runtime.close()
