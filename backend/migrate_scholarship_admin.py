"""
Adds the administration columns and the audit table. Only adds things: no row is changed, and
existing records keep every value. Safe to run again.

  python migrate_scholarship_admin.py
"""
from sqlalchemy import inspect, text

from app import models  # noqa: F401
from app.database import Base, engine as default_engine
from app.models.opportunity import ScholarshipAuditLog

COLUMNS = {
    "record_version": "INTEGER",
    "data_flags": "JSON",
    "source_checks": "JSON",
    "archived_at": "TIMESTAMP WITH TIME ZONE",
    "archived_by_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
    "archive_reason": "TEXT",
}


def main(engine=default_engine):
    existing = {column["name"] for column in inspect(engine).get_columns("scholarships")}
    with engine.begin() as conn:
        for name, sql_type in COLUMNS.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE scholarships ADD COLUMN {name} {sql_type}"))
    Base.metadata.create_all(bind=engine, tables=[ScholarshipAuditLog.__table__])
    print("Columns and audit table ok")


if __name__ == "__main__":
    main()
