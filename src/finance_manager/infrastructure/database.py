from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from finance_manager.config import database_url


class Base(DeclarativeBase):
    pass


def build_engine(url: str | None = None):
    engine = create_engine(url or database_url(), future=True)

    if (url or database_url()).startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def build_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def initialize_database(engine):
    from finance_manager.infrastructure import models  # noqa: F401

    Base.metadata.create_all(engine)
