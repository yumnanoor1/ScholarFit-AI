from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os

from app.core.config import is_production

load_dotenv()

# Docker Compose mein DATABASE_URL environment variable set hai
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://fitscholar_user:fitscholar_password@localhost:5432/fitscholar_db")

# In production, database errors never carry the submitted values into logs
engine = create_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=is_production())

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_application_schema(bind=None):
    """Create the existing application tables, leaving scholarship RAG tables to their migration."""
    from app.models.scholarship_knowledge import SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES

    target = bind or engine
    application_tables = [
        table for table in Base.metadata.tables.values()
        if table.name not in SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES
    ]
    Base.metadata.create_all(bind=target, tables=application_tables)