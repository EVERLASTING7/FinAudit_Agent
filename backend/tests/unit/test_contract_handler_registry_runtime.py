from uuid import uuid4

import pytest

from app.workers.contract_handler_registry import (
    CONTRACT_HANDLER_REGISTRY_HASH,
    contract_registry_artifact_hashes,
    load_contract_handler,
)
from app.workers.handler_registry import HandlerRegistryError


def test_contract_handler_registry_is_pinned_and_validates_payloads() -> None:
    handler = load_contract_handler()
    assert handler.registry_hash == CONTRACT_HANDLER_REGISTRY_HASH
    assert handler.handler.job_type == "contract_extract"
    assert handler.handler.logical_queue == "extraction"
    assert tuple(step.step_code for step in handler.handler.steps) == ("extract",)

    payload: dict[str, object] = {
        "file_id": str(uuid4()),
        "parse_version_id": str(uuid4()),
    }
    handler.validate_input(payload)
    handler.validate_summary({"contract_id": str(uuid4()), "field_count": 13})
    with pytest.raises(HandlerRegistryError):
        handler.validate_input({"file_id": payload["file_id"]})
    with pytest.raises(HandlerRegistryError):
        handler.validate_summary({"contract_id": str(uuid4()), "field_count": 14})


def test_contract_registry_raw_artifacts_are_stable() -> None:
    assert contract_registry_artifact_hashes() == {
        "registry.json": "8dcacb387bbc06c1cb77c772f3b51c46934934b56f077102beca81ab04b6e602",
        "registry.schema.json": (
            "9bef52684a93dd509abd30752af872b54df9a3329cb52137236eb6c51b9a349a"
        ),
        "input.contract_extract.v1.schema.json": (
            "86d73e4c0086f6e0e7ca8e0b0f62575e13b0b255e6c6501518d99f833af07079"
        ),
        "summary.contract_extract.v1.schema.json": (
            "cb548b5c6c1578515c2a3c07c2a31b5a7fbbc84e98f1869b6383f02c76615089"
        ),
    }
