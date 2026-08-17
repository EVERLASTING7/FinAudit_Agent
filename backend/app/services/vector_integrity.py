"""向量与 Qdrant 最小 payload 的稳定摘要。"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from uuid import UUID

from app.adapters.qdrant_vector import JsonValue


def point_payload(index_version_id: UUID, content_sha256: str) -> dict[str, JsonValue]:
    if len(content_sha256) != 64:
        raise ValueError("content hash is invalid")
    return {
        "content_sha256": content_sha256,
        "index_version_id": str(index_version_id),
    }


def vector_sha256(vector: tuple[float, ...]) -> str:
    if not vector or any(not math.isfinite(value) for value in vector):
        raise ValueError("vector is invalid")
    digest = hashlib.sha256()
    digest.update(struct.pack(">I", len(vector)))
    try:
        for value in vector:
            digest.update(struct.pack(">f", value))
    except (OverflowError, struct.error) as error:
        raise ValueError("vector is invalid") from error
    return digest.hexdigest()


def payload_sha256(payload: dict[str, JsonValue]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["payload_sha256", "point_payload", "vector_sha256"]
