from __future__ import annotations

import math
import struct

import pytest

from app.services.vector_integrity import vector_sha256


def _qdrant_float32_round_trip(vector: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(struct.unpack(">f", struct.pack(">f", value))[0] for value in vector)


def test_vector_hash_survives_qdrant_float32_round_trip() -> None:
    vector = (0.123456789, -0.987654321, 1.0 / 3.0)

    assert vector_sha256(vector) == vector_sha256(_qdrant_float32_round_trip(vector))


def test_vector_hash_distinguishes_different_float32_vectors() -> None:
    first = _qdrant_float32_round_trip((0.123456789,))
    second = _qdrant_float32_round_trip((0.123556789,))

    assert vector_sha256(first) != vector_sha256(second)


@pytest.mark.parametrize("vector", [(), (math.nan,), (math.inf,), (-math.inf,)])
def test_vector_hash_rejects_empty_or_non_finite_vectors(vector: tuple[float, ...]) -> None:
    with pytest.raises(ValueError, match="vector is invalid"):
        vector_sha256(vector)
