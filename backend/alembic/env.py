from alembic import context
from app.db.migration import create_migration_engine, read_migration_url
from app.models import Base

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """在不建立数据库连接的情况下生成迁移 SQL。"""
    context.configure(
        url=read_migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """使用独立连接执行迁移，并固定 PostgreSQL 会话时区。"""
    engine = create_migration_engine(read_migration_url())

    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TIME ZONE 'UTC'")
            connection.commit()
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
