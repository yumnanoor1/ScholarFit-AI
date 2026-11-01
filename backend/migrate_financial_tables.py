"""
Creates the tables behind the financial plan and sourced program costs.
create_all() only adds missing tables, so running this is safe at any time; existing data is untouched.
"""
from sqlalchemy import text

from app import models  # noqa: F401
from app.database import Base, engine

NEW_TABLES = ["student_financial_plans", "program_costs"]
PROGRAM_COST_COLUMNS = {"amount_max": "DOUBLE PRECISION", "note": "TEXT", "includes": "VARCHAR"}


def main():
    Base.metadata.create_all(bind=engine, tables=[Base.metadata.tables[name] for name in NEW_TABLES])
    with engine.begin() as conn:
        for name, sql_type in PROGRAM_COST_COLUMNS.items():
            conn.execute(text(f"ALTER TABLE program_costs ADD COLUMN IF NOT EXISTS {name} {sql_type}"))
    print("Tables ok:", ", ".join(NEW_TABLES))


if __name__ == "__main__":
    main()
