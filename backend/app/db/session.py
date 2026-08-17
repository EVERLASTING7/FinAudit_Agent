from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, parse_database_url

DEFAULT_APPLICATION_CONNECT_TIMEOUT_SECONDS = 10


def create_application_engine(settings: Settings) -> Engine:
    """为 Backend/Worker 创建共享的 PostgreSQL 运行时 Engine。"""

    active_settings = Settings.model_validate(settings)
    database_url = parse_database_url(active_settings.database_url.get_secret_value())
    return create_engine(
        database_url,
        connect_args={
            "connect_timeout": DEFAULT_APPLICATION_CONNECT_TIMEOUT_SECONDS,
            "client_encoding": "UTF8",
            "options": "-c timezone=UTC",
        },
        hide_parameters=True,
        max_overflow=active_settings.db_max_overflow,
        pool_pre_ping=True,
        pool_size=active_settings.db_pool_size,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """构造显式事务 Session 工厂；提交与回滚由 Application Service 控制。"""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
