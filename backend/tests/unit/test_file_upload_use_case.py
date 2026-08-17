import hashlib
from collections.abc import Iterator

import pytest

from app.core.errors import AppError
from app.schemas.files import FileUploadIntent, SecurityScanStatus
from app.services.file_service import UploadContentMetadata, validate_single_file_upload

PDF_CONTENT = b"%PDF-1.7\nsynthetic upload"
VALID_INTENT = FileUploadIntent.model_validate({"intended_business_type": "contract"})


class OneShotChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.iterations = 0
        self.yielded: list[bytes] = []

    def __iter__(self) -> Iterator[bytes]:
        self.iterations += 1
        if self.iterations > 1:
            raise AssertionError("upload source must not be iterated twice")
        for chunk in self._chunks:
            self.yielded.append(chunk)
            yield chunk


def test_validate_single_file_upload_returns_stable_metadata() -> None:
    result = validate_single_file_upload(
        VALID_INTENT,
        (PDF_CONTENT[:7], PDF_CONTENT[7:]),
        file_name="contract.pdf",
        declared_mime="application/pdf",
        max_size_bytes=len(PDF_CONTENT),
        security_scan_status=SecurityScanStatus.CLEAN,
    )

    assert result == UploadContentMetadata(
        size_bytes=len(PDF_CONTENT),
        sha256=hashlib.sha256(PDF_CONTENT).hexdigest(),
    )


def test_validate_single_file_upload_consumes_source_once() -> None:
    chunks = OneShotChunks((PDF_CONTENT[:4], PDF_CONTENT[4:12], PDF_CONTENT[12:]))

    validate_single_file_upload(
        VALID_INTENT,
        chunks,
        file_name="contract.pdf",
        declared_mime="application/pdf",
        max_size_bytes=len(PDF_CONTENT),
        security_scan_status=SecurityScanStatus.CLEAN,
    )

    assert chunks.iterations == 1
    assert chunks.yielded == [PDF_CONTENT[:4], PDF_CONTENT[4:12], PDF_CONTENT[12:]]


def test_validate_single_file_upload_requires_exact_validated_intent_without_echoing_it() -> None:
    class DerivedUploadIntent(FileUploadIntent):
        secret_marker: str

    intent = DerivedUploadIntent.model_validate(
        {
            "intended_business_type": "contract",
            "secret_marker": "intent-secret-must-not-leak",
        }
    )
    chunks = OneShotChunks((PDF_CONTENT,))

    with pytest.raises(AppError) as exc_info:
        validate_single_file_upload(
            intent,
            chunks,
            file_name="contract.pdf",
            declared_mime="application/pdf",
            max_size_bytes=len(PDF_CONTENT),
            security_scan_status=SecurityScanStatus.CLEAN,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.message == "请求参数不符合约束"
    assert exc_info.value.details == []
    assert "intent-secret-must-not-leak" not in str(exc_info.value)
    assert chunks.iterations == 0


def test_validate_single_file_upload_rejects_invalid_model_construct_before_consuming() -> None:
    intent = FileUploadIntent.model_construct(
        intended_business_type="contract",
        target_knowledge_base_id=None,
        auto_process_requested=True,
    )
    chunks = OneShotChunks((PDF_CONTENT,))

    with pytest.raises(AppError) as exc_info:
        validate_single_file_upload(
            intent,
            chunks,
            file_name="contract.pdf",
            declared_mime="application/pdf",
            max_size_bytes=len(PDF_CONTENT),
            security_scan_status=SecurityScanStatus.CLEAN,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.message == "请求参数不符合约束"
    assert exc_info.value.details == []
    assert chunks.iterations == 0


def test_validate_single_file_upload_rejects_mutated_same_class_without_leaking(
    capsys: pytest.CaptureFixture[str],
) -> None:
    intent = FileUploadIntent.model_validate({"intended_business_type": "contract"})
    intent.auto_process_requested = "mutated-secret-must-not-leak"  # type: ignore[assignment]
    chunks = OneShotChunks((PDF_CONTENT,))

    with pytest.raises(AppError) as exc_info:
        validate_single_file_upload(
            intent,
            chunks,
            file_name="contract.pdf",
            declared_mime="application/pdf",
            max_size_bytes=len(PDF_CONTENT),
            security_scan_status=SecurityScanStatus.CLEAN,
        )

    captured = capsys.readouterr()
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.message == "请求参数不符合约束"
    assert exc_info.value.details == []
    assert "mutated-secret-must-not-leak" not in str(exc_info.value)
    assert "mutated-secret-must-not-leak" not in captured.out
    assert "mutated-secret-must-not-leak" not in captured.err
    assert chunks.iterations == 0


def test_validate_single_file_upload_preserves_size_limit_error_and_stops_consuming() -> None:
    chunks = OneShotChunks((b"%PDF", b"-too-large", b"must-not-be-consumed"))

    with pytest.raises(AppError) as exc_info:
        validate_single_file_upload(
            VALID_INTENT,
            chunks,
            file_name="contract.pdf",
            declared_mime="application/pdf",
            max_size_bytes=5,
            security_scan_status=SecurityScanStatus.CLEAN,
        )

    assert exc_info.value.status_code == 413
    assert exc_info.value.code == "FILE_TOO_LARGE"
    assert exc_info.value.message == "上传文件超过允许大小"
    assert exc_info.value.details == []
    assert chunks.iterations == 1
    assert chunks.yielded == [b"%PDF", b"-too-large"]


def test_validate_single_file_upload_preserves_signature_error_without_echoing_input() -> None:
    sensitive_content = b"not-a-pdf-sensitive-content"
    sensitive_file_name = "sensitive-customer-name.pdf"

    with pytest.raises(AppError) as exc_info:
        validate_single_file_upload(
            VALID_INTENT,
            (sensitive_content,),
            file_name=sensitive_file_name,
            declared_mime="application/pdf",
            max_size_bytes=len(sensitive_content),
            security_scan_status=SecurityScanStatus.CLEAN,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"
    assert exc_info.value.message == "文件签名不匹配"
    assert exc_info.value.details == []
    assert sensitive_file_name not in str(exc_info.value)
    assert sensitive_content.decode() not in str(exc_info.value)


@pytest.mark.parametrize(
    "security_scan_status",
    [SecurityScanStatus.PENDING, "clean"],
)
def test_validate_single_file_upload_requires_exact_clean_status(
    security_scan_status: object,
) -> None:
    with pytest.raises(AppError) as exc_info:
        validate_single_file_upload(
            VALID_INTENT,
            (PDF_CONTENT,),
            file_name="contract.pdf",
            declared_mime="application/pdf",
            max_size_bytes=len(PDF_CONTENT),
            security_scan_status=security_scan_status,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.message == "请求参数不符合约束"
    assert exc_info.value.details == []
