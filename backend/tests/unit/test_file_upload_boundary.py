import hashlib
from collections.abc import Iterator

import pytest

from app.core.errors import AppError
from app.services.file_service import UploadContentMetadata, measure_upload_stream


@pytest.mark.parametrize(
    "chunks",
    [
        [b"abc", b"def"],
        [b"a", b"bcde", b"f"],
    ],
)
def test_measure_upload_stream_is_independent_of_chunk_boundaries(chunks: list[bytes]) -> None:
    result = measure_upload_stream(chunks, max_size_bytes=6)

    assert result == UploadContentMetadata(
        size_bytes=6,
        sha256=hashlib.sha256(b"abcdef").hexdigest(),
    )


@pytest.mark.parametrize("chunks", [[], [b""], [b"", b""]])
def test_measure_upload_stream_rejects_empty_content(chunks: list[bytes]) -> None:
    with pytest.raises(AppError) as exc_info:
        measure_upload_stream(chunks, max_size_bytes=1)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "FILE_SIGNATURE_MISMATCH"
    assert exc_info.value.message == "文件签名不匹配"
    assert exc_info.value.details == []


def test_measure_upload_stream_allows_content_at_the_exact_size_boundary() -> None:
    result = measure_upload_stream([b"abc", b"def"], max_size_bytes=6)

    assert result.size_bytes == 6


def test_measure_upload_stream_rejects_size_boundary_plus_one_without_consuming_more_chunks() -> (
    None
):
    consumed: list[bytes] = []

    def chunks() -> Iterator[bytes]:
        for chunk in (b"ab", b"cd", b"should-not-be-consumed"):
            consumed.append(chunk)
            yield chunk

    with pytest.raises(AppError) as exc_info:
        measure_upload_stream(chunks(), max_size_bytes=3)

    assert exc_info.value.status_code == 413
    assert exc_info.value.code == "FILE_TOO_LARGE"
    assert exc_info.value.message == "上传文件超过允许大小"
    assert consumed == [b"ab", b"cd"]


@pytest.mark.parametrize("max_size_bytes", [0, -1, True, 1.5, "1"])
def test_measure_upload_stream_rejects_invalid_size_limits(max_size_bytes: object) -> None:
    with pytest.raises(ValueError, match="max_size_bytes"):
        measure_upload_stream([b"content"], max_size_bytes=max_size_bytes)  # type: ignore[arg-type]


def test_measure_upload_stream_rejects_int_subclasses_with_untrusted_comparisons() -> None:
    class LyingLimit(int):
        def __le__(self, other: object) -> bool:
            return False

        def __lt__(self, other: object) -> bool:
            return False

    with pytest.raises(ValueError, match="max_size_bytes"):
        measure_upload_stream([b"content"], max_size_bytes=LyingLimit(1))


def test_measure_upload_stream_rejects_non_bytes_chunks_without_consuming_more_chunks() -> None:
    consumed: list[object] = []

    def chunks() -> Iterator[object]:
        for chunk in (b"valid", bytearray(b"invalid"), b"should-not-be-consumed"):
            consumed.append(chunk)
            yield chunk

    with pytest.raises(TypeError, match="upload chunks must be bytes"):
        measure_upload_stream(chunks(), max_size_bytes=100)  # type: ignore[arg-type]

    assert consumed == [b"valid", bytearray(b"invalid")]


def test_measure_upload_stream_rejects_bytes_subclasses_with_untrusted_length() -> None:
    class LyingBytes(bytes):
        def __len__(self) -> int:
            return 0

    with pytest.raises(TypeError, match="upload chunks must be bytes"):
        measure_upload_stream([LyingBytes(b"content")], max_size_bytes=1)
