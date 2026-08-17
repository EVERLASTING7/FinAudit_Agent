"""AI Gateway 的显式目标单次分派。"""

from __future__ import annotations

from collections.abc import Mapping

from app.ai.contracts import (
    EmbeddingAdapter,
    EmbeddingOutcome,
    EmbeddingRequest,
    EmbeddingResult,
    ExternalError,
    LlmAdapter,
    LlmOutcome,
    LlmRequest,
    LlmResult,
    ModelTarget,
    TransportPolicy,
)


class AdapterNotRegisteredError(LookupError):
    """显式目标未绑定到对应 Adapter。"""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        super().__init__("AI adapter is not registered")


class GatewayContractError(RuntimeError):
    """Adapter 返回值违反 Gateway 内存契约。"""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        super().__init__("AI adapter returned an invalid outcome")


class GatewayAdapterError(RuntimeError):
    """Adapter 抛出未规范化异常时使用的脱敏边界错误。"""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        super().__init__("AI adapter call failed")


class AiGateway:
    """按调用方给出的目标分派一次，不执行路由、重试或降级。"""

    def __init__(
        self,
        *,
        llm_adapters: Mapping[str, LlmAdapter],
        embedding_adapters: Mapping[str, EmbeddingAdapter],
    ) -> None:
        self._llm_adapters = dict(llm_adapters)
        self._embedding_adapters = dict(embedding_adapters)

    def generate(
        self,
        request: LlmRequest,
        target: ModelTarget,
        policy: TransportPolicy,
    ) -> LlmOutcome:
        adapter = self._llm_adapters.get(target.adapter_id)
        if adapter is None:
            raise AdapterNotRegisteredError(request.trace_id)

        adapter_failed = False
        outcome: LlmOutcome | None = None
        try:
            outcome = adapter.generate(request, target, policy)
        except Exception:
            adapter_failed = True
        if adapter_failed:
            # 在 except 上下文退出后抛出，避免通过异常链泄露 provider 原文。
            raise GatewayAdapterError(request.trace_id)
        if not isinstance(outcome, (LlmResult, ExternalError)):
            raise GatewayContractError(request.trace_id)
        if outcome.trace_id != request.trace_id:
            raise GatewayContractError(request.trace_id)
        if isinstance(outcome, LlmResult) and outcome.target != target:
            raise GatewayContractError(request.trace_id)
        return outcome

    def embed(
        self,
        request: EmbeddingRequest,
        target: ModelTarget,
        policy: TransportPolicy,
    ) -> EmbeddingOutcome:
        adapter = self._embedding_adapters.get(target.adapter_id)
        if adapter is None:
            raise AdapterNotRegisteredError(request.trace_id)

        adapter_failed = False
        outcome: EmbeddingOutcome | None = None
        try:
            outcome = adapter.embed(request, target, policy)
        except Exception:
            adapter_failed = True
        if adapter_failed:
            # 在 except 上下文退出后抛出，避免通过异常链泄露 provider 原文。
            raise GatewayAdapterError(request.trace_id)
        if not isinstance(outcome, (EmbeddingResult, ExternalError)):
            raise GatewayContractError(request.trace_id)
        if outcome.trace_id != request.trace_id:
            raise GatewayContractError(request.trace_id)
        if isinstance(outcome, EmbeddingResult) and outcome.target != target:
            raise GatewayContractError(request.trace_id)
        if isinstance(outcome, EmbeddingResult) and len(outcome.vectors) != len(
            request.input_texts
        ):
            raise GatewayContractError(request.trace_id)
        return outcome
