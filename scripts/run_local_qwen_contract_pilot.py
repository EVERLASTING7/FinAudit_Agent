"""用本机 Ollama 对一份公开扫描合同运行生产 Prompt/Validator pilot。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from app.ai.extraction_output import (  # noqa: E402
    ExtractionOutputError,
    validate_contract_extraction_output,
)
from app.ai.contracts import LlmRequest  # noqa: E402
from app.ai.extraction_prompts import (  # noqa: E402
    CONTRACT_EXTRACTION_PROMPT,
    ExtractionPromptBlock,
    build_extraction_prompt_request,
)

import scripts.verify_public_business_benchmark as benchmark  # noqa: E402

_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
_MAX_OCR_RESULT_BYTES = 16 * 1024 * 1024
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_FIELD_TERMS = (
    "合同",
    "编号",
    "名称",
    "甲方",
    "乙方",
    "采购人",
    "供应商",
    "金额",
    "人民币",
    "签订",
    "签署",
    "日期",
    "期限",
    "生效",
    "到期",
    "终止",
    "付款",
)


def _read_object(path: Path, *, limit: int) -> dict[str, object]:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("bounded JSON input exceeded")
    value = json.loads(raw)
    if type(value) is not dict:
        raise ValueError("JSON root must be an object")
    return value


def _blocks(
    payload: dict[str, object], case_id: str
) -> tuple[ExtractionPromptBlock, ...]:
    raw_cases = payload.get("cases")
    if type(raw_cases) is not list:
        raise ValueError("OCR result cases are invalid")
    selected = sorted(
        (
            case
            for case in raw_cases
            if type(case) is dict
            and str(case.get("case_id", "")).startswith(f"{case_id}-p")
        ),
        key=lambda case: str(case["case_id"]),
    )
    if not selected or any(case.get("status") != "succeeded" for case in selected):
        raise ValueError("OCR result is incomplete")
    raw_lines: list[tuple[int, str]] = []
    for page_no, case in enumerate(selected, start=1):
        lines = case.get("lines")
        if type(lines) is not list:
            raise ValueError("OCR lines are invalid")
        for raw_line in lines:
            if type(raw_line) is not str:
                raise ValueError("OCR line is invalid")
            text = " ".join(raw_line.split())
            if text:
                raw_lines.append((page_no, text))
    relevant = {
        index
        for index, (_, text) in enumerate(raw_lines)
        if any(term in "".join(text.split()) for term in _FIELD_TERMS)
    }
    selected_indexes = sorted(
        {
            neighbor
            for index in relevant
            for neighbor in (index - 1, index, index + 1)
            if 0 <= neighbor < len(raw_lines)
        }
    )[:80]
    if not selected_indexes:
        raise ValueError("OCR field blocks are empty")
    parse_id = uuid5(NAMESPACE_URL, f"finaudit-public-local-qwen/{case_id}/parse")
    result: list[ExtractionPromptBlock] = []
    for block_index, raw_index in enumerate(selected_indexes):
        page_no, text = raw_lines[raw_index]
        result.append(
            ExtractionPromptBlock(
                block_id=uuid5(
                    NAMESPACE_URL,
                    f"finaudit-public-local-qwen/{case_id}/block/{block_index}",
                ),
                parse_version_id=parse_id,
                page_no=page_no,
                block_index=block_index,
                text=text[:4000],
                bbox=None,
                confidence=None,
            )
        )
    if not result:
        raise ValueError("OCR blocks are empty")
    return tuple(result)


def _ollama(prompt: LlmRequest) -> tuple[str, dict[str, object], float]:
    request_data = {
        "model": "qwen3:8b",
        "messages": [
            {"role": "system", "content": prompt.system_instruction},
            {"role": "user", "content": prompt.user_content},
        ],
        "stream": False,
        "format": "json",
        "think": False,
        "options": {"temperature": 0, "seed": 0, "num_ctx": 8192},
    }
    request = urllib.request.Request(
        _OLLAMA_URL,
        data=json.dumps(request_data, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.monotonic()
    with opener.open(request, timeout=180) as response:
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
    elapsed = time.monotonic() - started
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("Ollama response exceeded the byte limit")
    body = json.loads(raw)
    if type(body) is not dict:
        raise ValueError("Ollama response is invalid")
    message = body.get("message")
    if type(message) is not dict or type(message.get("content")) is not str:
        raise ValueError("Ollama message is invalid")
    return message["content"], body, elapsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", default="93691")
    parser.add_argument(
        "--ocr-result",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "public-contract-ocr-pilot-v1" / "result.json",
    )
    args = parser.parse_args()
    allowed_ids = {case.case_id for case in benchmark._HAIKOU_CASES}
    if args.case_id not in allowed_ids:
        print("LOCAL_QWEN_CONTRACT_PILOT=INVALID_CASE", file=sys.stderr)
        return 2

    try:
        ocr = _read_object(args.ocr_result, limit=_MAX_OCR_RESULT_BYTES)
        blocks = _blocks(ocr, args.case_id)
        prompt = build_extraction_prompt_request(
            artifact=CONTRACT_EXTRACTION_PROMPT,
            trace_id=str(
                uuid5(NAMESPACE_URL, f"finaudit-public-local-qwen/{args.case_id}/trace")
            ),
            blocks=blocks,
        )
        output_text, body, elapsed = _ollama(prompt)
    except urllib.error.HTTPError as error:
        print(f"LOCAL_QWEN_CONTRACT_PILOT=HTTP_{error.code}")
        return 1
    except urllib.error.URLError:
        print("LOCAL_QWEN_CONTRACT_PILOT=LOOPBACK_UNAVAILABLE")
        return 1
    except TimeoutError:
        print("LOCAL_QWEN_CONTRACT_PILOT=TIMEOUT")
        return 1
    except (OSError, ValueError) as error:
        print(f"LOCAL_QWEN_CONTRACT_PILOT=RUNTIME_{type(error).__name__.upper()}")
        return 1

    output_valid = True
    try:
        output = validate_contract_extraction_output(output_text, blocks=blocks)
    except ExtractionOutputError:
        output_valid = False
        actual: dict[str, object] = {}
    else:
        actual = output.facts.model_dump(mode="json")
    expected = benchmark._haikou_expected(
        (benchmark.HAIKOU_ROOT / f"{args.case_id}.html").read_bytes()
    )
    matched = [
        field_code
        for field_code, expected_value in expected.items()
        if actual.get(field_code) is not None
        and benchmark._normalized(str(actual[field_code]))
        == benchmark._normalized(expected_value)
    ]
    summary = {
        "schema_version": "public-local-qwen-contract-pilot-v1",
        "case_id": args.case_id,
        "ocr_block_count": len(blocks),
        "prompt_char_count": len(prompt.system_instruction) + len(prompt.user_content),
        "output_valid": output_valid,
        "actual_non_null_count": sum(value is not None for value in actual.values()),
        "matched_field_count": len(matched),
        "expected_field_count": len(expected),
        "matched_fields": sorted(matched),
        "elapsed_ms": round(elapsed * 1000, 3),
        "prompt_eval_count": body.get("prompt_eval_count"),
        "eval_count": body.get("eval_count"),
        "block_selection": "field_term_plus_adjacent_lines_max_80",
        "response_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
        "provider_network_calls": 0,
        "paid_cost_cny": "0.000000",
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
