"""受出站策略约束的 OpenAI-compatible Chat/Embedding Adapter。"""

from __future__ import annotations

import hashlib
import ipaddress
import math
import queue
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from app.ai.contracts import (
    EmbeddingOutcome,
    EmbeddingRequest,
    EmbeddingResult,
    ExternalError,
    ExternalErrorCategory,
    LlmOutcome,
    LlmRequest,
    LlmResult,
    ModelTarget,
    TransportPolicy,
)
from app.ai.network_policy import (
    OutboundNetworkPolicy,
    ResolutionBinding,
    authorize_peer,
    authorize_resolution,
)
from app.ai.response_boundary import (
    ResponseBoundaryError,
    encode_request_body,
    inspect_response_wire,
    parse_response_json,
)
from app.ai.retry_policy import parse_retry_after_seconds
from app.ai.strict_json import JsonValue

OPENAI_CHAT_COMPLETIONS_ADAPTER_ID = "openai_chat_completions_v1"
OPENAI_EMBEDDINGS_ADAPTER_ID = "openai_embeddings_v1"

_Resolver = Callable[[str, int], tuple[str, ...]]
_PeerAddressReader = Callable[[httpx.Response], str | None]
_Clock = Callable[[], float]


class OpenAiCompatibleConfigurationError(ValueError):
    """固定错误文本，不携带 Profile、模型或 secret 原值。"""

    def __init__(self) -> None:
        super().__init__("OpenAI-compatible adapter configuration is invalid")


@dataclass(frozen=True, slots=True)
class OpenAiCompatibleProfile:
    profile_type: Literal["chat", "embedding"]
    base_url: str
    model_id: str
    allowed_response_model_ids: tuple[str, ...]
    api_key: SecretStr = field(repr=False, compare=False)
    network_policy: OutboundNetworkPolicy
    registry_bytes: bytes = field(repr=False, compare=False)
    max_request_bytes: int = 4_194_304
    max_response_header_bytes: int = 65_536
    max_response_body_bytes: int = 2_097_152
    embedding_dimension: int | None = None
    use_max_completion_tokens: bool = False
    thinking_mode: Literal["disabled", "adaptive", "enabled"] | None = None
    service_tier: Literal["standard"] | None = None

    def __post_init__(self) -> None:
        adapter_id = (
            OPENAI_CHAT_COMPLETIONS_ADAPTER_ID
            if self.profile_type == "chat"
            else OPENAI_EMBEDDINGS_ADAPTER_ID
            if self.profile_type == "embedding"
            else None
        )
        if (
            adapter_id is None
            or not isinstance(self.api_key, SecretStr)
            or not self.api_key.get_secret_value().strip()
            or not isinstance(self.network_policy, OutboundNetworkPolicy)
            or self.network_policy.base_url != self.base_url
            or not isinstance(self.base_url, str)
            or not isinstance(self.model_id, str)
            or not self.model_id.strip()
            or not self.allowed_response_model_ids
            or len(set(self.allowed_response_model_ids)) != len(self.allowed_response_model_ids)
            or any(
                not isinstance(value, str) or not value.strip()
                for value in self.allowed_response_model_ids
            )
            or not isinstance(self.registry_bytes, bytes)
            or not self.registry_bytes
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in (
                    self.max_request_bytes,
                    self.max_response_header_bytes,
                    self.max_response_body_bytes,
                )
            )
            or (self.profile_type == "chat") != (self.embedding_dimension is None)
            or not isinstance(self.use_max_completion_tokens, bool)
            or (
                self.profile_type == "embedding"
                and (
                    self.use_max_completion_tokens
                    or self.thinking_mode is not None
                    or self.service_tier is not None
                )
            )
            or (
                self.embedding_dimension is not None
                and (
                    isinstance(self.embedding_dimension, bool)
                    or not isinstance(self.embedding_dimension, int)
                    or self.embedding_dimension <= 0
                )
            )
        ):
            raise OpenAiCompatibleConfigurationError

        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.path not in {"/v1", "/compatible-mode/v1"}
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            or parsed.hostname is None
        ):
            raise OpenAiCompatibleConfigurationError

    @property
    def target(self) -> ModelTarget:
        adapter_id = (
            OPENAI_CHAT_COMPLETIONS_ADAPTER_ID
            if self.profile_type == "chat"
            else OPENAI_EMBEDDINGS_ADAPTER_ID
        )
        return ModelTarget(adapter_id=adapter_id, model_id=self.model_id)


