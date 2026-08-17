from uuid import uuid4

import pytest

from app.workers.handler_registry import HandlerRegistryError
from app.workers.invoice_handler_registry import (
    INVOICE_HANDLER_REGISTRY_HASH,
    INVOICE_HANDLER_REGISTRY_V1_HASH,
    INVOICE_HANDLER_REGISTRY_V1_VERSION,
    invoice_registry_artifact_hashes,
    load_invoice_handler,
)


def test_invoice_handler_registry_is_pinned_and_routes_to_extraction() -> None:
    handler = load_invoice_handler()

    assert handler.registry_hash == INVOICE_HANDLER_REGISTRY_HASH
    assert handler.handler.job_type == "invoice_extract"
    assert handler.handler.logical_queue == "extraction"
    assert handler.handler.max_attempts == 3
    assert tuple(step.step_code for step in handler.handler.steps) == ("extract",)
    assert tuple(scope.start_step_code for scope in handler.handler.retry_scopes) == ("extract",)

    legacy = load_invoice_handler(INVOICE_HANDLER_REGISTRY_V1_VERSION)
    assert legacy.registry_hash == INVOICE_HANDLER_REGISTRY_V1_HASH
    assert legacy.handler.handler_code_version == "invoice-extract-handler-v1"


def test_invoice_handler_validates_exact_input_and_summary() -> None:
    handler = load_invoice_handler()
    file_id = str(uuid4())
    parse_version_id = str(uuid4())
    handler.validate_input({"file_id": file_id, "parse_version_id": parse_version_id})
    handler.validate_summary(
        {
            "invoice_id": str(uuid4()),
            "field_count": 13,
            "item_count": 1,
            "duplicate_status": "unique",
        }
    )

    with pytest.raises(HandlerRegistryError):
        handler.validate_input({"file_id": file_id})
    with pytest.raises(HandlerRegistryError):
        handler.validate_summary(
            {
                "invoice_id": str(uuid4()),
                "field_count": 14,
                "item_count": 0,
                "duplicate_status": "unique",
            }
        )


def test_invoice_registry_raw_artifacts_are_stable() -> None:
    hashes = invoice_registry_artifact_hashes()
    assert hashes == {
        "registry.json": "23f3f850a6274f4b780e478702aad81f085a9f3ac814af2b44828390bbf2d5dc",
        "registry.schema.json": (
            "9bef52684a93dd509abd30752af872b54df9a3329cb52137236eb6c51b9a349a"
        ),
        "input.invoice_extract.v1.schema.json": (
            "f96995b1375425cf37b128b2ae4aae5522ea8fbdf58fe170499b5b007f4a03af"
        ),
        "summary.invoice_extract.v2.schema.json": (
            "953837dfd1f1144ed78d9d8c0e2a801657acab54ba30e37ea6ebb8dae80832a0"
        ),
    }

    assert invoice_registry_artifact_hashes(INVOICE_HANDLER_REGISTRY_V1_VERSION) == {
        "registry.json": "aeb76c075797b242a52f16902be0bfc564e2ad1f0034cb3c4384d9553352bdf0",
        "registry.schema.json": (
            "9bef52684a93dd509abd30752af872b54df9a3329cb52137236eb6c51b9a349a"
        ),
        "input.invoice_extract.v1.schema.json": (
            "f96995b1375425cf37b128b2ae4aae5522ea8fbdf58fe170499b5b007f4a03af"
        ),
        "summary.invoice_extract.v1.schema.json": (
            "fae0722e558ec2b31f8c40c02e2a24d6142043c107c2e692b1c52eb355bffe9d"
        ),
    }
