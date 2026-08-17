from __future__ import annotations

import hashlib
import io
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from app.core.errors import AppError
from app.schemas.files import SecurityScanStatus
from app.services.file_service import QuarantineIntakeFacts, prepare_quarantine_intake

PDF_CONTENT = b"%PDF-1.7\nsynthetic quarantine upload"


class ObservedStream(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.measurement_read_positions: list[int] = []

    def read(self, size: int = -1) -> bytes:
        if size == 1024 * 1024:
            self.measurement_read_positions.append(self.tell())
            size = min(size, 5)
        return super().read(size)


def test_prepare_quarantine_intake_returns_pending_facts_and_rewinds_external_stream() -> None:
    stream = ObservedStream(PDF_CONTENT)
    stream.seek(7)

    result = prepare_quarantine_intake(
        stream,
        file_name="Quarterly.PDF",
        declared_mime=" APPLICATION/PDF ",
        max_size_bytes=len(PDF_CONTENT),
    )

    assert result == QuarantineIntakeFacts(
        size_bytes=len(PDF_CONTENT),
        sha256=hashlib.sha256(PDF_CONTENT).hexdigest(),
        extension=".pdf",
        declared_mime="application/pdf",
        detected_mime="application/pdf",
    )
    assert result.security_scan_status is SecurityScanStatus.PENDING
    assert stream.tell() == 0
    assert not stream.closed
    assert stream.measurement_read_positions[0] == 0
    assert stream.measurement_read_positions[-1] == len(PDF_CONTENT)
    assert stream.measurement_read_positions == sorted(set(stream.measurement_read_positions))

    with pytest.raises(FrozenInstanceError):
        result.size_bytes = 0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("payload", "file_name", "max_size_bytes", "expected_code"),
    [
        (b"not-a-pdf-sensitive-content", "sensitive.pdf", 100, "FILE_SIGNATURE_MISMATCH"),
        (PDF_CONTENT, "contract.pdf", len(PDF_CONTENT) - 1, "FILE_TOO_LARGE"),
        (PDF_CONTENT, "contract.txt", len(PDF_CONTENT), "FILE_FORMAT_NOT_SUPPORTED"),
    ],
)
def test_prepare_quarantine_intake_rewinds_without_closing_on_validation_failure(
    payload: bytes,
    file_name: str,
    max_size_bytes: int,
    expected_code: str,
) -> None:
    stream = ObservedStream(payload)
    stream.seek(3)

    with pytest.raises(AppError) as exc_info:
        prepare_quarantine_intake(
            stream,
            file_name=file_name,
            declared_mime="application/pdf",
            max_size_bytes=max_size_bytes,
        )

    assert exc_info.value.code == expected_code
    assert stream.tell() == 0
    assert not stream.closed
    assert payload.decode(errors="ignore") not in str(exc_info.value)


@pytest.mark.parametrize(
    ("file_name", "declared_mime"),
    [
        (b"contract.pdf", "application/pdf"),
        ("contract.pdf", type("UntrustedMime", (str,), {})("application/pdf")),
    ],
)
def test_prepare_quarantine_intake_rejects_non_exact_text_inputs_before_reading(
    file_name: Any,
    declared_mime: Any,
) -> None:
    stream = ObservedStream(PDF_CONTENT)

    with pytest.raises(AppError) as exc_info:
        prepare_quarantine_intake(
            stream,
            file_name=file_name,
            declared_mime=declared_mime,
            max_size_bytes=len(PDF_CONTENT),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "VALIDATION_ERROR"
    assert stream.measurement_read_positions == []
    assert stream.tell() == 0
    assert not stream.closed