def _system_resolver(hostname: str, port: int) -> tuple[str, ...]:
    records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return tuple(sorted({str(record[4][0]) for record in records}))


def _network_stream_peer(response: httpx.Response) -> str | None:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return None
    get_extra_info = getattr(stream, "get_extra_info", None)
    if not callable(get_extra_info):
        return None
    server_address = get_extra_info("server_addr")
    if (
        not isinstance(server_address, tuple)
        or not server_address
        or not isinstance(server_address[0], str)
    ):
        return None
    return server_address[0]


def _raw_header_values(headers: tuple[tuple[bytes, bytes], ...], name: bytes) -> tuple[bytes, ...]:
    return tuple(value for field_name, value in headers if field_name.lower() == name)


def _content_encoding(headers: tuple[tuple[bytes, bytes], ...]) -> Literal["identity", "gzip"]:
    values = _raw_header_values(headers, b"content-encoding")
    if not values:
        return "identity"
    if len(values) != 1:
        raise ResponseBoundaryError
    try:
        value = values[0].decode("ascii", errors="strict").strip().lower()
    except UnicodeDecodeError:
        raise ResponseBoundaryError from None
    if value not in {"identity", "gzip"}:
        raise ResponseBoundaryError
    return cast(Literal["identity", "gzip"], value)


def _is_json_content_type(headers: tuple[tuple[bytes, bytes], ...]) -> bool:
    values = _raw_header_values(headers, b"content-type")
    if len(values) != 1:
        return False
    try:
        value = values[0].decode("ascii", errors="strict")
    except UnicodeDecodeError:
        return False
    return value.split(";", maxsplit=1)[0].strip().lower() == "application/json"


def _non_negative_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _error_discriminator(payload: JsonValue) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None, None
    error_type = error.get("type")
    error_code = error.get("code")
    return (
        error_type if isinstance(error_type, str) else None,
        error_code if isinstance(error_code, str) else None,
    )


def _http_error(
    *,
    trace_id: str,
    status_code: int,
    raw_headers: tuple[tuple[bytes, bytes], ...],
    body: bytes | None,
    diagnostic_available: bool,
    wall_clock_epoch_seconds: float,
) -> ExternalError:
    if status_code == 429:
        retry_after = (
            parse_retry_after_seconds(
                status_code=status_code,
                header_values=_raw_header_values(raw_headers, b"retry-after"),
                wall_clock_epoch_seconds=wall_clock_epoch_seconds,
            )
            if diagnostic_available
            else None
        )
        return ExternalError(
            trace_id=trace_id,
            category=ExternalErrorCategory.RATE_LIMITED,
            status_code=429,
            retry_after_seconds=retry_after,
        )
    if 500 <= status_code <= 599:
        return ExternalError(
            trace_id=trace_id,
            category=ExternalErrorCategory.SERVER_ERROR,
            status_code=status_code,
        )
    if 300 <= status_code <= 399:
        return ExternalError(
            trace_id=trace_id,
            category=ExternalErrorCategory.PROVIDER_CONFIGURATION_ERROR,
            status_code=status_code,
        )
    if 200 <= status_code <= 299:
        return ExternalError(
            trace_id=trace_id,
            category=ExternalErrorCategory.INVALID_RESPONSE,
            status_code=status_code,
        )

    error_type: str | None = None
    error_code: str | None = None
    if diagnostic_available and body is not None and _is_json_content_type(raw_headers):
        try:
            error_type, error_code = _error_discriminator(parse_response_json(body))
        except ResponseBoundaryError:
            pass
    discriminators = {error_type, error_code}
    if status_code == 400 and discriminators.intersection(
        {
            "context_length_exceeded",
            "context_window_exceeded",
            "max_context_length_exceeded",
        }
    ):
        category = ExternalErrorCategory.CONTEXT_LIMIT
    elif status_code in {400, 403} and discriminators.intersection(
        {"content_policy_violation", "content_filter", "safety_violation"}
    ):
        category = ExternalErrorCategory.CONTENT_REJECTED
    else:
        category = ExternalErrorCategory.CLIENT_ERROR
    return ExternalError(trace_id=trace_id, category=category, status_code=status_code)


