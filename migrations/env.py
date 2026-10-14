from alembic import context
from traceai.config import Settings
from traceai.db import Base, create_database_engine
from traceai import models  # register model metadata

if context.is_offline_mode():
    context.configure(url=Settings().database_url.get_secret_value(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_database_engine(Settings())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
