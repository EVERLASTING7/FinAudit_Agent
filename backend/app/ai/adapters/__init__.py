"""模型服务 Adapter 边界。"""

from app.ai.adapters.deterministic_hash import (
    DETERMINISTIC_HASH_ADAPTER_ID,
    DeterministicHashEmbeddingAdapter,
)
from app.ai.adapters.openai_compatible import (
    OPENAI_CHAT_COMPLETIONS_ADAPTER_ID,
    OPENAI_EMBEDDINGS_ADAPTER_ID,
    OpenAiChatCompletionsAdapter,
    OpenAiCompatibleConfigurationError,
    OpenAiCompatibleProfile,
    OpenAiEmbeddingsAdapter,
)

__all__ = [
    "DETERMINISTIC_HASH_ADAPTER_ID",
    "OPENAI_CHAT_COMPLETIONS_ADAPTER_ID",
    "OPENAI_EMBEDDINGS_ADAPTER_ID",
    "DeterministicHashEmbeddingAdapter",
    "OpenAiChatCompletionsAdapter",
    "OpenAiCompatibleConfigurationError",
    "OpenAiCompatibleProfile",
    "OpenAiEmbeddingsAdapter",
]