class _OpenAiCompatibleAdapterBase:
    def __init__(
        self,
        profile: OpenAiCompatibleProfile,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: _Resolver = _system_resolver,
        peer_address_reader: _PeerAddressReader = _network_stream_peer,
        monotonic_clock: _Clock = time.monotonic,
        wall_clock: _Clock = time.time,
    ) -> None:
        self._profile = profile
        self._resolver = resolver
        self._peer_address_reader = peer_address_reader
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            headers={"Accept-Encoding": "identity"},
        )

    @property
    def target(self) -> ModelTarget:
        return self._profile.target

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> _OpenAiCompatibleAdapterBase:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def _network_binding(
        self,
        trace_id: str,
        *,
        deadline: float,
    ) -> ResolutionBinding | ExternalError:
        parsed = urlsplit(self._profile.base_url)
        hostname = parsed.hostname
        if hostname is None:
            return ExternalError(
                trace_id=trace_id,
                category=ExternalErrorCategory.PROVIDER_CONFIGURATION_ERROR,
            )
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        result_queue: queue.SimpleQueue[tuple[str, ...] | BaseException] = queue.SimpleQueue()

        def resolve() -> None:
            try:
                result_queue.put(self._resolver(hostname, port))
            except BaseException as error:
                result_queue.put(error)

        resolver_thread = threading.Thread(target=resolve, daemon=True)
        resolver_thread.start()
        resolver_thread.join(max(0.0, deadline - self._monotonic_clock()))
        if resolver_thread.is_alive():
            return ExternalError(
                trace_id=trace_id,
                category=ExternalErrorCategory.CONNECT_TIMEOUT,
            )
        try:
            resolution = result_queue.get_nowait()
        except queue.Empty:
            resolution = RuntimeError()
        if isinstance(resolution, BaseException):
            return ExternalError(
                trace_id=trace_id,
                category=ExternalErrorCategory.CONNECTION_ERROR,
            )
        addresses = resolution
        decision = authorize_resolution(
            self._profile.network_policy,
            hostname=hostname,
            resolved_addresses=addresses,
            registry_bytes=self._profile.registry_bytes,
        )
        if not decision.allowed or decision.binding is None:
            return ExternalError(
                trace_id=trace_id,
                category=ExternalErrorCategory.PROVIDER_CONFIGURATION_ERROR,
            )
        return decision.binding

    @staticmethod
    def _bound_url(
        binding: ResolutionBinding,
        *,
        scheme: str,
        port: int,
        path: str,
    ) -> tuple[str, str]:
        """连接到已批准 IP，同时保留原 hostname 的 Host/SNI。"""

        address = binding.resolved_addresses[0]
        parsed_address = ipaddress.ip_address(address)
        host = f"[{address}]" if parsed_address.version == 6 else address
        default_port = 443 if scheme == "https" else 80
        authority = host if port == default_port else f"{host}:{port}"
        return f"{scheme}://{authority}{path}", address

    def _send(
        self,
        *,
        trace_id: str,
        path: Literal["/chat/completions", "/embeddings"],
        body: bytes,
        policy: TransportPolicy,
    ) -> tuple[bytes, tuple[tuple[bytes, bytes], ...]] | ExternalError:
        started = self._monotonic_clock()
        deadline = started + policy.total_timeout_seconds
        binding = self._network_binding(trace_id, deadline=deadline)
        if isinstance(binding, ExternalError):
            return binding
        remaining = deadline - self._monotonic_clock()
        if remaining <= 0:
            return ExternalError(
                trace_id=trace_id,
                category=ExternalErrorCategory.CONNECT_TIMEOUT,
            )
        timeout = httpx.Timeout(
            connect=min(policy.connect_timeout_seconds, remaining),
            read=min(policy.read_timeout_seconds, remaining),
            write=min(policy.read_timeout_seconds, remaining),
            pool=min(policy.connect_timeout_seconds, remaining),
        )
        parsed_base_url = urlsplit(self._profile.base_url)
        hostname = parsed_base_url.hostname
        if hostname is None:
            return ExternalError(
                trace_id=trace_id,
                category=ExternalErrorCategory.PROVIDER_CONFIGURATION_ERROR,
            )
        port = parsed_base_url.port or (443 if parsed_base_url.scheme == "https" else 80)
        request_url, selected_address = self._bound_url(
            binding,
            scheme=parsed_base_url.scheme,
            port=port,
            path=f"{parsed_base_url.path}{path}",
        )
        default_port = 443 if parsed_base_url.scheme == "https" else 80
        host_header = hostname if port == default_port else f"{hostname}:{port}"
        headers = {
            "Authorization": f"Bearer {self._profile.api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Host": host_header,
        }
        try:
            with self._client.stream(
                "POST",
                request_url,
                content=body,
                headers=headers,
                timeout=timeout,
                extensions={"sni_hostname": hostname},
            ) as response:
                raw_headers = tuple(response.headers.raw)
                peer_address = self._peer_address_reader(response)
                if (
                    peer_address is None
                    or peer_address != selected_address
                    or not authorize_peer(
                        self._profile.network_policy,
                        binding,
                        peer_address=peer_address,
                        registry_bytes=self._profile.registry_bytes,
                    ).allowed
                ):
                    return ExternalError(
                        trace_id=trace_id,
                        category=ExternalErrorCategory.PROVIDER_CONFIGURATION_ERROR,
                    )

                body_parts: list[bytes] = []
                body_length = 0
                body_limit_exceeded = False
                for chunk in response.iter_raw():
                    if self._monotonic_clock() >= deadline:
                        return ExternalError(
                            trace_id=trace_id,
                            category=ExternalErrorCategory.READ_TIMEOUT,
                        )
                    body_length += len(chunk)
                    if body_length > self._profile.max_response_body_bytes:
                        body_limit_exceeded = True
                        break
                    body_parts.append(chunk)
                raw_body = b"".join(body_parts)
                if self._monotonic_clock() >= deadline:
                    return ExternalError(
                        trace_id=trace_id,
                        category=ExternalErrorCategory.READ_TIMEOUT,
                    )
                if body_limit_exceeded:
                    if response.status_code == 200:
                        return ExternalError(
                            trace_id=trace_id,
                            category=ExternalErrorCategory.INVALID_RESPONSE,
                            status_code=200,
                        )
                    return _http_error(
                        trace_id=trace_id,
                        status_code=response.status_code,
                        raw_headers=raw_headers,
                        body=None,
                        diagnostic_available=False,
                        wall_clock_epoch_seconds=self._wall_clock(),
                    )
                try:
                    encoding = _content_encoding(raw_headers)
                    wire = inspect_response_wire(
                        status_code=response.status_code,
                        raw_headers=raw_headers,
                        raw_body=raw_body,
                        content_encoding=encoding,
                        max_header_bytes=self._profile.max_response_header_bytes,
                        max_body_bytes=self._profile.max_response_body_bytes,
                    )
                except ResponseBoundaryError:
                    if response.status_code != 200:
                        return _http_error(
                            trace_id=trace_id,
                            status_code=response.status_code,
                            raw_headers=raw_headers,
                            body=None,
                            diagnostic_available=False,
                            wall_clock_epoch_seconds=self._wall_clock(),
                        )
                    return ExternalError(
                        trace_id=trace_id,
                        category=ExternalErrorCategory.INVALID_RESPONSE,
                        status_code=200,
                    )
                if response.status_code != 200:
                    return _http_error(
                        trace_id=trace_id,
                        status_code=response.status_code,
                        raw_headers=raw_headers,
                        body=wire.body,
                        diagnostic_available=wire.diagnostic_available,
                        wall_clock_epoch_seconds=self._wall_clock(),
                    )
                if wire.body is None or not _is_json_content_type(raw_headers):
                    return ExternalError(
                        trace_id=trace_id,
                        category=ExternalErrorCategory.INVALID_RESPONSE,
                        status_code=200,
                    )
                return wire.body, raw_headers
        except httpx.ConnectTimeout:
            return ExternalError(
                trace_id=trace_id,
                category=ExternalErrorCategory.CONNECT_TIMEOUT,
            )
        except httpx.ReadTimeout:
            return ExternalError(
                trace_id=trace_id,
                category=ExternalErrorCategory.READ_TIMEOUT,
            )
        except (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.StreamError,
            httpx.WriteError,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
        ):
            return ExternalError(
                trace_id=trace_id,
                category=ExternalErrorCategory.CONNECTION_ERROR,
            )


