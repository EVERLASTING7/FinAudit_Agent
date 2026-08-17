from __future__ import annotations

import hashlib
import json
import os
import sys
from importlib import resources
from pathlib import Path
from uuid import uuid4

from pydantic import SecretStr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.ai.adapters.openai_compatible import (  # noqa: E402
    OpenAiChatCompletionsAdapter,
    OpenAiCompatibleProfile,
)
from app.ai.contracts import (  # noqa: E402
    ExternalError,
    LlmGenerationParameters,
    LlmRequest,
    LlmResult,
    TransportPolicy,
)
from app.ai.live_policy import LIVE_LLM_POLICY  # noqa: E402
from app.ai.network_policy import OutboundNetworkPolicy  # noqa: E402
from app.ai.strict_json import StrictJsonError, parse_strict_json  # noqa: E402

_CONFIRMATION = "ALLOW_ONE_BOUNDED_MINIMAX_CALL"
_REGISTRY_SHA256 = "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"


class LiveSmokeError(RuntimeError):
    pass


def _required_secret() -> SecretStr:
    value = os.environ.get("LLM_API_KEY", "").strip()
    if not value or value.upper().startswith("REPLACE_"):
        raise LiveSmokeError("LLM_API_KEY_REQUIRED")
    return SecretStr(value)


def _estimated_cost_micro_usd(input_tokens: int, output_tokens: int) -> int:
    numerator = (
        input_tokens * LIVE_LLM_POLICY.input_price_micro_usd_per_million
        + output_tokens * LIVE_LLM_POLICY.output_price_micro_usd_per_million
    )
    return (numerator + 999_999) // 1_000_000


def main() -> int:
    if os.environ.get("FINAUDIT_LIVE_AI_SMOKE") != _CONFIRMATION:
        raise LiveSmokeError("LIVE_AI_SMOKE_CONFIRMATION_REQUIRED")
    registry_bytes = (
        resources.files("app.ai.artifacts.cr011_v1")
        .joinpath("ip-deny-cidrs-v1.json")
        .read_bytes()
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
            api_key=_required_secret(),
            network_policy=network_policy,
            registry_bytes=registry_bytes,
            max_request_bytes=LIVE_LLM_POLICY.max_request_bytes,
            max_response_header_bytes=LIVE_LLM_POLICY.max_response_header_bytes,
            max_response_body_bytes=LIVE_LLM_POLICY.max_response_body_bytes,
            use_max_completion_tokens=LIVE_LLM_POLICY.use_max_completion_tokens,
            thinking_mode="disabled",
            service_tier="standard",
        )
    )
    try:
        request = LlmRequest(
            trace_id=str(uuid4()),
            system_instruction=(
                'Return only the strict JSON object {"ok":true}. '
                "Do not return Markdown or any other text."
            ),
            user_content="adapter smoke test",
            parameters=LlmGenerationParameters(
                temperature=LIVE_LLM_POLICY.temperature,
                top_p=LIVE_LLM_POLICY.top_p,
                max_tokens=128,
            ),
        )
        result = adapter.generate(
            request,
            adapter.target,
            TransportPolicy(
                connect_timeout_seconds=5,
                read_timeout_seconds=30,
                total_timeout_seconds=35,
                max_attempts=1,
            ),
        )
    finally:
        adapter.close()

    if isinstance(result, ExternalError):
        print(
            json.dumps(
                {
                    "category": result.category.value,
                    "http_status": result.status_code,
                    "status": "failed",
                },
                separators=(",", ":"),
            )
        )
        return 1
    if not isinstance(result, LlmResult):
        raise LiveSmokeError("LIVE_AI_RESULT_INVALID")
    try:
        structured = parse_strict_json(result.output_text.encode("utf-8")).value
    except (UnicodeError, StrictJsonError):
        structured = None
    if structured != {"ok": True}:
        raise LiveSmokeError("LIVE_AI_STRUCTURED_OUTPUT_INVALID")
    if result.input_tokens is None or result.output_tokens is None:
        raise LiveSmokeError("LIVE_AI_USAGE_MISSING")
    summary = {
        "adapter_id": adapter.target.adapter_id,
        "estimated_cost_micro_usd": _estimated_cost_micro_usd(
            result.input_tokens,
            result.output_tokens,
        ),
        "input_tokens": result.input_tokens,
        "model_id": result.target.model_id,
        "output_sha256": hashlib.sha256(result.output_text.encode("utf-8")).hexdigest(),
        "output_tokens": result.output_tokens,
        "response_body_sha256": result.response_body_sha256,
        "status": "passed",
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LiveSmokeError as error:
        print(json.dumps({"code": str(error), "status": "failed"}, separators=(",", ":")))
        raise SystemExit(1) from None
