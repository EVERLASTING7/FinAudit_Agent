"""本地/测试真实 Chat 与 Embedding Adapter 的唯一构造入口。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.ai.adapters.openai_compatible import (
    OPENAI_CHAT_COMPLETIONS_ADAPTER_ID,
    OPENAI_EMBEDDINGS_ADAPTER_ID,
    OpenAiChatCompletionsAdapter,
    OpenAiCompatibleProfile,
    OpenAiEmbeddingsAdapter,
)
from app.ai.contracts import TransportPolicy
from app.ai.embedding_runtime import EmbeddingRuntime
from app.ai.gateway import AiGateway
from app.ai.live_policy import LIVE_EMBEDDING_POLICY, LIVE_LLM_POLICY
from app.ai.network_policy import OutboundNetworkPolicy
from app.ai.policy_loader import ValidatedPolicySnapshot
from app.ai.redis_runtime_control import (
    AiBreakerProfile,
    AiRateLimitProfile,
    RedisAiRuntimeControl,
)
from app.ai.routing import P0RateLimitPool
from app.core.config import Settings
from app.services.ai_call_audit import AiCallAuditService
from app.services.audited_llm import AuditedLlmInvoker

_REGISTRY_RESOURCE_PACKAGE = "app.ai.artifacts.cr011_v1"
_REGISTRY_RESOURCE_NAME = "ip-deny-cidrs-v1.json"
_REGISTRY_SHA256 = "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"


@dataclass(slots=True)
class LiveAiRuntime:
    chat_adapter: OpenAiChatCompletionsAdapter
    embedding_adapter: OpenAiEmbeddingsAdapter
    invoker: AuditedLlmInvoker
    embedding: EmbeddingRuntime
    runtime_control: RedisAiRuntimeControl

    def close(self) -> None:
        try:
            self.embedding_adapter.close()
        finally:
            try:
                self.chat_adapter.close()
            finally:
                self.runtime_control.close()


def _rate_limit_profile(value: str) -> AiRateLimitProfile:
    concurrency, rpm, tpm, burst = value.split("/")
    return AiRateLimitProfile(
        concurrency=int(concurrency),
        rpm=int(rpm),
        tpm=int(tpm),
        burst=int(burst),
    )


def create_live_ai_runtime(
    *,
    settings: Settings,
    session_factory: sessionmaker[Session],
    policy_snapshot: ValidatedPolicySnapshot,
) -> LiveAiRuntime:
    """只在启动 Policy 已明确允许真实调用时构造网络客户端。"""

    if not policy_snapshot.provider_calls_enabled:
        raise ValueError("provider calls are disabled")
    registry_bytes = (
        resources.files(_REGISTRY_RESOURCE_PACKAGE).joinpath(_REGISTRY_RESOURCE_NAME).read_bytes()
    )
    chat_network_policy = OutboundNetworkPolicy(
        endpoint_id=LIVE_LLM_POLICY.endpoint_id,
        network_scope="external_public",
        base_url=LIVE_LLM_POLICY.base_url,
        approved_hostnames=LIVE_LLM_POLICY.approved_hostnames,
        allowed_cidrs=LIVE_LLM_POLICY.allowed_cidrs,
        billing_mode="external_usd",
        address_policy_version="ip-deny-cidrs-v1",
        registry_sha256=_REGISTRY_SHA256,
    )
    adapter = OpenAiChatCompletionsAdapter(
        OpenAiCompatibleProfile(
            profile_type="chat",
            base_url=LIVE_LLM_POLICY.base_url,
            model_id=LIVE_LLM_POLICY.model_id,
            allowed_response_model_ids=LIVE_LLM_POLICY.allowed_response_model_ids,
            api_key=settings.llm_api_key,
            network_policy=chat_network_policy,
            registry_bytes=registry_bytes,
            max_request_bytes=LIVE_LLM_POLICY.max_request_bytes,
            max_response_header_bytes=LIVE_LLM_POLICY.max_response_header_bytes,
            max_response_body_bytes=LIVE_LLM_POLICY.max_response_body_bytes,
            use_max_completion_tokens=LIVE_LLM_POLICY.use_max_completion_tokens,
            thinking_mode=LIVE_LLM_POLICY.thinking_mode,
            service_tier=LIVE_LLM_POLICY.service_tier,
        )
    )
    assert settings.embedding_api_key is not None
    embedding_network_policy = OutboundNetworkPolicy(
        endpoint_id=LIVE_EMBEDDING_POLICY.endpoint_id,
        network_scope="external_public",
        base_url=LIVE_EMBEDDING_POLICY.base_url,
        approved_hostnames=LIVE_EMBEDDING_POLICY.approved_hostnames,
        allowed_cidrs=LIVE_EMBEDDING_POLICY.allowed_cidrs,
        billing_mode="external_cny",
        address_policy_version="ip-deny-cidrs-v1",
        registry_sha256=_REGISTRY_SHA256,
    )
    try:
        embedding_adapter = OpenAiEmbeddingsAdapter(
            OpenAiCompatibleProfile(
                profile_type="embedding",
                base_url=LIVE_EMBEDDING_POLICY.base_url,
                model_id=LIVE_EMBEDDING_POLICY.model_id,
                allowed_response_model_ids=(LIVE_EMBEDDING_POLICY.allowed_response_model_ids),
                api_key=settings.embedding_api_key,
                network_policy=embedding_network_policy,
                registry_bytes=registry_bytes,
                max_request_bytes=LIVE_EMBEDDING_POLICY.max_request_bytes,
                max_response_header_bytes=(LIVE_EMBEDDING_POLICY.max_response_header_bytes),
                max_response_body_bytes=LIVE_EMBEDDING_POLICY.max_response_body_bytes,
                embedding_dimension=LIVE_EMBEDDING_POLICY.embedding_dimension,
            )
        )
    except Exception:
        adapter.close()
        raise
    try:
        redis_client = Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=False,
            decode_responses=False,
        )
        runtime_control = RedisAiRuntimeControl(
            redis_client,
            namespace=f"finaudit:ai:runtime:v1:{settings.app_env.value}",
            pool_limits={
                P0RateLimitPool.RAG: _rate_limit_profile(settings.ai_rag_limits),
                P0RateLimitPool.ASYNC_GENERATION: _rate_limit_profile(
                    settings.ai_async_generation_limits
                ),
                P0RateLimitPool.EMBEDDING: _rate_limit_profile(settings.ai_embedding_limits),
            },
            breaker=AiBreakerProfile(
                failures=settings.ai_breaker_failures,
                window_seconds=settings.ai_breaker_window_seconds,
                open_seconds=settings.ai_breaker_open_seconds,
                half_open_probes=settings.ai_breaker_half_open_probes,
            ),
        )
    except Exception:
        embedding_adapter.close()
        adapter.close()
        raise
    gateway = AiGateway(
        llm_adapters={OPENAI_CHAT_COMPLETIONS_ADAPTER_ID: adapter},
        embedding_adapters={OPENAI_EMBEDDINGS_ADAPTER_ID: embedding_adapter},
    )
    return LiveAiRuntime(
        chat_adapter=adapter,
        embedding_adapter=embedding_adapter,
        invoker=AuditedLlmInvoker(
            session_factory=session_factory,
            gateway=gateway,
            adapter=adapter,
            policy_snapshot=policy_snapshot,
            llm_policy=LIVE_LLM_POLICY,
            runtime_control=runtime_control,
        ),
        embedding=EmbeddingRuntime(
            gateway=gateway,
            target=embedding_adapter.target,
            transport_policy=TransportPolicy(
                connect_timeout_seconds=settings.llm_connect_timeout_seconds,
                read_timeout_seconds=LIVE_EMBEDDING_POLICY.operation.deadline_seconds,
                total_timeout_seconds=LIVE_EMBEDDING_POLICY.operation.deadline_seconds,
                max_attempts=(
                    LIVE_EMBEDDING_POLICY.operation.max_provider_attempts_per_business_operation
                ),
            ),
            runtime_control=runtime_control,
            policy_snapshot=policy_snapshot,
            embedding_policy=LIVE_EMBEDDING_POLICY,
            audit_writer=AiCallAuditService(session_factory),
        ),
        runtime_control=runtime_control,
    )


__all__ = ["LiveAiRuntime", "create_live_ai_runtime"]
