from app.ai.adapters.deterministic_hash import (
    DETERMINISTIC_HASH_ADAPTER_ID,
    DeterministicHashEmbeddingAdapter,
)
from app.ai.contracts import EmbeddingRequest, ModelTarget, TransportPolicy


def test_embedding_is_normalized_reproducible_and_ordered() -> None:
    adapter = DeterministicHashEmbeddingAdapter(model_id="offline-v1", vector_size=64)
    request = EmbeddingRequest(trace_id="trace-1", input_texts=("合同金额", "合同金额", "发票日期"))

    result = adapter.embed(
        request,
        adapter.target,
        TransportPolicy(1, 1, 2, 1),
    )

    assert adapter.target == ModelTarget(DETERMINISTIC_HASH_ADAPTER_ID, "offline-v1")
    assert len(result.vectors) == 3
    assert result.vectors[0] == result.vectors[1]
    assert result.vectors[0] != result.vectors[2]
    assert abs(sum(value * value for value in result.vectors[0]) - 1.0) < 1e-12


def test_nfkc_equivalent_input_has_same_vector() -> None:
    adapter = DeterministicHashEmbeddingAdapter(model_id="offline-v1", vector_size=16)

    assert adapter.embed_text("ＡＢＣ 123") == adapter.embed_text("abc 123")
