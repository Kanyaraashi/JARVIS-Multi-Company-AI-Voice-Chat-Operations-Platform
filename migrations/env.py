"""Alembic setup. It reuses the same database settings as the app (.env).

Migrations must run as the database OWNER (the user that created the tables).
If ADMIN_DATABASE_URL is set it is used, otherwise DATABASE_URL.
"""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

import app.models  # noqa: F401  (registers all tables)
from app.db import Base, engine

config = context.config
if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    admin_url = os.getenv("ADMIN_DATABASE_URL")
    connectable = create_engine(admin_url) if admin_url else engine
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    if admin_url:
        connectable.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline mode is not supported. Run the command normally.")
run_migrations_online()
