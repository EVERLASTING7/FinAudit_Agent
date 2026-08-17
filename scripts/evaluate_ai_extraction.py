from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from app.ai.strict_json import StrictJsonError, parse_strict_json
from app.evaluation.ai_extraction_metrics import (
    AiExtractionEvaluationInput,
    evaluate_ai_extraction,
)

_MAX_INPUT_BYTES = 16_777_216


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(_MAX_INPUT_BYTES + 1)
    if len(raw) > _MAX_INPUT_BYTES:
        raise ValueError("evaluation input exceeds the fixed byte limit")
    return raw


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: evaluate_ai_extraction.py <approved-evaluation.json>", file=sys.stderr)
        return 2
    try:
        raw = _read_bounded(Path(sys.argv[1]))
        payload = parse_strict_json(raw).value
        evaluation = AiExtractionEvaluationInput.model_validate(payload)
    except (OSError, StrictJsonError, ValidationError, ValueError):
        print("AI_EXTRACTION_EVALUATION_INPUT_INVALID", file=sys.stderr)
        return 2

    result = evaluate_ai_extraction(evaluation)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=True, sort_keys=True))
    return 0 if result.threshold_status == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
