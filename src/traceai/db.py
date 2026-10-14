"""Database lifecycle and transaction boundaries."""
from functools import partial

import simplejson
from psycopg.types.json import set_json_dumps, set_json_loads
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from traceai.config import Settings


class Base(DeclarativeBase):
    pass


def create_database_engine(settings: Settings):
    engine = create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
    )

    @event.listens_for(engine, "connect")
    def exact_json(connection, record):
        set_json_dumps(partial(simplejson.dumps, use_decimal=True, allow_nan=False), connection)
        set_json_loads(partial(simplejson.loads, use_decimal=True, allow_nan=False), connection)
    return engine


def session_factory(engine):
    # Callers use `with factory.begin() as session` for atomic writes.
    return sessionmaker(bind=engine, expire_on_commit=False)
