"""本地/测试真实 LLM Adapter 与持久审计调用器的唯一构造入口。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from sqlalchemy.orm import Session, sessionmaker

from app.ai.adapters.openai_compatible import (
    OPENAI_CHAT_COMPLETIONS_ADAPTER_ID,
    OpenAiChatCompletionsAdapter,
    OpenAiCompatibleProfile,
)
from app.ai.gateway import AiGateway
from app.ai.live_policy import LIVE_LLM_POLICY
from app.ai.network_policy import OutboundNetworkPolicy
from app.ai.policy_loader import ValidatedPolicySnapshot
from app.core.config import Settings
from app.services.audited_llm import AuditedLlmInvoker

_REGISTRY_RESOURCE_PACKAGE = "app.ai.artifacts.cr011_v1"
_REGISTRY_RESOURCE_NAME = "ip-deny-cidrs-v1.json"
_REGISTRY_SHA256 = "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"


@dataclass(slots=True)
class LiveLlmRuntime:
    adapter: OpenAiChatCompletionsAdapter
    invoker: AuditedLlmInvoker

    def close(self) -> None:
        self.adapter.close()


def create_live_llm_runtime(
    *,
    settings: Settings,
    session_factory: sessionmaker[Session],
    policy_snapshot: ValidatedPolicySnapshot,
) -> LiveLlmRuntime:
    """只在启动 Policy 已明确允许真实调用时构造网络客户端。"""

    if not policy_snapshot.provider_calls_enabled:
        raise ValueError("provider calls are disabled")
    registry_bytes = (
        resources.files(_REGISTRY_RESOURCE_PACKAGE).joinpath(_REGISTRY_RESOURCE_NAME).read_bytes()
    )
    network_policy = OutboundNetworkPolicy(
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
            network_policy=network_policy,
            registry_bytes=registry_bytes,
            max_request_bytes=LIVE_LLM_POLICY.max_request_bytes,
            max_response_header_bytes=LIVE_LLM_POLICY.max_response_header_bytes,
            max_response_body_bytes=LIVE_LLM_POLICY.max_response_body_bytes,
            use_max_completion_tokens=LIVE_LLM_POLICY.use_max_completion_tokens,
            thinking_mode=LIVE_LLM_POLICY.thinking_mode,
            service_tier=LIVE_LLM_POLICY.service_tier,
        )
    )
    gateway = AiGateway(
        llm_adapters={OPENAI_CHAT_COMPLETIONS_ADAPTER_ID: adapter},
        embedding_adapters={},
    )
    return LiveLlmRuntime(
        adapter=adapter,
        invoker=AuditedLlmInvoker(
            session_factory=session_factory,
            gateway=gateway,
            adapter=adapter,
            policy_snapshot=policy_snapshot,
            llm_policy=LIVE_LLM_POLICY,
        ),
    )


__all__ = ["LiveLlmRuntime", "create_live_llm_runtime"]
