from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

from app.database import SCHEMA, get_engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

# Models will be added alongside their migrations in the next backend stages.
target_metadata = None


def run_migrations_online() -> None:
    engine = get_engine()
    with engine.connect() as connection:
        # Fixed identifier: never interpolate user input into DDL.
        exists = connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"),
            {"schema": SCHEMA},
        ).scalar_one()
        if not exists:
            connection.execute(text('CREATE SCHEMA IF NOT EXISTS "zapara"'))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA,
            include_schemas=False,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported; connect to PostgreSQL")
run_migrations_online()
