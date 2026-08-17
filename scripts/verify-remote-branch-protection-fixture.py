from __future__ import annotations

import json
import sys
from typing import Any

MAX_FIXTURE_BYTES = 16 * 1024
FAIL_MARKER = "BRANCH_PROTECTION_FIXTURE_VERIFY=FAIL"
PASS_MARKERS = (
    "BRANCH_PROTECTION_FIXTURE_VERIFY=PASS",
    "BRANCH_PROTECTION_EVIDENCE_SCOPE=SYNTHETIC_OFFLINE_ONLY",
    "BASELINE_TASK_STATUS=PARTIAL (remote branch protection evidence required)",
    "REMOTE_BRANCH_PROTECTION=NOT_RUN (synthetic fixture only)",
)
ROOT_KEYS = {"fixture_version", "evidence_scope", "branches"}
BRANCH_KEYS = {
    "name",
    "allow_force_push",
    "require_pull_request",
    "minimum_independent_reviews",
    "required_check_categories",
}


class FixtureError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FixtureError("duplicate key")
        result[key] = value
    return result


def _reject_non_json_constant(_: str) -> None:
    raise FixtureError("non-JSON constant")


def _read_fixture() -> bytes:
    payload = sys.stdin.buffer.read(MAX_FIXTURE_BYTES + 1)
    if not payload or len(payload) > MAX_FIXTURE_BYTES:
        raise FixtureError("fixture size is invalid")
    if payload.startswith(b"\xef\xbb\xbf"):
        raise FixtureError("UTF-8 BOM is forbidden")
    return payload


def _parse_fixture(payload: bytes) -> Any:
    text = payload.decode("utf-8", errors="strict")
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_json_constant,
    )


def _validate_branch(branch: Any, expected_name: str) -> None:
    if type(branch) is not dict or set(branch) != BRANCH_KEYS:
        raise FixtureError("branch object is invalid")
    if branch["name"] != expected_name or type(branch["name"]) is not str:
        raise FixtureError("branch name is invalid")
    if branch["allow_force_push"] is not False:
        raise FixtureError("force push policy is invalid")
    if branch["require_pull_request"] is not True:
        raise FixtureError("pull request policy is invalid")

    reviews = branch["minimum_independent_reviews"]
    if type(reviews) is not int or reviews < 1:
        raise FixtureError("review policy is invalid")

    checks = branch["required_check_categories"]
    if type(checks) is not list or checks != ["static", "test"]:
        raise FixtureError("required check categories are invalid")


def validate_fixture(payload: bytes) -> None:
    document = _parse_fixture(payload)
    if type(document) is not dict or set(document) != ROOT_KEYS:
        raise FixtureError("fixture root is invalid")
    if document["fixture_version"] != "branch-protection-fixture-v1":
        raise FixtureError("fixture version is invalid")
    if document["evidence_scope"] != "synthetic_offline_only":
        raise FixtureError("evidence scope is invalid")

    branches = document["branches"]
    if type(branches) is not list or len(branches) != 2:
        raise FixtureError("branch collection is invalid")
    _validate_branch(branches[0], "main")
    _validate_branch(branches[1], "develop")


def main() -> int:
    try:
        if sys.argv != [sys.argv[0], "--stdin"]:
            raise FixtureError("only --stdin is supported")
        payload = _read_fixture()
        validate_fixture(payload)
    except Exception:
        print(FAIL_MARKER)
        return 1

    for marker in PASS_MARKERS:
        print(marker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
