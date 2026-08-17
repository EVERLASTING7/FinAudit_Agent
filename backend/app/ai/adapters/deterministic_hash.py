"""离线可复算的词项哈希 Embedding；不访问 Provider 或网络。"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter

from app.ai.contracts import (
    EmbeddingRequest,
    EmbeddingResult,
    ModelTarget,
    TransportPolicy,
)

DETERMINISTIC_HASH_ADAPTER_ID = "deterministic_hash_v1"
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]", re.ASCII)


class DeterministicHashEmbeddingAdapter:
    """用于离线链路和可重建测试索引，不宣称语义模型质量。"""

    def __init__(self, *, model_id: str, vector_size: int) -> None:
        if not model_id.strip() or vector_size <= 0:
            raise ValueError("deterministic embedding profile is invalid")
        self._model_id = model_id
        self._vector_size = vector_size

    @property
    def target(self) -> ModelTarget:
        return ModelTarget(DETERMINISTIC_HASH_ADAPTER_ID, self._model_id)

    def embed(
        self,
        request: EmbeddingRequest,
        target: ModelTarget,
        policy: TransportPolicy,
    ) -> EmbeddingResult:
        if target != self.target or not isinstance(policy, TransportPolicy):
            raise ValueError("deterministic embedding target is invalid")
        return EmbeddingResult(
            trace_id=request.trace_id,
            target=target,
            vectors=tuple(self.embed_text(value) for value in request.input_texts),
        )

    def embed_text(self, value: str) -> tuple[float, ...]:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        base_tokens = _TOKEN_PATTERN.findall(normalized)
        cjk = "".join(token for token in base_tokens if len(token) == 1 and not token.isascii())
        tokens = base_tokens + [cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))]
        if not tokens:
            tokens = [normalized or "empty"]

        values = [0.0] * self._vector_size
        for token, count in Counter(tokens).items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], "big") % self._vector_size
            sign = 1.0 if digest[8] & 1 else -1.0
            values[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(component * component for component in values))
        if norm == 0:
            digest = hashlib.sha256(normalized.encode("utf-8")).digest()
            values[int.from_bytes(digest[:8], "big") % self._vector_size] = 1.0
            norm = 1.0
        return tuple(component / norm for component in values)


__all__ = ["DETERMINISTIC_HASH_ADAPTER_ID", "DeterministicHashEmbeddingAdapter"]
