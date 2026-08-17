from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

QDRANT_ENDPOINT = "http://qdrant:6333"
COLLECTION_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,127}$")


class BootstrapError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if type(value) is not str or not value:
        raise BootstrapError(f"MISSING_{name}")
    return value


def _request(method: str, path: str, payload: dict[str, object] | None = None) -> object:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(QDRANT_ENDPOINT + path, data=body, headers=headers, method=method)
    with urlopen(request, timeout=3) as response:  # noqa: S310 - endpoint is fixed above
        raw = response.read(1_048_577)
    if len(raw) > 1_048_576:
        raise BootstrapError("QDRANT_RESPONSE_TOO_LARGE")
    return json.loads(raw)


def _wait_until_ready() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            _request("GET", "/collections")
            return
        except (BootstrapError, HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(0.5)
    raise BootstrapError("QDRANT_NOT_READY")


def _collection_vectors(document: object) -> tuple[object, object]:
    if not isinstance(document, dict):
        raise BootstrapError("QDRANT_COLLECTION_VERIFY_FAILED") from None
    result = document.get("result")
    if not isinstance(result, dict):
        raise BootstrapError("QDRANT_COLLECTION_VERIFY_FAILED")
    config = result.get("config")
    if not isinstance(config, dict):
        raise BootstrapError("QDRANT_COLLECTION_VERIFY_FAILED")
    params = config.get("params")
    if not isinstance(params, dict):
        raise BootstrapError("QDRANT_COLLECTION_VERIFY_FAILED")
    vectors = params.get("vectors")
    if not isinstance(vectors, dict):
        raise BootstrapError("QDRANT_COLLECTION_VERIFY_FAILED")
    return vectors.get("size"), vectors.get("distance")


def bootstrap(environment: Mapping[str, str]) -> str:
    if _required(environment, "APP_ENV") != "local":
        raise BootstrapError("APP_ENV_MUST_BE_LOCAL")
    collection = _required(environment, "QDRANT_COLLECTION")
    if COLLECTION_PATTERN.fullmatch(collection) is None:
        raise BootstrapError("QDRANT_COLLECTION_INVALID")
    if _required(environment, "QDRANT_VECTOR_SIZE") != "1024":
        raise BootstrapError("QDRANT_VECTOR_SIZE_INVALID")
    if _required(environment, "QDRANT_DISTANCE") != "Cosine":
        raise BootstrapError("QDRANT_DISTANCE_INVALID")

    _wait_until_ready()
    outcome = "already_initialized"
    try:
        document = _request("GET", f"/collections/{collection}")
    except HTTPError as error:
        if error.code != 404:
            raise BootstrapError("QDRANT_COLLECTION_INSPECT_FAILED") from None
        _request(
            "PUT",
            f"/collections/{collection}",
            {"vectors": {"size": 1024, "distance": "Cosine"}},
        )
        outcome = "created"
        document = _request("GET", f"/collections/{collection}")
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise BootstrapError("QDRANT_COLLECTION_INSPECT_FAILED") from None
    if _collection_vectors(document) != (1024, "Cosine"):
        raise BootstrapError("QDRANT_COLLECTION_PROFILE_DRIFT")
    return outcome


def main() -> int:
    try:
        if sys.argv != [sys.argv[0]]:
            raise BootstrapError("ARGUMENTS_NOT_SUPPORTED")
        outcome = bootstrap(os.environ)
    except BootstrapError as error:
        print("LOCAL_QDRANT_BOOTSTRAP=FAIL")
        print(f"LOCAL_QDRANT_REASON={error.code}")
        return 1
    except Exception:
        print("LOCAL_QDRANT_BOOTSTRAP=FAIL")
        print("LOCAL_QDRANT_REASON=UNEXPECTED_FAILURE")
        return 1
    print("LOCAL_QDRANT_BOOTSTRAP=PASS")
    print(f"LOCAL_QDRANT_OUTCOME={outcome.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
