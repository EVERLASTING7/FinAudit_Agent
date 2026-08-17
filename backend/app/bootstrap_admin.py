"""受信任操作者执行的一次性 first-org/admin 初始化 CLI。"""

from __future__ import annotations

import os
import re
import stat
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NoReturn
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.auth_security import hash_password
from app.core.config import Settings
from app.core.password_policy import validate_new_password
from app.db.session import create_application_engine
from app.models.auth import Organization, Role, User, UserRole
from app.repositories.operation_log import OperationLogRepository
from app.schemas.users import UserCreateRequest

BootstrapOutcome = Literal["created", "already_initialized"]

_BOOTSTRAP_LOCK_IDENTITY = "finaudit:first-org-admin-bootstrap:v1"
_ORGANIZATION_CODE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_MAX_PASSWORD_FILE_BYTES = 512
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400


class BootstrapAdminError(RuntimeError):
    """只暴露稳定错误码，不携带输入、路径、凭据或数据库异常。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BootstrapAdminConfig:
    organization_name: str
    organization_unified_social_credit_code: str
    organization_tax_number: str
    admin_username: str
    admin_display_name: str
    admin_password: str = field(repr=False)


def _fail(code: str) -> NoReturn:
    raise BootstrapAdminError(code) from None


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if type(value) is not str or not value:
        _fail(f"{name}_REQUIRED")
    return value


def _validate_organization_text(value: str, *, max_length: int, code: str) -> str:
    if (
        value != value.strip()
        or not 1 <= len(value) <= max_length
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        _fail(code)
    return value


def _validate_organization_code(value: str, *, code: str) -> str:
    if _ORGANIZATION_CODE.fullmatch(value) is None:
        _fail(code)
    return value


def _decode_mountinfo_path(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def _is_read_only_mount(path: Path) -> bool:
    selected_length = -1
    selected_read_only = False
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as stream:
            for line in stream:
                before_separator, separator, _after_separator = line.partition(" - ")
                fields = before_separator.split()
                if separator != " - " or len(fields) < 6:
                    raise OSError
                mount_point = _decode_mountinfo_path(fields[4])
                target = str(path)
                if target != mount_point and not target.startswith(mount_point.rstrip("/") + "/"):
                    continue
                if len(mount_point) > selected_length:
                    selected_length = len(mount_point)
                    selected_read_only = "ro" in fields[5].split(",")
    except OSError:
        return False
    return selected_length >= 0 and selected_read_only


def _read_password_file(value: str) -> str:
    path = Path(value)
    descriptor = -1
    try:
        if not path.is_absolute():
            raise OSError
        before = os.lstat(path)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size < 1
            or before.st_size > _MAX_PASSWORD_FILE_BYTES
            or int(getattr(before, "st_file_attributes", 0)) & _FILE_ATTRIBUTE_REPARSE_POINT
            or (os.name != "nt" and before.st_mode & 0o022 and not _is_read_only_mount(path))
        ):
            raise OSError
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if os.name != "nt":
            if no_follow is None:
                raise OSError
            flags |= no_follow
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_mode) != (
            before.st_dev,
            before.st_ino,
            before.st_mode,
        ):
            raise OSError
        raw = os.read(descriptor, _MAX_PASSWORD_FILE_BYTES + 1)
        after = os.fstat(descriptor)
        if len(raw) > _MAX_PASSWORD_FILE_BYTES or (
            after.st_dev,
            after.st_ino,
            after.st_mode,
        ) != (before.st_dev, before.st_ino, before.st_mode):
            raise OSError
        password = raw.decode("utf-8", errors="strict")
    except (OSError, UnicodeError, ValueError):
        _fail("BOOTSTRAP_ADMIN_PASSWORD_FILE_INVALID")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        return validate_new_password(password)
    except ValueError:
        _fail("BOOTSTRAP_ADMIN_PASSWORD_INVALID")


def load_config(environment: Mapping[str, str]) -> BootstrapAdminConfig:
    password = _read_password_file(_required(environment, "BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    try:
        user = UserCreateRequest.model_validate(
            {
                "username": _required(environment, "BOOTSTRAP_ADMIN_USERNAME"),
                "display_name": _required(environment, "BOOTSTRAP_ADMIN_DISPLAY_NAME"),
                "initial_password": password,
                "fixed_roles": ["system_admin"],
            }
        )
    except ValueError:
        _fail("BOOTSTRAP_ADMIN_PROFILE_INVALID")

    return BootstrapAdminConfig(
        organization_name=_validate_organization_text(
            _required(environment, "BOOTSTRAP_ORGANIZATION_NAME"),
            max_length=200,
            code="BOOTSTRAP_ORGANIZATION_NAME_INVALID",
        ),
        organization_unified_social_credit_code=_validate_organization_code(
            _required(environment, "BOOTSTRAP_ORGANIZATION_USCC"),
            code="BOOTSTRAP_ORGANIZATION_USCC_INVALID",
        ),
        organization_tax_number=_validate_organization_code(
            _required(environment, "BOOTSTRAP_ORGANIZATION_TAX_NUMBER"),
            code="BOOTSTRAP_ORGANIZATION_TAX_NUMBER_INVALID",
        ),
        admin_username=user.username,
        admin_display_name=user.display_name,
        admin_password=password,
    )


def _database_now(session: Session) -> object:
    return session.execute(select(func.clock_timestamp())).scalar_one()


def _existing_bootstrap_matches(session: Session, config: BootstrapAdminConfig) -> bool:
    organizations = (
        session.execute(
            select(Organization).order_by(Organization.id).with_for_update(of=Organization)
        )
        .scalars()
        .all()
    )
    if not organizations:
        return False
    if len(organizations) != 1:
        _fail("BOOTSTRAP_STATE_CONFLICT")
    organization = organizations[0]
    if (
        organization.name != config.organization_name
        or organization.unified_social_credit_code != config.organization_unified_social_credit_code
        or organization.tax_number != config.organization_tax_number
        or organization.status != "active"
        or organization.deleted_at is not None
    ):
        _fail("BOOTSTRAP_PROFILE_CONFLICT")

    admin = session.execute(
        select(User)
        .where(
            User.organization_id == organization.id,
            User.username == config.admin_username,
            User.deleted_at.is_(None),
        )
        .with_for_update(of=User)
    ).scalar_one_or_none()
    if admin is None or admin.status != "active":
        _fail("BOOTSTRAP_STATE_CONFLICT")
    system_role = session.execute(
        select(Role).where(Role.code == "system_admin", Role.is_enabled.is_(True))
    ).scalar_one_or_none()
    if system_role is None:
        _fail("BOOTSTRAP_ROLE_UNAVAILABLE")
    assignment = session.execute(
        select(UserRole).where(
            UserRole.user_id == admin.id,
            UserRole.role_id == system_role.id,
            UserRole.assignment_source == "bootstrap",
            UserRole.assignment_reason == "system_bootstrap",
            UserRole.expires_at.is_(None),
            UserRole.revoked_at.is_(None),
        )
    ).scalar_one_or_none()
    if assignment is None:
        _fail("BOOTSTRAP_STATE_CONFLICT")
    return True


def bootstrap_first_admin(settings: Settings, config: BootstrapAdminConfig) -> BootstrapOutcome:
    engine = create_application_engine(settings)
    try:
        with Session(engine) as session, session.begin():
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                {"identity": _BOOTSTRAP_LOCK_IDENTITY},
            ).one()
            if _existing_bootstrap_matches(session, config):
                return "already_initialized"

            if session.execute(select(func.count()).select_from(User)).scalar_one() != 0:
                _fail("BOOTSTRAP_STATE_CONFLICT")
            system_role = session.execute(
                select(Role)
                .where(Role.code == "system_admin", Role.is_enabled.is_(True))
                .with_for_update(of=Role)
            ).scalar_one_or_none()
            if system_role is None:
                _fail("BOOTSTRAP_ROLE_UNAVAILABLE")

            now = _database_now(session)
            organization_id = uuid4()
            admin_id = uuid4()
            organization = Organization(
                id=organization_id,
                singleton_key=1,
                name=config.organization_name,
                unified_social_credit_code=config.organization_unified_social_credit_code,
                tax_number=config.organization_tax_number,
                status="active",
                row_version=1,
                created_at=now,
                created_by=None,
                updated_at=now,
                updated_by=None,
                deleted_at=None,
                deleted_by=None,
                delete_reason=None,
            )
            session.add(organization)
            session.flush()

            admin = User(
                id=admin_id,
                organization_id=organization_id,
                username=config.admin_username,
                email=None,
                display_name=config.admin_display_name,
                password_hash=hash_password(config.admin_password),
                status="active",
                failed_login_count=0,
                locked_until=None,
                password_changed_at=now,
                force_change_on_login=True,
                token_invalid_before=now,
                row_version=1,
                created_at=now,
                created_by=None,
                updated_at=now,
                updated_by=None,
                deleted_at=None,
                deleted_by=None,
                delete_reason=None,
            )
            session.add(admin)
            session.flush()
            organization.created_by = admin_id
            organization.updated_by = admin_id
            session.add(
                UserRole(
                    id=uuid4(),
                    user_id=admin_id,
                    role_id=system_role.id,
                    assigned_by=None,
                    assignment_source="bootstrap",
                    assigned_at=now,
                    expires_at=None,
                    break_glass_request_id=None,
                    assignment_reason="system_bootstrap",
                    revoked_at=None,
                    revoked_by=None,
                    revoke_reason=None,
                )
            )
            OperationLogRepository(session).append(
                organization_id=organization_id,
                actor_kind="system",
                actor_id=None,
                action_code="system.bootstrap.completed",
                outcome="succeeded",
                resource_type="organization",
                resource_id=organization_id,
                trace_id=uuid4(),
                change_summary={
                    "initial_admin_id": str(admin_id),
                    "role_code": "system_admin",
                },
            )
        return "created"
    finally:
        engine.dispose()


def main() -> int:
    try:
        if sys.argv != [sys.argv[0]]:
            _fail("BOOTSTRAP_ARGUMENTS_NOT_SUPPORTED")
        config = load_config(os.environ)
        outcome = bootstrap_first_admin(Settings(), config)
    except BootstrapAdminError as error:
        print("FINAUDIT_ADMIN_BOOTSTRAP=FAIL")
        print(f"FINAUDIT_ADMIN_BOOTSTRAP_REASON={error.code}")
        return 1
    except Exception:
        print("FINAUDIT_ADMIN_BOOTSTRAP=FAIL")
        print("FINAUDIT_ADMIN_BOOTSTRAP_REASON=UNEXPECTED_FAILURE")
        return 1

    print("FINAUDIT_ADMIN_BOOTSTRAP=PASS")
    print(f"FINAUDIT_ADMIN_BOOTSTRAP_OUTCOME={outcome.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BootstrapAdminConfig",
    "BootstrapAdminError",
    "bootstrap_first_admin",
    "load_config",
    "main",
]
