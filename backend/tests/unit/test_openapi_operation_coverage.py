from __future__ import annotations

from pathlib import Path

from app.bootstrap import create_app
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401 - imported fixture registration
    build_startup_settings,
)


def test_every_p0_openapi_operation_identity_is_frozen_by_a_backend_test(
    exact_policy_file: Path,
) -> None:
    openapi = create_app(build_startup_settings(exact_policy_file)).openapi()
    all_operation_ids = [
        operation["operationId"]
        for path_item in openapi["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    api_operation_ids = [
        operation["operationId"]
        for path, path_item in openapi["paths"].items()
        if path.startswith("/api/v1")
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(all_operation_ids) == len(set(all_operation_ids)) == 100
    assert len(api_operation_ids) == len(set(api_operation_ids)) == 97

    test_root = Path(__file__).resolve().parents[1]
    this_file = Path(__file__).resolve()
    test_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(test_root.rglob("test_*.py"))
        if path.resolve() != this_file
    )
    missing = sorted(
        operation_id for operation_id in api_operation_ids if operation_id not in test_sources
    )

    assert missing == [], f"OpenAPI operation identities without a contract test: {missing}"
