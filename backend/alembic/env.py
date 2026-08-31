from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401
from app.core.config import settings
from app.models.base import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    """Ignore legacy MySQL identity-index aliases during schema comparison.

    Early migrations created a unique constraint plus a separately named index
    for these identity columns. SQLAlchemy 2 represents ``unique=True,
    index=True`` as a single unique index, while MySQL reflects the historical
    pair as two indexes. Their names differ but their lookup guarantees do not.
    Other indexes and every column, constraint and foreign key remain checked.
    """

    if type_ != "index":
        return True
    columns = tuple(column.name for column in object_.columns)
    return not (
        len(columns) == 1
        and columns[0] in {"public_id", "domain_code", "task_id", "username", "role"}
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
