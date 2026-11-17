import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import database_identity, database_url, is_production

logger = logging.getLogger(__name__)

# One source of truth: app.core.config loads backend/.env by absolute path,
# so the API, the discovery worker and the diagnostics all resolve the same
# database however the process was started. (Docker Compose sets DATABASE_URL
# in the real environment, which still wins.)
DATABASE_URL = database_url()

# In production, database errors never carry the submitted values into logs
# Bounded on purpose: the API, the scheduler and the discovery worker share
# one machine. The defaults allow 5 + 10 overflow connections; on a small host
# every extra connection is another socket and another server backend. These
# are QueuePool options, so they are only passed for a server database --
# SQLite (used by the tests) rejects them outright.
_POOL_OPTIONS = {
    "pool_size": 5,
    "max_overflow": 5,
    "pool_timeout": 30,
    "pool_recycle": 1800,
}
_is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    hide_parameters=is_production(),
    **({} if _is_sqlite else _POOL_OPTIONS),
)

DATABASE_IDENTITY = database_identity(engine.url)
logger.info(
    "Database configured: database=%s host=%s port=%s",
    DATABASE_IDENTITY["database"],
    DATABASE_IDENTITY["host"],
    DATABASE_IDENTITY["port"],
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def application_tables():
    """Return application tables, leaving RAG and discovery tables to explicit migrations."""
    from app.models.scholarship_knowledge import SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES
    from app.models.scholarship_discovery import SCHOLARSHIP_DISCOVERY_TABLE_NAMES
    from app.models.scholarship_discovery_publication import SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES

    return [
        table for table in Base.metadata.tables.values()
        if table.name not in (
            SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES
            | SCHOLARSHIP_DISCOVERY_TABLE_NAMES
            | SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES
        )
    ]


def create_application_schema(bind=None):
    """Create application tables, leaving RAG and discovery tables to explicit migrations."""
    Base.metadata.create_all(bind=bind or engine, tables=application_tables())