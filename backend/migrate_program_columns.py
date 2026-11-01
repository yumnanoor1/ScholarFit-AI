"""
Programs table mein verification ke naye columns add karo.
create_all() existing table ko alter nahi karta, is liye ye script chahiye.
Safe to run multiple times (ADD COLUMN IF NOT EXISTS).
"""
from sqlalchemy import text

from app.database import engine

COLUMNS = {
    "tuition_amount": "DOUBLE PRECISION",
    "tuition_currency": "VARCHAR",
    "language_of_instruction": "VARCHAR",
    "last_verified": "DATE",
}


def main():
    with engine.begin() as conn:
        for name, sql_type in COLUMNS.items():
            conn.execute(text(f"ALTER TABLE programs ADD COLUMN IF NOT EXISTS {name} {sql_type}"))
            print(f"programs.{name} ok")


if __name__ == "__main__":
    main()
