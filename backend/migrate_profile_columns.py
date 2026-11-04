"""
Adds the profile-data columns used by the profile forms and their consumers.
create_all() does not alter existing tables, so this script is needed once.
Safe to run multiple times (ADD COLUMN IF NOT EXISTS); existing rows keep their data.
"""
from sqlalchemy import text

from app.database import engine

COLUMNS = {
    "nationality": "VARCHAR",
    "date_of_birth": "DATE",
    "institution": "VARCHAR",
    "academic_status": "VARCHAR",
    "graduation_date": "VARCHAR",
    "work_experience": "TEXT",
    "preferred_fields": "JSON",
    "preferred_degree_levels": "JSON",
    "preferred_funding_types": "JSON",
    "funding_preference": "VARCHAR",
    "language_test": "JSON",
    "tuition_budget_amount": "DOUBLE PRECISION",
    "tuition_budget_currency": "VARCHAR",
    "living_budget_amount": "DOUBLE PRECISION",
    "living_budget_currency": "VARCHAR",
    "form_details": "JSON",
}


def main():
    with engine.begin() as conn:
        for name, sql_type in COLUMNS.items():
            conn.execute(text(f"ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS {name} {sql_type}"))
            print(f"student_profiles.{name} ok")


if __name__ == "__main__":
    main()
