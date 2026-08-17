from uuid import UUID

import pytest

from app.core.refresh_tokens import issue_refresh_token, parse_refresh_token


def test_refresh_token_round_trip_is_opaque_and_hash_only() -> None:
    session_id = UUID("60000000-0000-4000-8000-000000000001")

    issued = issue_refresh_token(session_id)
    parsed = parse_refresh_token(issued.wire_value)

    assert parsed == issued
    assert issued.wire_value.startswith(f"{session_id}.")
    assert len(issued.digest) == 64
    assert issued.wire_value not in issued.digest
    assert issued.wire_value not in repr(issued)
    assert issued.digest not in repr(issued)


@pytest.mark.parametrize(
    "value",
    (
        "",
        "60000000-0000-4000-8000-000000000001.secret",
        "60000000-0000-4000-8000-000000000001." + "a" * 42 + "=",
        "60000000-0000-4000-8000-000000000001." + "!" * 43,
        "60000000000040008000000000000001." + "a" * 43,
    ),
)
def test_refresh_token_parser_rejects_noncanonical_input(value: str) -> None:
    with pytest.raises(ValueError, match="format"):
        parse_refresh_token(value)


def test_refresh_rotation_produces_a_new_secret_for_the_same_session() -> None:
    session_id = UUID("60000000-0000-4000-8000-000000000001")

    first = issue_refresh_token(session_id)
    second = issue_refresh_token(session_id)

    assert first.session_id == second.session_id
    assert first.wire_value != second.wire_value
    assert first.digest != second.digest
