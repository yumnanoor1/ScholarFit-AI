"""
Adds the institution columns and the scholarship_program_links table, then fills them from the
reviewed data in scholarship_program_link_data.py. Safe to run again: a scholarship whose
institution_scope is set and a pair that already has a row are left alone, so admin edits stay.
No scholarship or program row is deleted, and their other columns are never written.

  python migrate_scholarship_program_links.py          add, fill and report
  python migrate_scholarship_program_links.py --check  add columns and table, report only
"""
import sys
from collections import Counter

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.database import Base, engine as default_engine
from app.models.opportunity import Program, Scholarship, ScholarshipProgramLink, University
from app.services.scholarship_matching import evaluate_match
from scholarship_program_link_data import INSTITUTIONS, LINKS

COLUMNS = {
    "institution_scope": "VARCHAR",
    "host_institution": "VARCHAR",
    "host_university_id": "INTEGER REFERENCES universities(id) ON DELETE SET NULL",
}


def add_schema(engine):
    existing = {column["name"] for column in inspect(engine).get_columns("scholarships")}
    with engine.begin() as conn:
        for name, sql_type in COLUMNS.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE scholarships ADD COLUMN {name} {sql_type}"))
    Base.metadata.create_all(bind=engine, tables=[ScholarshipProgramLink.__table__])


def fill(session):
    """Returns (scholarships filled, links added)."""
    filled = added = 0
    for scholarship in session.query(Scholarship):
        if scholarship.id in INSTITUTIONS and not scholarship.institution_scope:
            scope, name, university_id = INSTITUTIONS[scholarship.id]
            if university_id is not None:
                university = session.get(University, university_id)
                if university is None or university.name != name:
                    raise ValueError(f"Scholarship {scholarship.id}: university {university_id} is not {name}")
            scholarship.institution_scope, scholarship.host_institution, scholarship.host_university_id = scope, name, university_id
            filled += 1
    existing = {(link.scholarship_id, link.program_id) for link in session.query(ScholarshipProgramLink)}
    for row in LINKS:
        pair = (row["scholarship_id"], row["program_id"])
        if pair not in existing and session.get(Scholarship, pair[0]) and session.get(Program, pair[1]):
            session.add(ScholarshipProgramLink(**row))
            added += 1
    session.commit()
    return filled, added


def report(session):
    links = {(link.scholarship_id, link.program_id): link for link in session.query(ScholarshipProgramLink)}
    scholarships = session.query(Scholarship).order_by(Scholarship.id).all()
    programs = session.query(Program).order_by(Program.id).all()
    outcomes = Counter()
    linked = set()
    for scholarship in scholarships:
        for program in programs:
            outcome = evaluate_match(scholarship, program, links.get((scholarship.id, program.id)))["outcome"]
            outcomes[outcome] += 1
            if outcome != "not_a_match":
                linked.add(scholarship.id)
    print("Scholarships:", len(scholarships), "Programs:", len(programs), "Pairs:", len(scholarships) * len(programs))
    print("Institution scope:", dict(Counter(item.institution_scope for item in scholarships)))
    print("Stored relationships:", dict(Counter(link.outcome for link in links.values())))
    print("All pairs:", dict(outcomes))
    print("Scholarships with no possible program:", [item.id for item in scholarships if item.id not in linked])


def main(engine=default_engine, check_only=False):
    add_schema(engine)
    with Session(engine) as session:
        if not check_only:
            print("Filled %d scholarships, added %d relationships" % fill(session))
        report(session)


if __name__ == "__main__":
    main(check_only="--check" in sys.argv)
