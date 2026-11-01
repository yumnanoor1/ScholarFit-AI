"""
Creates the table behind saved scholarships.
create_all() only adds missing tables, so running this is safe at any time; existing data is untouched.
"""
from app import models  # noqa: F401
from app.database import Base, engine
from app.models.opportunity import Scholarship  # noqa: F401


def main():
    Base.metadata.create_all(bind=engine, tables=[Base.metadata.tables["saved_scholarships"]])
    print("Table ok: saved_scholarships")


if __name__ == "__main__":
    main()
