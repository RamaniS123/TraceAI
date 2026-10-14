"""Database lifecycle and transaction boundaries."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from traceai.config import Settings


class Base(DeclarativeBase):
    pass


def create_database_engine(settings: Settings):
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
    )


def session_factory(engine):
    # Callers use `with factory.begin() as session` for atomic writes.
    return sessionmaker(bind=engine, expire_on_commit=False)
