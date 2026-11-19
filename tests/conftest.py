import pytest

from finance_manager.infrastructure.database import (
    Base, build_engine, build_session_factory, initialize_database
)


@pytest.fixture
def session():
    engine = build_engine("sqlite://")
    initialize_database(engine)
    factory = build_session_factory(engine)
    with factory() as db:
        yield db
    engine.dispose()
