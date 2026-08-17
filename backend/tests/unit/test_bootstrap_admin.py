from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.bootstrap_admin import BootstrapAdminError, load_config


def _environment(password_file: Path) -> dict[str, str]:
    return {
        "BOOTSTRAP_ORGANIZATION_NAME": "FinAudit Local",
        "BOOTSTRAP_ORGANIZATION_USCC": "91310000MA000001X1",
        "BOOTSTRAP_ORGANIZATION_TAX_NUMBER": "91310000MA000001X1",
        "BOOTSTRAP_ADMIN_USERNAME": "local-admin",
        "BOOTSTRAP_ADMIN_DISPLAY_NAME": "本地管理员",
        "BOOTSTRAP_ADMIN_PASSWORD_FILE": str(password_file),
    }


def test_load_config_reads_password_from_absolute_regular_file(tmp_path: Path) -> None:
    password_file = tmp_path / "initial-password"
    password_file.write_text("Finaudit local gate 密码 2026", encoding="utf-8")
    if os.name != "nt":
        password_file.chmod(0o400)

    config = load_config(_environment(password_file))

    assert config.admin_username == "local-admin"
    assert config.admin_display_name == "本地管理员"
    assert "密码" not in repr(config)


def test_load_config_rejects_relative_password_path(tmp_path: Path) -> None:
    password_file = tmp_path / "initial-password"
    password_file.write_text("Finaudit local gate 密码 2026", encoding="utf-8")
    environment = _environment(password_file)
    environment["BOOTSTRAP_ADMIN_PASSWORD_FILE"] = "initial-password"

    with pytest.raises(BootstrapAdminError) as exc_info:
        load_config(environment)

    assert exc_info.value.code == "BOOTSTRAP_ADMIN_PASSWORD_FILE_INVALID"


def test_load_config_never_includes_password_in_validation_error(tmp_path: Path) -> None:
    password = "short"
    password_file = tmp_path / "initial-password"
    password_file.write_text(password, encoding="utf-8")

    with pytest.raises(BootstrapAdminError) as exc_info:
        load_config(_environment(password_file))

    assert exc_info.value.code == "BOOTSTRAP_ADMIN_PASSWORD_INVALID"
    assert password not in str(exc_info.value)
