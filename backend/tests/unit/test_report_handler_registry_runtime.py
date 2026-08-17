from uuid import uuid4

import pytest

from app.workers.handler_registry import HandlerRegistryError
from app.workers.report_handler_registry import (
    REPORT_HANDLER_REGISTRY_HASH,
    load_report_handler,
    report_registry_artifact_hashes,
)


def test_report_handler_registry_is_pinned_and_routes_to_report() -> None:
    handler = load_report_handler()

    assert handler.registry_hash == REPORT_HANDLER_REGISTRY_HASH
    assert handler.handler.job_type == "report_generate"
    assert handler.handler.logical_queue == "report"
    assert handler.handler.max_attempts == 3
    assert tuple(step.step_code for step in handler.handler.steps) == ("generate",)
    assert tuple(scope.start_step_code for scope in handler.handler.retry_scopes) == ("generate",)


def test_report_handler_validates_exact_input_and_summary() -> None:
    handler = load_report_handler()
    report_id = str(uuid4())
    execution_id = str(uuid4())
    handler.validate_input(
        {
            "report_id": report_id,
            "execution_id": execution_id,
            "payload_sha256": "a" * 64,
        }
    )
    handler.validate_summary(
        {
            "report_id": report_id,
            "pdf_sha256": "b" * 64,
            "pdf_size_bytes": 1024,
            "xlsx_sha256": "c" * 64,
            "xlsx_size_bytes": 2048,
        }
    )

    with pytest.raises(HandlerRegistryError):
        handler.validate_input({"report_id": report_id})
    with pytest.raises(HandlerRegistryError):
        handler.validate_summary(
            {
                "report_id": report_id,
                "pdf_sha256": "b" * 64,
                "pdf_size_bytes": 0,
                "xlsx_sha256": "c" * 64,
                "xlsx_size_bytes": 2048,
            }
        )


def test_report_registry_raw_artifacts_are_stable() -> None:
    assert report_registry_artifact_hashes() == {
        "registry.json": "4631d62d8a7cea148cda432fbc2c52171e1a915bdc48782ff63d3f0c2d47e571",
        "input.report_generate.v1.schema.json": (
            "10aeaa07d48edb8eb7f2ceca4b9e4b38670b150444ef7addcf56239353f47afe"
        ),
        "summary.report_generate.v1.schema.json": (
            "51e18c0b20e61e8768902a4896b537f5068ade7608b4873af166d4a93cd0a5e6"
        ),
    }
