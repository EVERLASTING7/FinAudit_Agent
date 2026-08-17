from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.db.session import (
    DEFAULT_APPLICATION_CONNECT_TIMEOUT_SECONDS,
    create_application_engine,
    create_session_factory,
)
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401 - imported fixture registration
    build_startup_settings,
)


def test_application_engine_uses_bounded_safe_pool_settings(
    exact_policy_file: Path,
) -> None:
    settings = build_startup_settings(
        exact_policy_file,
        db_pool_size=3,
        db_max_overflow=4,
    )

    with patch("app.db.session.create_engine") as mocked_create_engine:
        create_application_engine(settings)

    database_url = mocked_create_engine.call_args.args[0]
    assert database_url.drivername == "postgresql+psycopg"
    assert mocked_create_engine.call_args.kwargs == {
        "connect_args": {
            "connect_timeout": DEFAULT_APPLICATION_CONNECT_TIMEOUT_SECONDS,
            "client_encoding": "UTF8",
            "options": "-c timezone=UTC",
        },
        "hide_parameters": True,
        "max_overflow": 4,
        "pool_pre_ping": True,
        "pool_size": 3,
    }


def test_application_engine_does_not_expose_password(
    exact_policy_file: Path,
) -> None:
    password = "runtime-password-must-not-leak"
    settings = build_startup_settings(
        exact_policy_file,
        database_url=f"postgresql+psycopg://runtime:{password}@postgresql:5432/finaudit",
    )

    engine = create_application_engine(settings)

    assert engine.hide_parameters is True
    assert password not in repr(engine.url)
    engine.dispose()


def test_application_engine_revalidates_mutated_settings(
    exact_policy_file: Path,
) -> None:
    settings = build_startup_settings(exact_policy_file)
    settings.db_pool_size = 0

    with (
        patch("app.db.session.create_engine") as mocked_create_engine,
        pytest.raises(ValidationError),
    ):
        create_application_engine(settings)

    mocked_create_engine.assert_not_called()


def test_session_factory_keeps_transaction_control_with_application_service(
    exact_policy_file: Path,
) -> None:
    engine = create_application_engine(build_startup_settings(exact_policy_file))
    factory = create_session_factory(engine)

    assert factory.kw["autoflush"] is False
    assert factory.kw["expire_on_commit"] is False
    with factory() as session:
        assert session.get_bind() is engine

    engine.dispose()
