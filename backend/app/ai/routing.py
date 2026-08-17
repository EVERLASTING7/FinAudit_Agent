"""P0 内建 AI 调用类型到模型候选的纯配置映射。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from app.ai.contracts import ModelRoute, ModelTarget


class P0AiPurpose(str, Enum):
    CONTRACT_FIELD_EXTRACTION = "contract_field_extraction"
    INVOICE_FIELD_EXTRACTION = "invoice_field_extraction"
    RISK_EXPLANATION = "risk_explanation"
    RAG_ANSWER = "rag_answer"
    REPORT_DRAFT = "report_draft"
    EMBEDDING = "embedding"


class P0RateLimitPool(str, Enum):
    RAG = "rag"
    ASYNC_GENERATION = "async_generation"
    EMBEDDING = "embedding"


_RATE_LIMIT_POOL_BY_PURPOSE: Mapping[P0AiPurpose, P0RateLimitPool] = MappingProxyType(
    {
        P0AiPurpose.CONTRACT_FIELD_EXTRACTION: P0RateLimitPool.ASYNC_GENERATION,
        P0AiPurpose.INVOICE_FIELD_EXTRACTION: P0RateLimitPool.ASYNC_GENERATION,
        P0AiPurpose.RISK_EXPLANATION: P0RateLimitPool.ASYNC_GENERATION,
        P0AiPurpose.RAG_ANSWER: P0RateLimitPool.RAG,
        P0AiPurpose.REPORT_DRAFT: P0RateLimitPool.ASYNC_GENERATION,
        P0AiPurpose.EMBEDDING: P0RateLimitPool.EMBEDDING,
    }
)


def rate_limit_pool_for_purpose(purpose: P0AiPurpose) -> P0RateLimitPool:
    """返回已批准的独立限流池；未知或未登记类型失败关闭。"""

    if not isinstance(purpose, P0AiPurpose):
        raise ValueError("purpose must be a registered P0AiPurpose")
    try:
        return _RATE_LIMIT_POOL_BY_PURPOSE[purpose]
    except KeyError as exc:
        raise ValueError("purpose has no registered rate-limit pool") from exc


@dataclass(frozen=True, slots=True)
class P0AiRoutingConfig:
    llm_adapter_id: str
    embedding_adapter_id: str
    extraction_model_id: str
    generation_model_id: str
    fallback_model_id: str
    report_draft_uses_fallback: bool
    embedding_model_id: str

    def __post_init__(self) -> None:
        required = {
            "llm_adapter_id": self.llm_adapter_id,
            "embedding_adapter_id": self.embedding_adapter_id,
            "extraction_model_id": self.extraction_model_id,
            "generation_model_id": self.generation_model_id,
            "fallback_model_id": self.fallback_model_id,
            "embedding_model_id": self.embedding_model_id,
        }
        for name, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

        if not isinstance(self.report_draft_uses_fallback, bool):
            raise ValueError("report_draft_uses_fallback must be a bool")
        if self.fallback_model_id in {
            self.extraction_model_id,
            self.generation_model_id,
        }:
            raise ValueError("fallback target must differ from primary targets")


def build_p0_model_routes(config: P0AiRoutingConfig) -> Mapping[str, ModelRoute]:
    extraction = ModelTarget(config.llm_adapter_id, config.extraction_model_id)
    generation = ModelTarget(config.llm_adapter_id, config.generation_model_id)
    embedding = ModelTarget(config.embedding_adapter_id, config.embedding_model_id)
    fallback = ModelTarget(config.llm_adapter_id, config.fallback_model_id)

    def llm_candidates(primary: ModelTarget) -> tuple[ModelTarget, ...]:
        return (primary, fallback)

    primary_by_purpose = {
        P0AiPurpose.CONTRACT_FIELD_EXTRACTION: extraction,
        P0AiPurpose.INVOICE_FIELD_EXTRACTION: extraction,
        P0AiPurpose.RISK_EXPLANATION: generation,
        P0AiPurpose.RAG_ANSWER: generation,
    }
    routes = {
        purpose.value: ModelRoute(purpose.value, llm_candidates(primary))
        for purpose, primary in primary_by_purpose.items()
    }
    report_candidates = (
        llm_candidates(generation) if config.report_draft_uses_fallback else (generation,)
    )
    routes[P0AiPurpose.REPORT_DRAFT.value] = ModelRoute(
        P0AiPurpose.REPORT_DRAFT.value,
        report_candidates,
    )
    routes[P0AiPurpose.EMBEDDING.value] = ModelRoute(
        P0AiPurpose.EMBEDDING.value,
        (embedding,),
    )
    return MappingProxyType(routes)
