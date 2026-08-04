"""SQLAlchemy engine and session configuration."""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from healthscope.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for application database models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_database_engine(database_url: str) -> Engine:
    """Create a resilient SQLAlchemy engine for a database URL."""

    return create_engine(database_url, pool_pre_ping=True)


@lru_cache
def get_engine() -> Engine:
    """Return the process-wide database engine."""

    return create_database_engine(get_settings().database_url)


EngineDependency = Annotated[Engine, Depends(get_engine)]


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory."""

    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Provide one transaction-scoped session to a request."""

    with get_session_factory().begin() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]
