"""对显式配置且已存在的 Qdrant 集合执行受限向量操作。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TypeAlias, cast
from urllib.parse import quote
from uuid import UUID

import httpx

from app.core.config import Settings, _is_validated_settings_instance

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

_MAX_BATCH_SIZE = 256
_MAX_ALLOWED_POINT_IDS = 10_000
_MAX_QUERY_LIMIT = 100
_MAX_PAYLOAD_BYTES = 256 * 1024
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_JSON_DEPTH = 20


class QdrantVectorStoreError(RuntimeError):
    """不回显 URL、API Key、请求载荷或服务端错误正文。"""

    def __init__(self) -> None:
        super().__init__("qdrant vector store operation failed")


@dataclass(frozen=True, slots=True)
class QdrantPoint:
    id: UUID
    vector: tuple[float, ...]
    payload: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class QdrantHit:
    id: UUID
    score: float
    payload: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class QdrantStoredPoint:
    id: UUID
    vector: tuple[float, ...]
    payload: dict[str, JsonValue]


class QdrantVectorAdapter:
    """不创建集合；查询必须先由 PostgreSQL 提供允许访问的 Point ID。"""

    __slots__ = (
        "_api_key",
        "_base_url",
        "_client",
        "_collection_path",
        "_distance",
        "_owns_client",
        "_vector_size",
        "_verified",
    )

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        if type(settings) is not Settings or not _is_validated_settings_instance(settings):
            raise TypeError("validated Settings are required")
        self._base_url = settings.qdrant_url.rstrip("/")
        self._collection_path = f"/collections/{quote(settings.qdrant_collection, safe='')}"
        self._vector_size = settings.qdrant_vector_size
        self._distance = settings.qdrant_distance
        api_key = settings.qdrant_api_key
        self._api_key = None if api_key is None else api_key.get_secret_value()
        self._verified = False
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(10.0, connect=3.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=False,
            trust_env=False,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def verify_collection(self) -> None:
        envelope = self._request("GET", self._collection_path)
        result = _require_object(envelope.get("result"))
        if result.get("status") != "green":
            raise QdrantVectorStoreError
        config = _require_object(result.get("config"))
        params = _require_object(config.get("params"))
        vectors = _require_object(params.get("vectors"))
        size = vectors.get("size")
        distance = vectors.get("distance")
        # 命名向量的结构没有顶层 size/distance；在契约冻结前必须拒绝推断。
        if type(size) is not int or size != self._vector_size or distance != self._distance:
            raise QdrantVectorStoreError
        self._verified = True

    def upsert(self, points: tuple[QdrantPoint, ...]) -> None:
        if not points or len(points) > _MAX_BATCH_SIZE:
            raise QdrantVectorStoreError
        normalized_points: list[dict[str, object]] = []
        seen_ids: set[UUID] = set()
        for point in points:
            if type(point) is not QdrantPoint or type(point.id) is not UUID or point.id in seen_ids:
                raise QdrantVectorStoreError
            seen_ids.add(point.id)
            normalized_points.append(
                {
                    "id": str(point.id),
                    "vector": self._normalize_vector(point.vector),
                    "payload": _normalize_json_object(point.payload),
                }
            )
        self._ensure_verified()
        envelope = self._request(
            "PUT",
            f"{self._collection_path}/points?wait=true",
            json_body={"points": normalized_points},
        )
        _require_completed(envelope)

    def query_authorized(
        self,
        vector: tuple[float, ...],
        *,
        allowed_point_ids: tuple[UUID, ...],
        limit: int,
    ) -> tuple[QdrantHit, ...]:
        """仅返回允许集合内候选；调用方仍须用 PostgreSQL 做最终授权复核。"""

        allowed_ids = _normalize_ids(allowed_point_ids, maximum=_MAX_ALLOWED_POINT_IDS)
        if type(limit) is not int or limit <= 0 or limit > _MAX_QUERY_LIMIT:
            raise QdrantVectorStoreError
        normalized_vector = self._normalize_vector(vector)
        self._ensure_verified()
        envelope = self._request(
            "POST",
            f"{self._collection_path}/points/query",
            json_body={
                "query": normalized_vector,
                "filter": {"must": [{"has_id": [str(point_id) for point_id in allowed_ids]}]},
                "limit": min(limit, len(allowed_ids)),
                "with_payload": True,
                "with_vector": False,
            },
        )
        result = _require_object(envelope.get("result"))
        raw_points = result.get("points")
        if type(raw_points) is not list or len(raw_points) > min(limit, len(allowed_ids)):
            raise QdrantVectorStoreError
        allowed_id_set = set(allowed_ids)
        seen_ids: set[UUID] = set()
        hits: list[QdrantHit] = []
        for raw_point in raw_points:
            point = _require_object(raw_point)
            point_id = _parse_uuid(point.get("id"))
            score = _normalize_number(point.get("score"))
            if point_id not in allowed_id_set or point_id in seen_ids:
                raise QdrantVectorStoreError
            seen_ids.add(point_id)
            raw_payload = point.get("payload")
            payload = {} if raw_payload is None else _normalize_json_object(raw_payload)
            hits.append(QdrantHit(id=point_id, score=score, payload=payload))
        return tuple(hits)

    def delete(self, point_ids: tuple[UUID, ...]) -> None:
        normalized_ids = _normalize_ids(point_ids, maximum=_MAX_BATCH_SIZE)
        self._ensure_verified()
        envelope = self._request(
            "POST",
            f"{self._collection_path}/points/delete?wait=true",
            json_body={"points": [str(point_id) for point_id in normalized_ids]},
        )
        _require_completed(envelope)

    def retrieve(self, point_ids: tuple[UUID, ...]) -> tuple[QdrantStoredPoint, ...]:
        """读取明确 Point 集用于索引一致性校验，不提供全量枚举。"""

        normalized_ids = _normalize_ids(point_ids, maximum=_MAX_BATCH_SIZE)
        self._ensure_verified()
        envelope = self._request(
            "POST",
            f"{self._collection_path}/points",
            json_body={
                "ids": [str(point_id) for point_id in normalized_ids],
                "with_payload": True,
                "with_vector": True,
            },
        )
        raw_result = envelope.get("result")
        if type(raw_result) is not list or len(raw_result) > len(normalized_ids):
            raise QdrantVectorStoreError
        expected = set(normalized_ids)
        by_id: dict[UUID, QdrantStoredPoint] = {}
        for raw_point in raw_result:
            point = _require_object(raw_point)
            point_id = _parse_uuid(point.get("id"))
            raw_vector = point.get("vector")
            if type(raw_vector) is not list or point_id not in expected or point_id in by_id:
                raise QdrantVectorStoreError
            vector = tuple(_normalize_number(value) for value in raw_vector)
            if len(vector) != self._vector_size:
                raise QdrantVectorStoreError
            raw_payload = point.get("payload")
            payload = {} if raw_payload is None else _normalize_json_object(raw_payload)
            by_id[point_id] = QdrantStoredPoint(point_id, vector, payload)
        return tuple(by_id[point_id] for point_id in normalized_ids if point_id in by_id)

    def _ensure_verified(self) -> None:
        if not self._verified:
            self.verify_collection()

    def _normalize_vector(self, vector: object) -> list[float]:
        if type(vector) is not tuple or len(vector) != self._vector_size:
            raise QdrantVectorStoreError
        return [_normalize_number(value) for value in vector]

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        headers = {"Accept": "application/json"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if self._api_key is not None:
            headers["api-key"] = self._api_key
        try:
            response = self._client.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=json_body,
            )
            if response.status_code != 200:
                raise ValueError
            content_length = response.headers.get("content-length")
            if content_length is not None and int(content_length) > _MAX_RESPONSE_BYTES:
                raise ValueError
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise ValueError
            raw_envelope: object = response.json()
            envelope = _require_object(raw_envelope)
            if envelope.get("status") != "ok":
                raise ValueError
            return envelope
        except Exception:
            raise QdrantVectorStoreError from None


def _normalize_ids(value: object, *, maximum: int) -> tuple[UUID, ...]:
    if type(value) is not tuple or not value or len(value) > maximum:
        raise QdrantVectorStoreError
    normalized: list[UUID] = []
    seen: set[UUID] = set()
    for point_id in value:
        if type(point_id) is not UUID or point_id in seen:
            raise QdrantVectorStoreError
        seen.add(point_id)
        normalized.append(point_id)
    return tuple(normalized)


def _normalize_number(value: object) -> float:
    if type(value) not in {int, float}:
        raise QdrantVectorStoreError
    normalized = float(cast(int | float, value))
    if not math.isfinite(normalized):
        raise QdrantVectorStoreError
    return normalized


def _parse_uuid(value: object) -> UUID:
    if type(value) is not str:
        raise QdrantVectorStoreError
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        raise QdrantVectorStoreError from None


def _require_object(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise QdrantVectorStoreError
    return cast(dict[str, object], value)


def _validate_json_value(value: object, *, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise QdrantVectorStoreError
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise QdrantVectorStoreError
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise QdrantVectorStoreError
        for item in value.values():
            _validate_json_value(item, depth=depth + 1)
        return
    raise QdrantVectorStoreError


def _normalize_json_object(value: object) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise QdrantVectorStoreError
    _validate_json_value(value)
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise ValueError
        decoded: object = json.loads(encoded)
        normalized = _require_object(decoded)
        return cast(dict[str, JsonValue], normalized)
    except Exception:
        raise QdrantVectorStoreError from None


def _require_completed(envelope: dict[str, object]) -> None:
    result = _require_object(envelope.get("result"))
    if result.get("status") != "completed":
        raise QdrantVectorStoreError


__all__ = [
    "JsonValue",
    "QdrantHit",
    "QdrantPoint",
    "QdrantStoredPoint",
    "QdrantVectorAdapter",
    "QdrantVectorStoreError",
]
