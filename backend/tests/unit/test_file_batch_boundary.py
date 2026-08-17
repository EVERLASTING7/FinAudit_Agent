import pytest

from app.core.errors import AppError
from app.services.file_service import validate_file_batch_count


@pytest.mark.parametrize(
    ("file_count", "max_batch_file_count"),
    [(1, 1), (19, 20), (20, 20), (3, 3)],
)
def test_validate_file_batch_count_allows_positive_counts_up_to_configured_limit(
    file_count: int,
    max_batch_file_count: int,
) -> None:
    validate_file_batch_count(file_count, max_batch_file_count=max_batch_file_count)


def test_validate_file_batch_count_rejects_limit_plus_one_with_contract_error() -> None:
    with pytest.raises(AppError) as exc_info:
        validate_file_batch_count(21, max_batch_file_count=20)

    assert exc_info.value.status_code == 413
    assert exc_info.value.code == "BATCH_LIMIT_EXCEEDED"
    assert exc_info.value.message == "超过单批文件数"


@pytest.mark.parametrize("file_count", [0, -1, True, 1.5, "1"])
def test_validate_file_batch_count_rejects_invalid_file_counts(file_count: object) -> None:
    with pytest.raises(ValueError, match="file_count"):
        validate_file_batch_count(file_count, max_batch_file_count=20)  # type: ignore[arg-type]


def test_validate_file_batch_count_rejects_int_subclass_file_count() -> None:
    class LyingCount(int):
        def __le__(self, other: object) -> bool:
            return False

        def __gt__(self, other: object) -> bool:
            return False

    with pytest.raises(ValueError, match="file_count"):
        validate_file_batch_count(LyingCount(21), max_batch_file_count=20)


@pytest.mark.parametrize("max_batch_file_count", [0, -1, True, 1.5, "20"])
def test_validate_file_batch_count_rejects_invalid_batch_limits(
    max_batch_file_count: object,
) -> None:
    with pytest.raises(ValueError, match="max_batch_file_count"):
        validate_file_batch_count(1, max_batch_file_count=max_batch_file_count)  # type: ignore[arg-type]


def test_validate_file_batch_count_rejects_int_subclass_batch_limit() -> None:
    class LyingLimit(int):
        def __le__(self, other: object) -> bool:
            return False

        def __lt__(self, other: object) -> bool:
            return False

    with pytest.raises(ValueError, match="max_batch_file_count"):
        validate_file_batch_count(1, max_batch_file_count=LyingLimit(20))
