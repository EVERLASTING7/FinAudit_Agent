import os
from pathlib import Path

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from app.core.config import parse_database_url

DEFAULT_CONNECT_TIMEOUT_SECONDS = 10


class MigrationConfigError(RuntimeError):
    """迁移配置无效，且错误信息不包含连接信息。"""


def _read_database_url_secret() -> str | None:
    directory = os.environ.get("FINAUDIT_SECRETS_DIR")
    if directory is None:
        return None
    path = Path(directory) / "database_url"
    try:
        if not Path(directory).is_absolute() or path.is_symlink():
            raise OSError
        info = path.stat()
        if not path.is_file() or not 1 <= info.st_size <= 4096:
            raise OSError
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise MigrationConfigError("DATABASE_URL secret mount 无效") from None


def read_migration_url() -> URL:
    """仅从当前进程读取并校验 Alembic 使用的 DATABASE_URL。"""
    raw_url = os.environ.get("DATABASE_URL") or _read_database_url_secret()
    if raw_url is None or not raw_url.strip():
        raise MigrationConfigError("迁移需要进程环境变量 DATABASE_URL")

    normalized_url = raw_url.strip()
    upper_url = normalized_url.upper()
    if "CHANGE_ME" in upper_url or "REPLACE_" in upper_url:
        raise MigrationConfigError("DATABASE_URL 不能使用占位符")

    try:
        database_url = parse_database_url(normalized_url)
    except ValueError:
        raise MigrationConfigError("DATABASE_URL 不是有效的 SQLAlchemy 数据库 URL") from None
    return database_url


def create_migration_engine(database_url: URL) -> Engine:
    """创建不复用连接且隐藏 SQL 参数的迁移 Engine。"""
    return create_engine(
        database_url,
        connect_args={
            "connect_timeout": DEFAULT_CONNECT_TIMEOUT_SECONDS,
            "client_encoding": "UTF8",
        },
        hide_parameters=True,
        poolclass=NullPool,
    )
