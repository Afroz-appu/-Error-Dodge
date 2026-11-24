import os

from alembic import context

from app.postgres_store import engine_for, metadata
from app.runtime_config import secret_setting

if context.is_offline_mode():
    context.configure(dialect_name="postgresql", target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = engine_for(secret_setting("ERROR_DODGE_DATABASE_URL"))
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