class OpenAiChatCompletionsAdapter(_OpenAiCompatibleAdapterBase):
    def __init__(
        self,
        profile: OpenAiCompatibleProfile,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: _Resolver = _system_resolver,
        peer_address_reader: _PeerAddressReader = _network_stream_peer,
        monotonic_clock: _Clock = time.monotonic,
        wall_clock: _Clock = time.time,
    ) -> None:
        if profile.profile_type != "chat":
            raise OpenAiCompatibleConfigurationError
        super().__init__(
            profile,
            transport=transport,
            resolver=resolver,
            peer_address_reader=peer_address_reader,
            monotonic_clock=monotonic_clock,
            wall_clock=wall_clock,
        )

    def request_body(self, request: LlmRequest, target: ModelTarget) -> bytes:
        if target != self.target or request.parameters is None:
            raise OpenAiCompatibleConfigurationError
        payload: dict[str, JsonValue] = {
            "model": target.model_id,
            "messages": [
                {"role": "system", "content": request.system_instruction},
                {"role": "user", "content": request.user_content},
            ],
            "temperature": request.parameters.temperature,
            "top_p": request.parameters.top_p,
            "n": 1,
            "stream": False,
        }
        token_field = (
            "max_completion_tokens" if self._profile.use_max_completion_tokens else "max_tokens"
        )
        payload[token_field] = request.parameters.max_tokens
        if self._profile.thinking_mode is not None:
            payload["thinking"] = {"type": self._profile.thinking_mode}
        if self._profile.service_tier is not None:
            payload["service_tier"] = self._profile.service_tier
        return encode_request_body(payload, max_bytes=self._profile.max_request_bytes)

    def generate(
        self,
        request: LlmRequest,
        target: ModelTarget,
        policy: TransportPolicy,
    ) -> LlmOutcome:
        try:
            body = self.request_body(request, target)
        except (OpenAiCompatibleConfigurationError, ResponseBoundaryError):
            return ExternalError(
                trace_id=request.trace_id,
                category=ExternalErrorCategory.PROVIDER_CONFIGURATION_ERROR,
            )
        response = self._send(
            trace_id=request.trace_id,
            path="/chat/completions",
            body=body,
            policy=policy,
        )
        if isinstance(response, ExternalError):
            return response
        raw_body, _ = response
        try:
            payload = parse_response_json(raw_body)
            return self._parse_success(request, target, payload, raw_body)
        except ResponseBoundaryError:
            return ExternalError(
                trace_id=request.trace_id,
                category=ExternalErrorCategory.INVALID_RESPONSE,
                status_code=200,
            )

    def _parse_success(
        self,
        request: LlmRequest,
        target: ModelTarget,
        payload: JsonValue,
        raw_body: bytes,
    ) -> LlmOutcome:
        if not isinstance(payload, dict):
            return self._invalid_response(request.trace_id)
        model = payload.get("model")
        choices = payload.get("choices")
        usage = payload.get("usage")
        if (
            not isinstance(model, str)
            or model not in self._profile.allowed_response_model_ids
            or not isinstance(choices, list)
            or len(choices) != 1
            or not isinstance(choices[0], dict)
            or not isinstance(usage, dict)
        ):
            return self._invalid_response(request.trace_id)
        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            return ExternalError(
                trace_id=request.trace_id,
                category=ExternalErrorCategory.OUTPUT_TRUNCATED,
                status_code=200,
            )
        if finish_reason == "content_filter":
            return ExternalError(
                trace_id=request.trace_id,
                category=ExternalErrorCategory.CONTENT_REJECTED,
                status_code=200,
            )
        message = choice.get("message")
        if (
            finish_reason != "stop"
            or choice.get("index") != 0
            or not isinstance(message, dict)
            or message.get("role") != "assistant"
            or not isinstance(message.get("content"), str)
            or not cast(str, message.get("content")).strip()
        ):
            return self._invalid_response(request.trace_id)
        input_tokens = _non_negative_integer(usage.get("prompt_tokens"))
        output_tokens = _non_negative_integer(usage.get("completion_tokens"))
        total_tokens = _non_negative_integer(usage.get("total_tokens"))
        if (
            input_tokens is None
            or output_tokens is None
            or total_tokens is None
            or input_tokens + output_tokens != total_tokens
        ):
            return self._invalid_response(request.trace_id)
        return LlmResult(
            trace_id=request.trace_id,
            target=target,
            output_text=cast(str, message["content"]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            response_body_sha256=hashlib.sha256(raw_body).hexdigest(),
        )

    @staticmethod
    def _invalid_response(trace_id: str) -> ExternalError:
        return ExternalError(
            trace_id=trace_id,
            category=ExternalErrorCategory.INVALID_RESPONSE,
            status_code=200,
        )


class OpenAiEmbeddingsAdapter(_OpenAiCompatibleAdapterBase):
    def __init__(
        self,
        profile: OpenAiCompatibleProfile,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: _Resolver = _system_resolver,
        peer_address_reader: _PeerAddressReader = _network_stream_peer,
        monotonic_clock: _Clock = time.monotonic,
        wall_clock: _Clock = time.time,
    ) -> None:
        if profile.profile_type != "embedding":
            raise OpenAiCompatibleConfigurationError
        super().__init__(
            profile,
            transport=transport,
            resolver=resolver,
            peer_address_reader=peer_address_reader,
            monotonic_clock=monotonic_clock,
            wall_clock=wall_clock,
        )

    def request_body(self, request: EmbeddingRequest, target: ModelTarget) -> bytes:
        if target != self.target:
            raise OpenAiCompatibleConfigurationError
        payload: JsonValue = {
            "model": target.model_id,
            "input": list(request.input_texts),
            "dimensions": self._profile.embedding_dimension,
            "encoding_format": "float",
        }
        return encode_request_body(payload, max_bytes=self._profile.max_request_bytes)

    def embed(
        self,
        request: EmbeddingRequest,
        target: ModelTarget,
        policy: TransportPolicy,
    ) -> EmbeddingOutcome:
        try:
            body = self.request_body(request, target)
        except (OpenAiCompatibleConfigurationError, ResponseBoundaryError):
            return ExternalError(
                trace_id=request.trace_id,
                category=ExternalErrorCategory.PROVIDER_CONFIGURATION_ERROR,
            )
        response = self._send(
            trace_id=request.trace_id,
            path="/embeddings",
            body=body,
            policy=policy,
        )
        if isinstance(response, ExternalError):
            return response
        raw_body, _ = response
        try:
            payload = parse_response_json(raw_body)
        except ResponseBoundaryError:
            return self._invalid_response(request.trace_id)
        if not isinstance(payload, dict):
            return self._invalid_response(request.trace_id)
        model = payload.get("model")
        data = payload.get("data")
        usage = payload.get("usage")
        if (
            not isinstance(model, str)
            or model not in self._profile.allowed_response_model_ids
            or not isinstance(data, list)
            or len(data) != len(request.input_texts)
            or not isinstance(usage, dict)
        ):
            return self._invalid_response(request.trace_id)
        vectors: dict[int, tuple[float, ...]] = {}
        for item in data:
            if not isinstance(item, dict):
                return self._invalid_response(request.trace_id)
            index = item.get("index")
            vector = item.get("embedding")
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or index in vectors
                or not 0 <= index < len(request.input_texts)
                or not isinstance(vector, list)
                or len(vector) != self._profile.embedding_dimension
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in vector
                )
            ):
                return self._invalid_response(request.trace_id)
            vectors[index] = tuple(float(cast(int | float, value)) for value in vector)
        if set(vectors) != set(range(len(request.input_texts))):
            return self._invalid_response(request.trace_id)
        input_tokens = _non_negative_integer(usage.get("prompt_tokens"))
        total_tokens = _non_negative_integer(usage.get("total_tokens"))
        if input_tokens is None or total_tokens != input_tokens:
            return self._invalid_response(request.trace_id)
        return EmbeddingResult(
            trace_id=request.trace_id,
            target=target,
            vectors=tuple(vectors[index] for index in range(len(vectors))),
            input_tokens=input_tokens,
            response_body_sha256=hashlib.sha256(raw_body).hexdigest(),
        )

    @staticmethod
    def _invalid_response(trace_id: str) -> ExternalError:
        return ExternalError(
            trace_id=trace_id,
            category=ExternalErrorCategory.INVALID_RESPONSE,
            status_code=200,
        )


__all__ = [
    "OPENAI_CHAT_COMPLETIONS_ADAPTER_ID",
    "OPENAI_EMBEDDINGS_ADAPTER_ID",
    "OpenAiChatCompletionsAdapter",
    "OpenAiCompatibleConfigurationError",
    "OpenAiCompatibleProfile",
    "OpenAiEmbeddingsAdapter",
]
